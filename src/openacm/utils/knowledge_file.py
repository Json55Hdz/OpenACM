"""Extract plain text from uploaded knowledge base files."""

import asyncio
import os
import tempfile
from pathlib import Path

import structlog

log = structlog.get_logger()

_TEXT_EXTS = {
    '.txt', '.md', '.csv', '.json', '.yaml', '.yml',
    '.toml', '.xml', '.html', '.htm',
    '.py', '.js', '.ts', '.tsx',
}


def _convert_with_markitdown(data: bytes, suffix: str) -> str:
    from markitdown import MarkItDown
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp_path = f.name
    try:
        return (MarkItDown().convert(tmp_path).text_content or "").strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def extract_text(filename: str, data: bytes) -> str:
    """Return Markdown/plain text extracted from file bytes.

    Plain text extensions are decoded directly. Binary formats
    (PDF, DOCX, XLSX, PPTX, …) are converted via MarkItDown.
    """
    ext = Path(filename).suffix.lower()
    if ext in _TEXT_EXTS:
        return data.decode("utf-8", errors="replace").strip()

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _convert_with_markitdown, data, ext)
    except Exception as exc:
        log.warning("knowledge_file: MarkItDown extraction failed", filename=filename, error=str(exc))
        raise ValueError(f"No se pudo extraer texto del archivo '{filename}': {exc}") from exc
