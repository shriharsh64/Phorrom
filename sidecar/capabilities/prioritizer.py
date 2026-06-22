"""Task Prioritization System (capability #8) — dynamic urgency x impact x dependency scoring.

Problem solved: turn a flat task list into a ranked, dependency-aware plan. Priority blends how
urgent and how impactful a task is with how much *other* work it unblocks (a critical-path
proxy). Pure, deterministic, and offline — no model needed.

Inputs : tasks with optional ``urgency``/``impact`` (0..1) and ``depends_on`` (task ids).
Outputs: per-task priority (0..1), readiness (all deps done), and how many tasks it blocks.
"""

from __future__ import annotations

from typing import Any

W_URGENCY = 0.45
W_IMPACT = 0.35
W_DEPENDENCY = 0.20


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_priorities(tasks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return {task_id: {priority, ready, blocks, depth}} for the given tasks."""

    by_id = {t["id"]: t for t in tasks}
    done = {t["id"] for t in tasks if t.get("status") == "done"}

    # How many tasks depend on each task (its out-degree as a blocker → criticality).
    blocks: dict[int, int] = {t["id"]: 0 for t in tasks}
    for t in tasks:
        for dep in t.get("depends_on") or []:
            if dep in blocks:
                blocks[dep] += 1
    max_blocks = max(blocks.values()) if blocks else 0

    # Longest dependency chain ending at each task (critical-path depth), memoized.
    depth_cache: dict[int, int] = {}

    def depth(tid: int, seen: frozenset[int]) -> int:
        if tid in depth_cache:
            return depth_cache[tid]
        if tid in seen:  # cycle guard
            return 0
        deps = [d for d in (by_id.get(tid, {}).get("depends_on") or []) if d in by_id]
        d = 0 if not deps else 1 + max(depth(dp, seen | {tid}) for dp in deps)
        depth_cache[tid] = d
        return d

    out: dict[int, dict[str, Any]] = {}
    for t in tasks:
        tid = t["id"]
        urgency = t.get("urgency")
        impact = t.get("impact")
        urgency = 0.5 if urgency is None else _clamp01(float(urgency))
        impact = 0.5 if impact is None else _clamp01(float(impact))
        dep_factor = (blocks[tid] / max_blocks) if max_blocks else 0.0
        priority = _clamp01(W_URGENCY * urgency + W_IMPACT * impact + W_DEPENDENCY * dep_factor)
        deps = t.get("depends_on") or []
        ready = all(d in done for d in deps) if t.get("status") != "done" else False
        out[tid] = {
            "priority": round(priority, 4),
            "ready": ready,
            "blocks": blocks[tid],
            "depth": depth(tid, frozenset()),
        }
    return out
