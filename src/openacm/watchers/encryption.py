"""
Local activity data encryption for OpenACM.

Generates a machine-local AES key (via Fernet = AES-128-CBC + HMAC-SHA256)
stored in config/activity.key.  This file never leaves the user's machine
and is excluded from version control.

All app_activities and detected_routines sensitive fields are encrypted
before being written to SQLite and decrypted after reading — the database
itself only ever contains ciphertext.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import structlog

log = structlog.get_logger()


def _key_path() -> Path:
    """Resolve the key file path relative to the project root."""
    # Walk up from this file to find config/
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "activity.key"
        if candidate.parent.exists():
            return candidate
    # Fallback: next to the running script
    return Path("config") / "activity.key"


class ActivityEncryptor:
    """
    Transparent encrypt/decrypt wrapper for activity strings.

    The Fernet key is auto-generated on first use and stored locally in
    config/activity.key.  Each call to encrypt() produces a different
    ciphertext (random IV), so two encryptions of the same plaintext
    are never identical — meaning SQL GROUP BY on encrypted columns
    will not work and must be done in Python after decryption.
    """

    def __init__(self, key_path: Path | None = None):
        self._key_path = key_path or _key_path()
        self._fernet = Fernet(self._load_or_create_key())

    # ─── Key management ───────────────────────────────────────

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            raw = self._key_path.read_bytes().strip()
            log.info("ActivityEncryptor: loaded local key", path=str(self._key_path))
            return raw

        key = Fernet.generate_key()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_bytes(key)
        # Restrict permissions on Unix (no-op on Windows)
        try:
            os.chmod(self._key_path, 0o600)
        except OSError:
            pass
        log.info("ActivityEncryptor: generated new local key", path=str(self._key_path))
        return key

    @property
    def key_path(self) -> str:
        return str(self._key_path)

    # ─── Encrypt / decrypt ────────────────────────────────────

    def encrypt(self, text: str) -> str:
        """Encrypt plaintext → URL-safe base64 ciphertext string."""
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        """
        Decrypt ciphertext → plaintext.  Returns value unchanged if it
        is not valid ciphertext (handles unencrypted legacy rows).
        """
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, Exception):
            return value  # legacy unencrypted row — return as-is
