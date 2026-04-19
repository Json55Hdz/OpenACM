"""Tests for openacm.web.state.ServerState"""
import pytest
from openacm.web.state import ServerState


def test_defaults_are_none_for_services():
    s = ServerState()
    assert s.brain is None
    assert s.database is None
    assert s.event_bus is None
    assert s.tool_registry is None
    assert s.config is None
    assert s.command_processor is None
    assert s.agent_bot_manager is None
    assert s.mcp_manager is None
    assert s.activity_watcher is None
    assert s.cron_scheduler is None
    assert s.swarm_manager is None
    assert s.content_watcher is None


def test_defaults_are_empty_collections():
    s = ServerState()
    assert s.channels == []
    assert s.custom_provider_ids == set()
    assert s.onboarding_triggered_flags == {}
    assert s.chat_ws_clients == set()
    assert s.ws_clients == set()
    assert s.pending_confirmations == {}
    assert s.session_allowed_commands == set()
    assert s.channel_shells == {}


def test_pending_chat_response_defaults_to_none():
    s = ServerState()
    assert s.pending_chat_response is None


def test_instances_do_not_share_collections():
    a = ServerState()
    b = ServerState()
    a.channels.append("x")
    assert b.channels == []
    a.custom_provider_ids.add("p")
    assert "p" not in b.custom_provider_ids


def test_can_assign_service():
    s = ServerState()
    s.brain = object()
    assert s.brain is not None


def test_can_mutate_collections():
    s = ServerState()
    s.ws_clients.add("ws1")
    assert "ws1" in s.ws_clients
    s.onboarding_triggered_flags["ch1"] = True
    assert s.onboarding_triggered_flags["ch1"] is True


def test_pending_chat_response_assignable():
    s = ServerState()
    payload = {"type": "message", "text": "hi"}
    s.pending_chat_response = payload
    assert s.pending_chat_response == payload
    s.pending_chat_response = None
    assert s.pending_chat_response is None
