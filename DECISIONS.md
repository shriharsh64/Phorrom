# Phorrom — Architecture Decision Records

Format: each ADR is short — Context / Decision / Consequences. Newest at top.

---

## ADR-0004 — Sidecar interpreter pinned to Python 3.11
**Context:** Machine default is Python 3.14; PyTorch / onnxruntime / chromadb wheels do not
yet exist for 3.14. Python 3.11 is also installed (`py -3.11`).
**Decision:** Create and bundle the sidecar venv with `py -3.11`. CI/docs must use 3.11.
**Consequences:** Reproducible ML stack today. Revisit when 3.12/3.13 wheels are universal.

## ADR-0003 — Shell ↔ sidecar transport = HTTP over loopback
**Context:** Tauri can talk to a Python sidecar via stdio or HTTP. We want to develop and
test the sidecar independently of the Rust shell.
**Decision:** FastAPI on 127.0.0.1, ephemeral free port chosen at launch, short-lived bearer
token passed shell→sidecar in memory. CORS locked to the Tauri origin.
**Consequences:** Sidecar is testable with curl/pytest alone; frontend can be developed in a
plain browser before Tauri exists. Slightly more setup than stdio.

## ADR-0002 — Provider catalog is data, not code
**Context:** Free-tier model availability and limits change without notice.
**Decision:** Adapters implement one interface; model lists come from live discovery cached in
SQLite; capability profiles + quotas live in editable config. No hardcoded model names in
routing logic.
**Consequences:** New models/providers added without a rebuild; routing degrades gracefully.

## ADR-0001 — Mock provider is a first-class citizen
**Context:** Tests and offline dev must not depend on Ollama or any cloud key.
**Decision:** Ship a deterministic `MockProvider` implementing the full provider interface
(configurable latency, token counts, canned/echo responses). All orchestrator/budgeter tests
run against it.
**Consequences:** Fully offline, deterministic CI; the app boots and demos with zero keys.
