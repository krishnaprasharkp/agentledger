import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from economics import Assumptions, estimate
from evaluate import corpus, pdf
from invoice_agent import provider
from main import app
from migrate import migrate
from security import MAX_REQUEST_BYTES, WorkspaceSecurity
from settings import Settings, get_settings


def invoice_request(client, case=0):
    return client.post(
        "/invoices/process",
        files={"file": ("invoice.pdf", pdf(corpus()[case]), "application/pdf")},
    )


def configure_provider(monkeypatch, handler, provider_name="openai", **overrides):
    settings = Settings(extraction_provider=provider_name, llm_api_key="test-key", **overrides)
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(provider, "Client", lambda **kwargs: httpx.Client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))


def provider_reply(request, *, fields=None, refusal=None, usage=None):
    if fields is None:
        fields = corpus()[0].expected
    return httpx.Response(200, request=request, headers={"x-request-id": "provider-request-1"}, json={
        "model": "invoice-model-version",
        "usage": usage if usage is not None else {"prompt_tokens": 1000, "completion_tokens": 200},
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(fields), "refusal": refusal}}],
    })


def test_strict_extraction_and_versioned_pricing(client, monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", json.dumps({
        "openai:invoice-model-version": {
            "input_per_million": "2", "output_per_million": "5", "source": "Test contract",
        },
    }))

    def handler(request):
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        spec = body["response_format"]["json_schema"]
        assert spec["strict"] and spec["schema"]["additionalProperties"] is False
        assert set(spec["schema"]["required"]) == set(corpus()[0].expected)
        assert "EVAL-001" in body["messages"][1]["content"]
        return provider_reply(request)

    configure_provider(monkeypatch, handler)
    response = invoice_request(client)
    assert response.status_code == 200
    result = response.json()
    execution = result["execution"]
    assert result["invoice"] == corpus()[0].expected
    assert result["validation"]["is_valid"] is True
    assert execution["usage_reported"] and execution["input_tokens"] == 1000 and execution["output_tokens"] == 200
    assert execution["model"] == "invoice-model-version"
    assert execution["model_latency_ms"] >= 0
    assert execution["provider_request_id"] == "provider-request-1"
    assert execution["provider_charge_usd"] is None
    assert Decimal(execution["estimated_cost_usd"]) == Decimal("0.003")
    assert execution["pricing"]["source"] == "Test contract"


def test_gateway_charge_remains_available_without_token_usage(client, monkeypatch):
    configure_provider(
        monkeypatch, lambda request: provider_reply(request, usage={"cost": 0.014}),
        provider_name="compatible", llm_usage_cost_is_usd=True,
    )
    response = invoice_request(client)
    result = response.json()["execution"]
    assert result["usage_reported"] is False
    assert Decimal(result["provider_charge_usd"]) == Decimal("0.014")
    metrics = client.get("/analytics/overview").json()["metrics"]
    assert metrics["provider_charge_runs"] == 1
    assert metrics["unknown_model_cost_runs"] == 0


@pytest.mark.parametrize(("kind", "status", "code"), [
    ("timeout", 504, "provider_timeout"),
    ("upstream", 503, "provider_http_error"),
    ("refusal", 422, "incomplete_extraction"),
    ("missing", 422, "missing_fields"),
    ("malformed", 502, "invalid_provider_output"),
])
def test_provider_failure_is_sanitized_and_tracked(client, monkeypatch, kind, status, code):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private details", request=request)
        if kind == "upstream":
            return httpx.Response(429, text="private details", headers={"x-request-id": "limit-id"}, request=request)
        if kind == "refusal":
            return provider_reply(request, refusal="private details")
        if kind == "missing":
            return provider_reply(request, fields={**corpus()[0].expected, "currency": None})
        return provider_reply(request, fields={"private details": True})

    configure_provider(monkeypatch, handler)
    response = invoice_request(client)
    assert response.status_code == status
    assert "private details" not in response.text
    assert "test-key" not in response.text
    events = client.get("/events").json()
    assert len(events) == 1
    assert events[0]["run_id"] == response.headers["x-run-id"]
    assert events[0]["error_code"] == code
    assert events[0]["status"] == "failure"
    assert events[0]["model_latency_ms"] is not None
    assert events[0]["usage_reported"] is (kind in {"refusal", "missing", "malformed"})
    if kind == "upstream":
        assert events[0]["provider_request_id"] == "limit-id"


def assumptions():
    return {
        "evidence_source": "Synthetic arithmetic test",
        "manual_minutes": {"low": 6, "high": 12},
        "review_minutes": {"low": 3, "high": 6},
        "hourly_labor_usd": {"low": 60, "high": 60},
        "overhead_usd_per_attempt": {"low": 1, "high": 2},
    }


def test_roi_uses_automatic_runs_and_manual_fallback(client):
    assert client.post("/analytics/roi", json=assumptions()).json()["status"] == "no_observations"
    assert invoice_request(client).status_code == 200
    assert invoice_request(client, 1).status_code == 200
    assert invoice_request(client, 4).status_code == 422
    result = client.post("/analytics/roi", json=assumptions()).json()
    metrics = result["observed"]
    assert (metrics["attempts"], metrics["processed"], metrics["passed"], metrics["review"], metrics["failed"]) == (3, 2, 1, 1, 1)
    assert metrics["model_cost_per_processed_usd"] == 0
    low, high = result["scenarios"]
    assert (low["manual_cost_usd"], low["fallback_cost_usd"], low["review_cost_usd"], low["net_savings_usd"]) == (18, 6, 6, 0)
    assert (high["manual_cost_usd"], high["fallback_cost_usd"], high["review_cost_usd"], high["net_savings_usd"]) == (36, 12, 3, 18)
    assert low["operating_cost_per_processed_usd"] == 9
    assert high["human_minutes_saved"] == 21
    assert result["roi_ratio_range"] == {"low": 0, "high": 1}
    assert result["assumptions"]["evidence_source"] == "Synthetic arithmetic test"


def test_roi_requires_a_range_for_unknown_model_cost():
    observed = {"attempts": 1, "unknown_model_cost_runs": 1, "failed": 1, "unclassified": 0,
                "review": 0, "processed": 0, "covered_model_cost_usd": Decimal(0)}
    assert estimate(observed, Assumptions.model_validate(assumptions()))["status"] == "missing_cost_assumption"
    inputs = assumptions() | {"unknown_model_cost_usd_per_attempt": {"low": 0.1, "high": 0.2}}
    low, high = estimate(observed, Assumptions.model_validate(inputs))["scenarios"]
    assert low["net_savings_usd"] == Decimal("-2.2")
    assert high["net_savings_usd"] == Decimal("-1.1")
    assert high["operating_cost_per_processed_usd"] is None


def test_existing_rows_survive_idempotent_migration():
    with create_engine("sqlite+pysqlite:///:memory:").begin() as connection:
        connection.execute(text(
            "CREATE TABLE agent_events (run_id CHAR(32) PRIMARY KEY, agent_id VARCHAR(255), "
            "model VARCHAR(255), input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, "
            "status VARCHAR(20), created_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO agent_events VALUES ('old-run', 'invoice-agent-v1', 'rule_based_v1',"
            "0, 0, 50, 'success', '2026-01-01')"
        ))
        engine = connection.engine
    try:
        migrate(engine)
        migrate(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT run_id, workflow FROM agent_events")).one() == ("old-run", None)
            assert connection.execute(text("SELECT count(*) FROM schema_migrations")).scalar_one() == 2
            assert "ix_agent_events_workflow_created_at" in {
                item["name"] for item in inspect(connection).get_indexes("agent_events")
            }
    finally:
        engine.dispose()


def test_workspace_key_and_body_limits(client):
    with TestClient(WorkspaceSecurity(app, key="private-key")) as protected:
        assert protected.get("/health").status_code == 200
        assert protected.get("/analytics/overview").status_code == 401
        assert protected.get("/events", headers={"X-Workspace-Key": "wrong"}).status_code == 401
        response = protected.get("/analytics/overview", headers={"X-Workspace-Key": "private-key"})
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        response = protected.post("/invoices/process", headers={"X-Workspace-Key": "private-key"},
                                  content=b"x" * (MAX_REQUEST_BYTES + 1))
        assert response.status_code == 413
        assert protected.get("/events", headers={"X-Workspace-Key": "private-key"}).json() == []
