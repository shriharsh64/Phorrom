"""Resource & Tooling Advisor tests — all offline via the mock provider.

Covers: heuristic catalog fallback, the scripted-LLM JSON parse path, ideation-gap
consumption, prerequisite ordering, persistence, and the mastery feedback loop.
"""

from __future__ import annotations

import json

import pytest

from sidecar.capabilities import resource_advisor as advisor
from sidecar.capabilities.resource_advisor import ProjectContext, parse_result
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry
from sidecar.storage.db import Database


def make_registry(responder=None) -> ProviderRegistry:
    return ProviderRegistry([MockProvider(responder=responder)])


# --------------------------------------------------------------------------- parsing

def test_parse_result_handles_code_fences_and_prose() -> None:
    text = 'Sure! Here you go:\n```json\n{"resources": [], "learning_plan": [], "detected_gaps": ["x"]}\n```'
    parsed = parse_result(text)
    assert parsed is not None
    assert parsed.detected_gaps == ["x"]


def test_parse_result_returns_none_on_garbage() -> None:
    assert parse_result("not json at all") is None


# --------------------------------------------------------------------------- heuristic fallback

def test_heuristic_is_never_empty_and_orders_prereq_first() -> None:
    ctx = ProjectContext(problem="smart irrigation", tech=["python", "ml"], task_types=["model"])
    res = advisor.heuristic_result(ctx, known_gaps=[], mastered=[])
    assert res.resources, "should always suggest free resources"
    assert res.learning_plan, "should always produce a learning plan"
    orders = [li.prereq_order for li in res.learning_plan]
    assert orders == sorted(orders), "learning plan must be prerequisite-first"
    # Foundations (ideation/understanding) come first.
    assert res.learning_plan[0].prereq_order == 0


def test_heuristic_skips_mastered_concepts() -> None:
    ctx = ProjectContext(problem="text summarizer", tech=["python", "nlp"])
    full = advisor.heuristic_result(ctx, known_gaps=[], mastered=[])
    mastered_name = full.learning_plan[0].concept
    pruned = advisor.heuristic_result(ctx, known_gaps=[], mastered=[mastered_name])
    assert all(li.concept != mastered_name for li in pruned.learning_plan)


def test_heuristic_incorporates_unmatched_ideation_gap() -> None:
    ctx = ProjectContext(problem="generic app", tech=["python"])
    res = advisor.heuristic_result(ctx, known_gaps=["Kalman filtering"], mastered=[])
    assert any("Kalman filtering" == li.concept for li in res.learning_plan)
    assert "Kalman filtering" in res.detected_gaps


# --------------------------------------------------------------------------- orchestration

@pytest.mark.asyncio
async def test_advise_uses_llm_json_when_parseable_and_persists() -> None:
    payload = {
        "resources": [
            {"kind": "library", "name": "FooLib", "stage": "prototyping", "url": "http://foo",
             "is_free": True, "rationale": "because"}
        ],
        "learning_plan": [
            {"concept": "Graphs", "title": "Graphs 101", "url": "http://g", "source": "docs",
             "rationale": "needed", "prereq_order": 1}
        ],
        "detected_gaps": ["Graphs"],
    }
    registry = make_registry(responder=lambda msgs, model: json.dumps(payload))
    db = Database(":memory:")
    pid = db.create_project("demo")

    result = await advisor.advise(registry, db, pid, ProjectContext(problem="p"), "mock", "mock-small")
    assert any(r.name == "FooLib" for r in result.resources)

    # Persisted to SQLite.
    assert any(r["name"] == "FooLib" for r in db.list_resource_suggestions(pid))
    learning = db.list_learning_items(pid)
    assert any(li["title"] == "Graphs 101" for li in learning)
    assert any(c["name"] == "Graphs" for c in db.list_concepts(pid))
    db.close()


@pytest.mark.asyncio
async def test_advise_falls_back_to_heuristic_on_unparseable_llm() -> None:
    # Default mock echoes (not JSON) -> parse fails -> heuristic fallback.
    registry = make_registry()
    db = Database(":memory:")
    pid = db.create_project("demo")
    result = await advisor.advise(
        registry, db, pid, ProjectContext(problem="web dashboard", tech=["react"]), "mock", "mock-small"
    )
    assert result.resources and result.learning_plan
    assert db.list_resource_suggestions(pid)
    db.close()


@pytest.mark.asyncio
async def test_advise_targets_ideation_gaps() -> None:
    registry = make_registry()
    db = Database(":memory:")
    pid = db.create_project("demo")
    # Ideation (#2) recorded that the user struggled with this concept.
    db.upsert_concept(pid, "Bayesian inference", status="gap", origin="ideation")
    result = await advisor.advise(registry, db, pid, ProjectContext(problem="x", tech=["python"]), "mock", "mock-small")
    assert any(li.concept == "Bayesian inference" for li in result.learning_plan)
    db.close()


# --------------------------------------------------------------------------- mastery feedback loop

def test_completing_learning_items_masters_concept() -> None:
    db = Database(":memory:")
    pid = db.create_project("demo")
    db.upsert_concept(pid, "Graphs", status="gap", origin="advisor")
    a = db.add_learning_item(pid, "Graphs", "Graphs 101")
    b = db.add_learning_item(pid, "Graphs", "Graphs 201", prereq_order=1)

    db.set_learning_status(a, "in_progress")
    assert db.mastered_concepts(pid) == []  # still learning
    concepts = {c["name"]: c["status"] for c in db.list_concepts(pid)}
    assert concepts["Graphs"] == "learning"

    db.set_learning_status(a, "done")
    db.set_learning_status(b, "done")
    assert "Graphs" in db.mastered_concepts(pid)  # all items done -> mastered
    db.close()
