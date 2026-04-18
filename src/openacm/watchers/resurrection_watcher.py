"""
resurrection_watcher.py - Background daemon for Code Resurrection.

Recursively indexes user code projects slowly when the system is idle.
Runs at most once per week — only pure source code, no assets or model files.
"""

import asyncio
import os
import json
import time
from pathlib import Path
import structlog

log = structlog.get_logger()

# How often to do a full rescan (seconds). Default: once a week.
RESCAN_INTERVAL = 7 * 24 * 3600  # 604 800 s

# Directories to skip entirely
EXCLUDED_DIRS = {
    "node_modules", ".venv", "venv", "env", ".git", "__pycache__", ".pytest_cache",
    ".next", "build", "dist", "out",
    # Unity / Unreal
    "Library", "Temp", "Logs", "obj", "Builds", "Binaries", "Intermediate", "Saved",
    "DerivedDataCache",
    # .NET
    "bin",
    # ML model caches / weights
    "models", "weights", "checkpoints", "cache", ".cache", ".huggingface",
    "hub", "blobs", "snapshots",
}

# Pure source-code extensions only — no JSON configs, no markup, no styles
ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".cs", ".cpp", ".h", ".c", ".rs", ".go", ".rb", ".php", ".java",
    ".kt", ".swift", ".lua", ".sh", ".bash", ".ps1",
}

MAX_FILE_SIZE = 500 * 1024  # 500 KB limit per file

class ResurrectionWatcher:
    def __init__(self, config, event_bus, rag_engine, database):
        self.config = config
        self.event_bus = event_bus
        self.rag = rag_engine
        self.db = database
        self._running = False
        self._paused = False
        self.state_file = Path("data/resurrection_state.json")
        self.indexed_files: dict[str, float] = {}  # filepath -> mtime
        self._last_full_scan: float = 0.0
        self._load_state()

    def _load_state(self):
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                # Support both old format (plain dict) and new format (with metadata)
                if isinstance(data, dict) and "indexed_files" in data:
                    self.indexed_files = data["indexed_files"]
                    self._last_full_scan: float = data.get("last_full_scan", 0.0)
                else:
                    self.indexed_files = data
                    self._last_full_scan = 0.0
        except Exception as e:
            log.warning("Failed to load resurrection state", error=str(e))

    def _save_state(self, full_scan_done: bool = False):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            if full_scan_done:
                self._last_full_scan = time.time()
            with open(self.state_file, "w") as f:
                json.dump({
                    "indexed_files": self.indexed_files,
                    "last_full_scan": self._last_full_scan,
                }, f)
        except Exception as e:
            log.warning("Failed to save resurrection state", error=str(e))

    async def start(self):
        if self._running:
            return
        self._running = True
        
        # Subscribe to thinking events to pause/resume
        from openacm.core.events import EVENT_THINKING
        self.event_bus.on(EVENT_THINKING, self._on_thinking)
        
        asyncio.create_task(self._index_loop())
        log.info("Resurrection Watcher (Code RAG) started")

    async def stop(self):
        self._running = False
        self._save_state(full_scan_done=False)

    async def _on_thinking(self, event_type: str, data: dict):
        status = data.get("status")
        if status == "start":
            if not self._paused:
                log.debug("Resurrection Watcher: IDLE paused (LLM is thinking)")
            self._paused = True
        elif status == "done":
            if self._paused:
                log.debug("Resurrection Watcher: IDLE resumed")
            self._paused = False

    async def _index_loop(self):
        # Short delay on startup so the rest of the system can boot first
        await asyncio.sleep(30)

        while self._running:
            try:
                # Check RAG readiness
                if not self.rag or not (hasattr(self.rag, "is_ready") and self.rag.is_ready):
                    await asyncio.sleep(300)
                    continue

                paths = getattr(self.config, "resurrection_paths", [])
                if not paths:
                    await asyncio.sleep(3600)
                    continue

                # Skip if the last full scan was less than RESCAN_INTERVAL ago
                elapsed = time.time() - self._last_full_scan
                if elapsed < RESCAN_INTERVAL:
                    sleep_for = RESCAN_INTERVAL - elapsed
                    log.info(
                        "Resurrection Watcher: next scan in",
                        hours=round(sleep_for / 3600, 1),
                    )
                    # Sleep in small chunks so stop() is responsive
                    while sleep_for > 0 and self._running:
                        await asyncio.sleep(min(sleep_for, 600))
                        sleep_for -= 600
                    continue

                log.info("Resurrection Watcher: starting weekly code scan")
                for root_path in paths:
                    if not self._running:
                        break
                    p = Path(root_path)
                    if not p.exists() or not p.is_dir():
                        continue
                    await self._walk_and_index(p, p.name)

                self._save_state(full_scan_done=True)
                log.info(
                    "Resurrection Watcher: weekly scan complete",
                    total_indexed=len(self.indexed_files),
                )

            except Exception as e:
                log.error("Error in resurrection loop", error=str(e))
                await asyncio.sleep(3600)

    async def _throttle(self):
        """Pause indexing if CPU or RAM is under pressure."""
        try:
            import psutil
            while self._running:
                cpu = psutil.cpu_percent(interval=0.2)
                ram = psutil.virtual_memory()
                # Back off if CPU > 50% or less than 400 MB free RAM
                if cpu > 50 or ram.available < 400 * 1024 * 1024:
                    await asyncio.sleep(5)
                else:
                    break
        except ImportError:
            pass  # psutil not available — no throttling

    async def _walk_and_index(self, root_directory: Path, project_name: str):
        CHUNK_SIZE = 150
        OVERLAP = 20
        import hashlib

        stack = [root_directory]

        while stack and self._running:
            current_dir = stack.pop()

            try:
                entries = await asyncio.to_thread(os.listdir, current_dir)
            except PermissionError:
                log.debug("Permission denied accessing dir", dir=str(current_dir))
                continue
            except Exception as e:
                log.debug("Unreadable directory", dir=str(current_dir), error=str(e))
                continue

            for entry in entries:
                if not self._running:
                    break

                # Pause while LLM is thinking
                while self._paused and self._running:
                    await asyncio.sleep(1.0)

                file_path = current_dir / entry

                try:
                    is_dir = await asyncio.to_thread(file_path.is_dir)
                    if is_dir:
                        if entry not in EXCLUDED_DIRS and not entry.startswith("."):
                            stack.append(file_path)
                        continue
                except Exception:
                    continue

                if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                    continue

                try:
                    stat = await asyncio.to_thread(file_path.stat)
                    if stat.st_size > MAX_FILE_SIZE:
                        continue

                    mtime = stat.st_mtime
                    str_path = str(file_path)

                    if str_path in self.indexed_files and self.indexed_files[str_path] >= mtime:
                        continue

                    # Throttle before hitting the embedding model
                    await self._throttle()

                    try:
                        if hasattr(self.rag, "delete_by_metadata"):
                            await self.rag.delete_by_metadata({"file": str_path})

                        content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
                        if not content.strip():
                            continue

                        lines = content.splitlines()
                        if not lines:
                            continue

                        # Build all chunks for this file, then upsert in ONE batch call
                        # (single embedding inference pass instead of N separate ones)
                        raw_chunks: list[dict] = []
                        chunk_idx = 0
                        for i in range(0, max(1, len(lines) - OVERLAP), CHUNK_SIZE - OVERLAP):
                            chunk_lines = lines[i:i + CHUNK_SIZE]
                            if not chunk_lines:
                                break
                            chunk_text = (
                                f"File: {str_path}\nProject: {project_name}\n"
                                f"Lines: {i}-{i+len(chunk_lines)}\n\n"
                                + "\n".join(chunk_lines)
                            )
                            chunk_id = hashlib.sha256(
                                f"{str_path}:{i}".encode()
                            ).hexdigest()[:16]
                            raw_chunks.append({
                                "id": f"{chunk_id}_{chunk_idx}",
                                "text": chunk_text,
                                "metadata": {
                                    "type": "code_archive",
                                    "project": project_name,
                                    "file": str_path,
                                    "chunk_idx": chunk_idx,
                                },
                            })
                            chunk_idx += 1

                        if raw_chunks:
                            await self.rag.ingest_raw_chunks(raw_chunks)

                        self.indexed_files[str_path] = mtime

                        if len(self.indexed_files) % 100 == 0:
                            log.info("Resurrection Watcher progress", indexed_files=len(self.indexed_files))
                            self._save_state(full_scan_done=False)

                        # Breathing room between files so the event loop stays responsive
                        await asyncio.sleep(2.0)

                    except UnicodeDecodeError:
                        pass
                    except Exception as e:
                        log.debug("Failed to ingest file", file=str_path, error=str(e))

                except Exception as e:
                    log.debug("Failed to stat file", file=str(file_path), error=str(e))

__all__ = ["ResurrectionWatcher"]
