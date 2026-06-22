"""Orchestrator API test — end-to-end run that decomposes, budgets, and (optionally) executes."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config


def make_client(responder=None) -> TestClient:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    app = create_app(cfg)
    if responder is not None:
        # swap the mock provider for a scripted one so decomposition returns a real DAG
        from sidecar.providers.mock import MockProvider
        from sidecar.providers.registry import ProviderRegistry
        app.state.registry = ProviderRegistry([MockProvider(responder=responder)])
    return TestClient(app)


def test_orchestrate_decomposes_and_budgets() -> None:
    client = make_client()
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    r = client.post("/orchestrate", json={"project_id": pid, "task": "Build a dashboard", "budget": 4000})
    assert r.status_code == 200
    body = r.json()
    assert len(body["subtasks"]) >= 2
    assert body["budget"]["available"] <= 4000
    assert body["budget"]["total_metered_tokens"] <= body["budget"]["available"]
    # subtasks were persisted
    subs = client.get("/orchestrate/subtasks", params={"task_id": body["task_id"]}).json()["subtasks"]
    assert len(subs) == len(body["subtasks"])


def test_orchestrate_routes_subtasks_to_models_and_executes() -> None:
    dag = {"subtasks": [
        {"id": "code", "type": "coding", "depends_on": [], "size_hint": 800, "value": 0.9,
         "p_required": 1.0, "quality_sensitivity": 1.0, "description": "write code"},
        {"id": "sum", "type": "summarization", "depends_on": [], "size_hint": 300, "value": 0.4,
         "p_required": 1.0, "quality_sensitivity": 0.1, "description": "summarize"},
    ]}
    client = make_client(responder=lambda m, model: json.dumps(dag))
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    body = client.post("/orchestrate", json={
        "project_id": pid, "task": "Ship feature", "budget": 5000, "execute": True,
    }).json()
    picks = {a["subtask"]: a["model"] for a in body["assignments"]}
    # The coding subtask should route to the stronger coding model; summary to the cheap one.
    assert picks["code"] == "mock-large"
    assert picks["sum"] == "mock-small"
    assert body["outputs"]  # execution produced output and recorded runs
