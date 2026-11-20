"""Independent reconciliation cases. Expected money is derived from fixture quantities."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from economics import Assumptions, estimate


def band(low, high=None):
    return {"low": str(low), "high": str(low if high is None else high)}


def check(value, low, high=None):
    assert (D(value["low"]), D(value["high"])) == (D(low), D(low if high is None else high))


def request(client, path, payload, status=201):
    response = client.post("/portfolio" + path, json=payload)
    assert response.status_code == status, response.text
    return response.json()


def common(**overrides):
    return {
        "evidence": "Independent audit fixture",
        "implementation_usd": band(13), "fixed_model_usd_monthly": band(3),
        "fixed_infrastructure_usd_monthly": band(4), "maintenance_usd_monthly": band(5),
        "review_usd_per_unit": band(2), "rework_usd_per_unit": band(5),
    } | overrides


def forecast(**overrides):
    return common() | {
        "months": 2, "units_monthly": band(10), "review_fraction": band(".25"),
        "rework_fraction": band(".1"), "model_usd_per_unit": band(1),
        "infrastructure_usd_per_unit": band(".5"),
    } | overrides


def baseline(cost=5, **metrics):
    return {"name": "Manual", "evidence": "Independent audit fixture",
            "manual_cost_usd_per_unit": band(cost), "outcome_per_unit": metrics}


def preview(client, inputs, manual=None, status=200):
    return request(client, "/forecasts/preview", inputs | {"baseline": manual or baseline()}, status)


@pytest.mark.parametrize(("units", "setup", "benefit", "operating", "net", "roi", "payback"), [
    (10, 13, 100, 74, 13, D(13)/87, D(1)),
    (10, 50, 100, 74, -24, D(-24)/124, D(50)/13),
    (0, 13, 0, 24, -37, D(-1), None),
])
def test_forecast_reconciles_fixed_variable_review_and_rework_costs(
    client, units, setup, benefit, operating, net, roi, payback,
):
    got = preview(client, forecast(units_monthly=band(units), implementation_usd=band(setup)))["estimates"]
    check(got["period_benefit_usd"], benefit)
    check(got["period_operating_usd"], operating)
    check(got["period_net_benefit_usd"], net)
    check(got["roi_ratio"], roi)
    check(got["cost_breakdown_usd"]["review"], units)
    check(got["cost_breakdown_usd"]["rework"], units)
    expected = str(payback) if payback is not None else None
    assert got["payback_months"] == {"earliest": expected, "latest": expected}


def test_exact_break_even_zero_cost_and_zero_setup_payback(client):
    inputs = forecast(months=1, units_monthly=band(1), implementation_usd=band(0),
                      fixed_model_usd_monthly=band(0), fixed_infrastructure_usd_monthly=band(0),
                      maintenance_usd_monthly=band(0), model_usd_per_unit=band(7),
                      infrastructure_usd_per_unit=band(0), review_fraction=band(0), rework_fraction=band(0))
    got = preview(client, inputs, baseline(7))["estimates"]
    check(got["roi_ratio"], 0)
    check(got["period_net_benefit_usd"], 0)
    assert got["payback_months"] == {"earliest": "0", "latest": "0"}
    negative = preview(client, inputs | {"implementation_usd": band(0, 7)}, baseline(0))["estimates"]
    assert negative["payback_months"] == {"earliest": "0", "latest": None}
    empty = preview(client, inputs | {"units_monthly": band(0)})["estimates"]
    check(empty["period_net_benefit_usd"], 0)
    assert empty["roi_ratio"] is None


def test_reserved_benefit_cannot_replace_manual_cost_and_names_do_not_mask_sensitivity(client):
    reserved = "counterfactual_manual_cost"
    valuation = {"direction": 1, "usd_per_metric_unit": band(1)}
    inputs = forecast(outcome_valuation={reserved: valuation},
                      expected_outcomes_per_unit={reserved: band(3)})
    preview(client, inputs, baseline(**{reserved: band(1)}), status=422)
    inputs = forecast(review_fraction=band(".25", ".5"), outcome_valuation={"review": valuation},
                      expected_outcomes_per_unit={"review": band(1, 3)})
    got = preview(client, inputs, baseline(review=band(1)))["estimates"]
    check(got["cost_breakdown_usd"]["review"], 10, 20)
    check(got["benefit_breakdown_usd"]["review"], 0, 40)
    assert D(got["component_sensitivity_span_usd"]["review"]) == 10
    assert D(got["component_sensitivity_span_usd"]["outcome: review"]) == 40


def org(client, name="Audit"):
    return request(client, "/organizations", {"name": name})["id"]


def workflow(client, organization, key, cost=5):
    path = "/organizations/" + organization + "/workflows"
    record = request(client, path, {"name": key, "department": "Support", "unit": "ticket", "benefit_pool": key,
                                    "outcome_metrics": ["escalated"]})
    path = "/workflows/" + record["id"]
    base = request(client, path + "/baselines", baseline(cost, escalated=band(".6")))["id"]
    deployment = request(client, path + "/deployments", {"name": "Pilot"})["id"]
    return path, base, deployment


def test_assessment_boundary_charge_precedence_missing_costs_and_provenance(client):
    path, baseline_id, deployment = workflow(client, org(client), "support")
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=30, hours=10, minutes=30)
    offset = timezone(timedelta(hours=5, minutes=30))
    execution_route = f"/deployments/{deployment}/executions"

    def event(run, at, units, reviewed, reworked, outcome, **charges):
        request(client, execution_route, {
            "external_run_id": run, "occurred_at": at.astimezone(offset).isoformat(),
            "units": units, "reviewed_units": reviewed, "reworked_units": reworked, "succeeded": True,
            "outcomes": {"escalated": outcome}, **charges,
        })

    event("before", start - timedelta(minutes=1), 100, 0, 0, 0)
    event("start", start, 3, 2, 1, 2, model_charge_usd="4", estimated_model_usd="9",
          estimated_model_evidence="Fixture estimate", infrastructure_charge_usd="2")
    event("estimated", start + timedelta(days=1), 2, 1, 1, 0, estimated_model_usd="3",
          estimated_model_evidence="Fixture estimate")
    event("no-call", start + timedelta(days=2), 1, 0, 1, 1, model_invoked=False, infrastructure_charge_usd="1")
    event("missing", end - timedelta(minutes=1), 4, 1, 0, 1, infrastructure_charge_usd="4")
    event("end", end, 100, 0, 0, 0)
    payload = common(implementation_usd=band(8), rework_usd_per_unit=band(3)) | {
        "baseline_id": baseline_id, "deployment_id": deployment, "start": start.isoformat(), "end": end.isoformat(),
        "outcome_valuation": {"escalated": {"direction": -1, "usd_per_metric_unit": band(3)}},
    }
    route = path + "/assessments"
    assert "missing model costs" in request(client, route, payload, 422)["detail"]
    payload["missing_model_usd_per_execution"] = band(1, 2)
    assert "missing infrastructure costs" in request(client, route, payload, 422)["detail"]
    payload["missing_infrastructure_usd_per_execution"] = band(2, 4)
    snapshot = request(client, route, payload)["snapshot"]
    got, measured = snapshot["estimates"], snapshot["measured"]
    assert D(got["months"]) == 1
    check(got["cost_breakdown_usd"]["variable_model"], 8, 9)
    check(got["cost_breakdown_usd"]["variable_infrastructure"], 9, 11)
    check(got["cost_breakdown_usd"]["review"], 8)
    check(got["cost_breakdown_usd"]["rework"], 9)
    check(got["period_operating_usd"], 46, 49)
    check(got["period_benefit_usd"], 56)
    check(got["period_net_benefit_usd"], -1, 2)
    check(got["roi_ratio"], D(-1)/57, D(2)/54)
    assert D(got["payback_months"]["earliest"]) == D(".8")
    assert D(got["payback_months"]["latest"]) == D(8)/7
    assert (measured["executions"], measured["units"], measured["outcomes"]["escalated"]) == (4, 10, "4")
    assert measured["model_charge_usd"] == "4"
    assert measured["no_model_call_runs"] == 1
    assert "estimated_model_usd" not in measured
    assert snapshot["prior_estimates"]["estimated_model_usd"] == "3"
    assert snapshot["assumptions"]["missing_model_usd_per_execution"] == band(1, 2)
    assert "no deployment executions" in request(client, route, payload | {
        "start": (end + timedelta(days=1)).isoformat(), "end": (end + timedelta(days=2)).isoformat(),
    }, 422)["detail"]
    event("synthetic", start + timedelta(hours=1), 1, 0, 0, 0, data_origin="synthetic")
    assert "synthetic and measured runs" in request(client, route, payload, 422)["detail"]


def test_rollup_sums_dollars_and_blocks_known_attribution_overlap(client):
    organization = org(client)
    a, baseline_a, _ = workflow(client, organization, "pool_a")
    b, baseline_b, _ = workflow(client, organization, "pool_b", cost=4)
    first = request(client, a + "/forecasts", forecast(baseline_id=baseline_a))
    second = request(client, b + "/forecasts", forecast(baseline_id=baseline_b))
    different_period = request(client, b + "/forecasts", forecast(baseline_id=baseline_b, months=3))
    external, external_base, _ = workflow(client, org(client, "Other"), "pool_a")
    outsider = request(client, external + "/forecasts", forecast(baseline_id=external_base))
    shared = [
        {"key": key, "kind": kind, "usd": band(value), "evidence": "Fixture"}
        for key, kind, value in (("shared_setup", "implementation", 5), ("shared_ops", "recurring_cost", 10),
                                 ("shared_benefit", "recurring_benefit", 20))
    ]
    route = "/organizations/" + organization + "/rollup"
    payload = {"analysis_ids": [first["id"], second["id"]], "shared_items": shared,
               "disjoint_attribution_confirmed": True}
    got = request(client, route, payload, 200)["estimates"]
    check(got["implementation_usd"], 31)
    check(got["period_benefit_usd"], 200)
    check(got["period_operating_usd"], 158)
    check(got["period_net_benefit_usd"], 11)
    check(got["roi_ratio"], D(11)/189)
    assert D(got["payback_months"]["latest"]) == D(62)/42
    request(client, route, payload | {"analysis_ids": [first["id"], first["id"]]}, 422)
    request(client, route, payload | {"analysis_ids": [first["id"], different_period["id"]]}, 422)
    request(client, route, payload | {"analysis_ids": [first["id"], outsider["id"]]}, 422)
    request(client, route, payload | {"shared_items": [shared[2], shared[2]]}, 422)
    request(client, route, payload | {"shared_items": [shared[2] | {"key": "pool_a"}]}, 422)
    request(client, route, payload | {"disjoint_attribution_confirmed": False}, 422)
    # Different keys with the same evidence and amount can represent legitimate separate benefits.
    # A blanket duplicate-by-value rule cannot establish whether the underlying benefit overlaps.
    renamed = shared[2] | {"key": "renamed_benefit"}
    unresolved_overlap = request(client, route, payload | {"shared_items": [*shared, renamed]}, 200)
    check(unresolved_overlap["estimates"]["period_benefit_usd"], 220)
    request(client, "/organizations/" + organization + "/workflows", {
        "name": "Same benefit under another workflow", "department": "Support", "unit": "claim",
        "benefit_pool": "pool_a",
    }, 409)


@pytest.mark.parametrize(("low_minutes", "benefit_low", "net_low", "roi_low"), [
    (6, 32_400, -9_600, D(-9_600)/42_000),
    (7, 37_800, -4_200, D(-4_200)/42_000),
])
def test_customer_support_recalculation_matches_independent_model(client, low_minutes, benefit_low, net_low, roi_low):
    payload = forecast(months=12, units_monthly=band(900, 1200), implementation_usd=band(8_000, 12_000),
                       fixed_model_usd_monthly=band(0), fixed_infrastructure_usd_monthly=band(80, 120),
                       maintenance_usd_monthly=band(250, 400), review_usd_per_unit=band("1.5", "2.1"),
                       rework_usd_per_unit=band(3, 5), model_usd_per_unit=band(".14", ".23"),
                       infrastructure_usd_per_unit=band(".04", ".08"), review_fraction=band(".25", ".4"),
                       rework_fraction=band(".05", ".1"))
    manual = baseline() | {"manual_cost_usd_per_unit": band(D(low_minutes) * 30 / 60, "4.8")}
    got = preview(client, payload, manual)["estimates"]
    check(got["period_operating_usd"], 11_574, 30_000)
    check(got["period_benefit_usd"], benefit_low, 69_120)
    check(got["period_net_benefit_usd"], net_low, 49_546)
    check(got["roi_ratio"], roi_low, D(49_546)/19_574)
    assert D(got["payback_months"]["earliest"]) == D(96_000)/57_546
    assert D(got["payback_months"]["latest"]) == D(144_000)/(benefit_low - 30_000)


def test_legacy_invoice_analysis_charges_failed_attempts_and_manual_fallback():
    metrics = {"attempts": 10, "processed": 8, "failed": 2, "unclassified": 0, "review": 2,
               "unknown_model_cost_runs": 1, "covered_model_cost_usd": D(2)}
    inputs = Assumptions(evidence_source="Fixture", manual_minutes=band(6), review_minutes=band(3),
                         hourly_labor_usd=band(60), overhead_usd_per_attempt=band(".5"))
    assert estimate(metrics, inputs)["status"] == "missing_cost_assumption"
    inputs.unknown_model_cost_usd_per_attempt = type(inputs.manual_minutes)(low=1, high=1)
    result = estimate(metrics, inputs)["scenarios"][0]
    assert result["manual_cost_usd"] == 60
    assert result["fallback_cost_usd"] == 12
    assert result["review_cost_usd"] == 6
    assert result["operating_cost_usd"] == 26
    assert result["operating_cost_per_processed_usd"] == D("3.25")
    assert result["net_savings_usd"] == 34
    assert result["roi_ratio"] == D(34)/26

def test_negative_outcome_can_reduce_benefits_below_zero(client):
    inputs = forecast(outcome_valuation={"escalated": {"direction": -1, "usd_per_metric_unit": band(8)}},
                      expected_outcomes_per_unit={"escalated": band(1)})
    got = preview(client, inputs, baseline(5, escalated=band(0)))["estimates"]
    check(got["benefit_breakdown_usd"]["escalated"], -160)
    check(got["period_benefit_usd"], -60)
    check(got["period_net_benefit_usd"], -147)
    check(got["roi_ratio"], D(-147)/87)


def test_customer_support_bounds_are_conservative_when_volume_is_shared():
    # Independent coherent scenarios use the same ticket volume on both sides of the equation.
    from itertools import product

    for low_minutes, expected_net in ((6, (-3660, 47008)), (7, (1740, 47008))):
        net = []
        for n, value, variable, fixed, setup in product(
            (10_800, 14_400), (D(low_minutes) / 2, D("4.8")), (D(".705"), D("1.65")),
            (3_960, 6_240), (8_000, 12_000),
        ):
            net.append(n * (value - variable) - fixed - setup)
        assert (min(net), max(net)) == expected_net
