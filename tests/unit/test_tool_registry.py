"""
Tests for openacm.tools.registry.ToolRegistry

Covers:
  - Constructor defaults (confirm_callback, empty caches)
  - INTENT_KEYWORDS: structure, non-empty categories, no duplicates within a category
  - _kw_match: word-boundary aware keyword matching
  - _is_conversational: short chat messages produce no tool intent
"""

import pytest

from openacm.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Constructor defaults
# ---------------------------------------------------------------------------

class TestToolRegistryInit:
    def test_confirm_callback_is_none(self, tool_registry):
        assert tool_registry.confirm_callback is None

    def test_tool_dict_is_empty_on_init(self, tool_registry):
        assert tool_registry.tools == {}

    def test_semantic_embeddings_none_on_init(self, tool_registry):
        assert tool_registry._tool_embeddings is None

    def test_tool_names_order_empty_on_init(self, tool_registry):
        assert tool_registry._tool_names_order == []

    def test_plugin_categories_empty_on_init(self, tool_registry):
        assert tool_registry._plugin_categories == set()


# ---------------------------------------------------------------------------
# INTENT_KEYWORDS class variable
# ---------------------------------------------------------------------------

class TestIntentKeywords:
    EXPECTED_CATEGORIES = {"system", "file", "web", "ai", "media", "google", "meta", "mcp", "ui", "iot"}

    def test_all_expected_categories_present(self):
        for cat in self.EXPECTED_CATEGORIES:
            assert cat in ToolRegistry.INTENT_KEYWORDS, f"Missing category: {cat}"

    def test_each_category_has_at_least_one_keyword(self):
        for cat, kws in ToolRegistry.INTENT_KEYWORDS.items():
            assert len(kws) > 0, f"Category '{cat}' has no keywords"

    def test_all_keywords_are_strings(self):
        for cat, kws in ToolRegistry.INTENT_KEYWORDS.items():
            for kw in kws:
                assert isinstance(kw, str), f"Non-string keyword in '{cat}': {kw!r}"

    def test_no_empty_keywords(self):
        for cat, kws in ToolRegistry.INTENT_KEYWORDS.items():
            for kw in kws:
                assert kw.strip(), f"Empty/whitespace keyword in '{cat}'"

    def test_no_duplicate_keywords_within_category(self):
        for cat, kws in ToolRegistry.INTENT_KEYWORDS.items():
            seen = set()
            for kw in kws:
                assert kw not in seen, f"Duplicate keyword '{kw}' in category '{cat}'"
                seen.add(kw)


# ---------------------------------------------------------------------------
# _kw_match — static word-boundary matcher
# ---------------------------------------------------------------------------

class TestKwMatch:
    def test_exact_word_matches(self):
        assert ToolRegistry._kw_match("run this command", "run") is True

    def test_substring_inside_word_does_not_match(self):
        # 'ui' must not match inside 'quieres'
        assert ToolRegistry._kw_match("quieres algo", "ui") is False

    def test_ai_not_matched_inside_said(self):
        assert ToolRegistry._kw_match("she said hello", "ai") is False

    def test_ai_matched_standalone(self):
        assert ToolRegistry._kw_match("use ai memory", "ai") is True

    def test_multiword_keyword_matches(self):
        assert ToolRegistry._kw_match("turn on the lights", "turn on") is True

    def test_special_char_keyword_substring_match(self):
        # Keywords with non-word chars fall back to substring matching
        assert ToolRegistry._kw_match("send me file.glb", ".glb") is True

    def test_case_sensitive_no_match(self):
        # _kw_match does NOT normalize case — callers lower() the message first
        assert ToolRegistry._kw_match("Run This", "run") is False

    def test_empty_message_no_match(self):
        assert ToolRegistry._kw_match("", "run") is False


# ---------------------------------------------------------------------------
# _is_conversational
# ---------------------------------------------------------------------------

class TestIsConversational:
    def test_greeting_is_conversational(self, tool_registry):
        assert tool_registry._is_conversational("hola") is True

    def test_thanks_is_conversational(self, tool_registry):
        assert tool_registry._is_conversational("gracias") is True

    def test_action_query_is_not_conversational(self, tool_registry):
        assert tool_registry._is_conversational("run this command please") is False

    def test_file_action_is_not_conversational(self, tool_registry):
        assert tool_registry._is_conversational("read the file") is False

    def test_long_message_always_not_conversational(self, tool_registry):
        # Messages over 80 chars skip the conversational check entirely
        long_msg = "hola " * 20  # 100+ chars, pure greetings but too long
        assert tool_registry._is_conversational(long_msg) is False
