"""API tests — exercise the FastAPI app end-to-end via TestClient, mock provider only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config


@pytest.fixture()
def client() -> TestClient:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    return TestClient(create_app(cfg))


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_providers_lists_mock_available(client: TestClient) -> None:
    resp = client.get("/providers")
    assert resp.status_code == 200
    by_name = {p["provider"]: p for p in resp.json()["providers"]}
    assert by_name["mock"]["available"] is True
    assert by_name["gemini"]["available"] is False


def test_chat_roundtrip_persists_history(client: TestClient) -> None:
    payload = {
        "messages": [{"role": "user", "content": "ping"}],
        "provider": "mock",
        "model": "mock-small",
    }
    resp = client.post("/chat", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "[mock:mock-small] ping"
    assert body["tokens_out"] > 0

    hist = client.get("/chat/history").json()["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant"]


def test_chat_unknown_provider_404(client: TestClient) -> None:
    payload = {"messages": [{"role": "user", "content": "x"}], "provider": "nope", "model": "m"}
    assert client.post("/chat", json=payload).status_code == 404


def test_auth_enforced_when_token_set() -> None:
    cfg = Config(db_path=":memory:", auth_token="secret", gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    c = TestClient(create_app(cfg))
    assert c.get("/health").status_code == 401
    assert c.get("/health", headers={"Authorization": "Bearer secret"}).status_code == 200
