"""Cloud backup tests — encryption, packaging, and a full backup→restore cycle offline."""

from __future__ import annotations

import zipfile
import io

import pytest

from sidecar.sync import crypto, drive, oauth


# --------------------------------------------------------------------------- encryption
def test_encrypt_decrypt_roundtrip() -> None:
    data = b"sensitive project state \x00\x01\x02"
    blob = crypto.encrypt(data, "correct horse battery staple")
    assert blob[:4] == b"PHO1"                 # self-describing header
    assert blob != data
    assert crypto.decrypt(blob, "correct horse battery staple") == data


def test_wrong_passphrase_rejected() -> None:
    blob = crypto.encrypt(b"secret", "right")
    with pytest.raises(ValueError):
        crypto.decrypt(blob, "wrong")


def test_decrypt_rejects_foreign_blob() -> None:
    with pytest.raises(ValueError):
        crypto.decrypt(b"not-a-phorrom-backup", "x")


def test_empty_passphrase_rejected() -> None:
    with pytest.raises(ValueError):
        crypto.encrypt(b"x", "")


# --------------------------------------------------------------------------- packaging
def test_package_includes_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    db = tmp_path / "phorrom.sqlite"; db.write_bytes(b"SQLite format 3\x00data")
    pkg = drive._package(str(db))
    with zipfile.ZipFile(io.BytesIO(pkg)) as z:
        assert "phorrom.sqlite" in z.namelist()
        assert "manifest.json" in z.namelist()
        assert z.read("phorrom.sqlite").startswith(b"SQLite format 3")


# --------------------------------------------------------------------------- backup/restore cycle
class _FakeDrive:
    """In-memory stand-in for the Drive transport helpers."""
    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.meta: dict[str, dict] = {}
        self.n = 0


def _wire_fake(monkeypatch):
    fake = _FakeDrive()
    monkeypatch.setattr(drive, "_service", lambda creds: fake)
    monkeypatch.setattr(drive, "_folder_id", lambda svc: "folder-1")

    def up(svc, name, parent, blob):
        svc.n += 1
        fid = f"file-{svc.n}"
        svc.store[fid] = blob
        svc.meta[fid] = {"id": fid, "name": name, "size": len(blob)}
        return svc.meta[fid]

    monkeypatch.setattr(drive, "_upload", up)
    monkeypatch.setattr(drive, "_download", lambda svc, file_id: svc.store[file_id])
    monkeypatch.setattr(drive, "_list", lambda svc, fid: list(svc.meta.values()))
    return fake


def test_backup_then_restore_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    _wire_fake(monkeypatch)
    db = tmp_path / "phorrom.sqlite"; db.write_bytes(b"SQLite format 3\x00ORIGINAL")

    res = drive.backup(str(db), "pass123", creds="dummy")
    assert res["ok"] and res["snapshot"]["name"].endswith(".phobak")
    fid = res["snapshot"]["id"]

    snaps = drive.list_snapshots(creds="dummy")
    assert any(s["id"] == fid for s in snaps["snapshots"])

    # Corrupt the local DB, then restore from the encrypted snapshot.
    db.write_bytes(b"CORRUPTED")
    out = drive.restore(fid, "pass123", str(db), creds="dummy")
    assert out["ok"] and "database" in out["restored"]
    assert db.read_bytes().endswith(b"ORIGINAL")  # restored from cloud


def test_restore_with_wrong_passphrase_fails_cleanly(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    _wire_fake(monkeypatch)
    db = tmp_path / "phorrom.sqlite"; db.write_bytes(b"SQLite format 3\x00X")
    fid = drive.backup(str(db), "right-pass", creds="dummy")["snapshot"]["id"]
    out = drive.restore(fid, "WRONG", str(db), creds="dummy")
    assert out["ok"] is False and "passphrase" in out["error"]


def test_backup_requires_connection() -> None:
    assert drive.backup(":memory:", "p", creds=None)["ok"] is False


def test_status_shape(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PHORROM_ROOT", str(tmp_path))
    monkeypatch.setattr(oauth, "load_credentials", lambda: None)
    st = oauth.status()
    assert st["connected"] is False and "credentials_present" in st
