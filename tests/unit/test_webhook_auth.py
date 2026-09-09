"""Tests for the three generic webhook auth verifiers."""
import hashlib
import hmac as hmac_stdlib
import time

from openacm.core.webhook_auth import (
    verify_bearer_token,
    verify_hmac_sha256,
    verify_request,
    verify_static_header_secret,
)


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac_stdlib.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


HMAC_CONFIG = {
    "secret": "test-secret-32-characters-long!!",
    "timestamp_header": "X-Timestamp",
    "signature_header": "X-Signature",
    "max_skew_seconds": 300,
}


class TestVerifyHmacSha256:
    def test_valid_signature_passes(self):
        now = 1788361200.0
        body = b'{"a":1}'
        ts = "1788361200"
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, body)}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, body, now=now) is True

    def test_tampered_body_fails(self):
        now = 1788361200.0
        ts = "1788361200"
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, b'{"a":1}')}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, b'{"a":2}', now=now) is False

    def test_wrong_secret_fails(self):
        now = 1788361200.0
        ts = "1788361200"
        body = b'{"a":1}'
        headers = {"X-Timestamp": ts, "X-Signature": _sign("wrong-secret", ts, body)}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, body, now=now) is False

    def test_expired_timestamp_fails(self):
        ts = "1788361200"
        body = b'{"a":1}'
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, body)}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, body, now=1788361200.0 + 301) is False

    def test_missing_signature_header_fails(self):
        headers = {"X-Timestamp": "1788361200"}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, b"{}", now=1788361200.0) is False

    def test_missing_timestamp_header_fails(self):
        headers = {"X-Signature": "sha256=" + "0" * 64}
        assert verify_hmac_sha256(HMAC_CONFIG, headers, b"{}", now=1788361200.0) is False


BEARER_CONFIG = {"token": "s3cr3t-token", "header_name": "Authorization"}


class TestVerifyBearerToken:
    def test_valid_token_passes(self):
        assert verify_bearer_token(BEARER_CONFIG, {"Authorization": "Bearer s3cr3t-token"}) is True

    def test_wrong_token_fails(self):
        assert verify_bearer_token(BEARER_CONFIG, {"Authorization": "Bearer nope"}) is False

    def test_missing_header_fails(self):
        assert verify_bearer_token(BEARER_CONFIG, {}) is False

    def test_missing_bearer_prefix_fails(self):
        assert verify_bearer_token(BEARER_CONFIG, {"Authorization": "s3cr3t-token"}) is False


STATIC_CONFIG = {"header_name": "X-Api-Secret", "secret": "s3cr3t"}


class TestVerifyStaticHeaderSecret:
    def test_matching_secret_passes(self):
        assert verify_static_header_secret(STATIC_CONFIG, {"X-Api-Secret": "s3cr3t"}) is True

    def test_wrong_secret_fails(self):
        assert verify_static_header_secret(STATIC_CONFIG, {"X-Api-Secret": "nope"}) is False

    def test_missing_header_fails(self):
        assert verify_static_header_secret(STATIC_CONFIG, {}) is False


class TestVerifyRequestDispatch:
    def test_dispatches_to_hmac(self):
        now = 1788361200.0
        ts = "1788361200"
        body = b"{}"
        headers = {"X-Timestamp": ts, "X-Signature": _sign(HMAC_CONFIG["secret"], ts, body)}
        assert verify_request("hmac_sha256", HMAC_CONFIG, headers, body) is False  # no `now` override -> real clock, expired

    def test_dispatches_to_bearer(self):
        assert verify_request("bearer_token", BEARER_CONFIG, {"Authorization": "Bearer s3cr3t-token"}, b"{}") is True

    def test_dispatches_to_static_header(self):
        assert verify_request("static_header_secret", STATIC_CONFIG, {"X-Api-Secret": "s3cr3t"}, b"{}") is True

    def test_unknown_scheme_returns_false(self):
        assert verify_request("something_else", {}, {}, b"{}") is False
