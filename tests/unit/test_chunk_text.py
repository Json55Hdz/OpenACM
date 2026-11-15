"""Long replies must be split across messages, never cut."""

import pytest

from openacm.utils.text import chunk_text


def test_short_text_is_one_piece():
    assert chunk_text("hola", 100) == ["hola"]


def test_empty_text_has_no_pieces():
    assert chunk_text("   ", 100) == []


def test_every_piece_fits_and_nothing_is_lost():
    text = " ".join(f"palabra{i}" for i in range(2000))
    pieces = chunk_text(text, 500)
    assert all(len(p) <= 500 for p in pieces)
    assert " ".join(pieces).split() == text.split()


def test_prefers_paragraph_breaks():
    text = ("a" * 60) + "\n\n" + ("b" * 60)
    assert chunk_text(text, 100) == ["a" * 60, "b" * 60]


def test_a_text_without_any_break_is_still_split():
    pieces = chunk_text("x" * 1050, 500)
    assert [len(p) for p in pieces] == [500, 500, 50]


@pytest.mark.parametrize("limit", [2000, 4096])
def test_platform_limits(limit):
    text = ("linea de texto\n" * 1000)
    pieces = chunk_text(text, limit)
    assert all(len(p) <= limit for p in pieces)
    assert sum(p.count("linea") for p in pieces) == 1000


def test_mask_secrets_hides_every_secret_at_any_depth():
    from openacm.utils.text import mask_secrets

    cfg = {"channels": {"whatsapp": {"app_secret": "abc", "access_token": "t", "verify_token": "v",
                                     "phone_number_id": "123", "empty_token": ""}},
           "llm": {"providers": {"x": {"api_key": "sk-1", "model": "m"}}}, "list": [{"password": "p"}]}
    out = mask_secrets(cfg)
    assert out["channels"]["whatsapp"] == {"app_secret": "***", "access_token": "***", "verify_token": "***",
                                           "phone_number_id": "123", "empty_token": ""}
    assert out["llm"]["providers"]["x"] == {"api_key": "***", "model": "m"}
    assert out["list"] == [{"password": "***"}]
    assert cfg["llm"]["providers"]["x"]["api_key"] == "sk-1"  # the original is untouched
