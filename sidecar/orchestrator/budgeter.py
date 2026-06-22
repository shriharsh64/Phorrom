"""Token-budget optimizer.

Problem solved: spend scarce free-tier tokens where they buy the most value/quality, while
*reserving* enough for future near-certain, token-heavy tasks so they never get starved.

Procedure (re-run after each batch on real usage):
1. Reserve future demand:  reserved = Σ size_hint · p_required · SAFETY  over upcoming tasks.
2. available = budget − reserved.
3. Solve an assignment (PuLP): maximize Σ value·quality·x[i,m] subject to
   - each ready subtask assigned to at most one model,
   - Σ metered tokens ≤ available,
   - Σ tokens routed to provider p ≤ p's remaining quota.
   Local/free-unlimited models cost no metered tokens and have no quota, so the optimizer
   naturally offloads low-quality-sensitivity work to them to preserve scarce quotas.
4. Greedy fallback for tiny problems or if the solver is unavailable.

This module is pure (no DB/network) so the over-spend guarantees are unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .decompose import Subtask
from .profiles import get_profile
from .router import Candidate

SAFETY = 1.2


@dataclass
class BudgetInputs:
    ready: list[Subtask]
    candidates: list[Candidate]
    budget: int                                  # total metered token budget
    future: list[Subtask] = field(default_factory=list)
    quotas: dict[str, int] = field(default_factory=dict)  # provider -> remaining metered tokens
    safety: float = SAFETY


@dataclass
class Assignment:
    subtask_id: str
    provider: str
    model: str
    tokens: int
    quality: float
    metered: bool


@dataclass
class BudgetResult:
    reserved: int
    available: int
    assignments: list[Assignment]
    total_metered_tokens: int
    per_provider_metered: dict[str, int]
    unassigned: list[str]
    method: str


def reserve_future(future: list[Subtask], safety: float = SAFETY) -> int:
    return round(sum(s.size_hint * s.p_required for s in future) * safety)


def _quality(subtask: Subtask, c: Candidate) -> float:
    return get_profile(c.provider, c.model).quality_for(subtask.type)


def _is_unlimited(c: Candidate) -> bool:
    return get_profile(c.provider, c.model).unlimited


def solve(inp: BudgetInputs) -> BudgetResult:
    reserved = reserve_future(inp.future, inp.safety)
    available = max(0, inp.budget - reserved)
    try:
        return _solve_pulp(inp, reserved, available)
    except Exception:  # noqa: BLE001 — any solver issue → deterministic greedy fallback
        return _solve_greedy(inp, reserved, available)


def _solve_pulp(inp: BudgetInputs, reserved: int, available: int) -> BudgetResult:
    import pulp

    prob = pulp.LpProblem("token_budget", pulp.LpMaximize)
    x: dict[tuple[str, str, str], pulp.LpVariable] = {}
    obj_terms = []
    for s in inp.ready:
        for c in inp.candidates:
            key = (s.id, c.provider, c.model)
            var = pulp.LpVariable(f"x_{s.id}_{c.provider}_{c.model}", cat="Binary")
            x[key] = var
            obj_terms.append(s.value * _quality(s, c) * var)
    prob += pulp.lpSum(obj_terms)

    # Each ready subtask gets at most one model.
    for s in inp.ready:
        prob += pulp.lpSum(x[(s.id, c.provider, c.model)] for c in inp.candidates) <= 1

    # Global metered-token budget (unlimited/local models excluded).
    metered_terms = [
        s.size_hint * x[(s.id, c.provider, c.model)]
        for s in inp.ready for c in inp.candidates if not _is_unlimited(c)
    ]
    if metered_terms:
        prob += pulp.lpSum(metered_terms) <= available

    # Per-provider remaining quota (metered providers only).
    providers = {c.provider for c in inp.candidates if not _is_unlimited(c)}
    for p in providers:
        quota = inp.quotas.get(p, available)
        prob += pulp.lpSum(
            s.size_hint * x[(s.id, c.provider, c.model)]
            for s in inp.ready for c in inp.candidates
            if c.provider == p and not _is_unlimited(c)
        ) <= quota

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"solver status {pulp.LpStatus[status]}")

    return _collect(inp, reserved, available, x_lookup=lambda k: x[k].value() or 0, method="pulp")


def _solve_greedy(inp: BudgetInputs, reserved: int, available: int) -> BudgetResult:
    """Assign highest-value subtasks first to their best feasible model within budget/quota."""

    spent = 0
    per_provider: dict[str, int] = {}
    chosen: dict[tuple[str, str, str], int] = {}
    for s in sorted(inp.ready, key=lambda s: s.value, reverse=True):
        best: tuple[float, Candidate] | None = None
        for c in inp.candidates:
            q = _quality(s, c)
            unlimited = _is_unlimited(c)
            if not unlimited:
                if spent + s.size_hint > available:
                    continue
                quota = inp.quotas.get(c.provider, available)
                if per_provider.get(c.provider, 0) + s.size_hint > quota:
                    continue
            # Prefer higher quality; tie-break toward unlimited to save metered budget.
            rank = (q, 1 if unlimited else 0)
            if best is None or rank > (best[0], 1 if _is_unlimited(best[1]) else 0):
                best = (q, c)
        if best is not None:
            c = best[1]
            chosen[(s.id, c.provider, c.model)] = 1
            if not _is_unlimited(c):
                spent += s.size_hint
                per_provider[c.provider] = per_provider.get(c.provider, 0) + s.size_hint
    return _collect(inp, reserved, available, x_lookup=lambda k: chosen.get(k, 0), method="greedy")


def _collect(inp: BudgetInputs, reserved: int, available: int, x_lookup, method: str) -> BudgetResult:
    assignments: list[Assignment] = []
    per_provider: dict[str, int] = {}
    total_metered = 0
    for s in inp.ready:
        for c in inp.candidates:
            if x_lookup((s.id, c.provider, c.model)) >= 0.5:
                unlimited = _is_unlimited(c)
                assignments.append(Assignment(
                    s.id, c.provider, c.model, s.size_hint, round(_quality(s, c), 4),
                    metered=not unlimited,
                ))
                if not unlimited:
                    total_metered += s.size_hint
                    per_provider[c.provider] = per_provider.get(c.provider, 0) + s.size_hint
                break
    assigned_ids = {a.subtask_id for a in assignments}
    unassigned = [s.id for s in inp.ready if s.id not in assigned_ids]
    return BudgetResult(
        reserved=reserved, available=available, assignments=assignments,
        total_metered_tokens=total_metered, per_provider_metered=per_provider,
        unassigned=unassigned, method=method,
    )
