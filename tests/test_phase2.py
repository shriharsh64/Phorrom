"""Phase 2 tests: prioritizer, problem architect, and file-manager security — all offline."""

from __future__ import annotations

import json

import pytest

from sidecar.capabilities import problem_architect
from sidecar.capabilities.prioritizer import compute_priorities
from sidecar.files import manager as files
from sidecar.files.manager import PathError
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry
from sidecar.storage.db import Database


# --------------------------------------------------------------------------- prioritizer

def test_priority_blends_urgency_impact_and_blocking() -> None:
    tasks = [
        {"id": 1, "urgency": 1.0, "impact": 1.0, "depends_on": [], "status": "todo"},
        {"id": 2, "urgency": 0.1, "impact": 0.1, "depends_on": [], "status": "todo"},
        {"id": 3, "urgency": 0.5, "impact": 0.5, "depends_on": [1], "status": "todo"},
    ]
    scores = compute_priorities(tasks)
    assert scores[1]["priority"] > scores[2]["priority"]
    assert scores[1]["blocks"] == 1  # task 3 depends on task 1
    assert scores[3]["depth"] == 1   # one dependency deep


def test_readiness_reflects_done_dependencies() -> None:
    tasks = [
        {"id": 1, "status": "done", "depends_on": []},
        {"id": 2, "status": "todo", "depends_on": [1]},
        {"id": 3, "status": "todo", "depends_on": [2]},
    ]
    scores = compute_priorities(tasks)
    assert scores[2]["ready"] is True    # its only dep (1) is done
    assert scores[3]["ready"] is False   # dep (2) not done


def test_priority_handles_dependency_cycle_without_hanging() -> None:
    tasks = [
        {"id": 1, "status": "todo", "depends_on": [2]},
        {"id": 2, "status": "todo", "depends_on": [1]},
    ]
    scores = compute_priorities(tasks)  # must terminate
    assert set(scores) == {1, 2}


# --------------------------------------------------------------------------- problem architect

@pytest.mark.asyncio
async def test_architect_uses_llm_json_and_persists() -> None:
    payload = {
        "statement": "Reduce water waste in small farms",
        "scope": "Smallholder farms in semi-arid regions",
        "gap": "Existing systems are too expensive",
        "stakeholders": ["farmers"],
        "success_criteria": ["30% less water"],
        "clarifying_questions": [],
    }
    reg = ProviderRegistry([MockProvider(responder=lambda m, model: json.dumps(payload))])
    db = Database(":memory:")
    pid = db.create_project("farm")
    rec = await problem_architect.architect(reg, db, pid, "save water on farms", "mock", "mock-small")
    assert rec.statement == "Reduce water waste in small farms"
    assert db.latest_problem_record(pid)["gap"] == "Existing systems are too expensive"
    db.close()


@pytest.mark.asyncio
async def test_architect_falls_back_to_heuristic_with_questions() -> None:
    reg = ProviderRegistry([MockProvider()])  # echoes -> unparseable -> heuristic
    db = Database(":memory:")
    pid = db.create_project("p")
    rec = await problem_architect.architect(reg, db, pid, "an app for stuff", "mock", "mock-small")
    assert rec.statement
    assert rec.clarifying_questions  # thin description -> asks questions
    db.close()


# --------------------------------------------------------------------------- file manager security

def test_read_write_within_root(tmp_path) -> None:
    db = Database(":memory:")
    pid = db.create_project("p", root_path=str(tmp_path))
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    assert files.read_file(tmp_path, "notes.txt")["content"] == "hello"

    res = files.propose_write(db, pid, tmp_path, "logs/run.md", "# Run\n", reason="log")
    assert "run.md" in res["diff"] or res["diff"] == "" or res["exists"] is False
    files.commit_write(db, res["id"], tmp_path)
    assert (tmp_path / "logs" / "run.md").read_text(encoding="utf-8") == "# Run\n"
    db.close()


def test_path_escape_is_blocked(tmp_path) -> None:
    db = Database(":memory:")
    db.create_project("p", root_path=str(tmp_path))
    with pytest.raises(PathError):
        files.read_file(tmp_path, "../secret.txt")
    with pytest.raises(PathError):
        files.resolve_in_root(tmp_path, "..\\..\\windows\\system32")


def test_commit_requires_pending(tmp_path) -> None:
    db = Database(":memory:")
    db.create_project("p", root_path=str(tmp_path))
    with pytest.raises(PathError):
        files.commit_write(db, 9999, tmp_path)
    db.close()
