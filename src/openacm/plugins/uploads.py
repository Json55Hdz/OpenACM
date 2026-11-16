"""
Upload-and-install for plugins the user wrote themselves (a .zip file).

A plugin is code that runs with all of OpenACM's access, so this path is built around
"never run anything the owner has not read about and explicitly approved":

1. Upload only STORES the file in a quarantine folder and analyses it. Nothing is
   extracted into the plugins folder, imported, or executed (and pip / setup.py are never
   involved: uploaded plugins are plain Python files, so installing cannot run code).
2. The analysis (manifest, file list, a static scan listing risky calls) is shown to the
   owner, who must type the plugin's name to approve it.
3. Approval extracts the files and records a SHA-256 of the whole tree. At every start the
   loader recomputes it: if a single byte changed since approval the plugin is NOT loaded.

The static scan is a help for reading, not a sandbox: a determined author can hide
behaviour from it. The real protection is that only the owner can approve, only after
seeing the report, and that the owner should read plugins they did not write.

Archive format::

    my_plugin.zip
      openacm_plugin.json     {"name": "my_plugin", "version": "1.0.0",
                               "description": "...", "author": "...",
                               "entry": "my_plugin:PLUGIN"}
      my_plugin/__init__.py   defines PLUGIN = MyPlugin()   (a Plugin subclass instance)
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import re
import shutil
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import structlog

log = structlog.get_logger()

MANIFEST = "openacm_plugin.json"
APPROVAL = ".openacm_approved.json"

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_FILES = 500
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_RATIO = 100  # uncompressed / compressed, per file: guards against zip bombs
QUARANTINE_TTL_S = 3600

# Only text-like assets and Python source: no native code, scripts or installers.
ALLOWED_SUFFIXES = {
    ".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".html", ".css", ".js",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".csv",
}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
ENTRY_RE = re.compile(r"^(?P<module>[A-Za-z_][\w.]*):(?P<attr>[A-Za-z_]\w*)$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")
RESERVED_NAMES = {"openacm", "test", "tests", "plugins", "uploaded", "quarantine", "src", "site", "setup"}


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Finding:
    level: str  # "high" | "info"
    file: str
    line: int
    what: str

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "file": self.file, "line": self.line, "what": self.what}


@dataclass
class Analysis:
    id: str
    sha256: str
    manifest: dict[str, Any]
    files: list[dict[str, Any]]
    findings: list[Finding] = field(default_factory=list)
    missing_modules: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sha256": self.sha256,
            "manifest": self.manifest,
            "files": self.files,
            "findings": [f.as_dict() for f in self.findings],
            "high_risk_count": sum(1 for f in self.findings if f.level == "high"),
            "missing_modules": self.missing_modules,
        }


# ── folders ───────────────────────────────────────────────────────────────────

def base_dir() -> Path:
    from openacm.plugins import plugins_dir

    base = plugins_dir()
    if base is None:
        from openacm.core.config import _find_project_root

        base = _find_project_root() / "data" / "plugins"
    return base


def uploaded_dir() -> Path:
    return base_dir() / "uploaded"


def quarantine_dir() -> Path:
    return base_dir() / "_quarantine"


# ── reading the archive safely ────────────────────────────────────────────────

def _clean_member_name(raw: str) -> str:
    """The member's path inside the plugin, or raise. No absolute paths, '..', drive letters,
    backslashes, hidden files or odd characters."""
    if not raw or "\\" in raw or "\x00" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise UploadError(f"Unsafe file name in the archive: {raw!r}")
    parts = PurePosixPath(raw).parts
    if any(p in ("", ".", "..") for p in parts):
        raise UploadError(f"Unsafe file name in the archive: {raw!r}")
    if any(p.startswith(".") for p in parts):
        raise UploadError(f"Hidden files are not allowed in a plugin: {raw!r}")
    if any(len(p) > 100 for p in parts) or len(raw) > 250:
        raise UploadError(f"File name too long: {raw[:60]!r}")
    return "/".join(parts)


def read_archive(data: bytes) -> dict[str, bytes]:
    """Validate the zip and return {clean path: bytes}. Raises UploadError."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise UploadError(f"The file is too big (limit {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB).", 413)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UploadError("That is not a valid .zip file.") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise UploadError("The archive is empty.")
    if len(infos) > MAX_FILES:
        raise UploadError(f"Too many files in the archive (limit {MAX_FILES}).")
    total = 0
    out: dict[str, bytes] = {}
    for info in infos:
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)  # 0 when the zip carries no file-type bits (many tools)
        if kind and kind != stat.S_IFREG:
            raise UploadError(f"Links and special files are not allowed: {info.filename!r}")
        if info.flag_bits & 0x1:
            raise UploadError("Encrypted archives are not allowed.")
        name = _clean_member_name(info.filename)
        if PurePosixPath(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise UploadError(
                f"File type not allowed: {name!r}. Plugins may only contain "
                + ", ".join(sorted(ALLOWED_SUFFIXES))
            )
        if info.file_size > MAX_FILE_BYTES:
            raise UploadError(f"{name!r} is too big (limit {MAX_FILE_BYTES // (1024 * 1024)} MB per file).")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 100_000:
            raise UploadError(f"{name!r} looks like a decompression bomb.")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise UploadError("The plugin is too big once unpacked.")
        if name in out:
            raise UploadError(f"Duplicate file in the archive: {name!r}")
        # Read with a hard cap that does not trust the declared size
        with zf.open(info) as fh:
            body = fh.read(MAX_FILE_BYTES + 1)
        if len(body) > MAX_FILE_BYTES:
            raise UploadError(f"{name!r} is too big.")
        out[name] = body
    return out


def _parse_manifest(files: dict[str, bytes]) -> dict[str, Any]:
    raw = files.get(MANIFEST)
    if raw is None:
        raise UploadError(f"The archive needs a {MANIFEST} file at its top level (see the guide on this page).")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UploadError(f"{MANIFEST} is not valid JSON.") from exc
    if not isinstance(manifest, dict):
        raise UploadError(f"{MANIFEST} must be a JSON object.")
    name = str(manifest.get("name", ""))
    if not NAME_RE.match(name) or name in RESERVED_NAMES:
        raise UploadError("'name' must be 3-40 characters: lowercase letters, digits, underscores, starting with a letter.")
    version = str(manifest.get("version", ""))
    if not VERSION_RE.match(version):
        raise UploadError("'version' is required (for example 1.0.0).")
    match = ENTRY_RE.match(str(manifest.get("entry", "")))
    if not match:
        raise UploadError("'entry' must look like 'my_plugin:PLUGIN' (module:variable).")
    module = match["module"]
    if module != name and not module.startswith(name + "."):
        raise UploadError(f"'entry' must live inside the package '{name}' (so it cannot shadow another module).")
    path_py = module.replace(".", "/") + ".py"
    path_pkg = module.replace(".", "/") + "/__init__.py"
    if path_py not in files and path_pkg not in files:
        raise UploadError(f"'entry' points to '{module}' but the archive has no {path_py} or {path_pkg}.")
    if importlib.util.find_spec(name.split(".")[0]) is not None and not _is_own_install(name):
        raise UploadError(f"A Python module called '{name}' already exists here; pick another plugin name.")
    for key in ("description", "author"):
        if key in manifest and not isinstance(manifest[key], str):
            raise UploadError(f"'{key}' must be text.")
    return {
        "name": name,
        "version": version,
        "description": str(manifest.get("description", ""))[:500],
        "author": str(manifest.get("author", ""))[:100],
        "entry": str(manifest["entry"]),
    }


def _is_own_install(name: str) -> bool:
    return (uploaded_dir() / name).is_dir()


# ── static scan (a reading aid, not a sandbox) ────────────────────────────────

_HIGH_IMPORTS = {
    "subprocess": "can run programs on this machine",
    "ctypes": "can call native code",
    "pickle": "can execute code when loading data",
    "marshal": "can execute code when loading data",
    "socket": "opens raw network connections",
    "pty": "can open a shell",
    "importlib": "can load arbitrary code at runtime",
    "builtins": "can tamper with Python itself",
}
_INFO_IMPORTS = {
    "requests": "makes web requests", "httpx": "makes web requests", "aiohttp": "makes web requests",
    "urllib": "makes web requests", "smtplib": "sends email", "ftplib": "uses FTP",
    "shutil": "copies/deletes files", "os": "uses the operating system", "sqlite3": "reads/writes databases",
}
_HIGH_CALLS = {
    "eval": "runs text as code", "exec": "runs text as code", "compile": "builds code from text",
    "__import__": "loads arbitrary modules", "system": "runs a shell command",
    "popen": "runs a shell command", "rmtree": "deletes whole folders",
    "getenv": "reads environment variables (API keys live there)",
    "environ": "reads environment variables (API keys live there)",
}


def scan_python(path: str, source: str) -> list[Finding]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise UploadError(f"{path} has a syntax error on line {exc.lineno}.") from exc
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for full in names:
                top = full.split(".")[0]
                if top in _HIGH_IMPORTS:
                    out.append(Finding("high", path, node.lineno, f"imports {top}: {_HIGH_IMPORTS[top]}"))
                elif top in _INFO_IMPORTS:
                    out.append(Finding("info", path, node.lineno, f"imports {top}: {_INFO_IMPORTS[top]}"))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name in _HIGH_CALLS:
                out.append(Finding("high", path, node.lineno, f"calls {name}(): {_HIGH_CALLS[name]}"))
        elif isinstance(node, ast.Attribute) and node.attr in ("environ", "__dict__", "__globals__", "__builtins__"):
            out.append(Finding("high", path, node.lineno, f"touches .{node.attr}"))
    return out


def tree_hash(files: dict[str, bytes]) -> str:
    """One SHA-256 over every file's name and content, order independent."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode("utf-8") + b"\x00" + hashlib.sha256(files[name]).digest())
    return h.hexdigest()


# ── step 1: quarantine + analysis ─────────────────────────────────────────────

def _purge_old_quarantine() -> None:
    folder = quarantine_dir()
    if not folder.is_dir():
        return
    cutoff = time.time() - QUARANTINE_TTL_S
    for item in folder.glob("*.zip"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            pass


def analyse_upload(data: bytes) -> Analysis:
    """Validate and analyse an uploaded archive, then keep it in quarantine. Executes nothing."""
    files = read_archive(data)
    manifest = _parse_manifest(files)
    findings: list[Finding] = []
    for name, body in sorted(files.items()):
        if name.endswith(".py"):
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise UploadError(f"{name} is not UTF-8 text.") from exc
            findings.extend(scan_python(name, text))
    findings.sort(key=lambda f: (f.level != "high", f.file, f.line))
    _purge_old_quarantine()
    upload_id = uuid.uuid4().hex[:16]
    folder = quarantine_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{upload_id}.zip").write_bytes(data)
    return Analysis(
        id=upload_id,
        sha256=hashlib.sha256(data).hexdigest(),
        manifest=manifest,
        files=[{"path": n, "bytes": len(b)} for n, b in sorted(files.items())],
        findings=findings,
    )


def discard_upload(upload_id: str) -> None:
    if re.fullmatch(r"[0-9a-f]{16}", upload_id or ""):
        (quarantine_dir() / f"{upload_id}.zip").unlink(missing_ok=True)


# ── step 2: approval → extract ────────────────────────────────────────────────

def install_approved(upload_id: str, typed_name: str, expected_sha256: str) -> dict[str, Any]:
    """Extract a quarantined upload after the owner typed the plugin name and the
    SHA-256 shown in the report matches the stored file. Returns the manifest."""
    if not re.fullmatch(r"[0-9a-f]{16}", upload_id or ""):
        raise UploadError("Unknown upload.", 404)
    path = quarantine_dir() / f"{upload_id}.zip"
    if not path.is_file():
        raise UploadError("That upload expired or does not exist. Upload the file again.", 404)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != str(expected_sha256 or "").lower():
        raise UploadError("The stored file does not match the report you approved.", 409)
    files = read_archive(data)  # validated again: never trust the earlier pass
    manifest = _parse_manifest(files)
    if typed_name != manifest["name"]:
        raise UploadError("The name you typed does not match the plugin's name.", 400)

    target = uploaded_dir() / manifest["name"]
    staging = uploaded_dir() / f".staging-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for name, body in files.items():
            dest = (staging / name).resolve()
            if staging.resolve() not in dest.parents:
                raise UploadError("Unsafe path in the archive.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        (staging / APPROVAL).write_text(
            json.dumps({"tree_sha256": tree_hash(files), "archive_sha256": hashlib.sha256(data).hexdigest(),
                        "approved_at": time.time(), "version": manifest["version"]}),
            encoding="utf-8",
        )
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    path.unlink(missing_ok=True)
    log.info("plugin.upload.installed", name=manifest["name"], version=manifest["version"])
    return manifest


def remove_uploaded(name: str) -> bool:
    if not NAME_RE.match(name or ""):
        raise UploadError("Invalid plugin name.")
    target = uploaded_dir() / name
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


# ── loading at startup ────────────────────────────────────────────────────────

def _read_tree(folder: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for item in sorted(folder.rglob("*")):
        if item.is_symlink():
            raise UploadError(f"symlink inside the plugin: {item.name}")
        if item.is_file() and item.name != APPROVAL:
            files[item.relative_to(folder).as_posix()] = item.read_bytes()
    return files


def verified_manifest(folder: Path) -> dict[str, Any] | None:
    """The manifest of an installed upload, but only if it is untouched since approval."""
    try:
        approval = json.loads((folder / APPROVAL).read_text(encoding="utf-8"))
        files = _read_tree(folder)
        if tree_hash(files) != approval.get("tree_sha256"):
            log.warning("plugin.upload.modified_since_approval", plugin=folder.name)
            return None
        return _parse_manifest_installed(files, folder.name)
    except Exception as exc:  # noqa: BLE001
        log.warning("plugin.upload.unverifiable", plugin=folder.name, error=str(exc))
        return None


def _parse_manifest_installed(files: dict[str, bytes], folder_name: str) -> dict[str, Any]:
    manifest = _parse_manifest(files)
    if manifest["name"] != folder_name:
        raise UploadError("folder name and manifest name differ")
    return manifest


def list_installed() -> list[dict[str, Any]]:
    root = uploaded_dir()
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        manifest = verified_manifest(folder)
        out.append({"name": folder.name, "verified": manifest is not None, **(manifest or {})})
    return out
