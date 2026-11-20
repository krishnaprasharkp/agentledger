import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import insert

from database import get_db
from db_models import AgentEventRecord
from main import app
from public_demo import create_public_demo
from security import WorkspaceSecurity
from settings import Settings

PREVIEW = {
    "evidence": "Synthetic fixture", "months": 12,
    "baseline": {"name": "Manual", "evidence": "Synthetic", "manual_cost_usd_per_unit": {"low": 4, "high": 4}},
    **{key: {"low": 0, "high": 0} for key in (
        "implementation_usd", "fixed_model_usd_monthly", "fixed_infrastructure_usd_monthly", "maintenance_usd_monthly",
        "review_usd_per_unit", "rework_usd_per_unit", "review_fraction", "rework_fraction",
        "model_usd_per_unit", "infrastructure_usd_per_unit",
    )},
    "units_monthly": {"low": 100, "high": 100},
}


def test_public_preview_and_synthetic_project_do_not_invoke_database():
    public = create_public_demo()

    def unexpected_database_call():
        pytest.fail("Public route tried to open a database session.")

    public.dependency_overrides[get_db] = unexpected_database_call
    with TestClient(public) as client:
        assert client.get("/app-mode").json() == {"public_demo": True}
        assert client.get("/health").status_code == 200
        sample = client.get("/demo/portfolio").json()
        assert len(sample["details"]) == 2
        assert sample["organization"]["name"] == "Synthetic demo"
        assert all(a["snapshot"]["measured"] is None for item in sample["details"] for a in item["analyses"])
        estimate = client.post("/demo/forecasts/preview", json=PREVIEW)
        assert estimate.status_code == 200
        assert estimate.json()["estimates"]["period_net_benefit_usd"] == {"low": "4800", "high": "4800"}
        assert client.get("/demo/portfolio").json() == sample
        validation = client.post("/demo/forecasts/preview", json={"evidence": "Not persisted"})
        assert validation.status_code == 422 and "Not persisted" not in validation.text


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/portfolio/organizations"), ("GET", "/portfolio/workflows/example"),
    ("GET", "/portfolio/deployments/example/executions"), ("POST", "/portfolio/organizations"),
    ("POST", "/portfolio/organizations/example/workflows"), ("POST", "/portfolio/organizations/example/rollup"),
    ("POST", "/portfolio/workflows/example/forecasts"), ("POST", "/portfolio/deployments/example/executions"),
    ("GET", "/analytics/overview"), ("GET", "/events"), ("POST", "/events"),
    ("POST", "/invoices/process"), ("POST", "/invoices/upload"),
    ("POST", "/adapters/customer-support/deployments/example/synthetic-probes/example"),
    ("GET", "/docs"), ("GET", "/openapi.json"),
])
def test_public_rejects_private_reads_and_writes_even_with_header(method, path):
    with TestClient(create_public_demo()) as client:
        for headers in ({}, {"X-Workspace-Key": "irrelevant-fixture"}):
            assert client.request(method, path, headers=headers).status_code in (401, 404)


def test_private_settings_and_middleware_fail_closed(client):
    with pytest.raises(ValidationError, match="requires WORKSPACE_API_KEY"):
        Settings(app_mode="private")
    with pytest.raises(ValidationError, match="must not have provider"):
        Settings(app_mode="public_demo", support_live_probe_enabled=True)
    with TestClient(WorkspaceSecurity(app, require_key=True)) as locked:
        assert locked.get("/events").status_code == 401
        assert locked.post("/portfolio/organizations", json={"name": "No"}).status_code == 401
    with TestClient(WorkspaceSecurity(app, require_key=True, key="private-fixture")) as locked:
        assert locked.get("/events").status_code == 401
        assert locked.get("/events", headers={"X-Workspace-Key": "private-fixture"}).status_code == 200


def test_request_and_event_listing_bounds(client):
    with TestClient(create_public_demo()) as public:
        assert public.post("/demo/forecasts/preview", content=b"x" * (16 * 1024 + 1)).status_code == 413
        assert public.post("/demo/forecasts/preview", content=iter([b"x" * 8192, b"y" * 8193])).status_code == 413
    with next(app.dependency_overrides[get_db]()) as db:
        db.execute(insert(AgentEventRecord), [{
            "agent_id": "fixture", "model": "fixture", "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "status": "success",
        }] * 110)
        db.commit()
    assert len(client.get("/events").json()) == 100
    assert len(client.get("/events", params={"offset": 100}).json()) == 10
    assert client.get("/events", params={"limit": 1001}).status_code == 422
    assert client.get("/events", params={"offset": 100001}).status_code == 422
