"""
Authentication for the web dashboard.
Simple token/password-based auth for local use.
"""

import hashlib
import secrets
from typing import Any


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == password_hash
