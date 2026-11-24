"""Customers' WhatsApp images/audios/documents are downloaded and handed to the agent (like Telegram)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_agent_whatsapp_channel import _make_channel


def _image_value(caption=None):
    image = {"id": "MEDIA1", "mime_type": "image/jpeg"}
    if caption:
        image["caption"] = caption
    return {"messages": [{"from": "573001112233", "id": "wamid.img", "type": "image", "image": image}]}


def _http_returning(meta, blob=b"JPEGDATA"):
    meta_resp = MagicMock(status_code=200)
    meta_resp.json.return_value = meta
    blob_resp = MagicMock(status_code=200, content=blob)
    http = MagicMock()
    http.get = AsyncMock(side_effect=[meta_resp, blob_resp])
    return http


class TestInboundImage:
    async def test_image_is_downloaded_saved_and_passed_as_attachment(self, tmp_path):
        ch, runner = _make_channel()
        ch._deliver = AsyncMock()
        ch._http = _http_returning({"url": "https://lookaside/x", "mime_type": "image/jpeg", "file_size": 8})

        with patch("openacm.security.crypto.get_media_dir", return_value=tmp_path):
            await ch.handle_incoming(_image_value())

        kwargs = runner.run.call_args.kwargs
        assert len(kwargs["attachments"]) == 1
        saved = tmp_path / kwargs["attachments"][0]
        assert saved.suffix == ".jpg" and saved.read_bytes() == b"JPEGDATA"
        assert "imagen" in kwargs["message"].lower()

    async def test_caption_becomes_the_message(self, tmp_path):
        ch, runner = _make_channel()
        ch._deliver = AsyncMock()
        ch._http = _http_returning({"url": "https://lookaside/x", "mime_type": "image/png"})

        with patch("openacm.security.crypto.get_media_dir", return_value=tmp_path):
            await ch.handle_incoming(_image_value("¿cuánto cuesta este?"))

        assert runner.run.call_args.kwargs["message"] == "¿cuánto cuesta este?"

    async def test_failed_download_still_answers_and_says_so(self):
        ch, runner = _make_channel()
        ch._deliver = AsyncMock()
        ch._http = MagicMock()
        ch._http.get = AsyncMock(side_effect=RuntimeError("boom"))

        await ch.handle_incoming(_image_value("mira"))

        kwargs = runner.run.call_args.kwargs
        assert not kwargs.get("attachments")
        assert "mira" in kwargs["message"] and "no se pudo descargar" in kwargs["message"]

    async def test_oversized_media_is_skipped(self):
        ch, _ = _make_channel()
        ch._http = _http_returning({"url": "https://lookaside/x", "mime_type": "image/jpeg", "file_size": 50 * 1024 * 1024})

        assert await ch._download_media("MEDIA1") is None
        assert ch._http.get.await_count == 1  # never fetched the bytes

    @pytest.mark.parametrize("mime,ext", [("audio/ogg", ".ogg"), ("application/pdf", ".pdf")])
    async def test_extension_follows_mime_type(self, tmp_path, mime, ext):
        ch, _ = _make_channel()
        ch._http = _http_returning({"url": "https://lookaside/x", "mime_type": mime})

        with patch("openacm.security.crypto.get_media_dir", return_value=tmp_path):
            file_id = await ch._download_media("M")

        assert file_id.endswith(ext)
