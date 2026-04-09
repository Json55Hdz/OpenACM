"""
resurrection_watcher.py - Background daemon for Code Resurrection.

Recursively indexes user code projects slowly when the system is idle.
"""

import asyncio
import os
import json
from pathlib import Path
import structlog

log = structlog.get_logger()

# Garbage patterns to exclude from code ingestion
EXCLUDED_DIRS = {
    "node_modules", ".venv", "venv", "env", ".git", "__pycache__", ".pytest_cache",
    ".next", "build", "dist", "out",
    # Unity / Unreal
    "Library", "Temp", "Logs", "obj", "Builds", "Binaries", "Intermediate", "Saved", "DerivedDataCache",
    # .NET
    "bin"
}

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".md", ".json",
    ".cs", ".cpp", ".h", ".c", ".rs", ".go", ".rb", ".php", ".java"
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
        self._load_state()

    def _load_state(self):
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    self.indexed_files = json.load(f)
        except Exception as e:
            log.warning("Failed to load resurrection state", error=str(e))

    def _save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self.indexed_files, f)
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
        self._save_state()

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
        # Wait a bit on startup
        await asyncio.sleep(10)
        
        while self._running:
            try:
                # Check RAG readiness correctly
                if not self.rag or not (hasattr(self.rag, "is_ready") and self.rag.is_ready):
                    await asyncio.sleep(60)
                    continue
                    
                paths = getattr(self.config, "resurrection_paths", [])
                if not paths:
                    await asyncio.sleep(60)  # Check again in a minute
                    continue

                for root_path in paths:
                    if not self._running:
                        break
                    
                    p = Path(root_path)
                    if not p.exists() or not p.is_dir():
                        continue
                        
                    await self._walk_and_index(p, p.name)

                # After full cycle, save state and sleep a long time
                self._save_state()
                await asyncio.sleep(300)  # Wait 5 minutes before full rescan
            except Exception as e:
                log.error("Error in resurrection loop", error=str(e))
                await asyncio.sleep(60)

    async def _walk_and_index(self, root_directory: Path, project_name: str):
        stack = [root_directory]
        
        while stack and self._running:
            current_dir = stack.pop()

            try:
                # Yield to event loop while retrieving directory contents
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
                    
                # Pause while LLM is active
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

                # It's a file
                if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                    continue
                
                try:
                    stat = await asyncio.to_thread(file_path.stat)
                    if stat.st_size > MAX_FILE_SIZE:
                        continue
                        
                    mtime = stat.st_mtime
                    str_path = str(file_path)
                    
                    # Already indexed and not modified?
                    if str_path in self.indexed_files and self.indexed_files[str_path] >= mtime:
                        continue
                        
                    # Slow down to protect CPU
                    await asyncio.sleep(0.5)
                    
                    # Read and ingest
                    try:
                        # Wipe obsolete chunks for this specific file from RAG before re-ingesting
                        if hasattr(self.rag, "delete_by_metadata"):
                            await self.rag.delete_by_metadata({"file": str_path})

                        content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
                        if not content.strip():
                            continue
                            
                        # Split into line-based chunks (150 lines per chunk, 20 lines overlap)
                        lines = content.splitlines()
                        CHUNK_SIZE = 150
                        OVERLAP = 20
                        
                        if not lines:
                            continue
                            
                        chunk_count = 0
                        for i in range(0, max(1, len(lines) - OVERLAP), CHUNK_SIZE - OVERLAP):
                            chunk_lines = lines[i:i + CHUNK_SIZE]
                            if not chunk_lines:
                                break
                                
                            chunk_text = "\n".join(chunk_lines)
                            
                            # Pass to RAG
                            await self.rag.ingest(
                                text=f"File: {str_path}\nProject: {project_name}\nLines: {i}-{i+len(chunk_lines)}\n\n{chunk_text}",
                                metadata={
                                    "type": "code_archive",
                                    "project": project_name,
                                    "file": str_path,
                                    "chunk_idx": chunk_count
                                }
                            )
                            chunk_count += 1
                            await asyncio.sleep(0.1) # Breve respiro al CPU entre chunks
                            
                        self.indexed_files[str_path] = mtime
                        
                        # Optionally log progress every 100 files
                        if len(self.indexed_files) % 100 == 0:
                            log.info("Resurrection Watcher progress", indexed_files=len(self.indexed_files))
                            self._save_state()
                            
                    except UnicodeDecodeError:
                        pass # probably binary, ignore
                    except Exception as e:
                        log.debug("Failed to ingest file content", file=str_path, error=str(e))
                        
                except Exception as e:
                    log.debug("Failed to stat file", file=str(file_path), error=str(e))

__all__ = ["ResurrectionWatcher"]
