import json
from decimal import Decimal
from secrets import token_urlsafe
from uuid import uuid4

import httpx
import pytest

from invoice_agent import provider
from main import app
from settings import Settings, get_settings


@pytest.fixture
def probe(client, monkeypatch):
    model = "synthetic-test-model"
    config = Settings(support_live_probe_enabled=True, llm_model=model,
                      llm_api_key=token_urlsafe(24), workspace_api_key=token_urlsafe(24))
    app.dependency_overrides[get_settings] = lambda: config
    monkeypatch.setenv("LLM_PRICING_JSON", json.dumps({
        f"openai:{model}": {"input_per_million": "2", "output_per_million": "4", "currency": "USD",
                            "effective_date": "2024-01-01", "source": "Synthetic pricing fixture"},
    }))
    org = client.post("/portfolio/organizations", json={"name": "Probe test"}).json()
    workflow = client.post(f"/portfolio/organizations/{org['id']}/workflows", json={
        "name": "Support", "department": "Operations", "unit": "ticket", "benefit_pool": "support",
    }).json()
    deployment = client.post(f"/portfolio/workflows/{workflow['id']}/deployments", json={
        "name": "Probe", "adapter": "customer_support_probe",
    }).json()
    node = deployment["id"]
    return config, f"/adapters/customer-support/deployments/{node}/synthetic-probes/{uuid4()}", node, workflow["id"]


def mock_transport(monkeypatch, handler):
    calls = []

    def counted(request):
        calls.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(provider, "Client", lambda **kwargs: httpx.Client(
        transport=httpx.MockTransport(counted), **kwargs,
    ))
    return calls


def output(request, model="synthetic-test-model", usage=None, category="account_access"):
    body = {"model": model, "choices": [{"finish_reason": "stop",
                                        "message": {"content": json.dumps({"category": category})}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body, headers={"x-request-id": "req_mock"}, request=request)


def send(client, path):
    response = client.post(path, json={"authorize_live_request": True})
    assert response.status_code == 200, response.status_code
    return response.json()


def test_probe_persists_provider_evidence_and_deduplicates(client, monkeypatch, probe):
    config, path, deployment, _ = probe

    def handler(request):
        assert request.headers["authorization"].startswith("Bearer ")
        payload = json.loads(request.content)
        assert payload["max_completion_tokens"] == 128
        assert payload["model"] == config.llm_model
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert "Synthetic ticket" in payload["messages"][1]["content"]
        assert "password" in payload["messages"][1]["content"]
        return output(request, usage={"prompt_tokens": 120, "completion_tokens": 30, "cost": "123"})

    calls = mock_transport(monkeypatch, handler)
    first = send(client, path)
    assert send(client, path)["id"] == first["id"]
    assert calls == ["https://api.openai.com/v1/chat/completions"]
    values = first["telemetry"]
    item = values["provider_evidence"]
    assert (values["input_tokens"], values["output_tokens"]) == (120, 30)
    assert values["succeeded"] is True and values["data_origin"] == "synthetic"
    assert values["model_charge_usd"] is None
    assert Decimal(values["estimated_model_usd"]) == Decimal("0.00036")
    assert item["provider_request_id"] == "req_mock"
    assert item["reported_model"] == config.llm_model
    assert item["status"] == "success" and item["duration_ms"] >= 0
    assert item["pricing"]["source"] == "Synthetic pricing fixture"
    assert item["pricing"]["currency"] == "USD" and item["pricing"]["effective_date"] == "2024-01-01"
    assert config.llm_api_key.get_secret_value() not in json.dumps(first)
    recent = client.get(f"/portfolio/deployments/{deployment}/executions").json()
    assert recent[0]["execution"]["telemetry"] == values
    assert recent[0]["outcomes"] == {}


@pytest.mark.parametrize(("case", "code", "provider_status"), [
    ("timeout", "provider_timeout", None),
    ("rate_limit", "provider_http_error", 429),
    ("bad_output", "invalid_provider_output", 200),
    ("wrong_classification", "unexpected_classification", 200),
])
def test_failure_is_recorded_without_retry_or_raw_body(client, monkeypatch, probe, case, code, provider_status):
    _, path, _, _ = probe

    def handler(request):
        if case == "timeout":
            raise httpx.ReadTimeout("Untrusted diagnostic", request=request)
        if case == "rate_limit":
            return httpx.Response(429, text="Untrusted diagnostic", headers={"x-request-id": "req_limit"}, request=request)
        if case == "bad_output":
            return httpx.Response(200, text="Untrusted diagnostic", request=request)
        return output(request, category="billing", usage={"prompt_tokens": 120, "completion_tokens": 30})

    calls = mock_transport(monkeypatch, handler)
    row = send(client, path)
    assert send(client, path)["id"] == row["id"]
    item = row["telemetry"]["provider_evidence"]
    assert item["status"] == "failure" and item["error_code"] == code
    assert item["provider_http_status"] == provider_status and item["duration_ms"] >= 0
    assert len(calls) == 1 and "Untrusted diagnostic" not in json.dumps(row)
    if case == "rate_limit":
        assert item["provider_request_id"] == "req_limit"
    if case == "wrong_classification":
        assert Decimal(row["telemetry"]["estimated_model_usd"]) == Decimal("0.00036")


@pytest.mark.parametrize(("usage", "model", "tokens"), [
    (None, "synthetic-test-model", (None, None)),
    ({"prompt_tokens": 120}, "synthetic-test-model", (120, None)),
    ({"prompt_tokens": 120, "completion_tokens": 30}, "unpriced-response-snapshot", (120, 30)),
])
def test_missing_usage_or_exact_pricing_leaves_cost_unknown(client, monkeypatch, probe, usage, model, tokens):
    _, path, _, _ = probe
    mock_transport(monkeypatch, lambda request: output(request, model=model, usage=usage))
    data = send(client, path)["telemetry"]
    assert data["succeeded"] is True
    assert (data["input_tokens"], data["output_tokens"]) == tokens
    assert data["estimated_model_usd"] is None and data["model_charge_usd"] is None


def test_missing_configuration_or_authorization_sends_nothing(client, monkeypatch, probe):
    config, path, deployment, _ = probe
    assert client.post(path, json={"authorize_live_request": False}).status_code == 422
    assert client.post(path, json={"authorize_live_request": 1}).status_code == 422
    calls = mock_transport(monkeypatch, lambda request: pytest.fail("Unexpected outbound call"))
    app.dependency_overrides[get_settings] = lambda: Settings()
    assert "disabled" in client.post(path, json={"authorize_live_request": True}).json()["detail"]
    app.dependency_overrides[get_settings] = lambda: Settings(support_live_probe_enabled=True)
    assert "credential" in client.post(path, json={"authorize_live_request": True}).json()["detail"]
    app.dependency_overrides[get_settings] = lambda: Settings(
        support_live_probe_enabled=True, llm_api_key=token_urlsafe(24),
    )
    assert "workspace access key" in client.post(path, json={"authorize_live_request": True}).json()["detail"]
    app.dependency_overrides[get_settings] = lambda: config
    monkeypatch.setenv("LLM_PRICING_JSON", "{}")
    assert "dated USD pricing" in client.post(path, json={"authorize_live_request": True}).json()["detail"]
    assert calls == []
    assert client.get(f"/portfolio/deployments/{deployment}/executions").json() == []


def test_probe_deployment_disallows_external_telemetry(client, probe):
    _, _, deployment, _ = probe
    response = client.post(f"/portfolio/deployments/{deployment}/executions", json={
        "external_run_id": str(uuid4()), "units": 1, "reviewed_units": 0, "reworked_units": 0,
        "succeeded": True,
    })
    assert response.status_code == 422



def test_duplicate_while_provider_call_is_pending_never_sends_again(client, monkeypatch, probe):
    _, path, _, _ = probe

    def handler(request):
        pending = send(client, path)["telemetry"]
        assert pending["provider_evidence"]["status"] == "pending"
        assert pending["model_invoked"] is None
        return output(request, usage={"prompt_tokens": 10, "completion_tokens": 2})

    calls = mock_transport(monkeypatch, handler)
    assert send(client, path)["telemetry"]["provider_evidence"]["status"] == "success"
    assert len(calls) == 1
