"""Phase 3 orchestrator tests — decomposition, routing, scheduling, and the budget optimizer.

The budgeter tests are the heart: they prove the reservation + constraints make over-spend
impossible. All offline via the mock provider / pure functions.
"""

from __future__ import annotations

import json

import pytest

from sidecar.orchestrator import scheduler
from sidecar.orchestrator.budgeter import BudgetInputs, reserve_future, solve
from sidecar.orchestrator.decompose import DAG, Subtask, decompose, parse_dag
from sidecar.orchestrator.router import Candidate, HeuristicRouter
from sidecar.providers.mock import MockProvider
from sidecar.providers.registry import ProviderRegistry

MOCK_CANDS = [Candidate("mock", "mock-small"), Candidate("mock", "mock-large")]


def st(id, type="reasoning", deps=None, size=500, value=0.5, p=1.0, qs=0.5) -> Subtask:
    return Subtask(id=id, type=type, depends_on=deps or [], size_hint=size, value=value,
                   p_required=p, quality_sensitivity=qs)


# --------------------------------------------------------------------------- decomposition

def test_parse_dag_rejects_cycle() -> None:
    bad = json.dumps({"subtasks": [
        {"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]},
    ]})
    assert parse_dag(bad) is None


def test_parse_dag_rejects_unknown_dependency() -> None:
    bad = json.dumps({"subtasks": [{"id": "a", "depends_on": ["ghost"]}]})
    assert parse_dag(bad) is None


@pytest.mark.asyncio
async def test_decompose_falls_back_to_heuristic_dag() -> None:
    reg = ProviderRegistry([MockProvider()])  # echo -> unparseable -> heuristic
    dag = await decompose(reg, "Build a soil-moisture dashboard", "mock", "mock-small")
    assert len(dag.subtasks) >= 2
    dag.validate_graph()  # must be a valid DAG


# --------------------------------------------------------------------------- scheduling

def test_ready_set_respects_dependencies() -> None:
    subs = [st("a"), st("b", deps=["a"]), st("c", deps=["a"])]
    ready0 = {s.id for s in scheduler.ready_set(subs, done=set())}
    assert ready0 == {"a"}
    ready1 = {s.id for s in scheduler.ready_set(subs, done={"a"})}
    assert ready1 == {"b", "c"}


def test_critical_path_length() -> None:
    subs = [st("a"), st("b", deps=["a"]), st("c", deps=["b"])]
    assert scheduler.critical_path_length(subs) == 3


# --------------------------------------------------------------------------- routing

def test_router_picks_strong_model_for_quality_sensitive_coding() -> None:
    coding = st("x", type="coding", qs=1.0)
    pick = HeuristicRouter().pick(coding, MOCK_CANDS)
    assert pick is not None and pick.model == "mock-large"  # large is the coding specialist


def test_router_offloads_low_sensitivity_summarization_to_cheap_model() -> None:
    # mock-small is the summarization specialist AND cheaper; should win when sensitivity low.
    summ = st("y", type="summarization", qs=0.1)
    pick = HeuristicRouter().pick(summ, MOCK_CANDS)
    assert pick is not None and pick.model == "mock-small"


# --------------------------------------------------------------------------- budgeter (core)

def test_reservation_reduces_available_budget() -> None:
    future = [st("f1", size=1000, p=1.0), st("f2", size=1000, p=0.5)]
    # reserved = (1000*1.0 + 1000*0.5) * 1.2 = 1800
    assert reserve_future(future) == 1800


def test_budget_never_overspends_metered_tokens() -> None:
    ready = [st(f"s{i}", type="coding", size=1000, value=0.9, qs=1.0) for i in range(5)]
    # Only metered models offered; tiny budget. Optimizer must not exceed it.
    res = solve(BudgetInputs(ready=ready, candidates=[Candidate("mock", "mock-large")],
                             budget=2500, quotas={"mock": 10_000}))
    assert res.total_metered_tokens <= res.available
    assert res.available == 2500  # no future tasks → nothing reserved


def test_reservation_protects_future_heavy_tasks() -> None:
    ready = [st(f"s{i}", type="coding", size=1000, value=0.9, qs=1.0) for i in range(5)]
    future = [st("big", size=3000, p=1.0)]
    res = solve(BudgetInputs(ready=ready, candidates=[Candidate("mock", "mock-large")],
                             budget=5000, future=future, quotas={"mock": 99_999}))
    # reserved = 3600 → available = 1400 → at most 1 metered task (1000) fits.
    assert res.reserved == 3600
    assert res.available == 1400
    assert res.total_metered_tokens <= 1400


def test_low_sensitivity_work_offloads_to_unlimited_local_model() -> None:
    # Local (ollama) is unlimited/free; budget is 0. Work must still be assigned, to local.
    ready = [st("a", type="summarization", size=1000, value=0.8, qs=0.1)]
    cands = [Candidate("ollama", "llama3.2:1b"), Candidate("mock", "mock-large")]
    res = solve(BudgetInputs(ready=ready, candidates=cands, budget=0, quotas={"mock": 0}))
    assert res.unassigned == []                      # got assigned despite zero metered budget
    assert res.total_metered_tokens == 0             # ...to a free/local model
    assert res.assignments[0].provider == "ollama"


def test_per_provider_quota_respected() -> None:
    ready = [st(f"s{i}", type="coding", size=1000, value=0.9, qs=1.0) for i in range(4)]
    res = solve(BudgetInputs(ready=ready, candidates=[Candidate("mock", "mock-large")],
                             budget=10_000, quotas={"mock": 2000}))
    assert res.per_provider_metered.get("mock", 0) <= 2000


def test_greedy_fallback_matches_constraints() -> None:
    ready = [st(f"s{i}", type="coding", size=1000, value=0.9 - i * 0.1, qs=1.0) for i in range(4)]
    inp = BudgetInputs(ready=ready, candidates=[Candidate("mock", "mock-large")],
                       budget=2000, quotas={"mock": 5000})
    from sidecar.orchestrator.budgeter import _solve_greedy, reserve_future as rf
    res = _solve_greedy(inp, reserved=rf(inp.future), available=2000)
    assert res.method == "greedy"
    assert res.total_metered_tokens <= 2000
