# Third-Party Integrations

OpenACM integrates a set of curated MIT-licensed libraries that enhance core capabilities without requiring architectural changes. All are optional — the system falls back gracefully if any are unavailable.

---

## MarkItDown

**Repo:** https://github.com/microsoft/markitdown  
**License:** MIT  
**Install:** `pip install "markitdown[docx,xlsx,pptx,audio-transcription]"`

### What it does

Converts any file format to clean Markdown optimized for LLM consumption. Used in `brain.py` as the universal file handler for attachments.

### Integration point

`src/openacm/core/brain.py` — attachment processing pipeline.

| Format | Without MarkItDown | With MarkItDown |
|---|---|---|
| `.docx` | `[File attached: doc.docx]` | Full document content as Markdown |
| `.xlsx` | `[File attached: sheet.xlsx]` | Tables rendered as Markdown |
| `.pptx` | `[File attached: slides.pptx]` | Slide content as text |
| `.zip` | `[File attached: archive.zip]` | Extracts and converts contents |
| Audio | Falls through to Whisper chain | `speech_recognition` fallback |
| Images (no vision model) | `[Image attached: ...]` | EXIF metadata + OCR text |

### Fallback behavior

If MarkItDown fails or is not installed, the attachment is shown as `[File attached: filename (ext)]`. Nothing breaks.

---

## Chonkie

**Repo:** https://github.com/chonkie-inc/chonkie  
**License:** MIT  
**Install:** `pip install "chonkie[sentence]"`

### What it does

A lightweight RAG chunking library with multiple strategies: token-based, sentence-based, semantic, and neural. Replaces naive paragraph/sentence splitting with linguistically aware chunking that improves retrieval quality in ChromaDB.

### Integration point

`src/openacm/core/rag.py` — `_split_text()` method, used whenever text is ingested into the vector store (conversation memory, notes, document ingestion via `ingest()`).

**Strategy used:** `SentenceChunker` — splits on sentence boundaries, respects semantic units, applies overlap between chunks.

```
chunk_size:    500 characters
chunk_overlap: 50 characters
```

### Why it matters

The naive split cut text at fixed character counts, often splitting mid-sentence and losing context at chunk boundaries. Chonkie ensures each chunk is a complete semantic unit, which directly improves the relevance of RAG-retrieved results.

### Fallback behavior

If chonkie is not installed or fails, `_split_text()` falls back to the original paragraph/sentence splitting logic transparently.

> **Note:** The Code Resurrection watcher (`resurrection_watcher.py`) uses line-based chunking (150 lines, 20-line overlap) and bypasses `_split_text()` entirely via `ingest_raw_chunks()` — chonkie does not affect it.

---

## Docling

**Repo:** https://github.com/DS4SD/docling  
**License:** MIT  
**Author:** IBM Research  
**Install:** `pip install "docling>=2.0"`

### What it does

Layout-aware document parsing for PDFs, Word, PowerPoint, Excel, HTML, and more. Unlike `pypdf` which extracts raw character streams, docling understands document structure: multi-column layouts, tables, headings, figures, and form fields. Output is structured Markdown.

### Integration point

`src/openacm/core/brain.py` — `_extract_pdf_text()` method, called when a `.pdf` attachment is processed.

**Priority chain:**
1. **docling** — layout-aware, handles tables and columns correctly
2. **pypdf** — basic text extraction fallback (always installed)

### Why it matters

`pypdf` on a multi-column PDF or a table-heavy document produces garbled text where columns run together. Docling reproduces the logical reading order and renders tables as Markdown tables the LLM can actually use.

### Fallback behavior

If docling fails (missing dep, corrupted PDF, etc.), `_extract_pdf_text()` falls back to `pypdf` automatically. A debug log entry is emitted.

---

## Instructor

**Repo:** https://github.com/jxnl/instructor  
**License:** MIT  
**Install:** `pip install "instructor>=1.0"`

### What it does

Structured LLM outputs with Pydantic validation and automatic retries. Wraps `litellm` (already used by OpenACM) to return typed Python objects instead of raw strings.

### Integration point

`src/openacm/core/brain.py` — `Brain.structured_extract()` async method.

```python
from pydantic import BaseModel

class Sentiment(BaseModel):
    label: str        # "positive" | "negative" | "neutral"
    score: float      # 0.0 – 1.0

result = await brain.structured_extract(
    text="I really loved this product!",
    schema=Sentiment,
    system="Classify the sentiment of the user message.",
)
# result.label == "positive"
# result.score == 0.95
```

### When to use it

Use `structured_extract()` inside custom tools or skills when you need the LLM to return data in a specific shape — for example, extracting entities from a document, classifying intent, or generating structured metadata.

The method handles:
- Automatic retries (up to 2) when the model returns malformed JSON
- Falls back to `None` if instructor is not installed or the call fails
- Uses the currently active model from `llm_router`

### Fallback behavior

If instructor is not installed, `structured_extract()` logs a warning and returns `None`. Tools that use it should handle `None` gracefully.
