"""Document & Research-Paper Generator (capability #5).

Problem solved: produce a rule-compliant, citeable report/paper grounded in the project's ACTUAL
data — problem record, ideas, tasks, prior-art results, progress — not invented content. We
assemble a structured Markdown document with a Jinja2 template, then call Pandoc to render it to
Markdown / DOCX / PDF (PDF via the local TinyTeX engine).

Inputs : project_id + desired format (md|docx|pdf) and citation style (ieee|acm|apa).
Outputs: a written file under the project's generated-docs dir, plus the Markdown source.

Grounding rule: every reference comes from a real retrieved prior-art result; nothing is
fabricated. If a section has no data, it says so.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from jinja2 import Template

from .. import tools
from ..storage.db import Database

STYLES = {"ieee": "IEEE", "acm": "ACM", "apa": "APA"}
FORMATS = {"md", "docx", "pdf"}

_TEMPLATE = Template(
    """---
title: "{{ title }}"
author: "{{ author }}"
date: "{{ date }}"
---

# Abstract

{{ abstract }}

# 1. Problem Statement

{{ problem.statement or "No problem statement defined yet." }}

{% if problem.gap %}**Gap addressed.** {{ problem.gap }}{% endif %}
{% if problem.scope %}**Scope.** {{ problem.scope }}{% endif %}
{% if problem.success_criteria %}**Success criteria.**
{% for c in problem.success_criteria %}- {{ c }}
{% endfor %}{% endif %}

# 2. Proposed Concepts

{% if ideas %}{% for idea in ideas %}### {{ loop.index }}. {{ idea.title }} (score {{ "%.2f"|format(idea.score) }})

{{ idea.description or "" }}
*Feasibility {{ "%.2f"|format(idea.feasibility or 0) }} · Novelty {{ "%.2f"|format(idea.novelty or 0) }} · Relevance {{ "%.2f"|format(idea.relevance or 0) }}.*{% if idea.rationale %} {{ idea.rationale }}{% endif %}

{% endfor %}{% else %}No ideas recorded yet.
{% endif %}

# 3. Related Work

{% if results %}The following prior art was retrieved and reviewed:

{% for r in results %}[{{ loop.index }}] {{ r.title }}{% if r.year %} ({{ r.year }}){% endif %}{% if r.authors %} — {{ r.authors|join(', ') }}{% endif %}.{% if r.url %} <{{ r.url }}>{% endif %}
{% endfor %}
{% if white_space %}
**White space.** {{ white_space }}{% endif %}
{% else %}No prior-art search has been run for this project.
{% endif %}

# 4. Work Plan

{% if tasks %}| # | Task | Status | Priority |
|---|------|--------|----------|
{% for t in tasks %}| {{ loop.index }} | {{ t.title }} | {{ t.status }} | {{ "%.2f"|format(t.priority or 0) }} |
{% endfor %}{% else %}No tasks defined yet.
{% endif %}

# 5. Progress &amp; Assessment

{% if progress %}Completion **{{ (progress.completion*100)|round|int }}%**, health **{{ (progress.health*100)|round|int }}%**.
{% if progress.risks %}
Key risks:
{% for r in progress.risks %}- [{{ r.severity }}] {{ r.detail }}
{% endfor %}{% endif %}{% else %}No progress assessment recorded yet.
{% endif %}

# 6. Future Scope

{{ future_scope }}

# References

{% if results %}{% for r in results %}[{{ loop.index }}] {{ r.authors|join(', ') if r.authors else "Unknown" }}. "{{ r.title }}."{% if r.year %} {{ r.year }}.{% endif %}{% if r.url %} {{ r.url }}.{% endif %}
{% endfor %}{% else %}_No external references cited (no prior-art search run)._
{% endif %}
"""
)


def build_markdown(data: dict, title: str, author: str, style: str) -> str:
    style_name = STYLES.get(style, "APA")
    abstract = (
        f"This {style_name}-style report documents the '{data['project']['name']}' project. "
        f"It frames the problem, proposes concepts, situates the work against retrieved prior "
        f"art, lays out the plan, and assesses progress. All content is derived from project "
        f"records; references are real retrieved sources."
    )
    future = "; ".join(
        i["title"] for i in data["ideas"][3:6]
    ) or "Extend the validated concepts, close the open skill gaps, and pursue the highest-scored breakthrough opportunities."
    return _TEMPLATE.render(
        title=title, author=author, date=time.strftime("%Y-%m-%d"),
        abstract=abstract, problem=data["problem"], ideas=data["ideas"],
        results=data["results"], white_space=data["white_space"], tasks=data["tasks"],
        progress=data["progress"], future_scope=future,
    )


def _gather(db: Database, project_id: int) -> dict:
    project = db.get_project(project_id) or {"name": f"Project {project_id}"}
    problem = db.latest_problem_record(project_id) or {
        "statement": "", "gap": None, "scope": None, "success_criteria": []}
    summary = db.latest_research_summary(project_id)
    return {
        "project": project,
        "problem": problem,
        "ideas": db.list_ideas(project_id),
        "results": db.list_research_results(project_id),
        "white_space": summary.get("white_space") if summary else None,
        "tasks": db.list_tasks(project_id),
        "progress": db.latest_progress_assessment(project_id),
    }


def _output_dir() -> Path:
    d = tools.project_root() / "generated-docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate(db: Database, project_id: int, fmt: str = "md", style: str = "apa",
             title: str | None = None, author: str = "Phorrom") -> dict:
    """Generate a document; returns {path, format, style, markdown, warning?}."""

    if fmt not in FORMATS:
        raise ValueError(f"unsupported format '{fmt}'")
    data = _gather(db, project_id)
    title = title or f"{data['project']['name']}: Project Report"
    md = build_markdown(data, title, author, style)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = _output_dir() / f"report-{project_id}-{stamp}"
    md_path = base.with_suffix(".md")
    md_path.write_text(md, encoding="utf-8")

    result = {"format": fmt, "style": style, "markdown": md, "path": str(md_path), "warning": None}
    if fmt == "md":
        out = md_path
    else:
        out, warning = _pandoc_render(md_path, base.with_suffix(f".{fmt}"), fmt)
        result["warning"] = warning
        if out is None:
            result["format"] = "md"  # fell back to markdown
            out = md_path
    result["path"] = str(out)
    db.audit("agent", "generate_doc", {"project_id": project_id, "format": result["format"],
             "style": style, "path": result["path"]})
    return result


def _pandoc_render(md_path: Path, out_path: Path, fmt: str) -> tuple[Path | None, str | None]:
    """Render Markdown to docx/pdf via Pandoc. Returns (path, warning)."""

    pandoc = tools.find_pandoc()
    if pandoc is None:
        return None, "Pandoc not found — returned Markdown instead."

    env = dict(os.environ)
    cmd = [pandoc, str(md_path), "-o", str(out_path), "--standalone"]
    if fmt == "pdf":
        latex = tools.latex_bin_dir()
        if latex is None:
            return None, "No LaTeX engine (TinyTeX) found — returned Markdown instead."
        env["PATH"] = latex + os.pathsep + env.get("PATH", "")  # let pandoc find pdflatex
        cmd += ["--pdf-engine=pdflatex"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"Pandoc failed: {e}"
    if proc.returncode != 0 or not out_path.exists():
        return None, f"Pandoc error: {proc.stderr.strip()[:400]}"
    return out_path, None
