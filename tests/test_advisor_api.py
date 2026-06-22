"""API tests for the advisor + ideation bridge, end-to-end via TestClient (mock provider)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.config import Config


@pytest.fixture()
def client() -> TestClient:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    c = TestClient(create_app(cfg))
    c.app_state_db = c.app.state.db  # type: ignore[attr-defined]
    return c


def _new_project(client: TestClient, name: str = "demo") -> int:
    return client.app.state.db.create_project(name)


def test_recommend_then_overview(client: TestClient) -> None:
    pid = _new_project(client)
    resp = client.post("/advisor/recommend", json={
        "project_id": pid,
        "context": {"problem": "smart irrigation", "tech": ["python", "iot"], "task_types": ["sensor"]},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["overview"]["resources"]
    assert body["overview"]["learning"]
    # progress block present and consistent
    prog = body["overview"]["progress"]
    assert prog["learning"]["total"] == len(body["overview"]["learning"])

    ov = client.get("/advisor/overview", params={"project_id": pid}).json()
    assert ov["progress"]["resources"]["total"] >= 1


def test_ideation_gap_flows_into_learning_plan(client: TestClient) -> None:
    pid = _new_project(client)
    g = client.post("/ideation/gaps", json={"project_id": pid, "concept": "PID control"})
    assert g.status_code == 200
    body = client.post("/advisor/recommend", json={"project_id": pid, "context": {"problem": "x"}}).json()
    concepts = [li["concept"] for li in body["overview"]["learning"]]
    assert "PID control" in concepts


def test_learning_status_masters_concept_and_feeds_back(client: TestClient) -> None:
    pid = _new_project(client)
    client.post("/advisor/recommend", json={"project_id": pid, "context": {"problem": "web app", "tech": ["react"]}})
    learning = client.get("/advisor/overview", params={"project_id": pid}).json()["learning"]
    # complete every item belonging to the first concept
    first_concept = learning[0]["concept"]
    for item in [li for li in learning if li["concept"] == first_concept]:
        r = client.post(f"/advisor/learning/{item['id']}/status", json={"status": "done"})
        assert r.status_code == 200

    mastered = client.get("/ideation/mastered", params={"project_id": pid}).json()["mastered"]
    assert first_concept in mastered


def test_invalid_status_rejected(client: TestClient) -> None:
    pid = _new_project(client)
    client.post("/advisor/recommend", json={"project_id": pid, "context": {"problem": "x"}})
    learning = client.get("/advisor/overview", params={"project_id": pid}).json()["learning"]
    r = client.post(f"/advisor/learning/{learning[0]['id']}/status", json={"status": "nonsense"})
    assert r.status_code == 422


def test_resource_status_404_for_missing(client: TestClient) -> None:
    r = client.post("/advisor/resources/99999/status", json={"status": "done"})
    assert r.status_code == 404


def test_recommend_returns_breakthroughs_and_status_update(client: TestClient) -> None:
    pid = _new_project(client)
    body = client.post("/advisor/recommend", json={
        "project_id": pid,
        "context": {"problem": "smart irrigation", "tech": ["python", "iot"]},
    }).json()
    bts = body["overview"]["breakthroughs"]
    assert bts, "breakthroughs should be present"
    assert bts[0]["score"] >= bts[-1]["score"]  # ranked
    assert isinstance(bts[0]["benefit_types"], list)

    r = client.post(f"/advisor/breakthroughs/{bts[0]['id']}/status", json={"status": "exploring"})
    assert r.status_code == 200
    bad = client.post(f"/advisor/breakthroughs/{bts[0]['id']}/status", json={"status": "nope"})
    assert bad.status_code == 422


def test_learning_overview_reports_gap_count(client: TestClient) -> None:
    pid = _new_project(client)
    client.post("/ideation/gaps", json={"project_id": pid, "concept": "ML foundations"})
    ov = client.post("/advisor/recommend", json={
        "project_id": pid, "context": {"problem": "x", "tech": ["python", "ml"]},
    }).json()["overview"]
    assert ov["progress"]["learning"]["gaps"] >= 1
