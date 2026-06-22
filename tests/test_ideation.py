"""Ideation engine tests, including the closed loop Ideation (#2) ⇄ Advisor (#3)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sidecar.app import create_app
from sidecar.capabilities import ideation
from sidecar.capabilities.ideation import score_idea
from sidecar.config import Config
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry
from sidecar.storage.db import Database


def reg(responder=None) -> ProviderRegistry:
    return ProviderRegistry([MockProvider(responder=responder)])


def test_score_idea_weights_relevance_highest() -> None:
    a = score_idea(feasibility=0.5, novelty=0.5, relevance=1.0)
    b = score_idea(feasibility=0.5, novelty=1.0, relevance=0.5)
    assert a > b  # relevance carries more weight than novelty


@pytest.mark.asyncio
async def test_ideate_ranks_and_persists() -> None:
    payload = {"ideas": [
        {"title": "Low relevance", "feasibility": 0.9, "novelty": 0.9, "relevance": 0.1,
         "required_concepts": []},
        {"title": "High relevance", "feasibility": 0.8, "novelty": 0.5, "relevance": 0.95,
         "required_concepts": ["Data pipelines"]},
    ]}
    db = Database(":memory:")
    pid = db.create_project("p")
    res = await ideation.ideate(reg(lambda m, model: json.dumps(payload)), db, pid, "a problem")
    assert res.ideas[0].title == "High relevance"  # ranked by score
    assert db.list_ideas(pid)[0]["title"] == "High relevance"
    db.close()


@pytest.mark.asyncio
async def test_ideation_writes_gaps_that_advisor_can_target() -> None:
    payload = {"ideas": [
        {"title": "Idea", "feasibility": 0.7, "novelty": 0.6, "relevance": 0.8,
         "required_concepts": ["Bayesian inference", "Data pipelines"]},
    ]}
    db = Database(":memory:")
    pid = db.create_project("p")
    res = await ideation.ideate(reg(lambda m, model: json.dumps(payload)), db, pid, "x")
    assert set(res.detected_gaps) == {"Bayesian inference", "Data pipelines"}
    # These are now 'gap' concepts of ideation origin — exactly what the advisor consumes.
    gaps = {c["name"]: c for c in db.list_concepts(pid, status="gap")}
    assert "Bayesian inference" in gaps and gaps["Bayesian inference"]["origin"] == "ideation"
    db.close()


@pytest.mark.asyncio
async def test_ideation_skips_mastered_concepts() -> None:
    payload = {"ideas": [{"title": "I", "feasibility": 0.7, "novelty": 0.6, "relevance": 0.8,
                          "required_concepts": ["Data pipelines", "Already Known"]}]}
    db = Database(":memory:")
    pid = db.create_project("p")
    db.upsert_concept(pid, "Already Known", status="mastered", origin="user")
    res = await ideation.ideate(reg(lambda m, model: json.dumps(payload)), db, pid, "x")
    assert "Already Known" not in res.detected_gaps
    db.close()


def _client() -> TestClient:
    cfg = Config(db_path=":memory:", auth_token=None, gemini_api_key=None,
                 ollama_host="http://127.0.0.1:11434")
    return TestClient(create_app(cfg))


def test_full_loop_ideate_advise_master_feedback() -> None:
    """Ideation surfaces a gap → advisor builds learning for it → completing it masters it →
    the mastered concept is fed back (visible to ideation)."""

    client = _client()
    # scripted ideation via the app's mock provider
    from sidecar.providers.mock import MockProvider
    from sidecar.providers.registry import ProviderRegistry
    payload = {"ideas": [{"title": "I", "feasibility": 0.7, "novelty": 0.6, "relevance": 0.9,
                          "required_concepts": ["Graph theory"]}]}
    client.app.state.registry = ProviderRegistry([MockProvider(responder=lambda m, md: json.dumps(payload))])

    pid = client.post("/projects", json={"name": "Demo"}).json()["id"]
    ideate = client.post("/ideation/ideate", json={"project_id": pid, "prompt": "x"}).json()
    assert "Graph theory" in ideate["result"]["detected_gaps"]

    # Advisor picks up the ideation gap.
    overview = client.post("/advisor/recommend", json={"project_id": pid, "context": {"problem": "x"}}).json()["overview"]
    assert any(li["concept"] == "Graph theory" for li in overview["learning"])

    # Complete the gap's learning items → concept mastered → fed back.
    for li in [x for x in overview["learning"] if x["concept"] == "Graph theory"]:
        client.post(f"/advisor/learning/{li['id']}/status", json={"status": "done"})
    mastered = client.get("/ideation/mastered", params={"project_id": pid}).json()["mastered"]
    assert "Graph theory" in mastered
