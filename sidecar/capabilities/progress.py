"""Progress Assessment Engine (capability #7).

Problem solved: turn the live task/concept/run data into an honest read on where the project
stands — non-binary milestone quality, a project completion %, a health score, flagged risks,
and concrete next steps. The numeric core is deterministic and testable; an optional model pass
adds a narrative grounded strictly in the computed numbers.

Inputs : a project's tasks (status/priority/impact/deps), concepts (gaps/mastered), runs.
Outputs: {completion, health, milestones[], risks[], recommendations[], narrative}.
"""

from __future__ import annotations

from typing import Any

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database
from .prioritizer import compute_priorities

# How "done" a status is, for non-binary milestone quality.
_STATUS_QUALITY = {"done": 1.0, "in_progress": 0.5, "blocked": 0.15, "todo": 0.0}


def _compute(db: Database, project_id: int) -> dict[str, Any]:
    tasks = db.list_tasks(project_id)
    concepts = db.list_concepts(project_id)
    priorities = compute_priorities(tasks)
    done_ids = {t["id"] for t in tasks if t["status"] == "done"}

    milestones: list[dict] = []
    risks: list[dict] = []
    weight_sum = 0.0
    quality_sum = 0.0

    for t in tasks:
        impact = t.get("impact")
        weight = max(0.1, float(impact) if impact is not None else 0.5)
        quality = _STATUS_QUALITY.get(t["status"], 0.0)

        # Non-binary nuance: a 'done' task whose dependencies aren't done is questionable.
        unmet = [d for d in (t.get("depends_on") or []) if d not in done_ids]
        if t["status"] == "done" and unmet:
            quality = 0.6
            risks.append({"type": "premature_done", "severity": "high", "task_id": t["id"],
                          "detail": f"'{t['title']}' is marked done but depends on unfinished work."})
        if t["status"] == "blocked":
            risks.append({"type": "blocked", "severity": "medium", "task_id": t["id"],
                          "detail": f"'{t['title']}' is blocked."})
        pr = priorities.get(t["id"], {})
        if t["status"] == "todo" and pr.get("priority", 0) >= 0.66:
            risks.append({"type": "stale_high_priority", "severity": "high", "task_id": t["id"],
                          "detail": f"High-priority '{t['title']}' hasn't been started."})

        weight_sum += weight
        quality_sum += weight * quality
        milestones.append({"task_id": t["id"], "title": t["title"], "status": t["status"],
                           "quality": round(quality, 3), "priority": pr.get("priority", 0)})

    open_gaps = [c["name"] for c in concepts if c["status"] == "gap"]
    if len(open_gaps) >= 3:
        risks.append({"type": "open_skill_gaps", "severity": "medium",
                      "detail": f"{len(open_gaps)} unaddressed skill gaps may slow execution."})
    if not tasks:
        risks.append({"type": "no_tasks", "severity": "high",
                      "detail": "No tasks defined yet — break the problem into milestones."})

    completion = round(quality_sum / weight_sum, 3) if weight_sum else 0.0
    # Health discounts completion by risk pressure (each risk weighted by severity, capped).
    sev = {"high": 0.12, "medium": 0.06, "low": 0.03}
    penalty = min(0.6, sum(sev.get(r["severity"], 0.05) for r in risks))
    health = round(max(0.0, completion * (1.0 - penalty)), 3)

    recommendations = _recommendations(tasks, priorities, risks, open_gaps)
    return {"completion": completion, "health": health, "milestones": milestones,
            "risks": risks, "recommendations": recommendations}


def _recommendations(tasks, priorities, risks, open_gaps) -> list[str]:
    recs: list[str] = []
    by_id = {t["id"]: t for t in tasks}
    # Start the highest-priority ready task.
    ready = sorted(
        [t for t in tasks if priorities.get(t["id"], {}).get("ready") and t["status"] == "todo"],
        key=lambda t: priorities[t["id"]]["priority"], reverse=True,
    )
    if ready:
        recs.append(f"Start next: '{ready[0]['title']}' (highest-priority ready task).")
    for r in risks:
        if r["type"] == "premature_done":
            recs.append(f"Verify '{by_id[r['task_id']]['title']}' — marked done with unfinished deps.")
        elif r["type"] == "blocked":
            recs.append(f"Unblock '{by_id[r['task_id']]['title']}'.")
    if open_gaps:
        recs.append(f"Close skill gap: '{open_gaps[0]}' (see the Advisor tab).")
    if not recs:
        recs.append("On track — keep executing the prioritized task list.")
    return recs[:6]


def _heuristic_narrative(m: dict[str, Any]) -> str:
    return (
        f"Completion {int(m['completion'] * 100)}%, health {int(m['health'] * 100)}%. "
        f"{len(m['risks'])} risk(s) flagged. "
        f"Top next step: {m['recommendations'][0] if m['recommendations'] else 'n/a'}"
    )


async def assess(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    provider: str = "mock",
    model: str = "mock-small",
    with_narrative: bool = True,
) -> dict[str, Any]:
    """Compute, optionally narrate (grounded in the numbers), persist, and return the assessment."""

    m = _compute(db, project_id)
    narrative: str | None = None
    if with_narrative:
        prov = registry.get(provider)
        if prov is not None and await prov.available():
            system = (
                "You are a project progress assessor. Using ONLY the metrics provided, write 2-3 "
                "sentences on project health and the single most important next action. Do not "
                "invent tasks or numbers."
            )
            payload = {k: m[k] for k in ("completion", "health", "risks", "recommendations")}
            try:
                import json as _json
                resp = await prov.generate(
                    [Message(role="system", content=system),
                     Message(role="user", content=_json.dumps(payload))], model)
                db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
                text = resp.text.strip()
                if text and "[mock:" not in text:
                    narrative = text
            except ProviderError:
                narrative = None
        if narrative is None:
            narrative = _heuristic_narrative(m)

    db.add_progress_assessment(project_id, m["completion"], m["health"], m["milestones"],
                               m["risks"], m["recommendations"], narrative)
    db.audit("agent", "progress_assess", {"project_id": project_id,
             "completion": m["completion"], "health": m["health"], "risks": len(m["risks"])})
    return {**m, "narrative": narrative}
