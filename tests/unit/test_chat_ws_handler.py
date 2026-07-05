"""Unit tests for _handle_chat_turn — the per-turn chat handler extracted
from ws_chat so the receive loop can stay free to read a "cancel" frame
while a turn is still running (see chat.py's ws_chat for the race this fixes).
"""
from unittest.mock import AsyncMock, MagicMock
import pytest
from openacm.web.routers import chat as chat_router
from openacm.web.state import _state


def _make_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture(autouse=True)
def _reset_state():
    old_brain = _state.brain
    old_clients = _state.chat_ws_clients
    old_pending = _state.pending_chat_response
    _state.chat_ws_clients = set()
    _state.pending_chat_response = None
    yield
    _state.brain = old_brain
    _state.chat_ws_clients = old_clients
    _state.pending_chat_response = old_pending


def _make_router(usage_snapshot=None):
    router = MagicMock()
    router.get_usage_snapshot.return_value = usage_snapshot or {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0, "requests": 0,
    }
    router.current_model = "test-model"
    return router


class TestHandleChatTurn:
    async def test_delivers_response_to_original_websocket(self, monkeypatch):
        ws = _make_ws()
        _state.brain = MagicMock()
        _state.brain.process_message = AsyncMock(return_value="Hola!")
        _state.brain.llm_router = _make_router()
        _state.chat_ws_clients = {ws}

        await chat_router._handle_chat_turn(ws, "hi", [], "web", "web", "web")

        ws.send_json.assert_awaited_once()
        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "response"
        assert payload["content"] == "Hola!"

    async def test_strips_attachment_lines_into_structured_list(self, monkeypatch):
        ws = _make_ws()
        _state.brain = MagicMock()
        _state.brain.process_message = AsyncMock(
            return_value="Here you go\nATTACHMENT:report.pdf\nATTACHMENT:chart.png"
        )
        _state.brain.llm_router = _make_router()
        _state.chat_ws_clients = {ws}

        await chat_router._handle_chat_turn(ws, "send report", [], "web", "web", "web")

        payload = ws.send_json.call_args[0][0]
        assert payload["content"] == "Here you go"
        assert payload["attachments"] == ["report.pdf", "chart.png"]

    async def test_computes_usage_delta_for_the_turn(self, monkeypatch):
        ws = _make_ws()
        _state.brain = MagicMock()
        _state.brain.process_message = AsyncMock(return_value="ok")
        router = _make_router()
        router.get_usage_snapshot.side_effect = [
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.01, "requests": 1},
            {"prompt_tokens": 130, "completion_tokens": 70, "total_tokens": 200, "cost": 0.015, "requests": 2},
        ]
        _state.brain.llm_router = router
        _state.chat_ws_clients = {ws}

        await chat_router._handle_chat_turn(ws, "hi", [], "web", "web", "web")

        usage = ws.send_json.call_args[0][0]["usage"]
        assert usage["prompt_tokens"] == 30
        assert usage["completion_tokens"] == 20
        assert usage["requests"] == 1

    async def test_no_brain_reports_error(self, monkeypatch):
        ws = _make_ws()
        _state.brain = None

        await chat_router._handle_chat_turn(ws, "hi", [], "web", "web", "web")

        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "error"
        assert payload["content"] == "Brain not available"

    async def test_process_message_exception_sends_error_payload(self, monkeypatch):
        ws = _make_ws()
        _state.brain = MagicMock()
        _state.brain.process_message = AsyncMock(side_effect=RuntimeError("boom"))
        _state.brain.llm_router = _make_router()
        _state.chat_ws_clients = {ws}

        await chat_router._handle_chat_turn(ws, "hi", [], "web", "web", "web")

        payload = ws.send_json.call_args[0][0]
        assert payload["type"] == "error"
        assert "boom" in payload["content"]

    async def test_falls_back_to_another_client_when_original_send_fails(self, monkeypatch):
        dead_ws = _make_ws()
        dead_ws.send_json.side_effect = Exception("connection closed")
        alive_ws = _make_ws()
        _state.brain = MagicMock()
        _state.brain.process_message = AsyncMock(return_value="hi there")
        _state.brain.llm_router = _make_router()
        _state.chat_ws_clients = {dead_ws, alive_ws}

        await chat_router._handle_chat_turn(dead_ws, "hi", [], "web", "web", "web")

        alive_ws.send_json.assert_awaited_once()
        payload = alive_ws.send_json.call_args[0][0]
        assert payload["content"] == "hi there"

    async def test_buffers_response_when_no_client_reachable(self, monkeypatch):
        dead_ws = _make_ws()
        dead_ws.send_json.side_effect = Exception("connection closed")
        _state.brain = MagicMock()
        _state.brain.process_message = AsyncMock(return_value="hi there")
        _state.brain.llm_router = _make_router()
        _state.chat_ws_clients = {dead_ws}

        await chat_router._handle_chat_turn(dead_ws, "hi", [], "web", "web", "web")

        assert _state.pending_chat_response is not None
        assert _state.pending_chat_response["content"] == "hi there"
