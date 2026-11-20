from datetime import datetime, timedelta, timezone
from decimal import Decimal

from evaluate import corpus, pdf
from main import app
from settings import Settings, get_settings


def bounds(low, high=None):
    return {"low": low, "high": low if high is None else high}


def create(client, path, payload):
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def workflow(client, org, name, adapter, metric):
    flow = create(client, f"/portfolio/organizations/{org}/workflows", {
        "name": name, "department": "Operations", "unit": "request", "benefit_pool": adapter,
        "outcome_metrics": [metric],
    })["id"]
    path = f"/portfolio/workflows/{flow}"
    baseline = create(client, path + "/baselines", {
        "name": "Manual handling", "evidence": "Synthetic test fixture",
        "manual_cost_usd_per_unit": bounds(10), "outcome_per_unit": {metric: bounds(0)},
    })["id"]
    deployment = create(client, path + "/deployments", {"name": name, "adapter": adapter})["id"]
    return path, baseline, deployment


def economics(baseline):
    return {
        "baseline_id": baseline, "evidence": "Synthetic test fixture", "implementation_usd": bounds(5),
        "fixed_model_usd_monthly": bounds(0), "fixed_infrastructure_usd_monthly": bounds(0),
        "maintenance_usd_monthly": bounds(0), "review_usd_per_unit": bounds(2),
        "rework_usd_per_unit": bounds(1),
    }


def forecast(baseline):
    return economics(baseline) | {
        "months": 1, "units_monthly": bounds(4), "review_fraction": bounds(0.5),
        "rework_fraction": bounds(0), "model_usd_per_unit": bounds(1), "infrastructure_usd_per_unit": bounds(0),
    }


def test_forecast_and_rollup_count_shared_cost_once(client):
    org = create(client, "/portfolio/organizations", {"name": "Test organization"})["id"]
    invoice, baseline, _ = workflow(client, org, "Invoice processing", "invoice", "validation_passed")
    ticket, ticket_baseline, _ = workflow(client, org, "IT service desk", "service_desk", "resolved")
    first = create(client, invoice + "/forecasts", forecast(baseline))
    second = create(client, ticket + "/forecasts", forecast(ticket_baseline))
    assert first["snapshot"]["measured"] is None
    assert Decimal(first["snapshot"]["estimates"]["period_net_benefit_usd"]["low"]) == 27
    shared = {"key": "hosting", "kind": "recurring_cost", "usd": bounds(3), "evidence": "Synthetic"}
    payload = {"analysis_ids": [first["id"], second["id"]], "shared_items": [shared],
               "disjoint_attribution_confirmed": True}
    endpoint = f"/portfolio/organizations/{org}/rollup"
    result = client.post(endpoint, json=payload)
    assert result.status_code == 200, result.text
    assert Decimal(result.json()["estimates"]["period_net_benefit_usd"]["low"]) == 51
    assert client.post(endpoint, json=payload | {"shared_items": [shared, shared]}).status_code == 422
    assert client.post(endpoint, json=payload | {"shared_items": [shared | {"key": "invoice"}]}).status_code == 422
    assert client.post(endpoint, json=payload | {"analysis_ids": [first["id"], first["id"]]}).status_code == 422
    assert client.post(endpoint, json=payload | {"disjoint_attribution_confirmed": False}).status_code == 422
    assert client.post(ticket + "/forecasts", json=forecast(baseline)).status_code == 422


def test_service_desk_measures_outcome_and_cost_without_mixing_estimates(client):
    org = create(client, "/portfolio/organizations", {"name": "Test organization"})["id"]
    path, baseline, deployment = workflow(client, org, "IT service desk", "service_desk", "resolved")
    now = datetime.now(timezone.utc)
    ticket = {
        "ticket_run_id": "external-id", "opened_at": (now - timedelta(hours=1)).isoformat(),
        "resolved_at": (now - timedelta(minutes=1)).isoformat(), "escalated": False,
        "reopened": False, "human_reviewed": True, "model_charge_usd": "0.05",
        "infrastructure_charge_usd": "0.10", "data_origin": "synthetic",
    }
    endpoint = f"/adapters/service-desk/deployments/{deployment}/tickets"
    create(client, endpoint, ticket)
    assert client.post(endpoint, json=ticket).status_code == 409
    result = create(client, path + "/assessments", economics(baseline) | {
        "deployment_id": deployment, "start": (now - timedelta(days=1)).isoformat(), "end": now.isoformat(),
        "outcome_valuation": {"resolved": {"direction": 1, "usd_per_metric_unit": bounds(3)}},
    })["snapshot"]
    assert result["measured"]["outcomes"] == {"resolved": "1"}
    assert result["measured"]["data_origin"] == "synthetic"
    assert Decimal(result["measured"]["model_charge_usd"]) == Decimal("0.05")
    assert Decimal(result["estimates"]["period_net_benefit_usd"]["low"]) == Decimal("5.85")
    assert result["estimates"]["payback_months"]["earliest"] is not None


def test_invoice_adapter_preserves_original_run_and_tracks_uncertainty(client):
    org = create(client, "/portfolio/organizations", {"name": "Test organization"})["id"]
    path, baseline, deployment = workflow(client, org, "Invoice processing", "invoice", "validation_passed")
    app.dependency_overrides[get_settings] = lambda: Settings(invoice_deployment_id=deployment)
    response = client.post("/invoices/process", files={
        "file": ("invoice.pdf", pdf(corpus()[1]), "application/pdf"),
    })
    assert response.status_code == 200, response.text
    run_id = response.json()["execution"]["run_id"]
    rows = client.get(f"/portfolio/deployments/{deployment}/executions").json()
    assert rows[0]["execution"]["external_run_id"] == run_id
    assert rows[0]["execution"]["telemetry"]["reviewed_units"] == 1
    assert rows[0]["outcomes"] == {"validation_passed": "0"}
    now = datetime.now(timezone.utc)
    request = economics(baseline) | {
        "deployment_id": deployment, "start": (now - timedelta(days=1)).isoformat(), "end": now.isoformat(),
    }
    assert client.post(path + "/assessments", json=request).status_code == 422
    estimate = create(client, path + "/assessments", request | {
        "missing_infrastructure_usd_per_execution": bounds(0, 1),
    })["snapshot"]["estimates"]
    assert Decimal(estimate["period_net_benefit_usd"]["low"]) == 2
    assert Decimal(estimate["period_net_benefit_usd"]["high"]) == 3


def test_forecast_preview_reuses_calculation_without_writing_records(client):
    org = create(client, "/portfolio/organizations", {"name": "Test organization"})["id"]
    path, baseline_id, _ = workflow(client, org, "Support", "service_desk", "resolved")
    payload = forecast(baseline_id) | {"implementation_usd": bounds(5, 80)}
    baseline = {
        "name": "Manual handling", "evidence": "Illustrative support inputs",
        "manual_cost_usd_per_unit": bounds(10),
    }
    before = client.get(path).json()
    preview = client.post("/portfolio/forecasts/preview", json={
        **{key: value for key, value in payload.items() if key != "baseline_id"}, "baseline": baseline,
    })
    assert preview.status_code == 200, preview.text
    assert client.get(path).json() == before
    assert preview.json()["estimates"] == create(client, path + "/forecasts", payload)["snapshot"]["estimates"]
    net = preview.json()["estimates"]["period_net_benefit_usd"]
    assert Decimal(net["low"]) < 0 < Decimal(net["high"])
