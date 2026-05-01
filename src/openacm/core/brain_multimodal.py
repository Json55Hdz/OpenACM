"""Multimodal attachment handling for Brain (PDF, audio, images)."""

import asyncio
from typing import Any

import litellm
import structlog

from openacm.constants import TRUNCATE_PDF_CHARS, TRUNCATE_FILE_CONTEXT_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()


class BrainMultimodalMixin:

    def _extract_pdf_text(self, raw_bytes: bytes) -> str:
        """
        Extract text from a PDF.
        Priority: docling (layout-aware, tables) → pypdf (basic) → error message.
        """
        import io

        # ── 1. docling — layout-aware, handles tables and columns ─────────
        try:
            from docling.document_converter import DocumentConverter
            from docling.datamodel.base_models import DocumentStream

            stream = DocumentStream(name="doc.pdf", stream=io.BytesIO(raw_bytes))
            converter = DocumentConverter()
            result = converter.convert(stream, raises_on_error=False)
            md = result.document.export_to_markdown()
            if md and md.strip():
                return truncate(md, TRUNCATE_PDF_CHARS)
        except Exception as e:
            log.debug("docling PDF extraction failed, falling back to pypdf", error=str(e))

        # ── 2. pypdf fallback ─────────────────────────────────────────────
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            return truncate(text, TRUNCATE_PDF_CHARS) or "[PDF has no extractable text]"
        except ImportError:
            return "[pypdf not installed — install with: pip install pypdf]"
        except Exception as e:
            log.warning("PDF extraction failed", error=str(e))
            return f"[PDF extraction error: {e}]"

    async def structured_extract(self, text: str, schema: type, system: str | None = None) -> Any | None:
        """
        Extract structured data from text using instructor + litellm.
        Returns a validated Pydantic model instance, or None if unavailable.

        Example:
            class Lang(BaseModel):
                language: str
                confidence: float
            result = await brain.structured_extract("Bonjour monde", Lang)
            # result.language == "French"
        """
        try:
            import instructor
            from litellm import completion as _completion

            client = instructor.from_litellm(_completion)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": text})

            return await asyncio.to_thread(
                client.chat.completions.create,
                model=self.llm_router.current_model,
                response_model=schema,
                messages=messages,
                max_retries=2,
            )
        except ImportError:
            log.warning("instructor not installed — structured_extract unavailable")
            return None
        except Exception as e:
            log.warning("structured_extract failed", error=str(e))
            return None

    async def _transcribe_audio(self, raw_bytes: bytes, ext: str) -> str | None:
        """
        Transcribe audio bytes to text.
        Priority: OpenAI Whisper API → faster-whisper local → None.
        """
        import os

        # ── 1. OpenAI Whisper API ──────────────────────────────────────────
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                import httpx
                mime_map = {
                    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                    ".m4a": "audio/mp4", ".webm": "audio/webm", ".flac": "audio/flac",
                }
                mime = mime_map.get(ext, "audio/mpeg")
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={"file": (f"audio{ext}", raw_bytes, mime)},
                        data={"model": "whisper-1"},
                        timeout=60.0,
                    )
                    if resp.status_code == 200:
                        return resp.json().get("text", "")
                    log.warning("Whisper API error", status=resp.status_code)
            except Exception as e:
                log.warning("OpenAI Whisper transcription failed", error=str(e))

        # ── 2. Local faster-whisper ────────────────────────────────────────
        try:
            import tempfile, os as _os
            from faster_whisper import WhisperModel

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(raw_bytes)
                tmp_path = f.name
            try:
                loop = asyncio.get_event_loop()

                def _run():
                    model = WhisperModel("base", device="cpu", compute_type="int8")
                    segments, _ = model.transcribe(tmp_path, beam_size=5)
                    return " ".join(seg.text for seg in segments).strip()

                return await loop.run_in_executor(None, _run)
            finally:
                _os.unlink(tmp_path)
        except ImportError:
            pass
        except Exception as e:
            log.warning("Local Whisper transcription failed", error=str(e))

        # ── 3. MarkItDown speech_recognition fallback ──────────────────────
        try:
            import tempfile, os as _os
            from markitdown import MarkItDown

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(raw_bytes)
                tmp_path = f.name
            try:
                loop = asyncio.get_event_loop()

                def _run_md():
                    result = MarkItDown().convert(tmp_path)
                    return (result.text_content or "").strip()

                text = await loop.run_in_executor(None, _run_md)
                if text:
                    return text
            finally:
                _os.unlink(tmp_path)
        except ImportError:
            pass
        except Exception as e:
            log.warning("MarkItDown audio transcription failed", error=str(e))

        return None

    async def _resolve_attachment_content(
        self,
        content: str,
        attachments: list[str],
    ) -> str | list:
        """Convert raw attachment IDs into structured LLM content (images, audio, PDFs, etc.)."""
        import base64
        from openacm.security.crypto import decrypt_file, get_media_dir

        structured_content: list = []
        if content:
            structured_content.append({"type": "text", "text": content})

        for att_id in attachments:
            file_path = get_media_dir() / att_id
            if not file_path.exists():
                continue
            try:
                raw_bytes = decrypt_file(file_path)
                b64 = base64.b64encode(raw_bytes).decode("utf-8")
                ext = file_path.suffix.lower()

                mime = "application/octet-stream"
                if ext == ".png":
                    mime = "image/png"
                elif ext in (".jpg", ".jpeg"):
                    mime = "image/jpeg"
                elif ext == ".gif":
                    mime = "image/gif"
                elif ext == ".webp":
                    mime = "image/webp"

                if mime.startswith("image/"):
                    try:
                        _vision_ok = litellm.supports_vision(model=self.llm_router.current_model)
                    except Exception:
                        _vision_ok = True
                    if _vision_ok:
                        structured_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                            "_file_id": att_id,
                        })
                    else:
                        try:
                            from markitdown import MarkItDown
                            md_text = (MarkItDown().convert(str(file_path)).text_content or "").strip()
                        except Exception:
                            md_text = ""
                        structured_content.append({
                            "type": "text",
                            "text": (
                                f"[Image — {file_path.name}]:\n{md_text}"
                                if md_text
                                else f"[Image attached: {file_path.name} — active model does not support vision]"
                            ),
                        })
                elif ext == ".pdf":
                    text = self._extract_pdf_text(raw_bytes)
                    structured_content.append({"type": "text", "text": f"[PDF — {file_path.name}]:\n{text}"})
                elif ext in (".mp3", ".wav", ".ogg", ".m4a", ".webm", ".flac"):
                    transcript = await self._transcribe_audio(raw_bytes, ext)
                    if transcript:
                        structured_content.append({"type": "text", "text": f"[Audio transcript]:\n{transcript}"})
                    else:
                        structured_content.append({
                            "type": "text",
                            "text": f"[Audio file attached: {file_path.name} — transcription unavailable. No Whisper API key or faster-whisper installed.]",
                        })
                else:
                    # For known text formats, decode the already-read bytes directly.
                    # MarkItDown is unreliable for plain text (can return empty for .md).
                    _text_exts = {
                        '.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.toml',
                        '.xml', '.html', '.htm', '.py', '.js', '.ts', '.tsx',
                        '.css', '.sh', '.bat', '.ps1', '.ini', '.cfg', '.conf',
                        '.log', '.sql', '.rst', '.tex',
                    }
                    file_text = ""
                    if ext in _text_exts:
                        try:
                            file_text = raw_bytes.decode("utf-8", errors="replace").strip()
                        except Exception:
                            pass
                    if not file_text:
                        # Fallback to MarkItDown for office/binary formats
                        try:
                            from markitdown import MarkItDown
                            file_text = (MarkItDown().convert(str(file_path)).text_content or "").strip()
                        except Exception:
                            pass
                    if file_text:
                        structured_content.append({
                            "type": "text",
                            "text": f"[{file_path.name}]:\n{truncate(file_text, TRUNCATE_FILE_CONTEXT_CHARS)}",
                        })
                    else:
                        structured_content.append({
                            "type": "text",
                            "text": f"[File attached: {file_path.name} ({ext}) — binary format, content not extractable]",
                        })
            except Exception as e:
                log.error("Failed to load attachment", error=str(e), file_id=att_id)

        return structured_content if structured_content else content
