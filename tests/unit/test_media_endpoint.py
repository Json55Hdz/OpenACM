"""Media endpoint: audio/video types and Range requests (needed to seek and to play on iOS)."""
import pytest

from openacm.web.routers.chat import _parse_byte_range


@pytest.mark.parametrize("header,total,expected", [
    (None, 100, None),
    ("bytes=0-9", 100, (0, 9)),
    ("bytes=10-", 100, (10, 99)),
    ("bytes=-20", 100, (80, 99)),
    ("bytes=90-500", 100, (90, 99)),
    ("bytes=100-110", 100, "invalid"),
    ("bytes=50-10", 100, "invalid"),
    ("bytes=-0", 100, "invalid"),
    ("bytes=0-1,5-6", 100, None),  # multi-range: just send everything
    ("items=0-1", 100, None),
    ("bytes=abc-", 100, None),
])
def test_parse_byte_range(header, total, expected):
    assert _parse_byte_range(header, total) == expected


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    import openacm.security.crypto as crypto

    monkeypatch.setattr(crypto, "get_media_dir", lambda: tmp_path)
    (tmp_path / "clip.mp4").write_bytes(bytes(range(100)))
    (tmp_path / "voice.ogg").write_bytes(b"x" * 10)
    return tmp_path


@pytest.fixture
def media_client(media_dir, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from openacm.web.routers import chat

    monkeypatch.setenv("DASHBOARD_TOKEN", "tok")
    app = FastAPI()
    chat.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers={"Authorization": "Bearer tok"})


async def test_video_is_served_inline_and_advertises_ranges(media_client):
    r = await media_client.get("/api/media/clip.mp4")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert r.headers["accept-ranges"] == "bytes" and "attachment" not in r.headers.get("content-disposition", "")


async def test_range_request_returns_partial_content(media_client):
    r = await media_client.get("/api/media/clip.mp4", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))
    assert r.headers["content-range"] == "bytes 10-19/100"


async def test_unsatisfiable_range_is_416(media_client):
    assert (await media_client.get("/api/media/clip.mp4", headers={"Range": "bytes=500-"})).status_code == 416


async def test_audio_formats_have_a_real_type(media_client):
    r = await media_client.get("/api/media/voice.ogg")
    assert r.headers["content-type"] == "audio/ogg" and "attachment" not in r.headers.get("content-disposition", "")
