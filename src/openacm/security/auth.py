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
    """Verify a password against its stored hash.

    Supports both the new PBKDF2 format and legacy bare SHA-256 hashes
    so existing passwords keep working until they are next updated.
    """
    if password_hash.startswith("pbkdf2$"):
        try:
            _, salt_hex, digest_hex = password_hash.split("$")
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(actual, expected)
    # Legacy: bare SHA-256 hex — use constant-time compare
    legacy = hashlib.sha256(password.encode()).hexdigest().encode()
    return hmac.compare_digest(legacy, password_hash.encode())
