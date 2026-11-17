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


def slug_filename(filename: str) -> str:
    """A safe Markdown file name for a knowledge collection: 'Tarifas 2026 (v2).PDF' -> 'tarifas-2026-v2.md'."""
    import re
    import unicodedata

    stem = Path(filename or "").stem
    stem = "".join(c for c in unicodedata.normalize("NFD", stem.lower()) if unicodedata.category(c) != "Mn")
    stem = re.sub(r"[^a-z0-9_]+", "-", stem).strip("-_")[:80] or "documento"
    return f"{stem}.md"


def as_searchable_markdown(title: str, text: str, chunk_chars: int = 1500) -> str:
    """Give converted text a title and '## ' sections, which is what the search splits blocks on.

    A PDF or Word file usually comes out without headings; left as is it would be ONE huge block.
    Text that already has '## ' headings is kept as it is.
    """
    text = text.strip()
    head = text if text.startswith("#") else f"# {title}\n\n{text}"
    if "\n## " in head or head.startswith("## "):
        return head + "\n"
    first, _, body = head.partition("\n")
    parts: list[str] = []
    cur = ""
    for para in body.split("\n\n"):
        if cur and len(cur) + len(para) > chunk_chars:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    sections = [f"## Parte {i}\n\n{p}" for i, p in enumerate(parts, 1)]
    return first + "\n\n" + "\n\n".join(sections) + "\n"


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
