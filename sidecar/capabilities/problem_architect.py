"""Problem-Statement Architect (capability #1).

Problem solved: turn a rough description into a structured, validated problem record — the
foundation everything else (ideation, resources, roadmap) builds on. It defines and scopes the
problem, names the gap, and surfaces clarifying questions when the framing is thin.

Generation goes through the provider layer; a deterministic heuristic builds a usable record
when the model is unavailable or returns unparseable output (local-first).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database


class ProblemRecord(BaseModel):
    statement: str = ""
    scope: str | None = None
    gap: str | None = None
    stakeholders: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validation: str | None = None
    clarifying_questions: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "You are Phorrom's Problem-Statement Architect. Given a rough description, produce a "
    "structured, well-scoped problem record and identify the gap it addresses. If the framing "
    "is thin, add clarifying_questions. Respond with ONLY a JSON object matching:\n"
    "{\"statement\":str,\"scope\":str,\"gap\":str,\"stakeholders\":[str],"
    "\"success_criteria\":[str],\"constraints\":[str],\"assumptions\":[str],"
    "\"validation\":str,\"clarifying_questions\":[str]}"
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


def parse_record(text: str) -> ProblemRecord | None:
    data = _extract_json(text)
    if data is None:
        return None
    try:
        return ProblemRecord.model_validate(data)
    except ValidationError:
        return None


def heuristic_record(description: str) -> ProblemRecord:
    """Build a serviceable record from raw text when no model is available."""

    text = description.strip()
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0] if text else "Untitled problem"
    thin = len(text.split()) < 12
    return ProblemRecord(
        statement=first,
        scope=text,
        gap="To be refined — clarify what existing solutions miss.",
        success_criteria=["Define a measurable outcome that signals the problem is solved."],
        assumptions=["Derived heuristically from the description; review before relying on it."],
        validation=(
            "Thin description — answer the clarifying questions to strengthen the framing."
            if thin else "Auto-structured from the description; review scope and gap."
        ),
        clarifying_questions=[
            "Who specifically experiences this problem, and how often?",
            "What do current alternatives fail to do?",
            "What does success look like in measurable terms?",
        ],
    )


async def architect(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    description: str,
    provider: str = "mock",
    model: str = "mock-small",
) -> ProblemRecord:
    """Generate, persist, and return a structured problem record for a project."""

    record: ProblemRecord | None = None
    prov = registry.get(provider)
    if prov is not None and await prov.available():
        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=description),
        ]
        try:
            resp = await prov.generate(messages, model)
            db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
            record = parse_record(resp.text)
        except ProviderError:
            record = None

    if record is None or not record.statement.strip():
        record = heuristic_record(description)

    db.add_problem_record(
        project_id,
        statement=record.statement,
        scope=record.scope,
        gap=record.gap,
        stakeholders=record.stakeholders,
        success_criteria=record.success_criteria,
        constraints=record.constraints,
        assumptions=record.assumptions,
        validation=record.validation,
        status="draft",
    )
    db.audit("agent", "problem_record", {"project_id": project_id, "statement": record.statement})
    return record
