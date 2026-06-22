"""Free research source adapters: arXiv and Semantic Scholar (both free, no key required).

Problem solved: retrieve real prior-art results so the agent can summarize what exists and
where the white space is — without fabricating. Each adapter returns a normalized
``ResearchResult``. HTTP clients are injected so the parsers can be tested offline with
``httpx.MockTransport``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class ResearchResult:
    source: str
    title: str
    authors: list[str]
    year: int | None
    url: str | None
    abstract: str | None

    def as_dict(self) -> dict:
        return {
            "source": self.source, "title": self.title, "authors": self.authors,
            "year": self.year, "url": self.url, "abstract": self.abstract,
        }


def _year_from(text: str | None) -> int | None:
    if not text or len(text) < 4 or not text[:4].isdigit():
        return None
    return int(text[:4])


async def search_arxiv(query: str, client: httpx.AsyncClient, limit: int = 5) -> list[ResearchResult]:
    params = {"search_query": f"all:{query}", "start": 0, "max_results": limit}
    try:
        resp = await client.get(ARXIV_API, params=params, timeout=15.0)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except (httpx.HTTPError, ET.ParseError):
        return []
    out: list[ResearchResult] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip()
        url = (entry.findtext(f"{_ATOM}id") or "").strip() or None
        year = _year_from(entry.findtext(f"{_ATOM}published"))
        authors = [a.findtext(f"{_ATOM}name") or "" for a in entry.findall(f"{_ATOM}author")]
        if title:
            out.append(ResearchResult("arxiv", title, [a for a in authors if a], year, url, summary))
    return out


async def search_semantic_scholar(
    query: str, client: httpx.AsyncClient, limit: int = 5
) -> list[ResearchResult]:
    params = {"query": query, "limit": limit, "fields": "title,year,abstract,authors,url"}
    try:
        resp = await client.get(S2_API, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    out: list[ResearchResult] = []
    for p in data.get("data", []) or []:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        authors = [a.get("name", "") for a in (p.get("authors") or [])]
        out.append(ResearchResult(
            "semantic_scholar", title, [a for a in authors if a],
            p.get("year"), p.get("url"), p.get("abstract"),
        ))
    return out
