"""
Tests for openacm.tools.registry.ToolRegistry

Covers:
  - Constructor defaults (confirm_callback, empty caches)
  - INTENT_KEYWORDS: structure, non-empty categories, no duplicates within a category
  - _kw_match: word-boundary aware keyword matching
  - _is_conversational: short chat messages produce no tool intent
"""

import numpy as np
import pytest

from openacm.tools.base import ToolDefinition
from openacm.tools.registry import ALWAYS_INCLUDE_TOOLS, ToolRegistry


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
    EXPECTED_CATEGORIES = {"system", "file", "web", "ai", "media", "google", "meta", "mcp", "ui"}

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

class TestIsRelevant:
    def test_matching_keyword_is_relevant(self, tool_registry):
        assert tool_registry.is_relevant("hay zapatos disponibles?", "Consulta disponibilidad de zapatos en la tienda") is True

    def test_no_matching_keyword_is_not_relevant(self, tool_registry):
        assert tool_registry.is_relevant("qué clima hace hoy?", "Consulta disponibilidad de zapatos en la tienda") is False

    def test_short_words_are_ignored_to_avoid_noise_matches(self, tool_registry):
        # "de" and "en" are 2 letters — must not cause an accidental match
        # against unrelated text that also happens to contain them.
        assert tool_registry.is_relevant("de qué color es el auto?", "Envía un correo de bienvenida") is False


# ---------------------------------------------------------------------------
# ALWAYS_INCLUDE_TOOLS — create_or_update_agent_flow must survive low similarity
# ---------------------------------------------------------------------------

class _FakeSemanticModel:
    """Deterministic stand-in for a sentence-transformer model.

    Assigns orthogonal vectors based on which known substring a text contains,
    so cosine similarity between the message and each tool is fully predictable
    without loading a real embeddings model (the `tool_registry` fixture
    intentionally has none loaded).
    """

    def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
        vecs = []
        for text in texts:
            if "create_or_update_agent_flow" in text:
                vecs.append([1.0, 0.0, 0.0])
            elif "some_other_tool" in text:
                vecs.append([0.0, 1.0, 0.0])
            else:
                vecs.append([0.0, 0.0, 1.0])
        return np.array(vecs, dtype=np.float32)


async def _dummy_handler(**kwargs):
    return "ok"


class TestAlwaysIncludeFlowTool:
    """create_or_update_agent_flow must be offered regardless of semantic score.

    Real-world flow-building messages can land just under
    SEMANTIC_TOOL_THRESHOLD on their own merit, which used to mean the tool
    was silently never offered to the LLM. It's now in ALWAYS_INCLUDE_TOOLS
    (registry.py), so get_tools_semantic must include it unconditionally —
    proven here with a message that is deliberately orthogonal (0 similarity)
    to every registered tool, including the flow tool itself.
    """

    def test_flow_tool_is_in_always_include_set(self):
        assert "create_or_update_agent_flow" in ALWAYS_INCLUDE_TOOLS

    def test_flow_tool_always_included_for_unrelated_message(self, tool_registry):
        tool_registry.tools["create_or_update_agent_flow"] = ToolDefinition(
            name="create_or_update_agent_flow",
            description="Build or update an agent flow conversationally.",
            parameters={"type": "object", "properties": {}},
            handler=_dummy_handler,
            category="ai",
        )
        tool_registry.tools["some_other_tool"] = ToolDefinition(
            name="some_other_tool",
            description="Completely unrelated helper tool.",
            parameters={"type": "object", "properties": {}},
            handler=_dummy_handler,
            category="general",
        )
        tool_registry._semantic_model = _FakeSemanticModel()

        selected = tool_registry.get_tools_semantic("hola, qué tal")

        selected_names = {t["function"]["name"] for t in selected}
        # Selected despite 0 similarity to the message — because it's always-include.
        assert "create_or_update_agent_flow" in selected_names
        # Sanity check: a normal tool with the same (0) similarity is NOT
        # included, proving the flow tool's inclusion is due to
        # ALWAYS_INCLUDE_TOOLS and not some accidental similarity match.
        assert "some_other_tool" not in selected_names


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


class _FixedEncoder:
    """encode() always returns the same unit vector [1, 0]."""

    def encode(self, texts, **kwargs):
        return np.array([[1.0, 0.0]] * len(texts))


class TestSemanticSelectionOrderSurvivesToolCap:
    """Providers cap tools per call (brain_loop: tools[:cap]). The list must be
    ranked by relevance so tools registered LAST (every plugin) are not the ones
    that fall off the end."""

    def _setup(self, tool_registry, n_builtin=20):
        names, embs = [], []
        for i in range(n_builtin):  # registered first, only mildly relevant
            n = f"builtin_{i}"
            tool_registry.tools[n] = ToolDefinition(
                name=n, description="x", parameters={"type": "object", "properties": {}},
                handler=_dummy_handler, category="general",
            )
            names.append(n)
            embs.append([0.5, 0.866])  # cosine 0.5 with [1, 0]
        for n, vec in (("plugin_best", [1.0, 0.0]), ("plugin_good", [0.8, 0.6])):
            tool_registry.tools[n] = ToolDefinition(
                name=n, description="x", parameters={"type": "object", "properties": {}},
                handler=_dummy_handler, category="audio",
            )
            names.append(n)  # registered last
            embs.append(vec)
        tool_registry._semantic_model = _FixedEncoder()
        tool_registry._tool_names_order = names
        tool_registry._tool_embeddings = np.array(embs)

    def test_most_relevant_tools_come_first_even_if_registered_last(self, tool_registry):
        self._setup(tool_registry)
        got = [t["function"]["name"] for t in tool_registry.get_tools_semantic("msg")]
        assert got[:2] == ["plugin_best", "plugin_good"]
        capped = got[:15]  # what brain_loop does for a 15-tool provider
        assert "plugin_best" in capped and "plugin_good" in capped

    def test_keyword_matched_plugin_tools_lead_the_intent_result(self, tool_registry):
        self._setup(tool_registry)
        tool_registry.register_plugin_keywords({"audio": ["escucha"]})
        got = [t["function"]["name"] for t in tool_registry.get_tools_by_intent("escucha esto")]
        assert got[:2] == ["plugin_best", "plugin_good"]


class TestKeywordFallbackRanksByCategoryHits:
    def test_strongest_matching_category_first_general_last(self, tool_registry):
        for name, cat in (("g1", "general"), ("b1", "browser"), ("d1", "desktop"), ("d2", "desktop")):
            tool_registry.tools[name] = ToolDefinition(
                name=name, description="x", parameters={"type": "object", "properties": {}},
                handler=_dummy_handler, category=cat,
            )
        tool_registry.INTENT_KEYWORDS = {
            "browser": ["navegador"],
            "desktop": ["mouse", "clic", "pantalla"],
        }
        got = [t["function"]["name"] for t in tool_registry.get_tools_by_intent("mueve el mouse y haz clic en la pantalla del navegador")]
        assert got.index("d1") < got.index("b1") < got.index("g1")


# ---------------------------------------------------------------------------
# Tool time limit
# ---------------------------------------------------------------------------

def _add_tool(registry, handler, **kwargs):
    registry.tools["probe"] = ToolDefinition(
        name="probe", description="probe", parameters={"type": "object", "properties": {}},
        handler=handler, **kwargs,
    )


class TestToolTimeLimit:
    async def test_a_tool_that_hangs_is_stopped_and_the_model_is_told(self, tool_registry):
        import asyncio

        async def hang(**_):
            await asyncio.sleep(30)
            return "never"

        _add_tool(tool_registry, hang, timeout_s=0.05)
        result = await tool_registry.execute("probe", {})
        assert "did not finish within" in result and "probe" in result
        assert "may have done part of the work" in result

    async def test_a_tool_inside_its_limit_returns_normally(self, tool_registry):
        async def fast(**_):
            return "done"

        _add_tool(tool_registry, fast, timeout_s=5)
        assert await tool_registry.execute("probe", {}) == "done"

    async def test_zero_means_no_limit(self, tool_registry, monkeypatch):
        import asyncio
        from openacm.tools import registry as reg

        monkeypatch.setattr(reg, "DEFAULT_TOOL_TIMEOUT_SECONDS", 0.01)

        async def slowish(**_):
            await asyncio.sleep(0.1)
            return "finished"

        _add_tool(tool_registry, slowish, timeout_s=0)
        assert await tool_registry.execute("probe", {}) == "finished"

    async def test_the_default_limit_applies_when_a_tool_sets_none(self, tool_registry, monkeypatch):
        import asyncio
        from openacm.tools import registry as reg

        monkeypatch.setattr(reg, "DEFAULT_TOOL_TIMEOUT_SECONDS", 0.05)

        async def hang(**_):
            await asyncio.sleep(30)

        _add_tool(tool_registry, hang)
        assert "did not finish within" in await tool_registry.execute("probe", {})

    async def test_a_timeout_raised_inside_the_tool_is_not_reported_as_ours(self, tool_registry):
        async def inner(**_):
            raise TimeoutError("upstream API timed out")

        _add_tool(tool_registry, inner, timeout_s=5)
        result = await tool_registry.execute("probe", {})
        assert "upstream API timed out" in result
        assert "did not finish within" not in result

    def test_run_command_keeps_its_own_limit(self):
        from openacm.tools.base import get_registered_tools
        import openacm.tools.system_cmd  # noqa: F401  (registers the tool)

        rc = next(t for t in get_registered_tools() if t.name == "run_command")
        assert rc.timeout_s == 0
