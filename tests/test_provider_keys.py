"""Runtime provider-key application (used by the Settings UI; keychain persistence is in Rust)."""

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


def _avail(body: dict) -> dict[str, bool]:
    return {p["provider"]: p["available"] for p in body["providers"]}


def test_setting_a_key_makes_provider_available(client: TestClient) -> None:
    before = _avail(client.get("/providers").json())
    assert before["gemini"] is False and before["groq"] is False

    after = _avail(client.post("/providers/keys", json={"gemini": "fake-key", "groq": "g"}).json())
    assert after["gemini"] is True and after["groq"] is True
    assert after["openrouter"] is False  # untouched (None) stays disabled


def test_clearing_a_key_disables_provider(client: TestClient) -> None:
    client.post("/providers/keys", json={"openrouter": "k"})
    assert _avail(client.get("/providers").json())["openrouter"] is True
    client.post("/providers/keys", json={"openrouter": ""})  # empty string clears
    assert _avail(client.get("/providers").json())["openrouter"] is False


def test_mock_and_ollama_unaffected(client: TestClient) -> None:
    after = _avail(client.post("/providers/keys", json={"gemini": "x"}).json())
    assert after["mock"] is True  # local/mock providers are never touched by key updates
