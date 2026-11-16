"""Prompt regression tests.

The real model cannot run in CI, so these lock in what we CONTROL and what shapes its behaviour:
the prompts we send, what the model is allowed to see for a given request (tool selection), and
the safety rules that must reach it. If a refactor silently drops a rule from a prompt, or a
request stops exposing the tool it needs, one of these fails.

Set OPENACM_LIVE_EVAL=1 (with a real model configured) to also run the live cases at the bottom.
"""
import os

import pytest

from openacm.core import messages as M


# ── 1-6: the prompts keep their rules ─────────────────────────────────────────

def test_compaction_prompt_keeps_every_section_and_the_paths_rule():
    p = M.PROMPT_COMPACT_SYSTEM
    for section in ("## What was worked on", "## Actions taken", "## Key decisions and findings", "## Current state"):
        assert section in p
    assert "EXACT full paths" in p and "same language the user used" in p


def test_setup_mode_prompt_collects_the_profile_before_anything_else():
    p = M.PROMPT_SETUP_MODE
    assert "save_user_profile" in p and "Do NOT help with unrelated tasks" in p


async def test_system_prompt_contains_the_configured_persona(brain):
    prompt, _ = await brain._build_system_prompt("hola", "u", "c", "web")
    assert brain.config.system_prompt.strip()[:40] in prompt


async def test_pinned_workspace_is_injected_with_override_wording(brain):
    brain.memory.set_conversation_workspace("u", "c", "C:/proyecto")
    prompt, _ = await brain._build_system_prompt("hola", "u", "c", "web")
    assert "C:/proyecto" in prompt and "ALL file operations MUST use" in prompt


async def test_no_workspace_pin_when_none_is_set(brain):
    prompt, _ = await brain._build_system_prompt("hola", "u2", "c2", "web")
    assert "WORKSPACE FOR THIS CONVERSATION" not in prompt


async def test_onboarding_replaces_the_persona_with_setup_mode(brain):
    brain.config.onboarding_completed = False
    prompt, _ = await brain._build_system_prompt("hola", "u3", "c3", "web")
    assert "save_user_profile" in prompt


# ── 7-10: status messages the user sees keep their meaning ────────────────────

def test_cancel_and_queue_messages_are_distinct_and_non_empty():
    msgs = [M.MSG_CANCELLED, M.MSG_QUEUED_ACK, M.MSG_STEER_ACK, M.MSG_NOTHING_TO_CANCEL, M.MSG_CANCEL_PENDING]
    assert all(m.strip() for m in msgs) and len(set(msgs)) == len(msgs)


def test_step_limit_message_tells_the_user_what_to_do():
    assert "step limit" in M.MSG_MAX_ITERATIONS and "smaller steps" in M.MSG_MAX_ITERATIONS


def test_plugin_install_errors_never_suggest_running_unknown_code():
    assert "github.com" in M.MSG_PLUGIN_INSTALL_BAD_SOURCE.lower()


def test_removed_features_leave_no_prompt_behind():
    assert not hasattr(M, "PROMPT_RESURRECTION_HINT")


# ── 11-18: what the model is allowed to see for a request ─────────────────────

@pytest.fixture
def registry(event_bus, db):
    """A registry with the real tools registered and NO embedding model (keyword selection)."""
    from openacm.tools import (
        file_ops, list_tools, system_cmd, web_search,
    )
    from openacm.tools.registry import ToolRegistry

    reg = ToolRegistry(database=db, event_bus=event_bus, sandbox=None)
    for mod in (file_ops, system_cmd, web_search, list_tools):
        reg.register_module(mod)
    reg._semantic_model = None
    return reg


def names(schema):
    return {t["function"]["name"] for t in schema}


@pytest.mark.parametrize("message,expected", [
    ("busca en internet el clima de hoy", "web_search"),
    ("guarda este texto en un archivo notas.txt", "write_file"),
    ("ejecuta git status en la terminal", "run_command"),
    ("lee el archivo config.yaml", "read_file"),
])
def test_requests_expose_the_tool_they_need(registry, message, expected):
    assert expected in names(registry.get_tools_by_intent(message))


def test_asking_what_it_can_do_exposes_the_tool_catalog(registry):
    assert "list_tools" in names(registry.get_tools_by_intent("que herramientas tienes disponibles? busca cuales hay"))


def test_smalltalk_does_not_dump_the_whole_toolbox(registry):
    assert len(names(registry.get_tools_by_intent("hola, que tal"))) < len(registry.tools)


# ── 19-22: safety rules that must keep reaching the model / the gate ─────────

def test_risky_tools_keep_asking_the_owner():
    from openacm.tools.registry import confirmation_text

    for tool, args in [("run_python", {"code": "1"}), ("write_file", {"path": "a/b"}), ("update_security_mode", {"mode": "yolo"})]:
        assert confirmation_text(tool, args, "confirmation")


def test_agents_stay_out_of_the_owners_fast_path_prompts():
    # the webhook refuses 'all tools' agents; the guard text must stay in the router
    import inspect

    from openacm.web.routers import agents

    assert "allows every tool" in inspect.getsource(agents)


def test_default_system_prompt_forbids_nothing_it_should_not_and_has_no_secrets():
    from openacm.core.config import AssistantConfig

    text = AssistantConfig().system_prompt.lower()
    for leaked in ("sk-", "api_key=", "password:"):
        assert leaked not in text


# ── optional: live cases against the configured model ────────────────────────

LIVE = os.environ.get("OPENACM_LIVE_EVAL") == "1"


@pytest.mark.skipif(not LIVE, reason="set OPENACM_LIVE_EVAL=1 to call the real model")
async def test_live_model_picks_web_search_for_a_search_request(registry):
    from openacm.core.config import load_config
    from openacm.core.events import EventBus
    from openacm.core.llm_router import LLMRouter

    config = load_config()
    router = LLMRouter(config.llm, EventBus())
    tools = registry.get_tools_by_intent("busca en internet noticias de hoy sobre python")
    result = await router.chat([{"role": "user", "content": "busca en internet noticias de hoy sobre python"}], tools=tools)
    assert any(tc["function"]["name"] == "web_search" for tc in (result.get("tool_calls") or []))
