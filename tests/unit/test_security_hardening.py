"""Regression tests for security hardening (token checks, SPA path guard, TTS regex)."""
import time
from unittest.mock import MagicMock

import pytest

from openacm.security.auth import tokens_match
from openacm.web.broadcast import _verify_ws_token
from openacm.web.routers.voice import _clean_for_tts

TEST_TOKEN = "test-dashboard-token"


class TestTokensMatch:
    def test_equal_tokens_match(self):
        assert tokens_match("abc", "abc") is True

    def test_different_tokens_do_not_match(self):
        assert tokens_match("abc", "abd") is False

    @pytest.mark.parametrize("provided, expected", [("", ""), (None, None), ("abc", ""), ("", "abc")])
    def test_empty_values_never_match(self, provided, expected):
        assert tokens_match(provided, expected) is False


class TestWebSocketToken:
    def _ws(self, token):
        ws = MagicMock()
        ws.query_params = {"token": token}
        return ws

    def test_rejects_when_no_dashboard_token_configured(self, monkeypatch):
        monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
        assert _verify_ws_token(self._ws("")) is False

    def test_accepts_matching_token(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
        assert _verify_ws_token(self._ws(TEST_TOKEN)) is True

    def test_rejects_wrong_token(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
        assert _verify_ws_token(self._ws("nope")) is False


class TestAuthCheckEndpoint:
    async def test_wrong_token_rejected(self, monkeypatch, client):
        monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
        resp = await client.get("/api/auth/check", params={"token": "wrong"})
        assert resp.status_code == 401


class TestSpaPathGuard:
    async def test_traversal_does_not_escape_static_dir(self, client):
        resp = await client.get("/..%2F..%2F..%2F..%2Fetc%2Fpasswd")
        assert "root:" not in resp.text


class TestCleanForTts:
    def test_strips_markdown_link(self):
        assert _clean_for_tts("see [docs](https://x.y/z) now") == "see docs now"

    def test_pathological_input_is_fast(self):
        start = time.perf_counter()
        _clean_for_tts("[" * 20000 + "](" * 20000)
        assert time.perf_counter() - start < 1.0
