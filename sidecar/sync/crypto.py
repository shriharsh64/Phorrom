"""Client-side encryption for cloud backups.

Problem solved: backups must be unreadable to anyone (including Google) without the user's
passphrase. We derive a key from the passphrase with PBKDF2-HMAC-SHA256 (per-backup random
salt) and encrypt with Fernet (AES-128-CBC + HMAC). The on-disk/in-cloud blob is
``magic || salt || fernet_token`` so it's self-describing and the salt travels with it.

Pure and deterministic-enough to unit-test (round-trip, wrong-passphrase, format).
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_MAGIC = b"PHO1"
_SALT_LEN = 16
_ITERATIONS = 200_000


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt(data: bytes, passphrase: str) -> bytes:
    if not passphrase:
        raise ValueError("a passphrase is required")
    salt = os.urandom(_SALT_LEN)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(data)
    return _MAGIC + salt + token


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if blob[:4] != _MAGIC:
        raise ValueError("not a Phorrom backup (bad magic header)")
    salt = blob[4 : 4 + _SALT_LEN]
    token = blob[4 + _SALT_LEN :]
    try:
        return Fernet(_derive_key(passphrase, salt)).decrypt(token)
    except InvalidToken as exc:
        raise ValueError("wrong passphrase or corrupted backup") from exc
