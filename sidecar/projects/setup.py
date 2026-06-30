"""Project setup: workspace, scaffolding, feature suggestion, prompt generation, export.

Problem solved: turn the new-project wizard's answers (description, deadline, chosen features,
extra details, API-key needs) into (a) a real folder on disk under the user's chosen workspace,
(b) a tailored prompt for *every* feature of the app written the specific way that feature
consumes input, and (c) a systematic, file-based mirror of everything the user and the app
produce — so the project survives independently of the SQLite DB and can be backed up to Drive.

Everything here is deterministic and offline (local-first): suggestions and prompts are built
from the description with simple keyword heuristics, no model call required.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..storage.db import Database


# --------------------------------------------------------------------------- app features
# The catalogue of app features a project drives. ``demands`` documents *how* each feature wants
# its input — the prompt generator targets exactly that shape. ``builder`` returns the ready
# prompt string for a given project context.
FEATURES: list[dict[str, str]] = [
    {
        "key": "chat",
        "label": "Chat co-pilot",
        "demands": "A free-form seed message that gives the assistant full project context.",
    },
    {
        "key": "plan",
        "label": "Plan (Problem-Statement Architect)",
        "demands": "A rough description; returns a structured, scoped problem record.",
    },
    {
        "key": "ideation",
        "label": "Ideation & Concept Engine",
        "demands": "An optional steer; returns ranked ideas with required concepts.",
    },
    {
        "key": "research",
        "label": "Prior-art research",
        "demands": "A short search query; returns grounded literature + white-space.",
    },
    {
        "key": "orchestrator",
        "label": "Multi-model orchestrator",
        "demands": "A single concrete task to decompose, plus a token budget.",
    },
    {
        "key": "advisor",
        "label": "Resource & learning advisor",
        "demands": "Problem, candidate ideas, task types and tech to recommend around.",
    },
    {
        "key": "docs",
        "label": "Document generation",
        "demands": "A report style (IEEE/ACM/APA) and a title; pulls from project data.",
    },
]

FEATURE_KEYS = [f["key"] for f in FEATURES]


# --------------------------------------------------------------------------- workspace
def default_workspace() -> str:
    """Sensible default location for the projects workspace (user's home)."""
    return str(Path.home() / "PhorromProjects")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-._").lower()
    return slug or "project"


def ensure_workspace(path: str, name: str | None = None) -> dict:
    """Create the workspace folder (where all projects live) and drop a marker file."""
    root = Path(path).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".phorrom-workspace.json"
    meta = {"name": name or root.name, "created": time.time()}
    marker.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"path": str(root.resolve()), "name": meta["name"]}


def unique_project_dir(workspace: str, name: str) -> Path:
    """Pick a non-colliding folder under the workspace for a new project."""
    base = Path(workspace).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    slug = slugify(name)
    candidate = base / slug
    n = 2
    while candidate.exists():
        candidate = base / f"{slug}-{n}"
        n += 1
    return candidate


# --------------------------------------------------------------------------- feature suggestion
# Keyword → suggested feature mapping. Each project always gets the core features; domain
# keywords in the description add targeted ones.
_KEYWORD_FEATURES: list[tuple[tuple[str, ...], dict[str, str]]] = [
    (("web", "site", "frontend", "react", "ui", "app"),
     {"name": "Responsive web UI", "description": "Accessible, mobile-friendly interface."}),
    (("api", "backend", "server", "rest", "endpoint"),
     {"name": "REST API", "description": "Documented endpoints with auth and validation."}),
    (("ml", "model", "ai", "machine learning", "predict", "classif", "neural"),
     {"name": "ML pipeline", "description": "Data prep, training, evaluation, inference."}),
    (("data", "dataset", "analytics", "dashboard", "chart", "report"),
     {"name": "Analytics dashboard", "description": "Charts and exportable reports."}),
    (("auth", "login", "user", "account", "sign"),
     {"name": "Authentication", "description": "Sign-up, login, sessions, roles."}),
    (("payment", "billing", "subscription", "stripe", "checkout"),
     {"name": "Payments", "description": "Checkout, invoicing, subscription handling."}),
    (("mobile", "android", "ios", "flutter"),
     {"name": "Mobile build", "description": "Native or cross-platform mobile target."}),
    (("real-time", "realtime", "chat", "notification", "websocket", "live"),
     {"name": "Real-time updates", "description": "WebSocket/push notifications."}),
    (("offline", "local", "desktop", "tauri", "electron"),
     {"name": "Offline-first storage", "description": "Local persistence with sync."}),
    (("search", "index", "elastic", "vector", "rag", "embedding"),
     {"name": "Search & retrieval", "description": "Full-text or vector search."}),
]

# Feature → API providers it typically needs, so the wizard can prompt for keys up front.
_FEATURE_API_HINTS: dict[str, list[str]] = {
    "ML pipeline": ["gemini", "groq", "openrouter"],
    "Search & retrieval": ["gemini", "openrouter"],
    "Payments": ["stripe"],
    "Real-time updates": [],
}


def suggest_features(description: str, deadline: str | None = None) -> dict:
    """Suggest concrete features and likely API-key needs from a free-text description."""
    text = (description or "").lower()
    seen: set[str] = set()
    suggestions: list[dict] = []
    for keywords, feature in _KEYWORD_FEATURES:
        if any(k in text for k in keywords) and feature["name"] not in seen:
            seen.add(feature["name"])
            suggestions.append({**feature, "enabled": True})
    # Always-useful baseline features so a thin description still yields a plan.
    for feat in (
        {"name": "Core MVP", "description": "Smallest end-to-end slice that delivers value."},
        {"name": "Testing & CI", "description": "Automated tests and a build pipeline."},
        {"name": "Documentation", "description": "User guide + developer/setup docs."},
    ):
        if feat["name"] not in seen:
            seen.add(feat["name"])
            suggestions.append({**feat, "enabled": True})

    api_keys = sorted({k for f in suggestions for k in _FEATURE_API_HINTS.get(f["name"], [])})
    return {"features": suggestions, "suggested_api_keys": api_keys}


# --------------------------------------------------------------------------- prompt generation
def _context_blurb(project: dict) -> str:
    """A compact one-paragraph project context used as a preamble in several prompts."""
    name = project.get("name") or "this project"
    desc = (project.get("description") or "").strip()
    deadline = project.get("deadline")
    details = project.get("details") or {}
    bits = [f'Project "{name}".']
    if desc:
        bits.append(desc if desc.endswith(".") else desc + ".")
    if deadline:
        bits.append(f"Target deadline: {deadline}.")
    for label, key in (("Domain", "domain"), ("Audience", "audience"),
                       ("Tech stack", "tech_stack"), ("Constraints", "constraints")):
        val = details.get(key)
        if val:
            bits.append(f"{label}: {val}.")
    return " ".join(bits)


def _enabled_feature_names(project: dict) -> list[str]:
    feats = project.get("features") or []
    out = []
    for f in feats:
        if isinstance(f, dict) and f.get("enabled", True) and f.get("name"):
            out.append(f["name"])
    return out


def generate_prompts(project: dict) -> dict[str, str]:
    """Build one ready-to-use prompt per app feature, each shaped how that feature consumes input."""
    ctx = _context_blurb(project)
    feats = _enabled_feature_names(project)
    feat_list = "; ".join(feats) if feats else "the core feature set"
    name = project.get("name") or "the project"
    deadline = project.get("deadline")
    by = f" by {deadline}" if deadline else ""

    return {
        "chat": (
            f"You are my project co-pilot for {name}. Context: {ctx} "
            f"Planned features: {feat_list}. "
            "Keep answers concrete and tied to this scope; ask before assuming."
        ),
        # /problem/define wants a rough description; give it the richest framing we have.
        "plan": (
            f"{ctx} The intended scope covers: {feat_list}. "
            f"Define and scope the core problem this project solves{by}, name the gap versus "
            "existing solutions, and list measurable success criteria."
        ),
        # /ideation/ideate takes an optional steer.
        "ideation": (
            f"Generate ideas that advance {name}. {ctx} "
            f"Bias toward ideas that strengthen these features: {feat_list}. "
            "Favour feasible, novel, directly-relevant concepts."
        ),
        # /research/prior-art wants a short query string.
        "research": _research_query(project, feats),
        # /orchestrate wants one concrete task.
        "orchestrator": (
            f"Build the first end-to-end slice of {name}: "
            f"{feats[0] if feats else 'the core MVP'}. "
            "Decompose into subtasks, route each to the best free model, and stay within budget."
        ),
        # /advisor/recommend consumes a problem + ideas + task types + tech.
        "advisor": (
            f"Recommend free tools, libraries, datasets and a prerequisite-first learning plan "
            f"for {name}. {ctx} Features to support: {feat_list}."
        ),
        # /docs/generate consumes a style + title.
        "docs": (
            f"Title: \"{name} — Technical Report\". "
            "Generate an IEEE-style report from the project's problem record, tasks, ideas and "
            "research, summarising progress and next steps."
        ),
    }


def _research_query(project: dict, feats: list[str]) -> str:
    details = project.get("details") or {}
    domain = details.get("domain")
    desc = (project.get("description") or "").strip()
    seed = domain or (feats[0] if feats else "") or desc[:60]
    return f"{seed} prior art and existing approaches".strip()


# --------------------------------------------------------------------------- scaffolding + export
def scaffold_project(workspace: str, name: str) -> str:
    """Create the project folder + standard subfolders; returns the absolute root path."""
    root = unique_project_dir(workspace, name)
    for sub in ("prompts", "exports", "generated-docs", "research", "assets"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return str(root.resolve())


def write_project_files(root: str, project: dict, prompts: dict[str, str]) -> list[str]:
    """Write the human-readable project metadata + one prompt file per feature."""
    base = Path(root)
    written: list[str] = []

    base.joinpath("project.json").write_text(
        json.dumps(_serializable(project), indent=2), encoding="utf-8"
    )
    written.append("project.json")

    base.joinpath("README.md").write_text(_readme(project), encoding="utf-8")
    written.append("README.md")

    pdir = base / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    label = {f["key"]: f["label"] for f in FEATURES}
    demands = {f["key"]: f["demands"] for f in FEATURES}
    index_lines = [f"# Generated prompts — {project.get('name', 'project')}", ""]
    for key in FEATURE_KEYS:
        prompt = prompts.get(key, "")
        body = (
            f"# {label.get(key, key)}\n\n"
            f"> **How this feature consumes input:** {demands.get(key, '')}\n\n"
            f"## Prompt\n\n{prompt}\n"
        )
        fname = f"{key}.md"
        pdir.joinpath(fname).write_text(body, encoding="utf-8")
        written.append(f"prompts/{fname}")
        index_lines.append(f"- **{label.get(key, key)}** → `prompts/{fname}`")
    pdir.joinpath("INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    written.append("prompts/INDEX.md")
    return written


def export_project_data(db: Database, project_id: int, root: str) -> dict:
    """Mirror everything the app has produced for a project into ``exports/`` as JSON.

    This is the autosave target: called on an interval so the on-disk folder always reflects
    the live DB and can be safely backed up to the cloud.
    """
    base = Path(root)
    edir = base / "exports"
    edir.mkdir(parents=True, exist_ok=True)

    project = db.get_project(project_id) or {}
    datasets: dict[str, Any] = {
        "project": _serializable(project),
        "problem": db.latest_problem_record(project_id),
        "tasks": db.list_tasks(project_id),
        "ideas": db.list_ideas(project_id),
        "research_results": db.list_research_results(project_id),
        "research_summary": db.latest_research_summary(project_id),
        "progress": db.latest_progress_assessment(project_id),
        "concepts": db.list_concepts(project_id),
        "resources": db.list_resource_suggestions(project_id),
        "learning": db.list_learning_items(project_id),
        "breakthroughs": db.list_breakthroughs(project_id),
        "chat": db.chat_history(project_id=project_id, limit=1000),
        "briefs": db.list_briefs(project_id),
    }
    written: list[str] = []
    for name, data in datasets.items():
        edir.joinpath(f"{name}.json").write_text(
            json.dumps(_serializable(data), indent=2, default=str), encoding="utf-8"
        )
        written.append(f"exports/{name}.json")

    # Refresh the prompt files too, in case project metadata changed.
    if project:
        prompts = project.get("prompts") or generate_prompts(project)
        write_project_files(root, project, prompts)

    stamp = {"synced_at": time.time(), "files": written}
    edir.joinpath("_sync.json").write_text(json.dumps(stamp, indent=2), encoding="utf-8")
    db.audit("agent", "project_sync", {"project_id": project_id, "files": len(written)})
    return {"ok": True, "root": root, "files": written, "synced_at": stamp["synced_at"]}


# --------------------------------------------------------------------------- helpers
def _serializable(obj: Any) -> Any:
    """Best-effort JSON-safe copy (DB rows are already plain dicts/lists)."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return json.loads(json.dumps(obj, default=str))


def _readme(project: dict) -> str:
    name = project.get("name", "Project")
    desc = project.get("description") or "_No description yet._"
    deadline = project.get("deadline") or "—"
    details = project.get("details") or {}
    feats = project.get("features") or []
    lines = [
        f"# {name}", "",
        desc, "",
        f"**Deadline:** {deadline}", "",
        "## Features", "",
    ]
    if feats:
        for f in feats:
            if isinstance(f, dict):
                mark = "x" if f.get("enabled", True) else " "
                lines.append(f"- [{mark}] **{f.get('name','')}** — {f.get('description','')}")
    else:
        lines.append("_None specified._")
    if details:
        lines += ["", "## Details", ""]
        for k, v in details.items():
            if v:
                lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
    lines += [
        "", "## Layout", "",
        "- `prompts/` — a tailored prompt for every app feature (see `prompts/INDEX.md`).",
        "- `exports/` — JSON mirror of problem, tasks, ideas, research, progress (autosaved).",
        "- `generated-docs/` — reports produced by the Docs feature.",
        "- `research/`, `assets/` — supporting material.",
        "", "_Managed by Phorrom. Files here are regenerated on autosave._", "",
    ]
    return "\n".join(lines)
