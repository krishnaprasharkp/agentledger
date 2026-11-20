def sample_event():
    return {
        "agent_id": "invoice-agent-001",
        "model": "test-model",
        "input_tokens": 1500,
        "output_tokens": 350,
        "latency_ms": 2200,
        "status": "success",
    }


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_event(client):
    response = client.post(
        "/events", json=sample_event()
    )

    assert response.status_code == 201
    assert "run_id" in response.json()
    assert "created_at" in response.json()


def test_retrieve_event(client):
    created = client.post(
        "/events", json=sample_event()
    )

    response = client.get("/events")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert (
        response.json()[0]["run_id"]
        == created.json()["run_id"]
    )


def test_negative_tokens(client):
    payload = sample_event()
    payload["input_tokens"] = -100

    response = client.post(
        "/events", json=payload
    )

    assert response.status_code == 422
    assert client.get("/events").json() == []


def test_invalid_status(client):
    payload = sample_event()
    payload["status"] = "unknown"

    response = client.post(
        "/events", json=payload
    )

    assert response.status_code == 422
