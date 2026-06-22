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
    is_gap: bool = False          # True = targets a concept the user is missing
    priority: float = 1.0         # higher = study sooner within its prerequisite tier


# Benefit categories a breakthrough can advance — "and much more project goal benefits".
BENEFIT_TYPES = {"business", "speed", "maintainability", "scalability", "cost", "ux", "learning"}


class Breakthrough(BaseModel):
    title: str
    description: str | None = None
    benefit_types: list[str] = Field(default_factory=list)
    impact: str = "medium"        # high|medium|low
    effort: str = "medium"        # high|medium|low
    rationale: str | None = None
    related_concepts: list[str] = Field(default_factory=list)
    score: float = 0.0


class AdvisorResult(BaseModel):
    resources: list[ResourceItem] = Field(default_factory=list)
    learning_plan: list[LearningItem] = Field(default_factory=list)
    breakthroughs: list[Breakthrough] = Field(default_factory=list)
    detected_gaps: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.resources and not self.learning_plan


_IMPACT_W = {"high": 3.0, "medium": 2.0, "low": 1.0}
_EFFORT_W = {"low": 1.0, "medium": 2.0, "high": 3.0}


def score_breakthrough(impact: str, effort: str, benefit_types: list[str]) -> float:
    """Rank by payoff: higher impact and broader benefit, discounted by effort."""

    imp = _IMPACT_W.get(impact, 2.0)
    eff = _EFFORT_W.get(effort, 2.0)
    breadth = 1.0 + 0.5 * max(0, len(benefit_types) - 1)  # reward multi-benefit wins
    return round(imp * breadth / eff, 3)


# --------------------------------------------------------------------------- prompt / parsing

SYSTEM_PROMPT = (
    "You are Phorrom's Resource & Tooling Advisor. Help the user UNDERSTAND their problem "
    "domain well enough to ideate, recommend the exact tools they need, build skill across "
    "EVERYTHING the project touches while leaning hardest into the GAPS they struggle with, "
    "and surface BREAKTHROUGH opportunities where an improvement yields a concrete project "
    "benefit (business, speed, maintainability/ease-of-future-change, scalability, cost, ux, "
    "or learning). Strongly prefer FREE and open-source options. Respond with ONLY a JSON "
    "object, no prose, matching this schema:\n"
    "{\n"
    '  "resources": [{"kind":"library|api|dataset|hardware|service|tool","name":str,'
    '"stage":str,"url":str,"is_free":bool,"rationale":str}],\n'
    '  "learning_plan": [{"concept":str,"title":str,"url":str,'
    '"source":"youtube|arxiv|freecodecamp|mdn|docs|other","rationale":str,"prereq_order":int,'
    '"is_gap":bool,"priority":number}],\n'
    '  "breakthroughs": [{"title":str,"description":str,'
    '"benefit_types":["business|speed|maintainability|scalability|cost|ux|learning"],'
    '"impact":"high|medium|low","effort":"high|medium|low","rationale":str,'
    '"related_concepts":[str]}],\n'
    '  "detected_gaps": [str]\n'
    "}\n"
    "Cover the whole project but mark gap-targeting items is_gap=true with higher priority. "
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
            "Build skill across everything the project touches, but target the learning plan "
            "(higher priority, is_gap=true) at the concepts the user struggled with and gaps "
            "you detect. Skip concepts already mastered. Also propose breakthrough "
            "opportunities where an improvement yields business/speed/maintainability/"
            "scalability/cost/ux/learning benefit; closing a gap that unlocks a new approach "
            "is itself a valid breakthrough."
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

def _gap_training_links(gap: str) -> list[dict]:
    """Extra ideation-oriented training for a gap: theory, prior art, and worked examples."""

    q = gap.replace(" ", "+")
    return [
        {"title": f"Deep dive: {gap}", "source": "youtube",
         "url": f"https://www.youtube.com/results?search_query={q}+explained"},
        {"title": f"Prior art / papers on {gap}", "source": "arxiv",
         "url": f"https://arxiv.org/search/?query={q}&searchtype=all"},
        {"title": f"Example open-source projects using {gap}", "source": "other",
         "url": f"https://github.com/search?q={q}&type=repositories"},
    ]


def _breakthrough_candidates(
    context: ProjectContext, gap_names: list[str]
) -> list[Breakthrough]:
    """Curated, benefit-tagged opportunities tailored by tech + observed gaps. Never empty."""

    tech = next((t for t in context.tech if t.strip()), "") or "core"
    out: list[Breakthrough] = []

    def add(title, benefits, impact, effort, rationale, related=None):
        out.append(Breakthrough(
            title=title, benefit_types=benefits, impact=impact, effort=effort,
            rationale=rationale, related_concepts=related or [],
            score=score_breakthrough(impact, effort, benefits),
        ))

    add("Expose the core capability as a reusable API/service",
        ["business", "scalability"], "high", "medium",
        "Lets other products and teams build on your work — opens reuse and B2B/B2C value beyond the hackathon.")
    add(f"Cache & precompute the hottest {tech} path",
        ["speed", "ux"], "medium", "low",
        "Cuts latency on the most-used flow: snappier demo and better user experience for near-zero cost.")
    add("Modularize the core behind a clean interface",
        ["maintainability", "speed"], "medium", "medium",
        "Isolates change so future features and pivots are cheap — decisive under hackathon time pressure.")
    add("Batch & parallelize the heavy workload",
        ["scalability", "speed"], "high", "medium",
        "Serves more load/users on the same resources and signals production-readiness to judges.")
    add("Offload heavy generation to local / open-source models",
        ["cost", "business"], "medium", "low",
        "Keeps recurring cost at ₹0 and de-risks free-tier limits — both a margin story and a differentiator.")

    # Gap-driven: closing a blocker the user struggles with can itself unlock a breakthrough.
    for gap in gap_names[:3]:
        add(f"Close the '{gap}' gap to unlock a differentiated approach",
            ["learning", "business"], "medium", "medium",
            f"Mastering {gap} removes the main reasoning blocker and could enable a feature competitors lack.",
            related=[gap])

    # Dedupe by title, keep highest score first.
    seen: set[str] = set()
    out.sort(key=lambda b: b.score, reverse=True)
    deduped = [b for b in out if not (b.title in seen or seen.add(b.title))]
    return deduped[:8]


def heuristic_result(context: ProjectContext, known_gaps: list[str], mastered: list[str]) -> AdvisorResult:
    """Curated, deterministic result from the free catalog. Covers everything; weights gaps."""

    haystack = context.haystack()
    mastered_set = {m.lower() for m in mastered}
    gap_set = {g.lower() for g in known_gaps}

    resources: list[ResourceItem] = []
    concepts: list[catalog.ConceptEntry] = list(catalog.FOUNDATIONS)

    for domain in catalog.CATALOG.values():
        if any(kw in haystack for kw in domain["match"]):
            for r in domain["resources"]:
                resources.append(ResourceItem(
                    kind=r["kind"], name=r["name"], stage=r["stage"], url=r["url"],
                    is_free=True, rationale=r["rationale"],
                ))
            concepts.extend(domain["concepts"])

    for r in catalog.GENERAL_RESOURCES:
        resources.append(ResourceItem(
            kind=r["kind"], name=r["name"], stage=r["stage"], url=r["url"],
            is_free=True, rationale=r["rationale"],
        ))

    learning: list[LearningItem] = []
    seen_titles: set[tuple[str, str]] = set()
    detected: list[str] = []           # gap concept names only
    covered: list[str] = []            # everything we're building skill in

    def emit(concept: str, title: str, url: str, source: str, rationale: str,
             order: int, is_gap: bool) -> None:
        key = (concept, title)
        if key in seen_titles:
            return
        seen_titles.add(key)
        learning.append(LearningItem(
            concept=concept, title=title, url=url, source=source, rationale=rationale,
            prereq_order=order, is_gap=is_gap, priority=3.0 if is_gap else 1.0,
        ))

    # Coverage: build skill across everything the project touches.
    for c in concepts:
        name = c["name"]
        if name.lower() in mastered_set:
            continue
        is_gap = name.lower() in gap_set
        covered.append(name)
        if is_gap:
            detected.append(name)
        for link in c["links"]:
            emit(name, link["title"], link["url"], link["source"], c["rationale"], c["order"], is_gap)
        # Extra ideation/training for gaps among the catalog concepts.
        if is_gap:
            for link in _gap_training_links(name):
                emit(name, link["title"], link["url"], link["source"],
                     "Ideation-focused training for a concept you struggle with.", c["order"], True)

    # Ideation-observed gaps with no catalog match: full gap treatment + ideation resources.
    matched_names = {c["name"].lower() for c in concepts}
    for gap in known_gaps:
        gl = gap.lower()
        if gl in mastered_set or gl in matched_names:
            continue
        detected.append(gap)
        covered.append(gap)
        for link in _gap_training_links(gap):
            emit(gap, link["title"], link["url"], link["source"],
                 "Surfaced as a concept you struggled to reason about during ideation.", 1, True)

    # Ideation-potential resources for the top gaps (papers + example projects to spark ideas).
    for gap in detected[:3]:
        q = gap.replace(" ", "+")
        resources.append(ResourceItem(
            kind="reference", name=f"arXiv: prior art on {gap}", stage="ideation",
            url=f"https://arxiv.org/search/?query={q}&searchtype=all", is_free=True,
            rationale="Ground your ideation in existing approaches to a concept you're closing.",
        ))

    # Sort prerequisite-first, then gaps/high-priority within each tier.
    learning.sort(key=lambda li: (li.prereq_order, -li.priority, li.concept))
    detected = list(dict.fromkeys(detected))

    return AdvisorResult(
        resources=resources,
        learning_plan=learning,
        breakthroughs=_breakthrough_candidates(context, detected),
        detected_gaps=detected,
    )


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
    else:
        # LLM gave resources/learning but maybe no breakthroughs — augment, and (re)score.
        if not result.breakthroughs:
            result.breakthroughs = _breakthrough_candidates(
                context, result.detected_gaps or known_gaps
            )
        for b in result.breakthroughs:
            if not b.score:
                b.score = score_breakthrough(b.impact, b.effort, b.benefit_types)
        result.breakthroughs.sort(key=lambda b: b.score, reverse=True)

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
            is_gap=li.is_gap, priority=li.priority,
        )
    for b in result.breakthroughs:
        db.add_breakthrough(
            project_id, title=b.title, description=b.description, benefit_types=b.benefit_types,
            impact=b.impact, effort=b.effort, rationale=b.rationale,
            related_concepts=b.related_concepts, score=b.score,
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
    breakthroughs = db.list_breakthroughs(project_id)

    def count(items: list[dict], field: str, value: str) -> int:
        return sum(1 for i in items if i[field] == value)

    progress = {
        "resources": {"total": len(resources), "done": count(resources, "status", "done")},
        "learning": {
            "total": len(learning),
            "todo": count(learning, "status", "todo"),
            "in_progress": count(learning, "status", "in_progress"),
            "done": count(learning, "status", "done"),
            "gaps": sum(1 for i in learning if i.get("is_gap")),
        },
        "concepts": {
            "gap": count(concepts, "status", "gap"),
            "learning": count(concepts, "status", "learning"),
            "mastered": count(concepts, "status", "mastered"),
        },
        "breakthroughs": {"total": len(breakthroughs)},
    }
    return {
        "resources": resources,
        "learning": learning,
        "concepts": concepts,
        "breakthroughs": breakthroughs,
        "progress": progress,
    }
