"""
Generic, provider-agnostic verifiers for webhook connectors (see
docs/superpowers/specs/2026-09-09-webhook-connectors-and-agent-flow-node-design.md).

Each function takes a connector's `auth_config` dict (shape depends on the
scheme — see the spec) plus the incoming request's headers (and raw body,
for HMAC) and returns a plain bool. No exceptions for "invalid" — only for
genuinely malformed input the caller couldn't have avoided (there is none
here; every failure mode returns False).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any


def verify_hmac_sha256(
    auth_config: dict[str, Any],
    headers: Any,
    raw_body: bytes,
    *,
    now: float | None = None,
) -> bool:
    """firma = HMAC-SHA256(secret, "<timestamp>.<raw body bytes>"),
    header value "sha256=<hex>". Rejects a timestamp more than
    max_skew_seconds away from now (either direction)."""
    timestamp = headers.get(auth_config["timestamp_header"])
    signature = headers.get(auth_config["signature_header"])
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > auth_config.get("max_skew_seconds", 300):
        return False
    message = f"{timestamp}.".encode("utf-8") + raw_body
    digest = hmac.new(auth_config["secret"].encode("utf-8"), message, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature)


def verify_bearer_token(auth_config: dict[str, Any], headers: Any) -> bool:
    header_name = auth_config.get("header_name", "Authorization")
    value = headers.get(header_name, "")
    if not value.startswith("Bearer "):
        return False
    return hmac.compare_digest(value[len("Bearer "):], auth_config["token"])


def verify_static_header_secret(auth_config: dict[str, Any], headers: Any) -> bool:
    value = headers.get(auth_config["header_name"], "")
    if not value:
        return False
    return hmac.compare_digest(value, auth_config["secret"])


_VERIFIERS = {
    "hmac_sha256": lambda cfg, headers, raw_body: verify_hmac_sha256(cfg, headers, raw_body),
    "bearer_token": lambda cfg, headers, raw_body: verify_bearer_token(cfg, headers),
    "static_header_secret": lambda cfg, headers, raw_body: verify_static_header_secret(cfg, headers),
}


def verify_request(auth_scheme: str, auth_config: dict[str, Any], headers: Any, raw_body: bytes) -> bool:
    verifier = _VERIFIERS.get(auth_scheme)
    if verifier is None:
        return False
    return verifier(auth_config, headers, raw_body)
