"""
File Operations Tools — read, write, list, and search files.
"""

import os
from pathlib import Path

from openacm.tools.base import tool


@tool(
    name="read_file",
    description=(
        "Read the contents of a file. Returns the text content of the file. "
        "Use this to inspect files on the system."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum number of lines to read (default: 200)",
                "default": 200,
            },
        },
        "required": ["path"],
    },
    risk_level="medium",
)
async def read_file(path: str, max_lines: int = 200, **kwargs) -> str:
    """Read file contents."""
    try:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return f"Error: File not found: {path}"
        if not file_path.is_file():
            return f"Error: Not a file: {path}"
        
        # Check file size (max 1MB)
        size = file_path.stat().st_size
        if size > 1_000_000:
            return f"Error: File too large ({size:,} bytes). Maximum is 1MB."
        
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        if total_lines > max_lines:
            content = "".join(lines[:max_lines])
            return f"{content}\n\n[... truncated: showing {max_lines} of {total_lines} lines]"
        
        return "".join(lines)
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool(
    name="write_file",
    description=(
        "Write content to a file. Creates the file if it doesn't exist, "
        "or overwrites it if it does. Parent directories are created automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file",
            },
            "append": {
                "type": "boolean",
                "description": "If true, append instead of overwrite (default: false)",
                "default": False,
            },
        },
        "required": ["path", "content"],
    },
    risk_level="high",
)
async def write_file(path: str, content: str, append: bool = False, **kwargs) -> str:
    """Write content to a file."""
    try:
        file_path = Path(path).resolve()
        
        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        mode = "a" if append else "w"
        with open(file_path, mode, encoding="utf-8") as f:
            f.write(content)
        
        action = "Appended to" if append else "Wrote"
        return f"{action} {file_path} ({len(content)} characters)"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


@tool(
    name="list_directory",
    description=(
        "List files and directories in a given directory path. "
        "Shows file names, sizes, and types."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the directory to list (default: current directory)",
                "default": ".",
            },
            "show_hidden": {
                "type": "boolean",
                "description": "Show hidden files/directories (default: false)",
                "default": False,
            },
        },
        "required": [],
    },
    risk_level="low",
)
async def list_directory(path: str = ".", show_hidden: bool = False, **kwargs) -> str:
    """List directory contents."""
    try:
        dir_path = Path(path).resolve()
        if not dir_path.exists():
            return f"Error: Directory not found: {path}"
        if not dir_path.is_dir():
            return f"Error: Not a directory: {path}"
        
        entries = []
        for entry in sorted(dir_path.iterdir()):
            name = entry.name
            if not show_hidden and name.startswith("."):
                continue
            
            if entry.is_dir():
                entries.append(f"  📁 {name}/")
            else:
                size = entry.stat().st_size
                size_str = _format_size(size)
                entries.append(f"  📄 {name} ({size_str})")
        
        if not entries:
            return f"Directory is empty: {dir_path}"
        
        header = f"📂 {dir_path}\n"
        return header + "\n".join(entries)
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error listing directory: {str(e)}"


@tool(
    name="search_files",
    description=(
        "Search for files by name pattern in a directory tree. "
        "Returns matching file paths."
    ),
    parameters={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to search in",
            },
            "pattern": {
                "type": "string",
                "description": "File name pattern to search for (e.g., '*.py', '*.log', 'config*')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: 50)",
                "default": 50,
            },
        },
        "required": ["directory", "pattern"],
    },
    risk_level="low",
)
async def search_files(
    directory: str, pattern: str, max_results: int = 50, **kwargs
) -> str:
    """Search for files matching a pattern."""
    try:
        dir_path = Path(directory).resolve()
        if not dir_path.exists():
            return f"Error: Directory not found: {directory}"
        
        matches = []
        for match in dir_path.rglob(pattern):
            matches.append(str(match))
            if len(matches) >= max_results:
                break
        
        if not matches:
            return f"No files matching '{pattern}' found in {directory}"
        
        result = f"Found {len(matches)} files matching '{pattern}':\n"
        result += "\n".join(f"  {m}" for m in matches)
        if len(matches) >= max_results:
            result += f"\n  [... results limited to {max_results}]"
        return result
    except Exception as e:
        return f"Error searching files: {str(e)}"


@tool(
    name="send_file_to_chat",
    description=(
        "Upload a local file so the user can download it from the chat. "
        "Use this whenever you generate a file for the user (like an Excel, PDF, Word doc, CSV, ZIP, etc.) "
        "and need to give it to them. It will encrypt the file and return a secure link."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file you want to send",
            },
        },
        "required": ["path"],
    },
    risk_level="low",
)
async def send_file_to_chat(path: str, **kwargs) -> str:
    """Send a local file to the secure media storage and get a link."""
    try:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return f"Error: File not found: {path}"
        if not file_path.is_file():
            return f"Error: Not a file: {path}"
            
        import secrets
        from openacm.security.crypto import save_encrypted
        
        file_bytes = file_path.read_bytes()
        ext = "".join(file_path.suffixes)
        if not ext:
            ext = ".bin"
            
        file_id = secrets.token_hex(16)
        file_name = f"upload_{file_id}{ext}"
        dest_path = Path("data/media") / file_name
        
        save_encrypted(file_bytes, dest_path)
        
        return (
            f"✅ File successfully prepared for download! You MUST include this exact URL "
            f"in your message so the user can download it: /api/media/{file_name}"
        )
    except PermissionError:
        return f"Error: Permission denied reading {path}"
    except Exception as e:
        return f"Error sending file: {str(e)}"


def _format_size(size: int) -> str:
    """Format a file size in human-readable form."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
