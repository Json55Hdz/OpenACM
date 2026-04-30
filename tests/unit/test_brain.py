"""
Tests for openacm.core.brain.Brain

Covers:
  - _prepare_messages_for_llm: message optimization logic (pure, no LLM calls)
      - nulls content of old tool messages
      - strips arguments JSON from old assistant tool_calls
      - strips reasoning_content from old messages
      - never mutates the original list
      - preserves messages in the recent window untouched
      - injects tool enforcement into system prompt for weak providers
  - initialization: LocalRouter created, cancel structures empty
"""

import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from openacm.core.llm_router import ProviderProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_weak_router():
    """Mock router that signals needs_tool_enforcement=True."""
    router = MagicMock()
    router.get_provider_profile = MagicMock(return_value=ProviderProfile(
        name="ollama",
        needs_tool_enforcement=True,
        tool_choice_mode="auto",
        max_tools_per_call=10,
    ))
    return router


def _sys(text="System prompt."):
    return {"role": "system", "content": text}


def _user(text="Hello"):
    return {"role": "user", "content": text}


def _assistant(text="OK"):
    return {"role": "assistant", "content": text}


def _assistant_with_tool_call(tool_id="c1", name="run", args='{"cmd":"ls"}'):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": tool_id, "type": "function", "function": {"name": name, "arguments": args}}],
    }


def _tool_result(tool_id="c1", content="output"):
    return {"role": "tool", "tool_call_id": tool_id, "content": content}


# ---------------------------------------------------------------------------
# _prepare_messages_for_llm
# ---------------------------------------------------------------------------

class TestPrepareMessagesForLlm:
    """
    Build message lists long enough to push old entries past the cutoff window
    (brain._RECENT_MSG_WINDOW = 6) so the optimizations kick in.
    """

    WINDOW = 6  # Brain._RECENT_MSG_WINDOW

    def _pad(self, n=10):
        """Return n filler user/assistant pairs to push messages into the old zone."""
        msgs = []
        for i in range(n):
            msgs.append(_user(f"msg {i}"))
            msgs.append(_assistant(f"reply {i}"))
        return msgs

    def test_nulls_old_tool_message_content(self, brain):
        old_tool = _tool_result("c0", "big output " * 100)
        messages = [_sys()] + [old_tool] + self._pad(5)
        result = brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        # The tool message should have been nulled
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert all(m["content"] == "" for m in tool_msgs)

    def test_strips_args_from_old_assistant_tool_calls(self, brain):
        old_call = _assistant_with_tool_call(args='{"very":"big","json":"payload" * 200}')
        messages = [_sys()] + [old_call] + self._pad(5)
        result = brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        assistant_msgs = [m for m in result if m.get("tool_calls")]
        for m in assistant_msgs:
            for tc in m["tool_calls"]:
                assert tc["function"]["arguments"] == "{}"

    def test_strips_reasoning_content_from_old_messages(self, brain):
        old_msg = {**_assistant("thinking done"), "reasoning_content": "internal thought " * 50}
        messages = [_sys()] + [old_msg] + self._pad(5)
        result = brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        assert all("reasoning_content" not in m for m in result)

    def test_does_not_mutate_original_list(self, brain):
        old_tool = _tool_result("c0", "output")
        messages = [_sys()] + [old_tool] + self._pad(5)
        original_content = old_tool["content"]
        brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        assert old_tool["content"] == original_content

    def test_recent_messages_kept_intact(self, brain):
        recent_tool = _tool_result("c_recent", "recent output")
        # Only a few messages so nothing falls in the old zone
        messages = [_sys(), _user("hi"), recent_tool]
        result = brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        result_tool = next(m for m in result if m.get("role") == "tool")
        assert result_tool["content"] == "recent output"

    def test_output_length_matches_input_length(self, brain):
        messages = [_sys()] + self._pad(4)
        result = brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        assert len(result) == len(messages)

    def test_tool_enforcement_injected_for_weak_provider(self, brain):
        """When provider needs enforcement, system prompt gets the enforcement suffix."""
        brain.llm_router = _make_weak_router()
        tool_def = [{"type": "function", "function": {"name": "run_command"}}]
        messages = [_sys("Base prompt.")]
        result = brain._prepare_messages_for_llm(messages, tools=tool_def, is_tool_loop=False)
        assert result[0]["role"] == "system"
        assert "Base prompt." in result[0]["content"]
        assert "MUST" in result[0]["content"]  # from _TOOL_ENFORCEMENT_MSG

    def test_tool_enforcement_skipped_in_tool_loop(self, brain):
        """Enforcement is NOT added when already inside a tool loop."""
        brain.llm_router = _make_weak_router()
        tool_def = [{"type": "function", "function": {"name": "run_command"}}]
        messages = [_sys("Base prompt.")]
        result = brain._prepare_messages_for_llm(messages, tools=tool_def, is_tool_loop=True)
        assert result[0]["content"] == "Base prompt."

    def test_tool_enforcement_skipped_without_tools(self, brain):
        """Enforcement is NOT added when no tools are provided."""
        brain.llm_router = _make_weak_router()
        messages = [_sys("Base prompt.")]
        result = brain._prepare_messages_for_llm(messages, tools=None, is_tool_loop=False)
        assert result[0]["content"] == "Base prompt."


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestBrainInit:
    def test_local_router_created(self, brain):
        assert brain.local_router is not None

    def test_channel_tasks_empty_on_init(self, brain):
        assert brain._channel_tasks == {}

    def test_channel_queue_empty_on_init(self, brain):
        assert brain._channel_queue == {}

    def test_cancel_flags_empty_on_init(self, brain):
        assert brain._cancel_flags == {}

    def test_memory_has_llm_router_injected(self, brain):
        assert brain.memory._llm_router is brain.llm_router

    def test_memory_has_event_bus_injected(self, brain):
        assert brain.memory._event_bus is brain.event_bus
