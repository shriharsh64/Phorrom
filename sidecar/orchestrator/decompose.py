"""Task decomposition → a validated subtask DAG.

Problem solved: split one task into smaller subtasks that can be routed to different models.
An LLM planner returns a JSON DAG; we validate the schema, reject/repair malformed output, and
fall back to a deterministic split when no model is available.

Subtask fields (the routing/budgeting signals):
- id, depends_on : DAG structure
- type           : coding|reasoning|summarization|creative|long_context|vision
- size_hint      : expected token magnitude
- value          : business value weight (0..1)
- p_required     : probability the subtask is actually needed (for budget reservation)
- quality_sensitivity : how much output quality matters (0..1)
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from .profiles import TASK_TYPES


class Subtask(BaseModel):
    id: str
    type: str = "reasoning"
    depends_on: list[str] = Field(default_factory=list)
    size_hint: int = Field(default=500, ge=1)
    value: float = Field(default=0.5, ge=0.0, le=1.0)
    p_required: float = Field(default=1.0, ge=0.0, le=1.0)
    quality_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    description: str = ""

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        return v if v in TASK_TYPES else "reasoning"


class DAG(BaseModel):
    subtasks: list[Subtask]

    def validate_graph(self) -> None:
        """Ensure ids are unique and dependencies reference existing, acyclic nodes."""

        ids = [s.id for s in self.subtasks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate subtask ids")
        idset = set(ids)
        for s in self.subtasks:
            for dep in s.depends_on:
                if dep not in idset:
                    raise ValueError(f"subtask '{s.id}' depends on unknown '{dep}'")
        # cycle check via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {i: WHITE for i in ids}
        adj = {s.id: s.depends_on for s in self.subtasks}

        def visit(n: str) -> None:
            color[n] = GRAY
            for m in adj[n]:
                if color[m] == GRAY:
                    raise ValueError("dependency cycle detected")
                if color[m] == WHITE:
                    visit(m)
            color[n] = BLACK

        for i in ids:
            if color[i] == WHITE:
                visit(i)


SYSTEM_PROMPT = (
    "You are Phorrom's task planner. Decompose the task into a DAG of subtasks that can be "
    "routed to different models. Respond with ONLY JSON:\n"
    '{"subtasks":[{"id":str,"type":"coding|reasoning|summarization|creative|long_context|'
    'vision","depends_on":[str],"size_hint":int,"value":0..1,"p_required":0..1,'
    '"quality_sensitivity":0..1,"description":str}]}\n'
    "Use stable short ids. depends_on must reference earlier ids. No cycles."
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


def parse_dag(text: str) -> DAG | None:
    data = _extract_json(text)
    if data is None:
        return None
    try:
        dag = DAG.model_validate(data)
        dag.validate_graph()
    except (ValidationError, ValueError):
        return None
    return dag if dag.subtasks else None


def heuristic_dag(task_title: str) -> DAG:
    """Deterministic generic split when no model is available: research → build → review."""

    return DAG(subtasks=[
        Subtask(id="research", type="reasoning", size_hint=600, value=0.6, p_required=1.0,
                quality_sensitivity=0.6, description=f"Research and frame: {task_title}"),
        Subtask(id="draft", type="coding", depends_on=["research"], size_hint=1200, value=0.9,
                p_required=1.0, quality_sensitivity=0.85, description=f"Produce the core artifact for: {task_title}"),
        Subtask(id="summary", type="summarization", depends_on=["draft"], size_hint=300,
                value=0.4, p_required=0.7, quality_sensitivity=0.4,
                description="Summarize results and next steps"),
    ])


async def decompose(
    registry: ProviderRegistry,
    task_title: str,
    provider: str = "mock",
    model: str = "mock-small",
) -> DAG:
    """Return a validated subtask DAG for a task (LLM with heuristic fallback)."""

    prov = registry.get(provider)
    if prov is not None and await prov.available():
        try:
            resp = await prov.generate(
                [Message(role="system", content=SYSTEM_PROMPT),
                 Message(role="user", content=task_title)],
                model,
            )
            dag = parse_dag(resp.text)
            if dag is not None:
                return dag
        except ProviderError:
            pass
    return heuristic_dag(task_title)
