"""Tests for openacm.utils.text.truncate()"""
import pytest
from openacm.utils.text import truncate


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
