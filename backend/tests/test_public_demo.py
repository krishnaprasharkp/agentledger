import asyncio
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import insert

from database import engine, get_db
from db_models import AgentEventRecord
from main import app
from public_demo import create_public_demo
import security
from security import DEMO_PREVIEW_PATH, PreviewBudget, PublicDemoSecurity, WorkspaceSecurity
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


def test_public_preview_and_synthetic_project_do_not_invoke_database(monkeypatch):
    public = create_public_demo()

    def unexpected_database_call():
        pytest.fail("Public route tried to open a database session.")

    public.dependency_overrides[get_db] = unexpected_database_call
    monkeypatch.setattr(engine, "connect", unexpected_database_call)
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
    with TestClient(WorkspaceSecurity(app, require_key=True)) as locked:
        assert locked.get("/events").status_code == 401
        assert locked.post("/portfolio/organizations", json={"name": "No"}).status_code == 401
    with TestClient(WorkspaceSecurity(app, require_key=True, key="private-fixture")) as locked:
        assert locked.get("/events").status_code == 401
        assert locked.get("/events", headers={"X-Workspace-Key": "private-fixture"}).status_code == 200


@pytest.mark.parametrize("configuration", [
    {"support_live_probe_enabled": True},
    {"extraction_provider": "openai"},
    {"llm_api_key": "unused-provider-fixture"},
    {"workspace_api_key": "unused-workspace-fixture"},
])
def test_demo_refuses_provider_and_workspace_configuration(configuration):
    with pytest.raises(ValidationError, match="must not have provider") as error:
        Settings(app_mode="public_demo", **configuration)
    assert "unused-" not in str(error.value)


def test_demo_database_engine_ignores_configured_workspace_dsn():
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "from database import engine; "
         "assert (engine.url.drivername, engine.url.host, engine.url.database) == ('sqlite+pysqlite', None, ':memory:')"],
        env=os.environ | {"APP_MODE": "public_demo", "DATABASE_URL": "postgresql+psycopg://unused.invalid/demo"},
        capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_preview_budget_is_atomic_under_concurrent_requests(monkeypatch):
    monkeypatch.setattr(security, "monotonic", lambda: 100)
    budget = PreviewBudget()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: budget.consume(), range(30)))
    assert results.count(0) == 12
    assert results.count(2) == 18


def test_preview_budget_ignores_forwarding_headers_and_refills(monkeypatch):
    now = 100
    monkeypatch.setattr(security, "monotonic", lambda: now)
    with TestClient(create_public_demo()) as client:
        for index in range(12):
            response = client.post(DEMO_PREVIEW_PATH, json={}, headers={
                "Forwarded": f"for=192.0.2.{index}",
                "X-Forwarded-For": f"192.0.2.{index}",
                "X-Real-IP": f"192.0.2.{index}",
                "CF-Connecting-IP": f"192.0.2.{index}",
            })
            assert response.status_code == 422

        def unread_body():
            pytest.fail("The throttled request body was read.")
            yield b""

        refused = client.post(DEMO_PREVIEW_PATH, content=unread_body(), headers={
            "Content-Type": "application/json", "X-Forwarded-For": "203.0.113.12",
        })
        assert refused.status_code == 429
        assert refused.headers["Retry-After"] == "2"
        assert refused.headers["Cache-Control"] == "no-store"
        assert client.get("/health").status_code == 200
        assert client.get("/demo/portfolio").status_code == 200
        now += 1
        assert client.post(DEMO_PREVIEW_PATH, json=PREVIEW).headers["Retry-After"] == "1"
        now += 1
        assert client.post(DEMO_PREVIEW_PATH, json=PREVIEW).status_code == 200
        assert client.post(DEMO_PREVIEW_PATH, json=PREVIEW).status_code == 429


def test_demo_security_headers_cover_success_and_public_errors():
    with TestClient(create_public_demo()) as client:
        responses = [
            (client.get("/health"), 200),
            (client.get("/portfolio/organizations"), 401),
            (client.get("/docs"), 404),
            (client.post(DEMO_PREVIEW_PATH, content=b"fixture", headers={"Content-Type": "text/plain"}), 415),
            (client.post(DEMO_PREVIEW_PATH, content=b'{"evidence": "fixture"', headers={
                "Content-Type": "application/json",
            }), 422),
            (client.post(DEMO_PREVIEW_PATH, content=b"x" * (16 * 1024 + 1), headers={
                "Content-Type": "application/json",
            }), 413),
        ]
        for response, status in responses:
            assert response.status_code == status
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["Referrer-Policy"] == "no-referrer"
            if response.request.url.path == DEMO_PREVIEW_PATH:
                assert response.headers["Cache-Control"] == "no-store"
                assert "fixture" not in response.text


def test_stalled_demo_preview_body_times_out_without_reaching_the_handler():
    async def verify():
        async def downstream(*args):
            pytest.fail("The forecast handler received an incomplete request.")

        async def stalled():
            await asyncio.Event().wait()

        messages = []

        async def collect(message):
            messages.append(message)

        middleware = PublicDemoSecurity(WorkspaceSecurity(downstream, body_timeout=0))
        await middleware({
            "type": "http", "path": DEMO_PREVIEW_PATH, "method": "POST",
            "headers": [(b"content-type", b"application/json")],
        }, stalled, collect)
        assert messages[0]["status"] == 408
        assert (b"cache-control", b"no-store") in messages[0]["headers"]

    asyncio.run(verify())


def test_request_and_event_listing_bounds(client):
    with TestClient(create_public_demo()) as public:
        headers = {"Content-Type": "application/json"}
        assert public.post(DEMO_PREVIEW_PATH, content=b"x" * (16 * 1024 + 1), headers=headers).status_code == 413
        assert public.post(DEMO_PREVIEW_PATH, content=iter([b"x" * 8192, b"y" * 8193]), headers=headers).status_code == 413
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
