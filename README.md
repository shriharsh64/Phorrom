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

## Running

### Desktop app (Tauri) — recommended
Requires the Rust toolchain (see Prerequisites). Tauri starts Vite **and** auto-launches the
Python sidecar (Rust spawns the venv interpreter on 127.0.0.1:8008 and stops it on exit):

```bash
npm install
npm run tauri dev      # builds the Rust shell, opens the desktop window
```

### Building the installer (double-click installable)
Produces `src-tauri/target/release/bundle/nsis/Phorrom_<ver>_x64-setup.exe`, which bundles the
app + a standalone sidecar (no Python needed on the target machine).

```bash
# 1. Build the standalone sidecar (PyInstaller) and stage it for Tauri:
sidecar/.venv/Scripts/pyinstaller --noconfirm --onefile --name phorrom-sidecar \
  --distpath build/sidecar-dist --workpath build/sidecar-work --specpath build \
  --collect-all uvicorn --collect-all fastapi --collect-all starlette --collect-all pydantic \
  --collect-all sklearn --collect-all scipy --collect-all numpy --collect-all joblib --collect-all pulp \
  --collect-submodules sidecar --hidden-import anyio --hidden-import httpx --hidden-import h11 \
  sidecar_main.py
#    then copy build/sidecar-dist/phorrom-sidecar.exe to
#    src-tauri/binaries/phorrom-sidecar-<rustc-host-triple>.exe   (e.g. -x86_64-pc-windows-msvc.exe)

# 2. Build the app + installer:
npm run tauri build
```
At runtime the installed app launches the bundled sidecar next to its executable and keeps its
SQLite DB under the OS app-data dir.

### Browser + sidecar (no Rust needed)
```bash
# terminal 1 — sidecar
sidecar/.venv/Scripts/python -m uvicorn sidecar.app:app --port 8008 --app-dir .
# terminal 2 — frontend
npm run dev            # open the printed http://localhost:1420
```

## License
TBD.
