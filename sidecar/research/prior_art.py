"""Prior-art aggregator: search free sources, dedupe, and summarize the white space.

Problem solved: capability #4's brain. It runs the source adapters, merges + dedupes results,
and asks the model for a grounded summary that identifies what's already covered and where the
*white space* is — citing results by index, never inventing papers. If the model is
unavailable or returns nothing, a clearly-labelled non-fabricating heuristic summary is used.
"""

from __future__ import annotations

import httpx

from ..providers.base import Message, ProviderError
from ..providers.registry import ProviderRegistry
from ..storage.db import Database
from .sources import ResearchResult, search_arxiv, search_semantic_scholar


def _dedupe(results: list[ResearchResult]) -> list[ResearchResult]:
    seen: set[str] = set()
    out: list[ResearchResult] = []
    for r in results:
        key = r.title.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out


async def gather(query: str, client: httpx.AsyncClient, limit: int = 5) -> list[ResearchResult]:
    arxiv = await search_arxiv(query, client, limit)
    s2 = await search_semantic_scholar(query, client, limit)
    return _dedupe([*arxiv, *s2])


def _grounded_prompt(query: str, results: list[ResearchResult]) -> list[Message]:
    lines = []
    for i, r in enumerate(results, 1):
        abs = (r.abstract or "")[:400]
        lines.append(f"[{i}] ({r.source}, {r.year}) {r.title}\n    {abs}")
    catalog = "\n".join(lines)
    system = (
        "You summarize prior art for a project. Use ONLY the numbered results provided — never "
        "invent papers or facts. Cite results as [n]. Output two short paragraphs: (1) what the "
        "existing work covers, (2) the WHITE SPACE — what appears NOT addressed and where this "
        "project could be novel. If results are thin, say so."
    )
    user = f"Topic: {query}\n\nResults:\n{catalog}"
    return [Message(role="system", content=system), Message(role="user", content=user)]


def _heuristic_summary(query: str, results: list[ResearchResult]) -> tuple[str, str]:
    if not results:
        return (
            f"No prior-art results were retrieved for '{query}' (sources may be offline). "
            "No claims can be made without sources.",
            f"White space cannot be assessed for '{query}' without retrieved results.",
        )
    sources = ", ".join(sorted({r.source for r in results}))
    summary = (
        f"Retrieved {len(results)} result(s) for '{query}' from {sources}. "
        f"Most relevant: {results[0].title} ({results[0].year})."
    )
    white_space = (
        f"Review the {len(results)} retrieved result(s); aspects of '{query}' not reflected in "
        "their titles/abstracts are candidate white space. (Heuristic — not model-generated.)"
    )
    return summary, white_space


async def prior_art_search(
    registry: ProviderRegistry,
    db: Database,
    project_id: int,
    query: str,
    client: httpx.AsyncClient,
    provider: str = "mock",
    model: str = "mock-small",
    limit: int = 5,
) -> dict:
    """Search, persist results, summarize white space (grounded), persist + return everything."""

    results = await gather(query, client, limit)
    for r in results:
        db.add_research_result(project_id, query, r.source, r.title, r.authors, r.year,
                               r.url, r.abstract)

    summary: str | None = None
    white_space: str | None = None
    grounded = True
    prov = registry.get(provider)
    if results and prov is not None and await prov.available():
        try:
            resp = await prov.generate(_grounded_prompt(query, results), model)
            db.record_run(resp.provider, resp.model, resp.tokens_in, resp.tokens_out, resp.latency_ms)
            text = resp.text.strip()
            if text and "[mock:" not in text:  # the bare echo mock isn't a real summary
                summary = text
        except ProviderError:
            summary = None

    if summary is None:
        summary, white_space = _heuristic_summary(query, results)
        grounded = bool(results)  # heuristic over real results is still source-grounded

    db.add_research_summary(project_id, query, summary, white_space, len(results), grounded)
    db.audit("agent", "prior_art", {"project_id": project_id, "query": query, "n": len(results)})
    return {
        "query": query,
        "results": [r.as_dict() for r in results],
        "summary": summary,
        "white_space": white_space,
        "n_results": len(results),
        "grounded": grounded,
    }
