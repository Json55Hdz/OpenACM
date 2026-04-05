"""
Output Compressor — reduces token consumption from tool results.

Applies smart, context-aware compression to tool outputs before they
enter the LLM context window. Unlike naive truncation, this preserves
semantically critical content (errors, results, summaries) while
aggressively stripping noise (verbose progress lines, redundant headers,
repeated whitespace, decorative separators, etc.).

Typical savings: 40-80% depending on tool type.
"""

from __future__ import annotations

import json
import re


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compress(result: str, tool_name: str = "", tool_args: dict | None = None) -> tuple[str, int, int]:
    """
    Compress a tool result string.

    Args:
        result:    Raw tool output string.
        tool_name: Name of the tool that produced the output.
        tool_args: Original arguments passed to the tool (used for command-aware compression).

    Returns:
        (compressed_text, original_chars, compressed_chars)
    """
    original = len(result)

    # Pick the right compressor based on tool name
    if tool_name in ("run_command", "run_python"):
        command = (tool_args or {}).get("command", "")
        compressed = _compress_command(result, command=command)
    elif tool_name in ("read_file", "write_file", "file_ops"):
        path = (tool_args or {}).get("path", "")
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        compressed = _compress_file(result, ext=ext, path=path)
    elif tool_name == "web_search":
        compressed = _compress_web_search(result)
    elif tool_name == "system_info":
        compressed = _compress_system_info(result)
    else:
        compressed = _compress_generic(result)

    compressed = _shared_cleanup(compressed)
    return compressed, original, len(compressed)


# ---------------------------------------------------------------------------
# Per-tool compressors
# ---------------------------------------------------------------------------

# Commands that produce recursive directory listings on any OS
_DIR_LISTING_COMMANDS = re.compile(
    r"^\s*("
    # Windows
    r"dir\s+.*(/s|/a)"          # dir /s, dir /a/s, dir /s/b ...
    r"|dir\s*/[saSA]"           # dir /S (flag before path)
    # Unix/Mac — recursive or large listing flags
    r"|ls\s+.*-[lRar]*R"        # ls -R, ls -lR, ls -laR, ls -Ra ...
    r"|ls\s+-[lRar]*R"
    r"|find\b"                  # find . -type f  (always potentially huge)
    r"|tree\b"                  # tree (Windows + Unix)
    r")",
    re.IGNORECASE,
)

# ---- Windows dir /s patterns ------------------------------------------------
# Entry lines: "04/05/2026  10:30 AM    <DIR>  name" or "... 1,234 file.txt"
_WIN_DIR_ENTRY = re.compile(
    r"^\s*\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+(?:AM|PM)\s+",
    re.IGNORECASE,
)
# "Directory of C:\..."
_WIN_DIR_HEADER = re.compile(r"^\s*Directory of\s+", re.IGNORECASE)
# Summary lines at end of dir /s
_WIN_DIR_SUMMARY = re.compile(
    r"(Total Files Listed|File\(s\)|Dir\(s\)|bytes free)",
    re.IGNORECASE,
)

# ---- Unix ls -R patterns ----------------------------------------------------
# ls -R section header: "./path/to/dir:" (line ends with colon, starts with . or /)
_UNIX_LS_HEADER = re.compile(r"^(\.[\w./\-_ ]*|/[\w./\-_ ]*):\s*$")

# ---- Unix find output -------------------------------------------------------
# Lines that are just a path (find . output): start with ./ or /
_UNIX_FIND_LINE = re.compile(r"^\s*(\.{1,2}/|/)\S")

# ---- tree output (both Windows and Unix) ------------------------------------
# Lines with tree drawing chars or indented entries
_TREE_ENTRY = re.compile(r"^[│├└─\s]+\S")
# tree summary at the end: "N directories, M files"
_TREE_SUMMARY = re.compile(r"\d+\s+director(y|ies).*\d+\s+file", re.IGNORECASE)


def _compress_command(text: str, command: str = "") -> str:
    """
    Compress shell/command output.

    Strategy:
    - Detect recursive directory listings (dir /s, ls -R, tree, find .) and
      summarize them aggressively — keep only unique top-level dirs + final stats.
    - Always keep lines with errors, warnings, exceptions, or results.
    - Strip progress bars, download indicators, verbose pip/npm output.
    - Collapse repeated blank lines.
    - Deduplicate consecutive identical lines (e.g. spinner frames).
    """
    # --- Recursive directory listing: summarize instead of dump ---
    is_dir_listing = bool(command and _DIR_LISTING_COMMANDS.match(command))

    # Also auto-detect from content when command is not passed or not flagged
    if not is_dir_listing and len(text) > 1000:
        sample = text.splitlines()[:30]
        win_entries  = sum(1 for l in sample if _WIN_DIR_ENTRY.match(l))
        win_headers  = sum(1 for l in sample if _WIN_DIR_HEADER.match(l))
        unix_headers = sum(1 for l in sample if _UNIX_LS_HEADER.match(l))
        find_lines   = sum(1 for l in sample if _UNIX_FIND_LINE.match(l))
        tree_lines   = sum(1 for l in sample if _TREE_ENTRY.match(l))
        if win_entries > 5 or win_headers > 1 or unix_headers > 2 or find_lines > 10 or tree_lines > 8:
            is_dir_listing = True

    if is_dir_listing:
        return _summarize_dir_listing(text, command)

    # --- Normal command output ---
    lines = text.splitlines()
    kept: list[str] = []
    prev = None

    # Patterns that are ALWAYS dropped (noise)
    _DROP = re.compile(
        r"("
        r"Downloading\s+\S+.*\d+%"          # pip download progress
        r"|Collecting\s+\S+"                 # pip collecting
        r"|Obtaining\s+\S+"                  # pip obtaining
        r"|Using cached\s+\S+"              # pip cache hit
        r"|\[=+>?\s*\]"                     # progress bars [====>  ]
        r"|\d+%\|[█▉▊▋▌▍▎▏ ]+\|"           # tqdm bars
        r"|^\s*\|\s*\|"                     # empty table rows
        r"|^-{10,}$"                        # long separator lines
        r"|^={10,}$"
        r"|^#{10,}$"
        r")",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.rstrip()

        # Drop explicit noise
        if _DROP.search(stripped):
            continue

        # Deduplicate consecutive identical lines
        if stripped == prev:
            continue

        kept.append(stripped)
        prev = stripped

    result = "\n".join(kept)

    # Collapse 3+ blank lines into 2
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def _summarize_dir_listing(text: str, command: str = "") -> str:
    """
    Summarize a recursive directory listing into a compact representation.
    Detects and handles three formats:
      - Windows: dir /s  (date/time entries, "Directory of" headers)
      - Unix/Mac: ls -R  (path: headers, space-separated entries)
      - Unix/Mac: find   (one path per line)
      - All: tree        (box-drawing chars, "N directories, M files" summary)
    """
    lines = text.splitlines()
    _ERROR = re.compile(r"(error|access denied|cannot|permission denied|no such)", re.IGNORECASE)

    # Detect format from a sample of the output
    sample = lines[:40]
    scores = {
        "windows": sum(1 for l in sample if _WIN_DIR_ENTRY.match(l) or _WIN_DIR_HEADER.match(l)),
        "unix_ls": sum(1 for l in sample if _UNIX_LS_HEADER.match(l.strip())),
        "find":    sum(1 for l in sample if _UNIX_FIND_LINE.match(l)),
        "tree":    sum(1 for l in sample if _TREE_ENTRY.match(l)),
    }
    if command:
        cmd = command.lower()
        if cmd.startswith("dir"):
            scores["windows"] += 10
        elif "find" in cmd:
            scores["find"] += 10
        elif "tree" in cmd:
            scores["tree"] += 10
        elif cmd.startswith("ls"):
            scores["unix_ls"] += 10

    fmt = max(scores, key=scores.__getitem__)

    if fmt == "windows":
        return _summarize_windows_dir(lines, command, _ERROR)
    elif fmt == "unix_ls":
        return _summarize_unix_ls(lines, command, _ERROR)
    elif fmt == "find":
        return _summarize_find(lines, command, _ERROR)
    else:
        return _summarize_tree(lines, command, _ERROR)


def _summarize_windows_dir(lines: list[str], command: str, error_re) -> str:
    """Windows dir /s — 'Directory of C:\\path' headers + date/time entries."""
    dirs_seen: list[str] = []
    seen_set: set[str] = set()
    summary_lines: list[str] = []
    error_lines: list[str] = []
    file_count = dir_count = 0

    for line in lines:
        s = line.strip()
        if _WIN_DIR_HEADER.match(s):
            path = re.sub(r"(?i)^directory of\s+", "", s).strip()
            if path and path not in seen_set:
                seen_set.add(path)
                dirs_seen.append(path)
        elif _WIN_DIR_SUMMARY.search(s):
            summary_lines.append(s)
        elif _WIN_DIR_ENTRY.match(s):
            if "<DIR>" in s:
                dir_count += 1
            else:
                file_count += 1
        elif error_re.search(s):
            error_lines.append(s)

    return _build_listing_summary(command, dirs_seen, file_count, dir_count, summary_lines, error_lines, lines)


def _summarize_unix_ls(lines: list[str], command: str, error_re) -> str:
    """Unix/Mac ls -R — './path/to/dir:' section headers."""
    dirs_seen: list[str] = []
    seen_set: set[str] = set()
    error_lines: list[str] = []
    file_count = dir_count = 0

    for line in lines:
        s = line.strip()
        if _UNIX_LS_HEADER.match(s):
            path = s.rstrip(":")
            dir_count += 1
            if path not in seen_set:
                seen_set.add(path)
                dirs_seen.append(path)
        elif s and not _UNIX_LS_HEADER.match(s):
            for entry in s.split():
                if entry.endswith("/"):
                    dir_count += 1
                elif entry and not entry.startswith("."):
                    file_count += 1
        if error_re.search(s):
            error_lines.append(s)

    return _build_listing_summary(command, dirs_seen, file_count, dir_count, [], error_lines, lines)


def _summarize_find(lines: list[str], command: str, error_re) -> str:
    """Unix/Mac find — one path per line."""
    dirs_seen: list[str] = []
    seen_dirs: set[str] = set()
    error_lines: list[str] = []
    file_count = dir_count = 0

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if error_re.search(s):
            error_lines.append(s)
            continue
        sep = "/" if "/" in s else "\\"
        if s.endswith("/") or s.endswith("\\"):
            dir_count += 1
        else:
            file_count += 1
        parent = s.rsplit(sep, 1)[0] if sep in s else s
        if parent and parent not in seen_dirs:
            seen_dirs.add(parent)
            dirs_seen.append(parent)

    return _build_listing_summary(command, dirs_seen, file_count, dir_count, [], error_lines, lines)


def _summarize_tree(lines: list[str], command: str, error_re) -> str:
    """tree output — box-drawing chars, ends with 'N directories, M files'."""
    dirs_seen: list[str] = []
    seen_set: set[str] = set()
    summary_lines: list[str] = []
    error_lines: list[str] = []
    file_count = dir_count = 0

    for line in lines:
        s = line.strip()
        if _TREE_SUMMARY.search(s):
            summary_lines.append(s)
            m = re.search(r"(\d[\d,]*)\s+director", s, re.IGNORECASE)
            if m:
                dir_count = int(m.group(1).replace(",", ""))
            m = re.search(r"(\d[\d,]*)\s+file", s, re.IGNORECASE)
            if m:
                file_count = int(m.group(1).replace(",", ""))
        elif error_re.search(s):
            error_lines.append(s)
        else:
            name = re.sub(r"^[│├└─\s]+", "", s)
            # Directory heuristic: no extension or trailing slash
            if name and (name.endswith("/") or name.endswith("\\") or ("." not in name and len(name) > 1)):
                if name not in seen_set:
                    seen_set.add(name)
                    dirs_seen.append(name)

    return _build_listing_summary(command, dirs_seen, file_count, dir_count, summary_lines, error_lines, lines)


def _build_listing_summary(
    command: str,
    dirs_seen: list[str],
    file_count: int,
    dir_count: int,
    summary_lines: list[str],
    error_lines: list[str],
    original_lines: list[str],
) -> str:
    parts: list[str] = []
    if command:
        parts.append(f"Command: {command}")
    if dirs_seen:
        shown = dirs_seen[:10]
        parts.append(f"Directories ({len(dirs_seen)} found):")
        parts.extend(f"  {d}" for d in shown)
        if len(dirs_seen) > 10:
            parts.append(f"  ... and {len(dirs_seen) - 10} more")
    if file_count or dir_count:
        parts.append(f"Total: {file_count} files, {dir_count} directories")
    if summary_lines:
        parts.extend(summary_lines)
    if error_lines:
        parts.append("Errors:")
        parts.extend(f"  {e}" for e in error_lines[:10])
    if not parts:
        preview = "\n".join(original_lines[:20])
        return f"[Directory listing — {len(original_lines)} lines. Preview:]\n{preview}"
    return "\n".join(parts)


_LOCK_FILES = re.compile(
    r"(uv\.lock|package-lock\.json|yarn\.lock|Pipfile\.lock|poetry\.lock|composer\.lock|Gemfile\.lock)",
    re.IGNORECASE,
)


def _compress_file(text: str, ext: str = "", path: str = "") -> str:
    """Smart file compression dispatched by extension."""
    # Lock files are auto-generated noise — summarize package list only
    if _LOCK_FILES.search(path):
        return _compress_lock_file(text, path)

    dispatch = {
        "py":   _compress_code,
        "js":   _compress_code,
        "ts":   _compress_code,
        "jsx":  _compress_code,
        "tsx":  _compress_code,
        "log":  _compress_log,
        "csv":  _compress_csv,
        "json": _compress_json,
        "yaml": _compress_yaml,
        "yml":  _compress_yaml,
    }
    fn = dispatch.get(ext)
    if fn:
        return fn(text)

    # Generic: strip decorative separators + collapse blanks
    lines = text.splitlines()
    kept = [l for l in lines if not re.match(r"^[-=*]{8,}$", l.strip())]
    result = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", result)


# ---------------------------------------------------------------------------
# File type compressors
# ---------------------------------------------------------------------------

def _compress_code(text: str) -> str:
    """
    Compress source code files (Python, JS, TS).

    Keeps: imports, class/function/const definitions, decorators, inline comments.
    Strips: multi-line docstrings/block comments (replaced with one-liner),
            pure decorative comment lines (# ----), consecutive blank lines.
    """
    lines = text.splitlines()
    result: list[str] = []
    in_docstring = False
    docstring_char = None
    docstring_lines = 0

    for line in lines:
        stripped = line.strip()

        # Detect start/end of triple-quoted docstrings
        if not in_docstring:
            for q in ('"""', "'''"):
                if stripped.startswith(q):
                    # Single-line docstring — keep as-is
                    if stripped.count(q) >= 2 and len(stripped) > 6:
                        result.append(line)
                        break
                    # Multi-line start
                    in_docstring = True
                    docstring_char = q
                    docstring_lines = 1
                    result.append(line)  # keep opening line
                    break
            else:
                # Drop pure decorative comment lines
                if re.match(r"^\s*#\s*[-=*#]{6,}\s*$", line):
                    continue
                # Collapse 3+ blank lines to 1
                if stripped == "" and result and result[-1].strip() == "":
                    continue
                result.append(line)
        else:
            docstring_lines += 1
            if docstring_char and docstring_char in stripped:
                # Closing line
                in_docstring = False
                if docstring_lines > 4:
                    # Replace body with placeholder, keep closing
                    result.append(line.split(docstring_char)[0] + docstring_char)
                else:
                    result.append(line)
            elif docstring_lines <= 2:
                result.append(line)  # keep first content line of short docstrings
            # else: skip — long docstring body

    return "\n".join(result)


def _compress_log(text: str) -> str:
    """
    Compress log files.

    Always keeps: ERROR, CRITICAL, WARNING lines.
    Keeps first 5 + last 5 INFO lines.
    Drops DEBUG entirely.
    Adds summary counts.
    """
    lines = text.splitlines()

    _ERROR   = re.compile(r"\b(ERROR|CRITICAL|EXCEPTION|FATAL)\b", re.IGNORECASE)
    _WARNING = re.compile(r"\bWARN(ING)?\b", re.IGNORECASE)
    _INFO    = re.compile(r"\bINFO\b", re.IGNORECASE)
    _DEBUG   = re.compile(r"\bDEBUG\b", re.IGNORECASE)

    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []
    debug_count = 0
    other: list[str] = []

    for line in lines:
        if _ERROR.search(line):
            errors.append(line)
        elif _WARNING.search(line):
            warnings.append(line)
        elif _DEBUG.search(line):
            debug_count += 1
        elif _INFO.search(line):
            infos.append(line)
        else:
            other.append(line)

    parts: list[str] = []

    if errors:
        parts.append(f"=== ERRORS ({len(errors)}) ===")
        parts.extend(errors)

    if warnings:
        parts.append(f"=== WARNINGS ({len(warnings)}) ===")
        parts.extend(warnings[:20])
        if len(warnings) > 20:
            parts.append(f"  ... and {len(warnings) - 20} more warnings")

    if infos:
        shown = infos[:5] + (["  ..."] if len(infos) > 10 else []) + infos[-5:]
        parts.append(f"=== INFO (showing {len(shown)} of {len(infos)}) ===")
        parts.extend(shown)

    if other:
        parts.extend(other[:10])

    if debug_count:
        parts.append(f"[{debug_count} DEBUG lines omitted]")

    return "\n".join(parts) if parts else text


def _compress_csv(text: str) -> str:
    """
    Compress CSV files: keep header + first 15 rows + summary.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return text

    total = len(lines)
    if total <= 20:
        return text

    header = lines[0]
    preview = lines[1:16]
    col_count = len(header.split(","))

    result = [
        f"[CSV — {total - 1} rows, ~{col_count} columns]",
        header,
    ]
    result.extend(preview)
    result.append(f"... [{total - 16} more rows omitted]")
    return "\n".join(result)


def _compress_json(text: str) -> str:
    """
    Compress JSON: pretty-print with depth limit, truncate long string values.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return _compress_generic(text)

    def _truncate(obj, depth=0):
        if depth > 3:
            if isinstance(obj, dict):
                return f"{{...{len(obj)} keys}}"
            if isinstance(obj, list):
                return f"[...{len(obj)} items]"
        if isinstance(obj, dict):
            return {k: _truncate(v, depth + 1) for k, v in list(obj.items())[:20]}
        if isinstance(obj, list):
            inner = [_truncate(i, depth + 1) for i in obj[:10]]
            if len(obj) > 10:
                inner.append(f"...{len(obj) - 10} more")
            return inner
        if isinstance(obj, str) and len(obj) > 200:
            return obj[:197] + "..."
        return obj

    try:
        compact = json.dumps(_truncate(data), indent=2, ensure_ascii=False)
        return compact
    except Exception:
        return _compress_generic(text)


def _compress_yaml(text: str) -> str:
    """
    Compress YAML: truncate long string values, collapse repeated structures.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        # Truncate long inline values (key: "very long string...")
        if re.match(r"^\s*\w.*:\s+\S{100,}", line):
            line = line[:120] + "..."
        # Skip decorative separators
        if re.match(r"^#\s*[-=]{6,}", line):
            continue
        kept.append(line)
    result = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", result)


def _compress_lock_file(text: str, path: str = "") -> str:
    """
    Lock files (uv.lock, package-lock.json, yarn.lock, etc.) are auto-generated.
    Return only a package count + top-level names instead of the full content.
    """
    fname = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    # uv.lock / Pipfile.lock / poetry.lock — TOML-like, packages start with [[package]] or [package.*]
    pkg_names: list[str] = []

    if fname in ("uv.lock", "poetry.lock", "Pipfile.lock"):
        for line in text.splitlines():
            m = re.match(r'^name\s*=\s*"([^"]+)"', line.strip())
            if m:
                pkg_names.append(m.group(1))

    elif "package-lock" in fname or "yarn.lock" in fname:
        try:
            data = json.loads(text)
            pkgs = data.get("packages", data.get("dependencies", {}))
            pkg_names = [k.lstrip("node_modules/") for k in pkgs if k][:100]
        except Exception:
            # yarn.lock is not JSON — extract package names from headers
            for line in text.splitlines():
                m = re.match(r'^"?(@?[\w/.-]+)@', line)
                if m:
                    name = m.group(1)
                    if name not in pkg_names:
                        pkg_names.append(name)

    if pkg_names:
        sample = ", ".join(pkg_names[:30])
        suffix = f" (showing 30 of {len(pkg_names)})" if len(pkg_names) > 30 else ""
        return (
            f"[{fname} — {len(pkg_names)} packages{suffix}]\n"
            f"Packages: {sample}\n"
            f"[Full lock file omitted — auto-generated, not useful for analysis]"
        )

    # Fallback — just show size
    line_count = text.count("\n")
    return (
        f"[{fname} — {line_count:,} lines, auto-generated lock file]\n"
        f"[Content omitted — use a package manager command to inspect dependencies]"
    )


def _compress_web_search(text: str) -> str:
    """
    Compress web search results.

    Web results tend to be repetitive (URL + title + snippet × N).
    Keep all results but strip decorative separators and excess whitespace.
    """
    # Try to parse JSON results and re-emit as compact text
    try:
        data = json.loads(text)
        if isinstance(data, list):
            parts: list[str] = []
            for i, item in enumerate(data, 1):
                title = item.get("title", "")
                url = item.get("url", item.get("href", ""))
                snippet = item.get("snippet", item.get("body", item.get("content", "")))
                # Trim long snippets
                if len(snippet) > 300:
                    snippet = snippet[:297] + "..."
                parts.append(f"[{i}] {title}\n{url}\n{snippet}")
            return "\n\n".join(parts)
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: generic cleanup
    return _compress_generic(text)


def _compress_system_info(text: str) -> str:
    """
    Compress system_info output.

    System info tends to dump every property. Keep only the non-trivial lines.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Drop lines that are just "key: " with no value
        if re.match(r"^\w[\w\s]*:\s*$", stripped):
            continue
        kept.append(line.rstrip())
    result = "\n".join(kept)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def _compress_generic(text: str) -> str:
    """
    Generic compressor — safe for any output type.

    Conservative: only removes clearly redundant content.
    """
    # Collapse long separator lines
    text = re.sub(r"[-=*#]{10,}", "---", text)
    # Collapse 3+ blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing whitespace per line
    lines = [l.rstrip() for l in text.splitlines()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared post-processing
# ---------------------------------------------------------------------------

def _shared_cleanup(text: str) -> str:
    """Final cleanup applied to all compressors."""
    # Strip leading/trailing blank lines
    text = text.strip()
    # Collapse multiple spaces on a line (but not intentional indentation)
    text = re.sub(r"(?<=\S)  +", " ", text)
    return text


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def compression_summary(original: int, compressed: int) -> str:
    """Human-readable compression summary for logging."""
    if original == 0:
        return "0→0 chars (0%)"
    saved = original - compressed
    pct = saved / original * 100
    return f"{original:,}->{compressed:,} chars ({pct:.0f}% saved)"
