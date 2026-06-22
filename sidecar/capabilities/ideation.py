"""Ideation & Concept Engine (capability #2).

Problem solved: generate, evaluate, and rank ideas for a project by feasibility, novelty, and
relevance — and, critically, close the loop with the Resource Advisor (#3):
- it reads concepts the user has already **mastered** (so it can reason at a higher level and
  not re-suggest learning them);
- it writes the concepts each idea **requires but the user hasn't mastered** as ``gap``
  concepts (origin='ideation'), which the Advisor then targets with training.

Generation goes through the provider layer with a deterministic heuristic fallback.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database


class Idea(BaseModel):
    title: str
    description: str = ""
    feasibility: float = Field(default=0.5, ge=0.0, le=1.0)
    novelty: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str | None = None
    required_concepts: list[str] = Field(default_factory=list)
    score: float = 0.0


class IdeationResult(BaseModel):
    ideas: list[Idea] = Field(default_factory=list)
    detected_gaps: list[str] = Field(default_factory=list)


def score_idea(feasibility: float, novelty: float, relevance: float) -> float:
    """Relevance leads, then feasibility, then novelty — tuned for hackathon usefulness."""

    return round(0.40 * relevance + 0.35 * feasibility + 0.25 * novelty, 4)


SYSTEM_PROMPT = (
    "You are Phorrom's Ideation & Concept Engine. Given a problem and the concepts the user has "
    "already mastered, generate diverse, concrete ideas and score each by feasibility, novelty, "
    "and relevance (0..1). For each idea, list required_concepts (skills/knowledge needed to "
    "pursue it). Respond with ONLY JSON:\n"
    '{"ideas":[{"title":str,"description":str,"feasibility":0..1,"novelty":0..1,'
    '"relevance":0..1,"rationale":str,"required_concepts":[str]}]}'
)


def _extract_json(text: str) -> dict[str, Any] | None:
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


def parse_ideas(text: str) -> list[Idea] | None:
    data = _extract_json(text)
    if data is None or "ideas" not in data:
        return None
    try:
        ideas = [Idea.model_validate(i) for i in data["ideas"]]
    except (ValidationError, TypeError):
        return None
    return ideas or None


def heuristic_ideas(problem: str) -> list[Idea]:
    """Template ideas tailored to the problem text when no model is available."""

    topic = (problem.strip() or "the problem").rstrip(".")
    short = topic if len(topic) < 60 else topic[:57] + "…"
    return [
        Idea(title=f"Automation tool for {short}", feasibility=0.8, novelty=0.4, relevance=0.85,
             rationale="Direct, buildable solution to the stated problem.",
             required_concepts=["Workflow automation", "Domain data modeling"],
             description=f"Automate the core manual workflow behind {short}."),
        Idea(title=f"Analytics dashboard for {short}", feasibility=0.7, novelty=0.5, relevance=0.75,
             rationale="Turns raw signals into decisions; demos well.",
             required_concepts=["Data visualization", "Data pipelines"],
             description=f"Surface insights and trends around {short}."),
        Idea(title=f"ML-assisted assistant for {short}", feasibility=0.5, novelty=0.8, relevance=0.7,
             rationale="Higher novelty via prediction/recommendation; more skill-intensive.",
             required_concepts=["ML foundations", "Model evaluation & metrics"],
             description=f"Predict or recommend next actions for {short}."),
    ]


async def ideate(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    prompt: str | None = None,
    provider: str = "mock",
    model: str = "mock-small",
) -> IdeationResult:
    """Generate, rank, and persist ideas; write required-but-unmastered concepts as gaps."""

    problem_rec = db.latest_problem_record(project_id)
    problem = prompt or (problem_rec["statement"] if problem_rec else "") or ""
    mastered = db.mastered_concepts(project_id)
    mastered_set = {m.lower() for m in mastered}

    ideas: list[Idea] | None = None
    prov = registry.get(provider)
    if prov is not None and await prov.available():
        user = {"problem": problem, "concepts_already_mastered": mastered,
                "instruction": "Prefer ideas the user can realistically pursue; be concrete."}
        try:
            resp = await prov.generate(
                [Message(role="system", content=SYSTEM_PROMPT),
                 Message(role="user", content=json.dumps(user, ensure_ascii=False))],
                model,
            )
            db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
            ideas = parse_ideas(resp.text)
        except ProviderError:
            ideas = None

    if not ideas:
        ideas = heuristic_ideas(problem)

    for idea in ideas:
        idea.score = score_idea(idea.feasibility, idea.novelty, idea.relevance)
    ideas.sort(key=lambda i: i.score, reverse=True)

    # Persist ideas (fresh batch) and feed required-but-unmastered concepts back as gaps.
    db.clear_ideas(project_id)
    detected: list[str] = []
    for idea in ideas:
        db.add_idea(project_id, idea.title, idea.description, idea.feasibility, idea.novelty,
                    idea.relevance, idea.score, idea.rationale, idea.required_concepts)
        for concept in idea.required_concepts:
            if concept.lower() in mastered_set:
                continue
            db.upsert_concept(project_id, concept, status="gap", origin="ideation")
            detected.append(concept)

    detected = list(dict.fromkeys(detected))
    db.audit("agent", "ideate", {"project_id": project_id, "ideas": len(ideas), "gaps": detected})
    return IdeationResult(ideas=ideas, detected_gaps=detected)
