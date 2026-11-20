from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import product
from statistics import mean

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from economics_types import Range
from db_models import AgentEventRecord
from models import AgentEvent

router = APIRouter(prefix="/analytics", tags=["Execution economics"])
COHORT_LIMIT = 1000
ZERO = Decimal(0)


class Assumptions(BaseModel):
    evidence_source: str = Field(min_length=1, max_length=500, pattern=r"\S")
    manual_minutes: Range
    review_minutes: Range
    hourly_labor_usd: Range
    overhead_usd_per_attempt: Range
    unknown_model_cost_usd_per_attempt: Range | None = None


def cohort(db: Session, days: int):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    events = list(db.scalars(
        select(AgentEventRecord)
        .where(
            AgentEventRecord.workflow == "invoice_process",
            AgentEventRecord.created_at >= start,
            AgentEventRecord.created_at <= end,
        )
        .order_by(AgentEventRecord.created_at.desc(), AgentEventRecord.run_id.desc())
        .limit(COHORT_LIMIT + 1)
    ))
    return events[:COHORT_LIMIT], {
        "start": start, "end": end, "limit": COHORT_LIMIT, "truncated": len(events) > COHORT_LIMIT,
    }


def summarize(events):
    outcomes = Counter()
    input_tokens = output_tokens = usage_runs = 0
    provider_usd = estimated_usd = ZERO
    charges = estimates = rules = 0
    daily = defaultdict(Counter)
    model_latencies = []
    for event in events:
        if event.status == "failure":
            outcome = "failed"
        elif event.requires_human_review is True:
            outcome = "review"
        elif event.validation_passed is True:
            outcome = "passed"
        else:
            outcome = "unclassified"
        outcomes[outcome] += 1
        timestamp = event.created_at
        utc = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp
        daily[utc.date().isoformat()][outcome] += 1
        if event.usage_reported:
            usage_runs += 1
            input_tokens += event.input_tokens
            output_tokens += event.output_tokens
        if event.model_latency_ms is not None:
            model_latencies.append(event.model_latency_ms)
        if event.provider_charge_usd is not None:
            charges += 1
            provider_usd += event.provider_charge_usd
        elif event.estimated_cost_usd is not None:
            estimates += 1
            estimated_usd += event.estimated_cost_usd
        elif event.provider == "rules" or (event.provider and event.model_latency_ms is None):
            rules += 1

    attempts = len(events)
    processed = attempts - outcomes["failed"]
    unknown = attempts - charges - estimates - rules
    known_cost = provider_usd + estimated_usd
    return {
        "attempts": attempts,
        "processed": processed,
        "failed": outcomes["failed"],
        "review": outcomes["review"],
        "passed": outcomes["passed"],
        "unclassified": outcomes["unclassified"],
        "observed_straight_through_rate": outcomes["passed"] / attempts if attempts else None,
        "average_latency_ms": mean(event.latency_ms for event in events) if attempts else None,
        "average_model_latency_ms": mean(model_latencies) if model_latencies else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage_reported_runs": usage_runs,
        "provider_charge_runs": charges,
        "provider_charge_usd": provider_usd,
        "estimated_cost_runs": estimates,
        "estimated_model_cost_usd": estimated_usd,
        "zero_model_cost_runs": rules,
        "unknown_model_cost_runs": unknown,
        "covered_model_cost_usd": known_cost,
        "model_cost_per_processed_usd": known_cost / processed if processed and not unknown else None,
        "daily": [{"date": date, **counts} for date, counts in sorted(daily.items())],
    }


def estimate(metrics: dict, assumptions: Assumptions):
    count = metrics["attempts"]
    unknown = metrics["unknown_model_cost_runs"]
    if not count:
        return {"status": "no_observations", "scenarios": []}
    if unknown and assumptions.unknown_model_cost_usd_per_attempt is None:
        return {"status": "missing_cost_assumption", "scenarios": []}

    missing_cost = assumptions.unknown_model_cost_usd_per_attempt or Range(low=0, high=0)
    ranges = (
        assumptions.manual_minutes, assumptions.review_minutes, assumptions.hourly_labor_usd,
        assumptions.overhead_usd_per_attempt, missing_cost,
    )
    candidates = []
    for manual, review, labor, overhead_rate, missing_rate in product(
        *((bounds.low, bounds.high) for bounds in ranges)
    ):
        fallback_minutes = (metrics["failed"] + metrics["unclassified"]) * manual
        review_minutes = metrics["review"] * review
        manual_minutes = count * manual
        saved_minutes = manual_minutes - fallback_minutes - review_minutes
        model = metrics["covered_model_cost_usd"] + unknown * missing_rate
        overhead = count * overhead_rate
        manual_cost = manual_minutes * labor / 60
        review_cost = review_minutes * labor / 60
        fallback_cost = fallback_minutes * labor / 60
        operating_cost = model + overhead + review_cost + fallback_cost
        savings = manual_cost - operating_cost
        candidates.append({
            "manual_cost_usd": manual_cost,
            "review_cost_usd": review_cost,
            "fallback_cost_usd": fallback_cost,
            "model_cost_usd": model,
            "overhead_cost_usd": overhead,
            "operating_cost_usd": operating_cost,
            "operating_cost_per_processed_usd": operating_cost / metrics["processed"] if metrics["processed"] else None,
            "net_savings_usd": savings,
            "roi_ratio": savings / operating_cost if operating_cost else None,
            "human_minutes_saved": saved_minutes,
            "human_effort_reduction_ratio": saved_minutes / manual_minutes if manual_minutes else None,
        })
    worst = min(candidates, key=lambda case: case["net_savings_usd"])
    best = max(candidates, key=lambda case: case["net_savings_usd"])
    ratios = [case["roi_ratio"] for case in candidates]
    roi_range = None if None in ratios else {"low": min(ratios), "high": max(ratios)}
    return {
        "status": "estimated",
        "roi_ratio_range": roi_range,
        "scenarios": [{"label": "conservative", **worst}, {"label": "favorable", **best}],
    }


@router.get("/overview")
def overview(days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    events, window = cohort(db, days)
    return {
        "window": window,
        "metrics": summarize(events),
        "recent": [AgentEvent.model_validate(event) for event in events[:20]],
    }


@router.post("/roi")
def roi(assumptions: Assumptions, days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    events, window = cohort(db, days)
    metrics = summarize(events)
    return {"window": window, "observed": metrics, "assumptions": assumptions, **estimate(metrics, assumptions)}
