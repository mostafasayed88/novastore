"""HTTP API tests via FastAPI TestClient (offline: USE_MOCK_LLM is forced
in conftest before the app module is imported)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from novastore.api.app import create_app

    return TestClient(create_app())


def test_health():
    with _client() as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mock_llm"] is True


def test_customers_endpoint_lists_seeded_demo_ids():
    with _client() as client:
        response = client.get("/api/customers")
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert "cust_001" in ids


def test_chat_tracking_round_trip():
    with _client() as client:
        response = client.post(
            "/api/chat",
            json={"customer_id": "cust_001", "message": "Where is order 5482?"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "order_tracking"
    assert "shipped" in body["reply"].lower()
    assert body["data"]["order_id"] == "5482"


def test_chat_session_continues_transcript():
    with _client() as client:
        client.post("/api/chat", json={"customer_id": "cust_001", "message": "hello"})
        response = client.post(
            "/api/chat",
            json={
                "customer_id": "cust_001",
                "message": "Is iPhone 15 available?",
                "session_id": "sess_http_1",
            },
        )
        assert response.status_code == 200
        sessions = client.get("/api/admin/conversations").json()
        transcript = client.get("/api/admin/conversations/sess_http_1").json()
    assert any(s["session_id"] == "sess_http_1" for s in sessions)
    assert len(transcript) >= 2  # customer + agent messages recorded


def test_admin_endpoints_shape():
    with _client() as client:
        overview = client.get("/api/admin/overview").json()
        orders = client.get("/api/admin/orders").json()
        tickets = client.get("/api/admin/tickets").json()
        leads = client.get("/api/admin/leads").json()
    assert overview["orders"] >= 10
    assert {"order_id", "status"} <= set(orders[0])
    assert {"id", "subject"} <= set(tickets[0])
    assert {"id", "company"} <= set(leads[0])


def test_whatsapp_verify_rejects_wrong_token():
    with _client() as client:
        response = client.get(
            "/webhook/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
        )
    assert response.status_code == 403


def test_whatsapp_inbound_stub_is_501():
    with _client() as client:
        response = client.post("/webhook/whatsapp", json={})
    assert response.status_code == 501
    assert "docs/whatsapp.md" in response.json()["how"]
