"""
Code Editor Tools — precise, surgical file editing for programming tasks.

These tools let the LLM edit code without rewriting entire files.
They complement file_ops.py (read_file / write_file) with targeted operations.

Tools:
    edit_file        — Replace an exact string in a file (surgical edit).
                       Fails if old_string not found or is ambiguous (multiple matches).
    read_file_range  — Read lines N to M with visible line numbers.
    grep_in_files    — Search a regex pattern across files, with context lines.
    get_file_outline — AST / regex-based structure overview (classes, functions + line numbers).
    run_linter       — Run ruff (Python) or eslint (JS/TS) and return diagnostics.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from openacm.tools.base import tool


# ── edit_file ──────────────────────────────────────────────────────────────


@tool(
    name="edit_file",
    description=(
        "Surgically edit a file by replacing an EXACT string with new content. "
        "Much safer than rewriting the whole file — only the matched section changes. "
        "Fails with a clear error if old_string is not found or matches multiple places "
        "(in that case, include more surrounding context in old_string to make it unique). "
        "Supports any language. Preserves indentation and line endings."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "The EXACT text to find and replace. Must match character-for-character "
                    "including indentation and whitespace. Include enough surrounding lines "
                    "to make it unique in the file."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "The text to replace old_string with.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
    risk_level="high",
    category="file",
)
async def edit_file(path: str, old_string: str, new_string: str, **kwargs) -> str:
    """Surgical string replacement in a file."""
    try:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return f"Error: File not found: {path}"
        if not file_path.is_file():
            return f"Error: Not a file: {path}"

        content = file_path.read_text(encoding="utf-8", errors="replace")

        count = content.count(old_string)
        if count == 0:
            # Give a helpful hint: show nearby text to help LLM fix its query
            snippet = _find_nearest(content, old_string[:40])
            hint = f"\n\nHint — nearest match found:\n{snippet}" if snippet else ""
            return (
                f"Error: old_string not found in {file_path.name}. "
                f"Check indentation and whitespace.{hint}"
            )
        if count > 1:
            return (
                f"Error: old_string matches {count} places in {file_path.name}. "
                f"Add more surrounding context to old_string to make it unique."
            )

        new_content = content.replace(old_string, new_string, 1)
        file_path.write_text(new_content, encoding="utf-8")

        # Report what changed
        old_lines = old_string.count("\n") + 1
        new_lines = new_string.count("\n") + 1
        return (
            f"Edited {file_path.name}: replaced {old_lines} line(s) with {new_lines} line(s). "
            f"File now has {new_content.count(chr(10)) + 1} lines total."
        )
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error editing file: {e}"


def _find_nearest(content: str, query: str) -> str:
    """Find the closest matching line to give the LLM a hint."""
    query_stripped = query.strip().lower()
    best_line = ""
    best_score = 0
    for i, line in enumerate(content.splitlines(), 1):
        line_lower = line.strip().lower()
        # Simple overlap heuristic
        common = sum(1 for a, b in zip(line_lower, query_stripped) if a == b)
        if common > best_score:
            best_score = common
            best_line = f"  Line {i}: {line.rstrip()}"
    return best_line if best_score > 5 else ""


# ── read_file_range ────────────────────────────────────────────────────────


@tool(
    name="read_file_range",
    description=(
        "Read a specific range of lines from a file, with line numbers shown. "
        "Use this before edit_file to confirm the exact text to pass as old_string. "
        "Also useful for inspecting a function or class without reading the whole file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-indexed)",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (1-indexed, inclusive). Pass -1 for end of file.",
                "default": -1,
            },
        },
        "required": ["path", "start_line"],
    },
    risk_level="low",
    category="file",
)
async def read_file_range(path: str, start_line: int, end_line: int = -1, **kwargs) -> str:
    """Read a range of lines with line numbers."""
    try:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return f"Error: File not found: {path}"

        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total = len(lines)

        start = max(1, start_line) - 1  # convert to 0-indexed
        end = total if end_line == -1 else min(end_line, total)

        if start >= total:
            return f"Error: start_line {start_line} is beyond end of file ({total} lines)"

        selected = lines[start:end]
        numbered = "".join(f"{start + i + 1:5d} | {line}" for i, line in enumerate(selected))
        return f"{file_path} (lines {start + 1}–{start + len(selected)} of {total}):\n{numbered}"
    except Exception as e:
        return f"Error reading file range: {e}"


# ── grep_in_files ──────────────────────────────────────────────────────────


@tool(
    name="grep_in_files",
    description=(
        "Search for a regex pattern inside files in a directory. "
        "Returns matching lines with file path, line number, and surrounding context. "
        "Use this to find where a function is defined, where a variable is used, "
        "or to locate any string across the codebase."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for (Python re syntax)",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
                "default": ".",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py', '*.ts', '*'). Default: '*'",
                "default": "*",
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context to show before and after each match (default: 2)",
                "default": 2,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search (default: true)",
                "default": True,
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matches to return (default: 30)",
                "default": 30,
            },
        },
        "required": ["pattern"],
    },
    risk_level="low",
    category="file",
)
async def grep_in_files(
    pattern: str,
    directory: str = ".",
    file_pattern: str = "*",
    context_lines: int = 2,
    case_sensitive: bool = True,
    max_results: int = 30,
    **kwargs,
) -> str:
    """Search for a pattern across files."""
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        return f"Error: Directory not found: {directory}"

    results = []
    files_searched = 0
    total_matches = 0

    for file_path in sorted(dir_path.rglob(file_pattern)):
        if not file_path.is_file():
            continue
        # Skip binary-ish files and common noise dirs
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", ".venv", "venv")
               for part in file_path.parts):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        files_searched += 1
        lines = text.splitlines()
        matched_lines = [i for i, line in enumerate(lines) if regex.search(line)]

        for lineno in matched_lines:
            if total_matches >= max_results:
                break
            total_matches += 1

            # Context
            ctx_start = max(0, lineno - context_lines)
            ctx_end = min(len(lines), lineno + context_lines + 1)
            block = []
            for i in range(ctx_start, ctx_end):
                prefix = ">>>" if i == lineno else "   "
                block.append(f"  {prefix} {i + 1:5d} | {lines[i]}")

            rel = file_path.relative_to(dir_path)
            results.append(f"{rel}:{lineno + 1}\n" + "\n".join(block))

        if total_matches >= max_results:
            break

    if not results:
        return f"No matches for '{pattern}' in {dir_path} (searched {files_searched} files)"

    header = f"Found {total_matches} match(es) in {files_searched} files:\n\n"
    suffix = f"\n\n[Results limited to {max_results}]" if total_matches >= max_results else ""
    return header + "\n\n".join(results) + suffix


# ── get_file_outline ───────────────────────────────────────────────────────


@tool(
    name="get_file_outline",
    description=(
        "Get a structural outline of a source file: classes, functions, methods "
        "with their line numbers. Supports Python (AST-based, precise) and "
        "JavaScript/TypeScript/other languages (regex-based). "
        "Use this to understand a file's structure before reading or editing it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the source file",
            },
        },
        "required": ["path"],
    },
    risk_level="low",
    category="file",
)
async def get_file_outline(path: str, **kwargs) -> str:
    """Return an outline of classes and functions in a source file."""
    file_path = Path(path).resolve()
    if not file_path.exists():
        return f"Error: File not found: {path}"

    suffix = file_path.suffix.lower()
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    if suffix == ".py":
        return _python_outline(source, file_path.name)
    elif suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        return _js_outline(source, file_path.name)
    else:
        return _generic_outline(source, file_path.name)


def _python_outline(source: str, filename: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"Syntax error in {filename}: {e}"

    lines = source.splitlines()
    items = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            indent = ""
            # Determine if it's a method (parent is a class)
            kind = "class" if isinstance(node, ast.ClassDef) else (
                "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            )
            items.append((node.lineno, kind, node.name, indent))

    # Re-build with proper indentation using the actual source
    # Simpler: just collect top-level and class members separately
    outline_lines = [f"Outline of {filename} ({len(lines)} lines):\n"]
    items.sort(key=lambda x: x[0])

    # Walk top-level to get class hierarchy
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            end = _py_end_line(node, lines)
            outline_lines.append(f"  class {node.name}  (line {node.lineno}–{end})")
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    c_end = _py_end_line(child, lines)
                    prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    outline_lines.append(f"    {prefix} {child.name}()  (line {child.lineno}–{c_end})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = _py_end_line(node, lines)
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            outline_lines.append(f"  {prefix} {node.name}()  (line {node.lineno}–{end})")

    return "\n".join(outline_lines)


def _py_end_line(node: ast.AST, lines: list[str]) -> int:
    """Best-effort last line of an AST node."""
    try:
        return node.end_lineno  # type: ignore[attr-defined]
    except AttributeError:
        return len(lines)


def _js_outline(source: str, filename: str) -> str:
    lines = source.splitlines()
    patterns = [
        # class Foo / class Foo extends Bar
        (re.compile(r"^(?:export\s+(?:default\s+)?)?class\s+(\w+)"), "class"),
        # function foo / async function foo / export function foo
        (re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"), "function"),
        # const/let foo = () => / const foo = function
        (re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\()"), "const fn"),
        # foo() { / async foo() { (methods)
        (re.compile(r"^\s{2,}(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{"), "method"),
    ]

    outline_lines = [f"Outline of {filename} ({len(lines)} lines):\n"]
    for i, line in enumerate(lines, 1):
        for regex, kind in patterns:
            m = regex.match(line)
            if m:
                outline_lines.append(f"  {kind} {m.group(1)}  (line {i})")
                break

    if len(outline_lines) == 1:
        outline_lines.append("  (no top-level declarations found)")
    return "\n".join(outline_lines)


def _generic_outline(source: str, filename: str) -> str:
    """Fallback: show lines that look like definitions."""
    lines = source.splitlines()
    definition_re = re.compile(
        r"^\s*(def |async def |class |function |public |private |protected |fn |func )"
    )
    items = [(i + 1, line.strip()) for i, line in enumerate(lines) if definition_re.match(line)]
    if not items:
        return f"{filename}: no definition-like lines found (unsupported language for outline)"
    result = [f"Outline of {filename} ({len(lines)} lines):\n"]
    result += [f"  line {no:5d}: {text}" for no, text in items[:60]]
    if len(items) > 60:
        result.append(f"  ... ({len(items) - 60} more)")
    return "\n".join(result)


# ── run_linter ─────────────────────────────────────────────────────────────


@tool(
    name="run_linter",
    description=(
        "Run a linter on a source file and return diagnostics. "
        "Python: uses ruff (fast, catches style + bugs). "
        "JavaScript/TypeScript: uses eslint if available, else basic checks. "
        "Returns errors and warnings with line numbers so you can fix them immediately."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to lint",
            },
            "fix": {
                "type": "boolean",
                "description": "Auto-fix safe issues (ruff --fix). Default: false",
                "default": False,
            },
        },
        "required": ["path"],
    },
    risk_level="medium",
    category="file",
)
async def run_linter(path: str, fix: bool = False, **kwargs) -> str:
    """Lint a file and return diagnostics."""
    file_path = Path(path).resolve()
    if not file_path.exists():
        return f"Error: File not found: {path}"

    suffix = file_path.suffix.lower()

    if suffix == ".py":
        return await _lint_python(file_path, fix=fix)
    elif suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
        return await _lint_js(file_path)
    else:
        return f"No linter configured for {suffix} files. Supported: .py, .js, .ts, .jsx, .tsx"


async def _lint_python(file_path: Path, fix: bool) -> str:
    cmd = [sys.executable, "-m", "ruff", "check", str(file_path)]
    if fix:
        cmd.append("--fix")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return f"✅ {file_path.name}: no issues found (ruff)"
        return f"ruff — {file_path.name}:\n{output}"
    except FileNotFoundError:
        # ruff not installed — fall back to ast syntax check
        try:
            source = file_path.read_text(encoding="utf-8")
            ast.parse(source)
            return f"✅ {file_path.name}: syntax OK (ruff not installed, only syntax checked)"
        except SyntaxError as e:
            return f"SyntaxError in {file_path.name}:{e.lineno}: {e.msg}"
    except subprocess.TimeoutExpired:
        return "Error: linter timed out"


async def _lint_js(file_path: Path) -> str:
    # Try eslint
    cmd = ["npx", "eslint", "--no-eslintrc", "--rule", "{}", str(file_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return f"✅ {file_path.name}: no issues found (eslint)"
        return f"eslint — {file_path.name}:\n{output}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Basic syntax check via node
        try:
            result = subprocess.run(
                ["node", "--check", str(file_path)],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return f"✅ {file_path.name}: syntax OK (node --check)"
            return f"Syntax error — {file_path.name}:\n{result.stderr.strip()}"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return f"No linter available for {file_path.suffix}. Install ruff (Python) or eslint (JS/TS)."
