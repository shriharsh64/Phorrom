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
import random

from . import scheduler
from .bandit import BanditRouter
from .budgeter import BudgetInputs, solve
from .decompose import DAG, Subtask, decompose
from .profiles import get_profile
from .resilience import CircuitBreaker, ResilientExecutor
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


def _failover_order(primary: Candidate, candidates: list[Candidate], task_type: str) -> list[Candidate]:
    """Primary first, then other candidates by fit — local/free 'unlimited' models kept as
    last-resort so failover degrades gracefully toward something that always works."""

    others = [c for c in candidates if (c.provider, c.model) != (primary.provider, primary.model)]
    others.sort(key=lambda c: (get_profile(c.provider, c.model).unlimited,
                               -get_profile(c.provider, c.model).quality_for(task_type)))
    return [primary, *others]


async def _execute(
    registry: ProviderRegistry, db: Database, assignments, by_id: dict[str, Subtask],
    candidates: list[Candidate], executor: ResilientExecutor,
) -> dict[str, Any]:
    """Run each assigned subtask with retry + failover; record real token usage in the ledger."""

    outputs: dict[str, str] = {}
    failovers: dict[str, list[str]] = {}
    for a in assignments:
        sub = by_id[a.subtask_id]
        order = _failover_order(Candidate(a.provider, a.model), candidates, sub.type)
        try:
            res = await executor.generate(
                registry, [Message(role="user", content=sub.description or sub.id)], order)
        except ProviderError:
            continue
        r = res.response
        db.record_run(r.provider, r.model, r.tokens_in, r.tokens_out, r.latency_ms)
        # Log a training sample for the learned estimators: observed tokens + a quality proxy.
        quality_proxy = get_profile(r.provider, r.model).quality_for(sub.type)
        db.add_estimator_sample(sub.type, sub.size_hint, r.provider, r.model,
                                r.tokens_in + r.tokens_out, quality_proxy)
        outputs[a.subtask_id] = r.text
        if res.failed_over_from:
            failovers[a.subtask_id] = res.failed_over_from
    return {"outputs": outputs, "failovers": failovers}


async def orchestrate(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    task_title: str,
    budget: int = 4000,
    quotas: dict[str, int] | None = None,
    execute: bool = False,
    router: str = "heuristic",
    seed: int | None = None,
    breaker: CircuitBreaker | None = None,
    estimator: Any = None,
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

    # Optional contextual-bandit routing: allocation optimizes over Thompson-sampled qualities.
    bandit: BanditRouter | None = None
    quality_fn = None
    if router == "bandit":
        bandit = BanditRouter(rng=random.Random(seed))
        bandit.load_from_db(db, candidates)
        quality_fn = bandit.sample_quality
    elif router == "learned" and estimator is not None and getattr(estimator, "trained", False):
        # Allocation optimizes over the learned quality estimate for each subtask×model.
        quality_fn = lambda s, c: estimator.predict(s.type, s.size_hint, c.provider, c.model)[1]  # noqa: E731

    result = solve(BudgetInputs(
        ready=ready, candidates=candidates, budget=budget, future=future,
        quotas=quotas or {}, quality_fn=quality_fn,
    ))

    task_id = _persist_dag(db, project_id, task_title, dag)
    outputs: dict[str, str] = {}
    failovers: dict[str, list[str]] = {}
    if execute:
        executor = ResilientExecutor(breaker=breaker or CircuitBreaker())
        ex = await _execute(registry, db, result.assignments, by_id, candidates, executor)
        outputs, failovers = ex["outputs"], ex["failovers"]
        # Learn from this batch: observe a reward per assignment and persist the posterior.
        if bandit is not None:
            for a in result.assignments:
                reward = get_profile(a.provider, a.model).quality_for(by_id[a.subtask_id].type)
                bandit.observe(a.provider, a.model, by_id[a.subtask_id].type, reward)
                db.update_bandit_arm(a.provider, a.model, by_id[a.subtask_id].type, reward)

    db.audit("agent", "orchestrate", {
        "project_id": project_id, "task_id": task_id, "subtasks": len(dag.subtasks),
        "ready": len(ready), "reserved": result.reserved, "available": result.available,
        "method": result.method,
    })

    return {
        "task_id": task_id,
        "router": router,
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
        "failovers": failovers,
    }
