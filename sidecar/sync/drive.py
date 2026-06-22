"""Encrypted backup & restore to Google Drive.

Problem solved: snapshot the project's state (SQLite DB + generated docs) into one encrypted
blob and store it in a dedicated `Phorrom Backups` Drive folder, with restore. Contents are
encrypted client-side (see ``crypto``) before upload — Drive only ever sees ciphertext.

The Drive transport is isolated in small helpers (``_service``/``_folder_id``/``_upload``/
``_download``/``_list``) so backup/restore logic — packaging + encryption — is unit-testable
offline by stubbing those helpers.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

from .. import tools
from . import crypto, oauth

FOLDER_NAME = "Phorrom Backups"
EXT = ".phobak"


# --------------------------------------------------------------------------- packaging
def _package(db_path: str) -> bytes:
    """Zip the DB + generated docs + a manifest into one archive (plaintext, pre-encryption)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if db_path and db_path != ":memory:" and Path(db_path).exists():
            z.write(db_path, "phorrom.sqlite")
        gd = tools.project_root() / "generated-docs"
        if gd.is_dir():
            for f in gd.glob("*"):
                if f.is_file():
                    z.write(f, f"generated-docs/{f.name}")
        z.writestr("manifest.json", json.dumps({"created": time.time(), "version": 1}))
    return buf.getvalue()


def _restore_package(raw: bytes, db_path: str) -> list[str]:
    """Extract a package: overwrite the SQLite DB (takes effect on next restart)."""
    restored: list[str] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if "phorrom.sqlite" in names and db_path and db_path != ":memory:":
            Path(db_path).write_bytes(z.read("phorrom.sqlite"))
            restored.append("database")
        gd = tools.project_root() / "generated-docs"
        for n in names:
            if n.startswith("generated-docs/") and not n.endswith("/"):
                gd.mkdir(parents=True, exist_ok=True)
                (gd / Path(n).name).write_bytes(z.read(n))
                restored.append(n)
    return restored


# --------------------------------------------------------------------------- Drive transport
def _service(creds):
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _folder_id(svc) -> str:
    q = (f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
         "and trashed=false")
    files = svc.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
    return svc.files().create(body=meta, fields="id").execute()["id"]


def _upload(svc, name: str, parent: str, blob: bytes) -> dict:
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(io.BytesIO(blob), mimetype="application/octet-stream", resumable=True)
    return svc.files().create(body={"name": name, "parents": [parent]}, media_body=media,
                              fields="id,name,size,createdTime").execute()


def _download(svc, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def _list(svc, folder_id: str) -> list[dict]:
    res = svc.files().list(q=f"'{folder_id}' in parents and trashed=false",
                           fields="files(id,name,size,createdTime)",
                           orderBy="createdTime desc").execute()
    return res.get("files", [])


# --------------------------------------------------------------------------- public ops
def backup(db_path: str, passphrase: str, creds=None) -> dict:
    creds = creds or oauth.load_credentials()
    if not creds:
        return {"ok": False, "error": "not connected to Google"}
    if not passphrase:
        return {"ok": False, "error": "a passphrase is required to encrypt the backup"}
    blob = crypto.encrypt(_package(db_path), passphrase)
    svc = _service(creds)
    name = f"phorrom-{time.strftime('%Y%m%d-%H%M%S')}{EXT}"
    snap = _upload(svc, name, _folder_id(svc), blob)
    return {"ok": True, "snapshot": snap, "bytes": len(blob)}


def list_snapshots(creds=None) -> dict:
    creds = creds or oauth.load_credentials()
    if not creds:
        return {"ok": False, "error": "not connected to Google", "snapshots": []}
    svc = _service(creds)
    return {"ok": True, "snapshots": _list(svc, _folder_id(svc))}


def restore(file_id: str, passphrase: str, db_path: str, creds=None) -> dict:
    creds = creds or oauth.load_credentials()
    if not creds:
        return {"ok": False, "error": "not connected to Google"}
    blob = _download(_service(creds), file_id)
    try:
        raw = crypto.decrypt(blob, passphrase)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    restored = _restore_package(raw, db_path)
    return {"ok": True, "restored": restored,
            "note": "Restart the app for the restored database to take effect."}
