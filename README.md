# Phorrom

An end-to-end, local-first AI **project-management agent** desktop app. Phorrom understands a
project (reads its files), evolves with it (continuously re-plans), and acts on it (writes
docs, logs, next-task definitions). Its flagship is a **multi-model orchestrator** that
decomposes a task into subtasks, routes each to the most suitable *free* generative model, and
allocates a token budget so future token-heavy tasks never get starved.

> Status: **early scaffold** — see `PLAN.md` for the phased build and `DECISIONS.md` for ADRs.

## Principles
- **₹0 recurring** — open-source / free-tier / local only.
- **Local-first / offline-first** — core works with no internet (Ollama + mock provider);
  cloud free tiers are an optional accelerator.
- **Private & secure** — keys in the OS keychain; no telemetry; files never leave the machine
  unless you opt in per project.

## Tech stack
Tauri 2.x (Rust shell) · React 18 + TypeScript + Vite + Tailwind + React Flow (frontend) ·
Python 3.11 + FastAPI (AI sidecar) · SQLite + ChromaDB · PuLP/OR-Tools · networkx · PyTorch.

## Prerequisites
- **Node 18+** and npm
- **Python 3.11** (the sidecar is pinned to 3.11; on Windows use `py -3.11`)
- **Rust** (stable) + platform C toolchain — required to build the Tauri shell
  (Windows: MSVC Build Tools + WebView2; macOS: Xcode CLT; Linux: webkit2gtk + build-essential)
- **Ollama** (optional, recommended) for local models

## Setup
> Detailed per-OS setup is filled in as each phase lands. See `PLAN.md`.

```bash
# frontend deps
npm install

# sidecar (Windows)
py -3.11 -m venv sidecar/.venv
sidecar/.venv/Scripts/python -m pip install -r sidecar/requirements.txt
```

### Provider API keys (all optional — the app runs on the mock/Ollama with none)
Set as environment variables before launching the sidecar; missing keys simply disable that
provider. They will move to the OS keychain once the Tauri shell lands.

| Env var | Provider | Free key from |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio | aistudio.google.com |
| `GROQ_API_KEY` | Groq | console.groq.com |
| `OPENROUTER_API_KEY` | OpenRouter (`:free` models) | openrouter.ai |

## License
TBD.
