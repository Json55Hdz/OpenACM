"""Tests for openacm.utils.text"""
from openacm.utils.text import truncate, extract_and_strip_thinking


def test_short_string_unchanged():
    assert truncate("hello", 10) == "hello"


def test_exact_length_unchanged():
    assert truncate("hello", 5) == "hello"


def test_long_string_truncated():
    result = truncate("hello world", 5)
    assert result == "hello...[truncated]"


def test_default_suffix():
    result = truncate("abcdef", 3)
    assert result.endswith("...[truncated]")


def test_custom_suffix():
    result = truncate("hello world", 5, suffix="...")
    assert result == "hello..."


def test_empty_suffix():
    result = truncate("hello world", 5, suffix="")
    assert result == "hello"


def test_empty_string():
    assert truncate("", 10) == ""


def test_empty_string_zero_limit():
    assert truncate("", 0) == ""


def test_non_empty_zero_limit():
    result = truncate("hi", 0)
    assert result == "...[truncated]"


def test_content_before_suffix_is_correct_length():
    max_len = 8
    result = truncate("0123456789", max_len)
    content = result.replace("...[truncated]", "")
    assert len(content) == max_len


def test_unicode_string():
    s = "café résumé"
    result = truncate(s, 4)
    assert result.startswith("café")
    assert "...[truncated]" in result


def test_returns_string_type():
    assert isinstance(truncate("x", 100), str)


# ── extract_and_strip_thinking ───────────────────────────────────────────────


def test_thinking_standard_closed_block():
    content = "<think>I should greet the user</think>Hola! ¿Cómo estás?"
    clean, reasoning = extract_and_strip_thinking(content)
    assert clean == "Hola! ¿Cómo estás?"
    assert reasoning == "I should greet the user"


def test_thinking_standard_closed_thinking_tag():
    content = "<thinking>Analyzing user request</thinking>Respuesta clara."
    clean, reasoning = extract_and_strip_thinking(content)
    assert clean == "Respuesta clara."
    assert reasoning == "Analyzing user request"


def test_thinking_orphan_closing_tag_prefilled():
    # When prompt template prefills <think>, model only emits thoughts then </think> then answer
    content = (
        "¡Excelente elección! El iPhone 17 Pro Max es top. </think>\n"
        "¡Excelente elección! El iPhone 17 Pro Max es top."
    )
    clean, reasoning = extract_and_strip_thinking(content)
    assert clean == "¡Excelente elección! El iPhone 17 Pro Max es top."
    assert reasoning == "¡Excelente elección! El iPhone 17 Pro Max es top."
    assert "</think>" not in clean


def test_thinking_orphan_opening_tag_truncated():
    content = "<think>Thinking process was cut off before finishing"
    clean, reasoning = extract_and_strip_thinking(content)
    assert clean == ""
    assert reasoning == "Thinking process was cut off before finishing"


def test_thinking_multiple_blocks():
    content = "<think>Step 1</think>Middle text<think>Step 2</think>Final answer"
    clean, reasoning = extract_and_strip_thinking(content)
    assert clean == "Middle textFinal answer"
    assert "Step 1" in reasoning
    assert "Step 2" in reasoning


def test_thinking_with_existing_reasoning():
    content = "<think>extra thoughts</think>Final message"
    clean, reasoning = extract_and_strip_thinking(content, existing_reasoning="Provider reasoning")
    assert clean == "Final message"
    assert "Provider reasoning" in reasoning
    assert "extra thoughts" in reasoning


def test_thinking_no_tags():
    content = "Solo un mensaje normal sin etiquetas."
    clean, reasoning = extract_and_strip_thinking(content)
    assert clean == "Solo un mensaje normal sin etiquetas."
    assert reasoning == ""


def test_thinking_empty_content():
    clean, reasoning = extract_and_strip_thinking("", existing_reasoning="prior")
    assert clean == ""
    assert reasoning == "prior"

