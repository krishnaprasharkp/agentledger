"""Workflow-independent counterfactual economics and interval calculations."""
from decimal import Decimal

from fastapi import HTTPException

from economics_types import Range

ZERO = Decimal(0)
DAYS_PER_MONTH = Decimal("30.4375")


# Interval arithmetic keeps inputs independent. Bounds can be wider than feasible joint cases.
def interval(value):
    if isinstance(value, Range):
        return value.low, value.high
    if isinstance(value, dict):
        return Decimal(value["low"]), Decimal(value["high"])
    return value, value


def add(*parts):
    return sum(part[0] for part in parts), sum(part[1] for part in parts)


def subtract(left, right):
    return left[0] - right[1], left[1] - right[0]


def multiply(left, right):
    products = [a * b for a in left for b in right]
    return min(products), max(products)


def bounds(value):
    return {"low": str(value[0]), "high": str(value[1])}


def payback(implementation, recurring_net, months):
    if implementation == 0:
        return ZERO
    return implementation * months / recurring_net if recurring_net > 0 else None


def calculate(implementation, benefits, operating, months):
    recurring = subtract(benefits, operating)
    net = subtract(recurring, implementation)
    total_cost = add(operating, implementation)
    roi = None
    if total_cost[0] > 0:
        ratios = [(benefit - cost) / cost for benefit in benefits for cost in total_cost]
        roi = min(ratios), max(ratios)
    earliest = payback(implementation[0], recurring[1], months)
    latest = payback(implementation[1], recurring[0], months)
    return {
        "months": str(months), "implementation_usd": bounds(implementation),
        "period_benefit_usd": bounds(benefits), "period_operating_usd": bounds(operating),
        "period_net_benefit_usd": bounds(net), "roi_ratio": bounds(roi) if roi is not None else None,
        "payback_months": {"earliest": str(earliest) if earliest is not None else None,
                           "latest": str(latest) if latest is not None else None},
    }


def analyze(payload, baseline, metrics=None):
    forecast = metrics is None
    if forecast:
        months = Decimal(payload.months)
    else:
        elapsed = payload.end - payload.start
        days = elapsed.days + (elapsed.seconds + Decimal(elapsed.microseconds) / 1_000_000) / 86_400
        months = days / DAYS_PER_MONTH
    units = multiply(interval(payload.units_monthly), interval(months)) if forecast else interval(metrics["units"])
    manual = multiply(units, interval(baseline.assumptions["manual_cost_usd_per_unit"]))
    costs = {name: multiply(interval(getattr(payload, name + "_usd_monthly")), interval(months))
             for name in ("fixed_model", "fixed_infrastructure", "maintenance")}
    if forecast:
        costs["variable_model"] = multiply(units, interval(payload.model_usd_per_unit))
        costs["variable_infrastructure"] = multiply(units, interval(payload.infrastructure_usd_per_unit))
        reviewed = multiply(units, interval(payload.review_fraction))
        reworked = multiply(units, interval(payload.rework_fraction))
    else:
        for name in ("model", "infrastructure"):
            if metrics["missing_" + name] and getattr(payload, "missing_" + name + "_usd_per_execution") is None:
                raise HTTPException(422, f"Supply a cost range for executions with missing {name} costs.")
        costs["variable_model"] = add(
            interval(metrics["model_charge_usd"] + metrics["estimated_model_usd"]),
            multiply(interval(metrics["missing_model"]), interval(payload.missing_model_usd_per_execution or ZERO)),
        )
        costs["variable_infrastructure"] = add(
            interval(metrics["infrastructure_charge_usd"]),
            multiply(interval(metrics["missing_infrastructure"]),
                     interval(payload.missing_infrastructure_usd_per_execution or ZERO)),
        )
        reviewed, reworked = (interval(metrics[key]) for key in ("reviewed_units", "reworked_units"))
    costs["review"] = multiply(reviewed, interval(payload.review_usd_per_unit))
    costs["rework"] = multiply(reworked, interval(payload.rework_usd_per_unit))
    benefits = {"counterfactual_manual_cost": manual}
    for key, valuation in payload.outcome_valuation.items():
        if key == "counterfactual_manual_cost":
            raise HTTPException(422, "The counterfactual manual cost metric name is reserved.")
        prior = baseline.assumptions["outcome_per_unit"].get(key)
        if prior is None:
            raise HTTPException(422, f"Baseline outcome assumption is missing for {key}.")
        if forecast:
            expected = payload.expected_outcomes_per_unit.get(key)
            if expected is None:
                raise HTTPException(422, f"Forecast outcome assumption is missing for {key}.")
            delta = multiply(units, subtract(interval(expected), interval(prior)))
        else:
            if metrics["outcome_covered_units"].get(key, 0) != metrics["units"]:
                raise HTTPException(422, f"Assessment outcome coverage is incomplete for {key}.")
            delta = subtract(interval(metrics["outcomes"][key]), multiply(units, interval(prior)))
        benefits[key] = multiply(multiply(delta, interval(valuation.direction)), interval(valuation.usd_per_metric_unit))
    implementation = interval(payload.implementation_usd)
    results = calculate(implementation, add(*benefits.values()), add(*costs.values()), months)
    cost_components = costs | {"implementation": implementation}
    benefit_components = {
        f"outcome: {name}" if name in cost_components else name: value for name, value in benefits.items()
    }
    sensitivity = {
        name: str(high - low) for name, (low, high) in (cost_components | benefit_components).items()
    }
    return results | {
        "cost_breakdown_usd": {key: bounds(value) for key, value in costs.items()},
        "benefit_breakdown_usd": {key: bounds(value) for key, value in benefits.items()},
        "component_sensitivity_span_usd": sensitivity,
    }
