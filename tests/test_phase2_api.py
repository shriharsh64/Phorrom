"""Phase 2 API tests via TestClient: projects, problem, tasks, governed file writes."""

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


def test_project_lifecycle_and_problem(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    assert any(p["id"] == pid for p in client.get("/projects").json()["projects"])

    r = client.post("/problem/define", json={"project_id": pid, "description": "an app for stuff"})
    assert r.status_code == 200
    assert r.json()["latest"]["statement"]


def test_tasks_ranked_by_priority(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    client.post("/tasks", json={"project_id": pid, "title": "low", "urgency": 0.1, "impact": 0.1})
    high = client.post("/tasks", json={"project_id": pid, "title": "high", "urgency": 1.0, "impact": 1.0}).json()["id"]
    tasks = client.get("/tasks", params={"project_id": pid}).json()["tasks"]
    assert tasks[0]["id"] == high  # highest priority first
    assert "ready" in tasks[0]


def test_governed_write_requires_root_and_approval(client: TestClient, tmp_path) -> None:
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    # No root yet -> writes are refused.
    assert client.post("/files/propose", json={"project_id": pid, "path": "a.txt", "content": "x"}).status_code == 409

    client.post(f"/projects/{pid}/root", json={"root_path": str(tmp_path)})
    prop = client.post("/files/propose", json={
        "project_id": pid, "path": "notes/log.md", "content": "# Log\n", "reason": "demo",
    }).json()
    assert "diff" in prop and (tmp_path / "notes" / "log.md").exists() is False  # not written yet

    client.post(f"/files/commit/{prop['id']}")
    assert (tmp_path / "notes" / "log.md").read_text(encoding="utf-8") == "# Log\n"


def test_path_escape_rejected_via_api(client: TestClient, tmp_path) -> None:
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    client.post(f"/projects/{pid}/root", json={"root_path": str(tmp_path)})
    r = client.post("/files/read", json={"project_id": pid, "path": "../../etc/passwd"})
    assert r.status_code == 400
