"""Compare the current economics source with independent rational expectations."""
import argparse
import json
import os
import platform
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

from api_latency import bounds

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
from investment import analyze, calculate
from portfolio import AssessmentInput, ForecastPreview

F = Fraction
D = Decimal


def model(case, **overrides):
    values = {
        "months": 2, "units_monthly": bounds(10), "implementation_usd": bounds(13),
        "fixed_model_usd_monthly": bounds(3), "fixed_infrastructure_usd_monthly": bounds(4),
        "maintenance_usd_monthly": bounds(5), "review_usd_per_unit": bounds(2), "rework_usd_per_unit": bounds(5),
        "model_usd_per_unit": bounds(1), "infrastructure_usd_per_unit": bounds(".5"),
        "review_fraction": bounds(".25"), "rework_fraction": bounds(".1"), "evidence": "Synthetic audit",
        "baseline": {"name": case, "evidence": "Synthetic audit", "manual_cost_usd_per_unit": bounds(5)},
    }
    return ForecastPreview.model_validate(values | overrides)


def preview(payload):
    return analyze(payload, SimpleNamespace(assumptions=payload.baseline.model_dump(mode="json")))


def cases():
    yield "positive", preview(model("positive")), (13, 13, F(13, 87), F(13, 87), 1, 1)
    yield "negative", preview(model("negative", implementation_usd=bounds(50))), (
        -24, -24, F(-24, 124), F(-24, 124), F(50, 13), F(50, 13),
    )
    yield "zero_volume_fixed_costs", preview(model("zero volume", units_monthly=bounds(0))), (
        -37, -37, -1, -1, None, None,
    )
    yield "exact_break_even", calculate((D(0), D(0)), (D(7), D(7)), (D(7), D(7)), D(1)), (0, 0, 0, 0, 0, 0)
    yield "zero_cost_roi_undefined", calculate((D(0), D(0)), (D(10), D(10)), (D(0), D(0)), D(1)), (
        10, 10, None, None, 0, 0,
    )
    yield "interval_with_zero_denominator", calculate((D(0), D(5)), (D(0), D(2)), (D(0), D(0)), D(1)), (
        -5, 2, None, None, 0, None,
    )
    for minutes, expected_low in ((6, 32_400), (7, 37_800)):
        case = f"support_{minutes}_minutes"
        payload = model(
            case, months=12, units_monthly=bounds(900, 1200), implementation_usd=bounds(8000, 12_000),
            fixed_model_usd_monthly=bounds(0), fixed_infrastructure_usd_monthly=bounds(80, 120),
            maintenance_usd_monthly=bounds(250, 400), review_usd_per_unit=bounds("1.5", "2.1"),
            rework_usd_per_unit=bounds(3, 5), model_usd_per_unit=bounds(".14", ".23"),
            infrastructure_usd_per_unit=bounds(".04", ".08"), review_fraction=bounds(".25", ".4"),
            rework_fraction=bounds(".05", ".1"),
            baseline={"name": case, "evidence": "Synthetic audit", "manual_cost_usd_per_unit": bounds(D(minutes) / 2, "4.8")},
        )
        # Independently expand the quantities in the audit's published assumptions.
        # Lower total cost = 10800 * .705 + 3960 + 8000 = 19574.
        # Upper total cost = 14400 * 1.65 + 6240 + 12000 = 42000.
        yield case, preview(payload), (
            expected_low - 42000, 69120 - 19574, F(expected_low - 42000, 42000), F(69120 - 19574, 19574),
            F(96000, 69120 - 11574), F(144000, expected_low - 30000),
        )
    base = model("assessment")
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assessment = AssessmentInput.model_validate(base.model_dump() | {
        "baseline_id": "00000000-0000-0000-0000-000000000001",
        "deployment_id": "00000000-0000-0000-0000-000000000002",
        "start": t0, "end": t0 + timedelta(days=30, hours=10, minutes=30),
        "implementation_usd": bounds(8), "rework_usd_per_unit": bounds(3),
        "missing_model_usd_per_execution": bounds(1, 2), "missing_infrastructure_usd_per_execution": bounds(2, 4),
        "outcome_valuation": {"escalated": {"direction": -1, "usd_per_metric_unit": bounds(3)}},
    })
    measured = {"units": 10, "reviewed_units": 4, "reworked_units": 3, "model_charge_usd": D(4),
                "estimated_model_usd": D(3), "infrastructure_charge_usd": D(7),
                "missing_model": 1, "missing_infrastructure": 1,
                "outcomes": {"escalated": D(4)}, "outcome_covered_units": {"escalated": 10}}
    result = analyze(assessment, SimpleNamespace(assumptions={
        "manual_cost_usd_per_unit": bounds(5), "outcome_per_unit": {"escalated": bounds(".6")},
    }), measured)
    yield "assessment_with_missing_cost_ranges", result, (-1, 2, F(-1, 57), F(2, 54), F(4, 5), F(8, 7))
    yield "rollup_with_shared_costs", calculate((D(31), D(31)), (D(200), D(200)), (D(158), D(158)), D(2)), (
        11, 11, F(11, 189), F(11, 189), F(62, 42), F(62, 42),
    )


def render(value):
    with localcontext() as context:
        context.prec = 60
        return str(D(value.numerator) / D(value.denominator))


def main(output):
    rows = []
    maxima = {}
    for name, actual, expected in cases():
        observed = [
            actual["period_net_benefit_usd"]["low"], actual["period_net_benefit_usd"]["high"],
            (actual["roi_ratio"] or {}).get("low"), (actual["roi_ratio"] or {}).get("high"),
            actual["payback_months"]["earliest"], actual["payback_months"]["latest"],
        ]
        metrics = ["net.low", "net.high", "roi.low", "roi.high", "payback.earliest", "payback.latest"]
        if name.startswith("support_"):
            spans = actual["component_sensitivity_span_usd"]
            metrics += ["span.manual_value", "span.review", "span.implementation"]
            observed += [spans["counterfactual_manual_cost"], spans["review"], spans["implementation"]]
            expected += (36_720 if name == "support_6_minutes" else 31_320, 8_046, 4000)
        for metric, got, want in zip(metrics, observed, expected, strict=True):
            group = metric.split(".")[0]
            stats = maxima.setdefault(group, {"absolute": F(0), "relative": F(0), "defined": 0, "undefined": 0, "zero": 0})
            if got is None or want is None:
                if got is not None or want is not None:
                    raise AssertionError(f"{name} {metric}: mismatched undefined state")
                stats["undefined"] += 1
                rows.append({"case": name, "metric": metric, "expected": None, "actual": None})
                continue
            expected_value = F(want)
            error = abs(F(got) - expected_value)
            relative = error / abs(expected_value) if expected_value else None
            stats["defined"] += 1
            stats["zero"] += int(expected_value == 0)
            stats["absolute"] = max(error, stats["absolute"])
            if relative is not None:
                stats["relative"] = max(relative, stats["relative"])
            if error > F("1e-24") or (relative is not None and relative > F("1e-25")):
                raise AssertionError(f"{name} {metric}: excess error, expected {render(expected_value)}, got {got}")
            rows.append({"case": name, "metric": metric, "expected": render(expected_value), "actual": got,
                         "absolute_error": render(error), "relative_error": render(relative) if relative is not None else None})
    output.write_text(json.dumps({
        "python": platform.python_version(), "engine": "direct Python, no database queries or provider calls",
        "maxima": {name: {k: render(v) if isinstance(v, F) else v for k, v in row.items()} for name, row in maxima.items()},
        "comparisons": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(rows)} defined or undefined result positions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.output)
