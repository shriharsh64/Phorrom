"""Google OAuth (installed-app loopback flow).

Problem solved: connect one Google account for Drive backup. Uses the desktop `credentials.json`
with `run_local_server` (opens the browser, redirects to a loopback port). The resulting token
(incl. refresh token) is persisted as JSON under the data dir and auto-refreshed.

Note: ``authorize()`` blocks while the user consents in the browser, so its endpoint runs in a
threadpool. The token file should ideally live in the OS keychain — tracked as a hardening TODO.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import tools

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",   # only files the app creates
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def credentials_path() -> str | None:
    env = os.environ.get("PHORROM_GOOGLE_CREDENTIALS")
    if env and Path(env).exists():
        return env
    p = tools.project_root() / "credentials.json"
    return str(p) if p.exists() else None


def token_path() -> Path:
    base = Path(os.environ.get("PHORROM_DATA_DIR") or tools.project_root())
    base.mkdir(parents=True, exist_ok=True)
    return base / "google_token.json"


def load_credentials():
    """Return valid Credentials (refreshing if needed) or None."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tp = token_path()
    if not tp.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    except (ValueError, KeyError):
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tp.write_text(creds.to_json(), encoding="utf-8")
        except Exception:  # noqa: BLE001 - refresh can fail if revoked
            return None
    return creds if creds and creds.valid else None


def _email(creds) -> str | None:
    try:
        from googleapiclient.discovery import build
        svc = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        return svc.userinfo().get().execute().get("email")
    except Exception:  # noqa: BLE001
        return None


def authorize() -> dict:
    """Interactive: open the browser, consent, persist token. Blocks until consent completes."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    cp = credentials_path()
    if cp is None:
        return {"ok": False, "error": "credentials.json not found (place it at the project root)"}
    try:
        flow = InstalledAppFlow.from_client_secrets_file(cp, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"authorization failed: {exc}"}
    token_path().write_text(creds.to_json(), encoding="utf-8")
    return {"ok": True, "email": _email(creds)}


def status() -> dict:
    creds = load_credentials()
    return {
        "connected": bool(creds),
        "email": _email(creds) if creds else None,
        "credentials_present": credentials_path() is not None,
    }


def signout() -> dict:
    tp = token_path()
    if tp.exists():
        tp.unlink()
    return {"ok": True, "connected": False}
