# Phorrom — PLAN.md

> Cross-platform, local-first, ₹0-recurring desktop AI project-management agent.
> This document is the living plan. It records architecture, assumptions, open questions,
> and the phased task list. Updated at every phase gate.

---

## 1. Environment reality (this machine — Windows 11, 2026-06-22)

| Tool | Status | Decision |
|---|---|---|
| Node v22.21.1 / npm 10.9.4 | present | Use for Vite + React + Tauri frontend |
| Python 3.14 (default) | present | NOT used for sidecar — too new for ML wheels |
| Python 3.11 (via `py -3.11`) | present | **Sidecar interpreter** (PyTorch/onnx/chroma wheels exist) |
| Git | present | VCS |
| Rust / cargo | **MISSING** | Required for Tauri shell — see Open Question #1 |
| Ollama | **MISSING** | Required for local-model chat — see Open Question #2 |
| Pandoc / TeX Live / Tesseract | MISSING | Phase 4/5 — install later, not blocking |

---

## 2. Interpretation of the brief

Phorrom is three layers:

1. **Shell** — Tauri 2.x (Rust): windowing, FS access, OS keychain secrets, sidecar process
   management, bundling.
2. **Frontend** — React 18 + TS + Vite + Tailwind + React Flow (DAG canvas) + Zustand.
3. **Sidecar** — Python 3.11 + FastAPI on localhost: provider layer, orchestrator,
   token-budgeter, ML, docs, research, sync, storage (SQLite + ChromaDB).

The intelligence is one control loop:
**decompose → estimate → reserve+allocate budget → schedule → route+execute → observe+learn → re-plan.**

The flagship is the **multi-model orchestrator + token-budget optimizer**, which is also the
part the user emphasized most in their framing (split one task into model-matched subtasks;
protect tokens for future near-certain heavy tasks; selective + versatile prioritization;
dynamic workflow).

---

## 3. Architecture decisions (summary; full ADRs in DECISIONS.md)

- **Sidecar transport:** HTTP over localhost (127.0.0.1, random free port, bearer token in
  memory) rather than stdio — easier to test independently and to develop frontend-first.
- **Sidecar packaging (later):** bundled venv launched by Tauri via `tauri-plugin-shell`.
  PyInstaller is a fallback if venv bundling proves fragile cross-platform.
- **Secrets:** `keyring` (Rust crate) for OS keychain. Sidecar receives keys from the shell
  at runtime; never reads the keychain directly, never persists keys.
- **Provider list is DATA not code:** capability profiles + model catalogs live in editable
  config + SQLite cache, refreshed by dynamic discovery. Adapters share one interface.
- **DB:** SQLite (`storage/`) for tasks/subtasks/runs/token-ledger/audit/quotas; ChromaDB for
  vector memory. Frontend gets state via Tauri events + REST polling.

---

## 4. Assumptions (made to avoid stalling; revisit if wrong)

1. Sidecar runs on **Python 3.11** (`py -3.11`), not the system default 3.14.
2. Local-first means the app must be **fully functional with only the mock provider** for
   development and tests, Ollama optional, cloud optional.
3. Single-user, single-machine; no multi-tenant auth. "Actor" in audit log = user or agent.
4. "Project root" is a user-chosen directory; all FS read/write is sandboxed to it.
5. Free-tier cloud limits change often → never hardcode model names; treat as config/cache.
6. For the hackathon timeline, **Phases 1–3 are the demo core** (chat + capabilities +
   orchestrator/budgeter). Phases 4–5 are stretch.

---

## 5. Open questions (need user input only where genuinely blocking)

1. **Rust/MSVC toolchain** — Tauri needs Rust + the MSVC C++ build tools (multi-GB install).
   Install the full native toolchain now, or go **sidecar-first** (build + test the Python
   brain and a browser-served React UI immediately) and add the Tauri shell once Rust is in?
   *(Asked.)*
2. **Ollama** — install now for a true local-model Phase-1 chat, or ship Phase 1 against the
   mock + Gemini adapters and add Ollama when convenient? *(Asked.)*
3. **Gemini API key** — needed to exercise the one cloud adapter in Phase 1. User must create
   it at aistudio.google.com (free). Not blocking: mock provider covers the round-trip.

---

## 6. Phased task list (DoD = definition of done)

### Phase 1 — Foundation
- [ ] Repo scaffold (Tauri + React + Python sidecar) building on this OS
- [ ] localhost IPC (shell ↔ sidecar) working
- [ ] SQLite schema (projects, tasks, subtasks, runs, token_ledger, audit_log, provider_quota)
- [ ] Secret storage via OS keychain
- [ ] Provider layer: interface + Ollama adapter + Gemini adapter + **mock** adapter
- [ ] Minimal chat that round-trips through a model and persists
- **DoD:** chat with a (mock/local) model from the UI, persisted to SQLite.

### Phase 2 — Core capabilities & data model
- [x] Problem-Statement Architect flow; task model; dependency-aware prioritization
- [x] File manager: read + audited write with approval + diff preview (path-escape blocked)
- [x] Project picker + Plan UI
- [ ] Roadmap view in React Flow — deferred (structured views shipped; graph canvas is polish)
- **DoD met:** create a project, add tasks, read/write files safely (tested).

### Phase 3 — Orchestrator (flagship)  ✅ DONE
- [x] LLM decomposition → validated subtask DAG (schema + cycle/unknown-dep checks, fallback)
- [x] Heuristic router (capability-profile scoring) behind a Router interface
- [x] networkx scheduler (ready-set + critical-path)
- [x] PuLP token-budgeter with **future-demand reservation** + token ledger; greedy fallback
- [x] Orchestrator UI (DAG + budget + routing)
- [ ] Remaining cloud adapters (Groq/OpenRouter/...) + dynamic discovery + failover — TODO
- **DoD met:** task decomposes, subtasks route to different models, ledger+reservation
  provably prevent over-spend (proven by tests).

### Capability #2 — Ideation & Concept Engine  ✅ DONE (built after Phase 3, per request)
- [x] Generate/score/rank ideas (feasibility×novelty×relevance), persist, status, UI
- [x] Closed loop with Advisor (#3): ideation writes required-but-unmastered concepts as
      gaps → Advisor targets them → mastery feeds back via /ideation/mastered (loop test green)

### Phase 4 — ML & advanced  (partially blocked)
- [ ] Token/quality estimators (heuristic → LightGBM/PyTorch); priority net → ONNX — codeable
- [ ] Contextual-bandit router (Thompson sampling) — codeable (interface already in place)
- [ ] Patent/prior-art research (Semantic Scholar + arXiv) — codeable (needs network at runtime)
- [ ] IEEE/ACM/APA doc generation — **BLOCKED**: needs Pandoc + LaTeX (not installed)
- [ ] Multimodal input — **BLOCKED**: needs Tesseract OCR + whisper.cpp (not installed)
- **DoD:** predictions feed scheduling; a compliant paper generates from real project data.

### Phase 5 — Sync, polish, packaging  (blocked)
- [ ] Google Drive backup/restore — **BLOCKED**: needs OAuth client credentials (user-created)
- [ ] Dashboards (token ledger, provider health), onboarding, settings — codeable
- [ ] Cross-platform bundling + installers — **BLOCKED**: needs Rust/Tauri toolchain
- **DoD:** clean machine can install, run, back up to Drive, restore.

---

## 7. Working agreement
- Commit after every working increment.
- Pause and summarize at each phase gate before continuing.
- Prefer free/OSS/local. Flag any paid dependency.
- Strong typing + tests for every non-trivial module; mock provider keeps tests offline.
