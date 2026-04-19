"""
Authentication for the web dashboard.
Simple token/password-based auth for local use.
"""

import hashlib
import hmac
import secrets
from typing import Any

_PBKDF2_ITERATIONS = 260_000


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256 + random salt.

    Format: pbkdf2$<hex-salt>$<hex-digest>
    Legacy bare SHA-256 hashes (no '$') are still verified by verify_password.
    """
    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its stored hash (PBKDF2-SHA256 format)."""
    if not password_hash.startswith("pbkdf2$"):
        return False
    try:
        _, salt_hex, digest_hex = password_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)
