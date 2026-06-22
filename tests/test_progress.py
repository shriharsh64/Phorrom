"""Progress Assessment tests — deterministic scoring, risk flags, recommendations, API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sidecar.capabilities import progress
from sidecar.capabilities.progress import _compute
from sidecar.config import Config
from sidecar.app import create_app
from sidecar.storage.db import Database


def test_completion_is_impact_weighted_and_nonbinary() -> None:
    db = Database(":memory:")
    pid = db.create_project("p")
    a = db.add_task(pid, "high-impact", impact=1.0)
    db.add_task(pid, "low-impact", impact=0.2)
    db.set_task_status(a, "done")  # finish only the heavy one
    m = _compute(db, pid)
    # weighted completion = (1.0*1.0 + 0.2*0.0)/(1.0+0.2) ≈ 0.833 — not a flat 50%.
    assert 0.8 < m["completion"] < 0.86
    db.close()


def test_premature_done_is_flagged_and_quality_reduced() -> None:
    db = Database(":memory:")
    pid = db.create_project("p")
    dep = db.add_task(pid, "dependency")
    t = db.add_task(pid, "feature", depends_on=[dep])
    db.set_task_status(t, "done")  # done while its dependency is still todo
    m = _compute(db, pid)
    assert any(r["type"] == "premature_done" for r in m["risks"])
    ms = {x["task_id"]: x for x in m["milestones"]}
    assert ms[t]["quality"] == 0.6  # questionable completion, not 1.0
    db.close()


def test_stale_high_priority_risk_and_recommendation() -> None:
    db = Database(":memory:")
    pid = db.create_project("p")
    db.add_task(pid, "urgent thing", urgency=1.0, impact=1.0)  # high priority, still todo
    m = _compute(db, pid)
    assert any(r["type"] == "stale_high_priority" for r in m["risks"])
    assert any("Start next" in r for r in m["recommendations"])
    db.close()


def test_open_skill_gaps_risk() -> None:
    db = Database(":memory:")
    pid = db.create_project("p")
    for c in ("a", "b", "c"):
        db.upsert_concept(pid, c, status="gap", origin="ideation")
    m = _compute(db, pid)
    assert any(r["type"] == "open_skill_gaps" for r in m["risks"])
    db.close()


def test_health_discounted_by_risk() -> None:
    db = Database(":memory:")
    pid = db.create_project("p")
    t = db.add_task(pid, "only task", impact=1.0)
    db.set_task_status(t, "done")
    clean = _compute(db, pid)
    # Introduce a blocked task → risk → health should drop below completion.
    db.add_task(pid, "blocked one")
    db.set_task_status(list(db.list_tasks(pid))[-1]["id"], "blocked")
    risky = _compute(db, pid)
    assert risky["health"] <= risky["completion"]
    assert clean["health"] <= clean["completion"]
    db.close()


@pytest.mark.asyncio
async def test_assess_persists_and_adds_narrative() -> None:
    from sidecar.providers.mock import MockProvider
    from sidecar.providers.registry import ProviderRegistry
    db = Database(":memory:")
    pid = db.create_project("p")
    db.add_task(pid, "t1", impact=0.8)
    out = await progress.assess(ProviderRegistry([MockProvider()]), db, pid)
    assert out["narrative"]  # heuristic narrative when mock echoes
    assert db.latest_progress_assessment(pid)["completion"] == out["completion"]
    db.close()


def test_progress_api() -> None:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    client = TestClient(create_app(cfg))
    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    client.post("/tasks", json={"project_id": pid, "title": "a", "urgency": 1.0, "impact": 1.0})
    body = client.post("/progress/assess", json={"project_id": pid}).json()
    assert "health" in body and "recommendations" in body
    latest = client.get("/progress/latest", params={"project_id": pid}).json()["assessment"]
    assert latest["completion"] == body["completion"]
