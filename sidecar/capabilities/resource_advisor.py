"""Resource & Tooling Advisor (capability #3).

Problem solved: help the user *understand their problem domain well enough to ideate*, and
surface the exact free/open-source tools their project needs. It is explicitly ideation-first,
not generic upskilling.

Inputs : a project's context (problem record, ideas, task types, chosen tech) + concept gaps
         observed during ideation (capability #2), read from the shared ``concepts`` table.
Outputs: (1) recommended resources/tools per stage and (2) a prerequisite-ordered learning
         plan targeting the concepts the user is missing — both persisted to SQLite.

Generation goes through the model-provider layer; if the model is unavailable or returns
unparseable output, a curated catalog (``catalog.py``) provides a local-first fallback so the
advisor always returns something useful.

Bridge to Ideation (#2):
- reads concepts with status ``gap``/``learning`` (often written by ideation) and targets them;
- writes newly detected gaps back as concepts;
- when the user completes a concept's learning items it flips to ``mastered`` (see
  ``Database.set_learning_status``), and ``mastered_concepts`` is exposed for ideation to reuse.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database
from . import catalog


class ProjectContext(BaseModel):
    problem: str = ""
    ideas: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)

    def haystack(self) -> str:
        parts = [self.problem, *self.ideas, *self.task_types, *self.tech]
        return " ".join(parts).lower()


class ResourceItem(BaseModel):
    kind: str = "tool"
    name: str
    stage: str | None = None
    description: str | None = None
    url: str | None = None
    is_free: bool = True
    rationale: str | None = None


class LearningItem(BaseModel):
    concept: str
    title: str
    url: str | None = None
    source: str | None = None
    rationale: str | None = None
    prereq_order: int = 0


class AdvisorResult(BaseModel):
    resources: list[ResourceItem] = Field(default_factory=list)
    learning_plan: list[LearningItem] = Field(default_factory=list)
    detected_gaps: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.resources and not self.learning_plan


# --------------------------------------------------------------------------- prompt / parsing

SYSTEM_PROMPT = (
    "You are Phorrom's Resource & Tooling Advisor. Your job is to help the user UNDERSTAND "
    "their problem domain well enough to ideate, and to recommend the exact tools they need. "
    "Strongly prefer FREE and open-source options. Respond with ONLY a JSON object, no prose, "
    "matching this schema:\n"
    "{\n"
    '  "resources": [{"kind":"library|api|dataset|hardware|service|tool","name":str,'
    '"stage":str,"url":str,"is_free":bool,"rationale":str}],\n'
    '  "learning_plan": [{"concept":str,"title":str,"url":str,'
    '"source":"youtube|arxiv|freecodecamp|mdn|docs|other","rationale":str,"prereq_order":int}],\n'
    '  "detected_gaps": [str]\n'
    "}\n"
    "Order learning_plan prerequisite-first (lower prereq_order = learn earlier)."
)


def build_messages(context: ProjectContext, known_gaps: list[str], mastered: list[str]) -> list[Message]:
    user = {
        "problem": context.problem,
        "ideas": context.ideas,
        "task_types": context.task_types,
        "tech": context.tech,
        "concepts_user_struggled_with": known_gaps,
        "concepts_already_mastered": mastered,
        "instruction": (
            "Target the learning plan at the concepts the user struggled with and at gaps you "
            "detect from the problem/tech. Skip concepts already mastered."
        ),
    }
    return [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=json.dumps(user, ensure_ascii=False)),
    ]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Tolerantly pull a JSON object out of a model response (handles code fences / prose)."""

    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_result(text: str) -> AdvisorResult | None:
    data = _extract_json(text)
    if data is None:
        return None
    try:
        return AdvisorResult.model_validate(data)
    except ValidationError:
        return None


# --------------------------------------------------------------------------- heuristic fallback

def heuristic_result(context: ProjectContext, known_gaps: list[str], mastered: list[str]) -> AdvisorResult:
    """Curated, deterministic result from the free catalog. Never empty."""

    haystack = context.haystack()
    mastered_set = {m.lower() for m in mastered}

    resources: list[ResourceItem] = []
    concepts: list[catalog.ConceptEntry] = list(catalog.FOUNDATIONS)
    matched_any = False

    for domain in catalog.CATALOG.values():
        if any(kw in haystack for kw in domain["match"]):
            matched_any = True
            for r in domain["resources"]:
                resources.append(ResourceItem(
                    kind=r["kind"], name=r["name"], stage=r["stage"], url=r["url"],
                    is_free=True, rationale=r["rationale"],
                ))
            concepts.extend(domain["concepts"])

    # Always offer the generally-useful free resources.
    for r in catalog.GENERAL_RESOURCES:
        resources.append(ResourceItem(
            kind=r["kind"], name=r["name"], stage=r["stage"], url=r["url"],
            is_free=True, rationale=r["rationale"],
        ))

    # Build the learning plan from matched concepts, skipping already-mastered ones.
    learning: list[LearningItem] = []
    seen_titles: set[tuple[str, str]] = set()
    detected: list[str] = []
    for c in concepts:
        if c["name"].lower() in mastered_set:
            continue
        detected.append(c["name"])
        for link in c["links"]:
            key = (c["name"], link["title"])
            if key in seen_titles:
                continue
            seen_titles.add(key)
            learning.append(LearningItem(
                concept=c["name"], title=link["title"], url=link["url"],
                source=link["source"], rationale=c["rationale"], prereq_order=c["order"],
            ))

    # Ideation-observed gaps with no catalog match: give them a starting point.
    matched_concept_names = {c["name"].lower() for c in concepts}
    for gap in known_gaps:
        if gap.lower() in mastered_set or gap.lower() in matched_concept_names:
            continue
        detected.append(gap)
        learning.append(LearningItem(
            concept=gap,
            title=f"Search: understand '{gap}'",
            url=f"https://www.youtube.com/results?search_query={gap.replace(' ', '+')}+explained",
            source="youtube",
            rationale="Surfaced as a concept you struggled to reason about during ideation.",
            prereq_order=1,
        ))

    learning.sort(key=lambda li: (li.prereq_order, li.concept))
    # Dedupe detected gaps preserving order.
    detected = list(dict.fromkeys(detected))
    _ = matched_any  # matched_any retained for future telemetry; foundations always included.
    return AdvisorResult(resources=resources, learning_plan=learning, detected_gaps=detected)


# --------------------------------------------------------------------------- orchestration

async def advise(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    context: ProjectContext,
    provider: str = "mock",
    model: str = "mock-small",
) -> AdvisorResult:
    """Generate, persist, and return resource + learning recommendations for a project."""

    # Pull the shared skill model: open gaps (often from ideation) to target, mastered to skip.
    open_concepts = db.list_concepts(project_id, status="gap") + db.list_concepts(
        project_id, status="learning"
    )
    known_gaps = [c["name"] for c in open_concepts]
    mastered = db.mastered_concepts(project_id)

    result: AdvisorResult | None = None
    prov = registry.get(provider)
    if prov is not None and await prov.available():
        messages = build_messages(context, known_gaps, mastered)
        try:
            resp = await prov.generate(messages, model)
            db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
            result = parse_result(resp.text)
        except ProviderError:
            result = None

    # Local-first fallback: curated catalog whenever the model path fails or is empty.
    if result is None or result.is_empty():
        result = heuristic_result(context, known_gaps, mastered)

    _persist(db, project_id, result)
    db.audit("agent", "resource_advice", {
        "project_id": project_id,
        "resources": len(result.resources),
        "learning_items": len(result.learning_plan),
        "gaps": result.detected_gaps,
    })
    return result


def _persist(db: Database, project_id: int, result: AdvisorResult) -> None:
    db.clear_advisor_outputs(project_id)  # fresh suggestions; concepts/progress preserved
    for r in result.resources:
        db.add_resource_suggestion(
            project_id, kind=r.kind, name=r.name, stage=r.stage, description=r.description,
            url=r.url, is_free=r.is_free, rationale=r.rationale,
        )
    for li in result.learning_plan:
        db.add_learning_item(
            project_id, concept=li.concept, title=li.title, url=li.url, source=li.source,
            rationale=li.rationale, prereq_order=li.prereq_order,
        )
    # Register concepts (gaps detected + every learning concept) without downgrading mastery.
    concept_names = set(result.detected_gaps) | {li.concept for li in result.learning_plan}
    for name in concept_names:
        db.upsert_concept(project_id, name, status="gap", origin="advisor")


def overview(db: Database, project_id: int) -> dict[str, Any]:
    """Everything the frontend panel needs in one read: resources, learning, progress, concepts."""

    resources = db.list_resource_suggestions(project_id)
    learning = db.list_learning_items(project_id)
    concepts = db.list_concepts(project_id)

    def count(items: list[dict], field: str, value: str) -> int:
        return sum(1 for i in items if i[field] == value)

    progress = {
        "resources": {"total": len(resources), "done": count(resources, "status", "done")},
        "learning": {
            "total": len(learning),
            "todo": count(learning, "status", "todo"),
            "in_progress": count(learning, "status", "in_progress"),
            "done": count(learning, "status", "done"),
        },
        "concepts": {
            "gap": count(concepts, "status", "gap"),
            "learning": count(concepts, "status", "learning"),
            "mastered": count(concepts, "status", "mastered"),
        },
    }
    return {"resources": resources, "learning": learning, "concepts": concepts, "progress": progress}
