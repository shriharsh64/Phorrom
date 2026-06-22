"""The orchestrator control loop: decompose → schedule → reserve+allocate → route → execute.

Problem solved: ties the pieces into one run. Given a task, it decomposes into a subtask DAG,
finds the ready set, reserves tokens for the rest of the pipeline, solves the budgeted
assignment (which routes each ready subtask to the best feasible free model), optionally
executes the ready batch through the provider layer, and records real token usage so the next
re-plan runs on actual numbers.
"""

from __future__ import annotations

from typing import Any

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database
from . import scheduler
from .budgeter import BudgetInputs, solve
from .decompose import DAG, Subtask, decompose
from .router import Candidate


async def available_candidates(registry: ProviderRegistry) -> list[Candidate]:
    """Discover live (provider, model) options from every available provider."""

    candidates: list[Candidate] = []
    for info in await registry.discover():
        if not info["available"]:
            continue
        for model in info["models"]:
            candidates.append(Candidate(provider=info["provider"], model=model))
    return candidates


def _persist_dag(db: Database, project_id: int, task_title: str, dag: DAG) -> int:
    task_id = db.add_task(project_id, task_title)
    for s in dag.subtasks:
        db.add_subtask(task_id, s.id, s.type, s.depends_on, s.size_hint, s.value,
                       s.p_required, s.quality_sensitivity)
    return task_id


async def _execute(
    registry: ProviderRegistry, db: Database, assignments, by_id: dict[str, Subtask]
) -> dict[str, str]:
    """Run each assigned subtask through its model; record real token usage in the ledger."""

    outputs: dict[str, str] = {}
    for a in assignments:
        prov = registry.get(a.provider)
        if prov is None:
            continue
        sub = by_id[a.subtask_id]
        try:
            resp = await prov.generate(
                [Message(role="user", content=sub.description or sub.id)], a.model
            )
        except ProviderError:
            continue
        db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
        outputs[a.subtask_id] = resp.text
    return outputs


async def orchestrate(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    task_title: str,
    budget: int = 4000,
    quotas: dict[str, int] | None = None,
    execute: bool = False,
    decomposer_provider: str = "mock",
    decomposer_model: str = "mock-small",
) -> dict[str, Any]:
    dag = await decompose(registry, task_title, decomposer_provider, decomposer_model)
    candidates = await available_candidates(registry)
    if not candidates:  # nothing available → still return the plan
        candidates = [Candidate(decomposer_provider, decomposer_model)]

    by_id = {s.id: s for s in dag.subtasks}
    ready = scheduler.ready_set(dag.subtasks, done=set())
    ready_ids = {s.id for s in ready}
    future = [s for s in dag.subtasks if s.id not in ready_ids]

    result = solve(BudgetInputs(
        ready=ready, candidates=candidates, budget=budget, future=future, quotas=quotas or {},
    ))

    task_id = _persist_dag(db, project_id, task_title, dag)
    outputs: dict[str, str] = {}
    if execute:
        outputs = await _execute(registry, db, result.assignments, by_id)

    db.audit("agent", "orchestrate", {
        "project_id": project_id, "task_id": task_id, "subtasks": len(dag.subtasks),
        "ready": len(ready), "reserved": result.reserved, "available": result.available,
        "method": result.method,
    })

    return {
        "task_id": task_id,
        "subtasks": [s.model_dump() for s in dag.subtasks],
        "critical_path": scheduler.critical_path_length(dag.subtasks),
        "ready": [s.id for s in ready],
        "future": [s.id for s in future],
        "budget": {
            "total": budget,
            "reserved": result.reserved,
            "available": result.available,
            "total_metered_tokens": result.total_metered_tokens,
            "per_provider_metered": result.per_provider_metered,
            "method": result.method,
        },
        "assignments": [
            {"subtask": a.subtask_id, "provider": a.provider, "model": a.model,
             "tokens": a.tokens, "quality": a.quality, "metered": a.metered}
            for a in result.assignments
        ],
        "unassigned": result.unassigned,
        "outputs": outputs,
    }
