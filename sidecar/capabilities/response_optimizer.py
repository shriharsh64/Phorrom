"""Response Optimization Layer (capability #10).

Problem solved: the agent should not just answer — it should judge whether its answer is
relevant and at the right depth/tone for the task, and recalibrate if not. This implements a
generate → self-evaluate → re-steer loop:

1. Build steering directives from the requested depth/tone/focus.
2. Generate through the provider layer.
3. Self-evaluate the output (relevance to the task context + depth fit) — deterministic, so it
   works offline and is testable.
4. If below threshold and passes remain, append the eval's corrective directives and regenerate.
5. Return the best output plus the evaluation trace.

The evaluator is pure (keyword-overlap relevance + length-vs-depth fit); the generation step
uses any provider. Mock-friendly for tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "was",
    "but", "not", "all", "can", "will", "how", "what", "why", "use", "using", "about", "a", "an",
}

# Target character ranges per requested depth.
DEPTH_TARGETS = {"brief": (0, 400), "standard": (250, 1400), "deep": (900, 100_000)}


@dataclass
class Eval:
    score: float
    relevance: float
    depth_fit: float
    on_topic: bool
    directives: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{3,}", (text or "").lower())
            if w not in _STOPWORDS}


def evaluate(response: str, context_text: str, target_depth: str = "standard") -> Eval:
    """Score a response's relevance to the task context and fit to the requested depth."""

    ctx = keywords(context_text)
    resp = keywords(response)
    if ctx:
        overlap = ctx & resp
        relevance = len(overlap) / len(ctx)
        missing = sorted(ctx - resp)[:6]
    else:
        relevance, missing = 0.5, []  # no context to judge against → neutral

    lo, hi = DEPTH_TARGETS.get(target_depth, DEPTH_TARGETS["standard"])
    n = len(response or "")
    if lo <= n <= hi:
        depth_fit = 1.0
    elif n < lo:
        depth_fit = max(0.0, n / lo) if lo else 1.0
    else:
        depth_fit = max(0.3, hi / n)

    score = round(0.6 * relevance + 0.4 * depth_fit, 4)
    directives: list[str] = []
    if relevance < 0.5 and missing:
        directives.append(f"Focus more directly on: {', '.join(missing)}.")
    if n < lo:
        directives.append("Add more depth: concrete detail, steps, or examples.")
    elif n > hi:
        directives.append("Be more concise — keep only what's essential.")
    return Eval(score, round(relevance, 4), round(depth_fit, 4), relevance >= 0.2, directives, missing)


def build_directives(depth: str, tone: str | None, focus: str | None) -> str:
    parts = [f"Respond at '{depth}' depth."]
    if tone:
        parts.append(f"Use a {tone} tone.")
    if focus:
        parts.append(f"Center the answer on: {focus}.")
    return " ".join(parts)


@dataclass
class OptimizeResult:
    text: str
    score: float
    relevance: float
    depth_fit: float
    iterations: int
    directives: str
    trace: list[dict] = field(default_factory=list)


async def optimize(
    registry: ProviderRegistry,
    db: Database,
    prompt: str,
    context_text: str = "",
    depth: str = "standard",
    tone: str | None = None,
    focus: str | None = None,
    project_id: int | None = None,
    provider: str = "mock",
    model: str = "mock-small",
    threshold: float = 0.7,
    max_iters: int = 3,
) -> OptimizeResult:
    """Run the generate→self-eval→re-steer loop; persist the run; return the best output."""

    prov = registry.get(provider)
    base = "You are a helpful project co-pilot."
    directives = build_directives(depth, tone, focus)
    best: tuple[Eval, str] | None = None
    trace: list[dict] = []
    iterations = 0

    if prov is not None and await prov.available():
        for _ in range(max_iters):
            iterations += 1
            messages = [Message(role="system", content=f"{base} {directives}"),
                        Message(role="user", content=prompt)]
            try:
                resp = await prov.generate(messages, model)
            except ProviderError:
                break
            db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
            ev = evaluate(resp.text, context_text or prompt, depth)
            trace.append({"score": ev.score, "relevance": ev.relevance,
                          "depth_fit": ev.depth_fit, "directives": ev.directives})
            if best is None or ev.score > best[0].score:
                best = (ev, resp.text)
            if ev.score >= threshold:
                break
            if ev.directives:  # recalibrate for the next pass
                directives = f"{directives} {' '.join(ev.directives)}"

    if best is None:  # provider unavailable → evaluate the prompt echo deterministically
        ev = evaluate(prompt, context_text or prompt, depth)
        best, iterations = (ev, prompt), max(iterations, 1)
        trace.append({"score": ev.score, "relevance": ev.relevance,
                      "depth_fit": ev.depth_fit, "directives": ev.directives, "note": "no provider"})

    ev, text = best
    db.add_response_evaluation(project_id, prompt, ev.score, ev.relevance, ev.depth_fit,
                               iterations, directives)
    db.audit("agent", "optimize_response",
             {"project_id": project_id, "score": ev.score, "iterations": iterations})
    return OptimizeResult(text, ev.score, ev.relevance, ev.depth_fit, iterations, directives, trace)
