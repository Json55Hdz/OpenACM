"""
Knowledge-base tools — keyword search over Markdown collections in data/knowledge/<collection>/.

Agent knowledge injected into the system prompt is capped (see agent_runner._KNOWLEDGE_CHAR_LIMIT),
so large procedure manuals live on disk and the agent queries them on demand.
Search is exact-keyword (accent/case-insensitive), which suits codes, procedure names and city/plan filters.
"""

import re
import unicodedata
from pathlib import Path

from openacm.tools.base import tool

_MAX_BLOCK_CHARS = 2600
# brain_loop cuts any tool result over 6000 chars in the middle ([N chars omitted]);
# stay under that so the records the model sees are whole and the omitted ones are named.
_OUTPUT_BUDGET_CHARS = 5400
_STOPWORDS = {
    "para", "como", "con", "del", "los", "las", "una", "uno", "que", "por", "sus", "este", "esta",
    "hay", "son", "cual", "cuales", "donde", "cuando", "quiere", "necesito", "puede", "pueden",
    "the", "and", "de", "la", "el", "en", "se", "un", "al", "lo", "es", "si", "no", "y", "o", "a",
}

# (collection, mtime signature) -> list of blocks
_CACHE: dict[str, tuple[tuple, list[dict]]] = {}


def _knowledge_root() -> Path:
    from openacm.security.crypto import get_media_dir

    return get_media_dir().parent.parent.resolve() / "data" / "knowledge"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _norm(text)) if len(t) >= 2 and t not in _STOPWORDS]


def _collection_dir(collection: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", collection or ""):
        return None
    path = _knowledge_root() / collection
    return path if path.is_dir() else None


def available_collections() -> list[str]:
    root = _knowledge_root()
    return sorted(p.name for p in root.glob("*") if p.is_dir()) if root.is_dir() else []


def parse_collections(raw) -> list[str]:
    """The agent's collections as stored (a JSON list) -> list of names."""
    import json

    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def resolve_collection(collection: str, brain) -> tuple[str | None, str | None]:
    """(collection to use, error). An agent only reaches the collections assigned to it."""
    cfg = getattr(brain, "config", None)
    wanted = (collection or "").strip()
    if getattr(cfg, "is_agent", False):
        mine = list(getattr(cfg, "knowledge_collections", None) or [])
        if not mine:
            return None, "Error: this agent has no knowledge collections. The owner can add files for it in the agent's Knowledge tab."
        wanted = wanted or mine[0]
        if wanted not in mine:
            return None, f"Error: '{wanted}' is not one of this agent's knowledge collections. Yours: {', '.join(repr(m) for m in mine)}."
        return wanted, None
    if wanted:
        return wanted, None
    names = available_collections()
    if len(names) == 1:
        return names[0], None
    return ("colsanitas", None) if "colsanitas" in names else (None, _not_found(""))


def _not_found(collection: str) -> str:
    names = available_collections()
    listing = ", ".join(f"'{n}'" for n in names) if names else "none yet"
    return f"Error: knowledge collection '{collection}' not found. Available collections: {listing}. Pass one of them as 'collection'."


def _split_blocks(file: Path) -> list[dict]:
    """Split one Markdown file into searchable blocks (one per '### ' record / '## ' section)."""
    text = file.read_text(encoding="utf-8", errors="replace")
    title = text.split("\n", 1)[0].lstrip("# ").strip()
    blocks: list[dict] = []
    current: list[str] = []
    section = ""

    def flush():
        body = "\n".join(current).strip()
        if body:
            blocks.append({"file": file.name, "title": title, "section": section, "text": body})

    for line in text.splitlines():
        if line.startswith("### ") or line.startswith("## "):
            flush()
            current = [line]
            section = line.lstrip("# ").strip()
        else:
            current.append(line)
            # flat files (no '###'): cut long runs of bullets into ~1500 char blocks
            if not section.startswith(("Registros",)) and sum(len(x) for x in current) > 1500 and line.startswith("- "):
                flush()
                current = []
    flush()
    for b in blocks:
        b["norm"] = _norm(b["text"])
        b["head"] = _norm(f"{b['title']} {b['section']}")
    return blocks


def _load(collection: str) -> list[dict] | None:
    base = _collection_dir(collection)
    if base is None:
        return None
    files = sorted(base.glob("*.md"))
    sig = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    cached = _CACHE.get(collection)
    if cached and cached[0] == sig:
        return cached[1]
    blocks: list[dict] = []
    for f in files:
        blocks.extend(_split_blocks(f))
    _CACHE[collection] = (sig, blocks)
    return blocks


def _search(blocks: list[dict], query: str, filtro: str, max_results: int) -> list[dict]:
    q_tokens = list(dict.fromkeys(_tokens(query)))
    f_tokens = list(dict.fromkeys(_tokens(filtro)))
    if not q_tokens:
        return []
    scored: list[tuple[float, dict]] = []
    for b in blocks:
        if f_tokens and not all(t in b["head"] or t in b["norm"][:400] for t in f_tokens):
            continue
        hit = 0
        score = 0.0
        for t in q_tokens:
            n = b["norm"].count(t)
            if n:
                hit += 1
                score += 1.0 + min(n, 5) * 0.2
                if t in b["head"]:
                    score += 1.5
        if hit == 0:
            continue
        # reward covering more of the query; prefer shorter (more specific) blocks
        score *= (hit / len(q_tokens)) ** 2
        score /= 1 + len(b["text"]) / 6000
        scored.append((score, b))
    scored.sort(key=lambda x: -x[0])
    return [dict(b, score=s) for s, b in scored[:max_results]]


@tool(
    name="search_knowledge",
    description=(
        "Search a Markdown knowledge collection (e.g. 'colsanitas') by keywords. Returns the best-matching "
        "records with their full text (procedure, codes, voucher/'volante' rules, observations, branch info). "
        "Use short, specific keywords (procedure name, CUPS/Bukeala code, clinic) and the optional 'filtro' "
        "to restrict by city/plan/type (e.g. 'Cali EPS'). If nothing is found, retry with fewer or different words."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords to look for, e.g. 'ecografia abdomen total' or '881202'."},
            "filtro": {
                "type": "string",
                "description": "Optional words that must appear in the record's context, e.g. 'Bogota EPS' or 'Ibague MP'.",
                "default": "",
            },
            "collection": {"type": "string", "description": "Knowledge collection to search. Leave empty to use your own (agents only reach the collections assigned to them).", "default": ""},
            "max_results": {"type": "integer", "description": "Max records to return (default 6, max 12).", "default": 6},
        },
        "required": ["query"],
    },
    risk_level="low",
    category="ai",
)
async def search_knowledge(query: str, filtro: str = "", collection: str = "", max_results: int = 6, **kwargs) -> str:
    collection, err = resolve_collection(collection, kwargs.get("_brain"))
    if err:
        return err
    blocks = _load(collection)
    if blocks is None:
        return _not_found(collection)
    max_results = max(1, min(int(max_results or 6), 12))
    results = _search(blocks, query, filtro, max_results)
    if not results:
        hint = " Try without 'filtro' or with fewer keywords." if filtro else " Try fewer or different keywords."
        return f"No results for '{query}'.{hint}"
    header = f"Found {len(results)} record(s) for '{query}'" + (f" [filtro: {filtro}]" if filtro else "") + ":\n"
    out = [header]
    used = len(header)
    shown = 0
    for i, r in enumerate(results, 1):
        text = r["text"]
        if len(text) > _MAX_BLOCK_CHARS:
            text = text[:_MAX_BLOCK_CHARS] + f"\n[... truncated; use read_knowledge_file('{r['file']}') for more]"
        block = f"--- [{i}] {r['file']} ({r['title']}) ---\n{text}\n"
        if used + len(block) > _OUTPUT_BUDGET_CHARS:
            room = _OUTPUT_BUDGET_CHARS - used - 400  # keep room for the 'not shown' list
            if shown == 0 and room > 500:  # never return nothing: cut the best record to fit
                block = block[:room] + "\n[... record cut to fit; narrow the search]\n"
                out.append(block)
                shown += 1
            break
        out.append(block)
        used += len(block)
        shown += 1
    rest = results[shown:]
    if rest:
        out.append(
            f"[{len(rest)} lower-ranked match(es) not shown. If the record you need is not above, search again with "
            "a more specific query or 'filtro'; do not mention this to the user.]"
        )
        for r in rest[:8]:
            out.append("- " + r["text"].split("\n", 1)[0][:110])
    return "\n".join(out)


@tool(
    name="read_knowledge_file",
    description=(
        "Read a knowledge file (by exact file name from the knowledge index) in pages of ~6000 characters. "
        "Use it when search_knowledge points to a file and you need the surrounding context, or for small reference sheets."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "File name, e.g. '39-preguntas-frecuentes.md'."},
            "offset": {"type": "integer", "description": "Character offset to start from (default 0).", "default": 0},
            "collection": {"type": "string", "description": "Knowledge collection of the file. Leave empty to use your own.", "default": ""},
        },
        "required": ["file"],
    },
    risk_level="low",
    category="ai",
)
async def read_knowledge_file(file: str, offset: int = 0, collection: str = "", **kwargs) -> str:
    collection, err = resolve_collection(collection, kwargs.get("_brain"))
    if err:
        return err
    base = _collection_dir(collection)
    if base is None:
        return _not_found(collection)
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]+\.md", file or ""):
        return "Error: invalid file name."
    path = (base / file).resolve()
    if path.parent != base.resolve() or not path.is_file():
        return f"Error: file '{file}' not found in collection '{collection}'."
    text = path.read_text(encoding="utf-8", errors="replace")
    offset = max(0, int(offset or 0))
    page = text[offset : offset + 6000]
    end = offset + len(page)
    footer = f"\n\n[... {len(text) - end} more characters; call again with offset={end}]" if end < len(text) else "\n\n[end of file]"
    return page + footer
