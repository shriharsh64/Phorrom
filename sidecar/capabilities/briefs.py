"""Feature briefs: a preliminary, continuously-updated response for every app feature.

Problem solved: the moment a project's description is stated, the user should see a useful
preliminary response in *every* feature (chat..docs) — and as the chat conversation evolves,
those responses should stay current. Re-storing a full regeneration on each message would be
wasteful, so instead each feature keeps a compact **knowledge base**: key points ranked by
importance, near-duplicates merged, capped to the top few. That is the "stored optimally by
importance / compressed" requirement — semantic compression, not byte-level.

Everything here is deterministic and offline (local-first): preliminary briefs are built from
the project metadata, and chat updates are extracted straight from the conversation text — no
extra model call per message, which keeps the loop cheap.
"""

from __future__ import annotations

import re
from typing import Any

from ..projects.setup import FEATURE_KEYS, _context_blurb, _enabled_feature_names

# How many key points each feature retains — the cap that bounds storage growth.
MAX_POINTS = 8

# Words that signal a point matters (raise importance). Tuned for project work.
_IMPORTANT_WORDS = {
    "must", "should", "need", "require", "critical", "key", "core", "important", "goal",
    "deadline", "risk", "blocker", "security", "privacy", "performance", "scal", "cost",
    "budget", "user", "customer", "metric", "success", "constraint", "deliver", "launch",
    "data", "model", "accuracy", "latency", "compliance", "integration", "api",
}

# Route an extracted key point to the features it informs (a point may inform several).
_FEATURE_ROUTING: dict[str, tuple[str, ...]] = {
    "plan": ("problem", "scope", "requirement", "goal", "success", "constraint", "milestone",
             "deadline", "task", "deliver", "risk", "plan"),
    "ideation": ("idea", "concept", "feature", "alternative", "approach", "novel", "could",
                 "maybe", "explore", "option"),
    "research": ("research", "prior", "paper", "patent", "existing", "competitor", "literature",
                 "state of the art", "benchmark", "study"),
    "orchestrator": ("build", "implement", "model", "budget", "token", "pipeline", "step",
                     "decompose", "subtask", "compute", "run"),
    "advisor": ("tool", "library", "dataset", "learn", "skill", "resource", "framework",
                "stack", "infrastructure", "service"),
    "docs": ("document", "report", "spec", "write", "summary", "documentation", "guide"),
}


# --------------------------------------------------------------------------- importance + extract
def score_importance(text: str) -> float:
    """Heuristic 0..1 importance: keyword hits + concreteness + a sane-length bonus."""
    t = text.lower()
    score = 0.35
    score += 0.08 * sum(1 for w in _IMPORTANT_WORDS if w in t)
    if re.search(r"\d", t):              # concrete numbers/dates carry weight
        score += 0.12
    words = len(t.split())
    if 5 <= words <= 28:                 # neither trivial nor a wall of text
        score += 0.1
    elif words < 4:
        score -= 0.15
    return max(0.0, min(1.0, round(score, 3)))


def _split_points(text: str) -> list[str]:
    """Break free text into candidate key-point clauses."""
    if not text:
        return []
    # Strip provider echo prefixes like "[mock:mock-small] ".
    text = re.sub(r"^\[[^\]]+\]\s*", "", text.strip())
    # Split on sentence boundaries, bullets and newlines.
    raw = re.split(r"(?:[.!?]\s+)|(?:\n[-*•]\s*)|\n{2,}", text)
    out: list[str] = []
    for piece in raw:
        clause = piece.strip(" -*•\t\r\n")
        if len(clause.split()) >= 3 and len(clause) <= 200:
            out.append(clause if clause.endswith((".", "!", "?")) else clause)
    return out


def extract_points(text: str, source: str = "chat") -> list[dict]:
    """Turn text into scored key points (deduped within this call)."""
    seen: set[str] = set()
    points: list[dict] = []
    for clause in _split_points(text):
        norm = _normalize(clause)
        if norm in seen:
            continue
        seen.add(norm)
        points.append({"text": clause, "importance": score_importance(clause), "source": source})
    return points


def route_features(text: str) -> list[str]:
    """Which features a key point informs (always includes chat)."""
    t = text.lower()
    feats = {"chat"}
    for feature, keys in _FEATURE_ROUTING.items():
        if any(k in t for k in keys):
            feats.add(feature)
    return list(feats)


# --------------------------------------------------------------------------- compression / merge
def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def _similar(a: str, b: str) -> bool:
    """Near-duplicate test via token Jaccard overlap."""
    sa, sb = set(_normalize(a).split()), set(_normalize(b).split())
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= 0.6


def merge_points(existing: list[dict], incoming: list[dict], cap: int = MAX_POINTS) -> list[dict]:
    """Merge new points into existing, deduping near-duplicates (keep the more important),
    then sort by importance and cap — bounding storage and keeping only what matters."""
    merged = [dict(p) for p in existing]
    for new in incoming:
        hit = next((p for p in merged if _similar(p["text"], new["text"])), None)
        if hit is None:
            merged.append(dict(new))
        elif new["importance"] > hit["importance"]:
            hit.update(new)  # keep the higher-importance phrasing
    merged.sort(key=lambda p: p.get("importance", 0), reverse=True)
    return merged[:cap]


# --------------------------------------------------------------------------- preliminary briefs
def _feature_summary(feature: str, project: dict) -> str:
    """A concise preliminary response tailored to how each feature frames the project."""
    name = project.get("name") or "the project"
    ctx = _context_blurb(project)
    feats = _enabled_feature_names(project)
    feat_list = ", ".join(feats) if feats else "the core feature set"
    deadline = project.get("deadline")
    by = f" by {deadline}" if deadline else ""
    templates = {
        "chat": f"Co-pilot ready for {name}. {ctx} I'll keep every feature in sync as we talk.",
        "plan": f"Preliminary plan for {name}: deliver {feat_list}{by}. Start by defining the core "
                f"problem and measurable success criteria, then break it into prioritized tasks.",
        "ideation": f"Initial idea directions for {name} centre on {feat_list}. Generate concepts "
                    f"that raise feasibility and novelty while staying on-scope.",
        "research": f"Prior-art angle for {name}: survey existing approaches to {feats[0] if feats else name} "
                    f"and map the white space worth claiming.",
        "orchestrator": f"First build slice for {name}: {feats[0] if feats else 'the core MVP'}. "
                        f"Decompose into model-matched subtasks under a token budget.",
        "advisor": f"Resourcing for {name}: shortlist free tools/libraries for {feat_list} and a "
                   f"prerequisite-first learning plan for any skill gaps.",
        "docs": f"Documentation outline for {name}: a technical report drawing on the problem record, "
                f"tasks, ideas and research as they fill in.",
    }
    return templates.get(feature, ctx)


def _seed_points(project: dict) -> list[dict]:
    """Seed key points from the description + chosen features (the preliminary knowledge base)."""
    pts = extract_points(project.get("description") or "", source="preliminary")
    if project.get("deadline"):
        pts.append({"text": f"Target deadline: {project['deadline']}.",
                    "importance": 0.85, "source": "preliminary"})
    for f in (project.get("features") or []):
        if isinstance(f, dict) and f.get("enabled", True) and f.get("name"):
            label = f["name"] + (f" — {f['description']}" if f.get("description") else "")
            pts.append({"text": f"Feature: {label}", "importance": 0.6, "source": "preliminary"})
    for key in ("domain", "audience", "tech_stack", "constraints"):
        val = (project.get("details") or {}).get(key)
        if val:
            pts.append({"text": f"{key.replace('_', ' ').title()}: {val}",
                        "importance": 0.55, "source": "preliminary"})
    return pts


def generate_preliminary(project: dict) -> dict[str, dict]:
    """Build a preliminary brief for every feature from the project metadata."""
    seed = _seed_points(project)
    briefs: dict[str, dict] = {}
    for feature in FEATURE_KEYS:
        if feature == "chat":
            pts = seed
        else:
            pts = [p for p in seed if feature in route_features(p["text"])] or seed
        briefs[feature] = {
            "summary": _feature_summary(feature, project),
            "points": merge_points([], pts),
        }
    return briefs


# --------------------------------------------------------------------------- chat-driven update
def update_from_exchange(
    briefs: dict[str, dict], user_text: str, assistant_text: str
) -> dict[str, dict]:
    """Fold the latest chat exchange into every feature's brief, importance-compressed.

    Returns only the features that actually changed (so the caller persists the minimum).
    """
    points = extract_points(f"{user_text}\n{assistant_text}", source="chat")
    if not points:
        return {}
    changed: dict[str, dict] = {}
    for feature in FEATURE_KEYS:
        relevant = [p for p in points if feature == "chat" or feature in route_features(p["text"])]
        if not relevant:
            continue
        current = briefs.get(feature) or {"summary": "", "points": []}
        merged = merge_points(current.get("points", []), relevant)
        if merged != current.get("points"):
            changed[feature] = {"summary": current.get("summary", ""), "points": merged}
    return changed


def serialize(briefs: dict[str, dict]) -> dict[str, Any]:
    """Stable shape for the API/exports."""
    return {f: {"summary": b.get("summary", ""), "points": b.get("points", [])}
            for f, b in briefs.items()}
