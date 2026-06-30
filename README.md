# Phorrom

An end-to-end, local-first AI **project-management agent** desktop app. Phorrom understands a
project (reads its files), evolves with it (continuously re-plans), and acts on it (writes
docs, logs, next-task definitions). Its flagship is a **multi-model orchestrator** that
decomposes a task into subtasks, routes each to the most suitable *free* generative model, and allocates a token budget so future token-heavy tasks never get starved.

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
In the **desktop app**, add keys in the **Settings** tab — they're stored in the OS keychain
(Windows Credential Manager / macOS Keychain / libsecret), injected into the sidecar on launch,
and applied live via `/providers/keys`. For the browser/sidecar dev flow you can instead set
environment variables before launching the sidecar; missing keys simply disable that provider.

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

## Projects, workspace & autosave
On first launch a **startup window** asks you to pick a **workspace folder** (with a name) where
every project is saved. From there you can **create a new project** or **open an existing one**.

The **new-project wizard** collects a description, deadline, suggested features (auto-suggested
from your description — toggle/edit/add), any API keys those features need, and extra details
(domain, audience, tech stack, constraints). On finish it:
- creates a dedicated folder under your workspace (`prompts/`, `exports/`, `generated-docs/`, …),
- generates a **tailored prompt for every app feature** (Chat, Plan, Ideation, Research,
  Orchestrator, Advisor, Docs) — each written the specific way that feature consumes input,
  viewable/copyable in the **Prompts** tab and saved under `prompts/`,
- writes `project.json` + `README.md` and a JSON mirror of all project data under `exports/`.

**Autosave** mirrors the live DB into the project folder on an interval (configurable in
Settings); enable **cloud autobackup** to also push an encrypted snapshot to Drive each interval
(uses the passphrase from your last manual backup, kept in memory for the session only).

The **Help & guide** tab documents every feature — what it does, how to use it, and best
practices.

## Document generation & multimodal (native tools)
The **Docs** tab generates IEEE/ACM/APA reports from real project data and runs OCR / speech-to-text.
These shell out to native tools, auto-discovered (env var → PATH → known location):

| Feature | Tool | Discovery / override |
|---|---|---|
| md / docx / pdf | Pandoc (+ TinyTeX for PDF) | `PHORROM_PANDOC`, `PHORROM_LATEX_BIN` |
| OCR | Tesseract | `PHORROM_TESSERACT` |
| speech-to-text | whisper.cpp + a `ggml-*.bin` model | `PHORROM_WHISPER`, `PHORROM_WHISPER_MODEL` |

TinyTeX is expected at the repo root (`TinyTeX/bin/windows`), and the whisper CLI + model under
`sidecar/Release/`. These are **not** bundled into the installer yet — install them (or set the
env overrides) when running. `PHORROM_ROOT` overrides the base dir used for repo-relative lookups.

## Cloud backup (Google Drive)
The **Settings** tab connects one Google account (installed-app loopback OAuth using
`credentials.json` at the project root) and backs up the SQLite DB + generated docs as an
**encrypted** snapshot to a `Phorrom Backups` Drive folder. Encryption is client-side
(PBKDF2-HMAC-SHA256 → Fernet) with your passphrase — Drive only ever stores ciphertext; restore
needs the same passphrase. Overrides: `PHORROM_GOOGLE_CREDENTIALS`, `PHORROM_DATA_DIR` (token
location). `credentials.json` and `google_token.json` are gitignored — never commit them.

## License
TBD.
