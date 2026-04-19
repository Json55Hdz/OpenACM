"""
ChannelShell — persistent PTY shell session for one channel.

Survives WebSocket reconnects so the terminal stays alive between page refreshes.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from fastapi import WebSocket


class ChannelShell:
    """Persistent PTY shell for one channel. Survives WS reconnects."""

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.clients: set[WebSocket] = set()
        self._platform: str = ""
        self._pty = None          # winpty.PtyProcess (Windows) or (master_fd, proc) tuple (Unix)
        self._alive = False
        self._reader_task: asyncio.Task | None = None
        self._output_listeners: list[asyncio.Queue] = []  # for run_command_capture
        self._cmd_lock = asyncio.Lock()                    # one command at a time

    async def start(self, cols: int = 220, rows: int = 50) -> None:
        import platform as _plat
        self._platform = _plat.system()
        loop = asyncio.get_event_loop()

        if self._platform == "Windows":
            from winpty import PtyProcess  # pywinpty
            self._pty = await loop.run_in_executor(
                None, lambda: PtyProcess.spawn("cmd.exe", dimensions=(rows, cols))
            )
        else:
            import pty as _pty_mod, subprocess, fcntl, termios, struct
            master_fd, slave_fd = _pty_mod.openpty()
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            proc = subprocess.Popen(
                ["/bin/bash", "-i"],
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                close_fds=True, preexec_fn=os.setsid,
            )
            os.close(slave_fd)
            self._pty = (master_fd, proc)

        self._alive = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        consecutive_errors = 0
        while self._alive:
            try:
                chunk = await loop.run_in_executor(None, self._read_chunk)
                consecutive_errors = 0
                if chunk is None:
                    self._alive = False
                    await self._broadcast_json({"type": "exit", "data": "shell exited"})
                    break
                if chunk:
                    await self._broadcast_json({"type": "output", "data": chunk})
            except asyncio.CancelledError:
                break
            except Exception:
                consecutive_errors += 1
                if consecutive_errors > 20:
                    self._alive = False
                    await self._broadcast_json({"type": "exit", "data": "shell read error"})
                    break
                await asyncio.sleep(0.05)

    def _read_chunk(self) -> str | None:
        """Blocking read — runs in thread executor. Returns None when process dies."""
        try:
            if self._platform == "Windows":
                if not self._pty.isalive():
                    return None
                data = self._pty.read(4096)
                return data if data else ""
            else:
                import select
                master_fd, proc = self._pty
                if proc.poll() is not None:
                    return None
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if r:
                    return os.read(master_fd, 4096).decode("utf-8", errors="replace")
                return ""
        except EOFError:
            return None
        except Exception:
            return None

    async def write(self, data: str) -> None:
        if not self._alive:
            return
        loop = asyncio.get_event_loop()
        try:
            if self._platform == "Windows":
                await loop.run_in_executor(None, self._pty.write, data)
            else:
                master_fd, _ = self._pty
                await loop.run_in_executor(None, os.write, master_fd, data.encode("utf-8"))
        except Exception:
            pass

    def resize(self, cols: int, rows: int) -> None:
        try:
            if self._platform == "Windows":
                self._pty.setwinsize(rows, cols)
            else:
                import fcntl, termios, struct
                master_fd, _ = self._pty
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass

    async def _broadcast_json(self, data: dict[str, Any]) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self.clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.clients -= dead
        for q in list(self._output_listeners):
            try:
                q.put_nowait(data)
            except Exception:
                pass

    async def run_command_capture(self, command: str, timeout: float = 30.0) -> str:
        """Write a command to the PTY and capture output. Serialized — one command at a time."""

        _ANSI = re.compile(r'\x1b(?:\[[0-9;]*[mGKHFABCDJsSu]|\][^\x07]*\x07|[()][AB012])')
        MAX_CAPTURE_CHARS = 80_000

        def strip_ansi(t: str) -> str:
            return _ANSI.sub("", t).replace("\r", "")

        def looks_like_prompt(text: str) -> bool:
            clean = strip_ansi(text).rstrip()
            if not clean:
                return False
            last = clean.splitlines()[-1] if "\n" in clean else clean
            return bool(re.search(r"[>$#]\s*$", last))

        async def _interrupt_pty() -> None:
            try:
                await self.write("\x03")
                await asyncio.sleep(0.3)
            except Exception:
                pass

        async with self._cmd_lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
            self._output_listeners.append(queue)
            parts: list[str] = []
            total_chars = 0
            output_capped = False

            try:
                await self.write(command + "\r\n")
                deadline = asyncio.get_event_loop().time() + timeout
                prompt_seen = False

                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        await _interrupt_pty()
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=min(remaining, 0.5))
                        if msg.get("type") == "output":
                            chunk = msg.get("data", "")
                            total_chars += len(chunk)

                            if total_chars <= MAX_CAPTURE_CHARS:
                                parts.append(chunk)
                            elif not output_capped:
                                output_capped = True
                                await _interrupt_pty()
                                break

                            combined = "".join(parts)
                            if looks_like_prompt(combined) and len(strip_ansi(combined).strip()) > len(command) + 2:
                                prompt_seen = True
                                break
                    except asyncio.TimeoutError:
                        combined = "".join(parts)
                        if prompt_seen or (parts and looks_like_prompt(combined)):
                            break
            finally:
                try:
                    self._output_listeners.remove(queue)
                except ValueError:
                    pass

            combined = strip_ansi("".join(parts)).strip()
            if combined.lower().startswith(command.strip().lower()):
                combined = combined[len(command.strip()):].strip()

            if output_capped:
                combined += f"\n[output truncated — exceeded {MAX_CAPTURE_CHARS:,} chars. Command was interrupted.]"

            return combined or "(sin salida)"

    async def run_interactive_capture(self, command: str, timeout: float = 600.0) -> str:
        """
        Run an interactive command in the PTY. Unlike run_command_capture, this:
        - Shows the session to the user (already happens via _broadcast_json)
        - Does NOT send Ctrl+C on timeout — user is in control
        - Waits until the shell prompt returns (user typed exit/Ctrl+D) or timeout
        - Returns the captured output for the brain
        """
        _ANSI = re.compile(r'\x1b(?:\[[0-9;]*[mGKHFABCDJsSu]|\][^\x07]*\x07|[()][AB012])')

        def strip_ansi(t: str) -> str:
            return _ANSI.sub("", t).replace("\r", "")

        def looks_like_prompt(text: str) -> bool:
            clean = strip_ansi(text).rstrip()
            if not clean:
                return False
            last = clean.splitlines()[-1] if "\n" in clean else clean
            return bool(re.search(r"[>$#%]\s*$", last))

        await self._broadcast_json({
            "type": "output",
            "data": f"\r\n\x1b[33m[ACM → interactive: {command.split()[0]}  |  exit/Ctrl+C to return control]\x1b[0m\r\n",
        })

        async with self._cmd_lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
            self._output_listeners.append(queue)
            parts: list[str] = []

            try:
                await self.write(command + "\r\n")
                deadline = asyncio.get_event_loop().time() + timeout

                while True:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=min(remaining, 1.0))
                        if msg.get("type") == "output":
                            chunk = msg.get("data", "")
                            parts.append(chunk)
                            combined = "".join(parts)
                            if looks_like_prompt(combined) and len(strip_ansi(combined).strip()) > len(command) + 2:
                                break
                    except asyncio.TimeoutError:
                        combined = "".join(parts)
                        if parts and looks_like_prompt(combined):
                            break
            finally:
                try:
                    self._output_listeners.remove(queue)
                except ValueError:
                    pass

        await self._broadcast_json({
            "type": "output",
            "data": "\r\n\x1b[33m[ACM ← control returned]\x1b[0m\r\n",
        })

        combined = strip_ansi("".join(parts)).strip()
        if combined.lower().startswith(command.strip().lower()):
            combined = combined[len(command.strip()):].strip()
        return combined or "(no output)"

    async def stop(self) -> None:
        self._alive = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        try:
            if self._platform == "Windows":
                if self._pty:
                    self._pty.terminate(force=True)
            else:
                if self._pty:
                    import signal
                    master_fd, proc = self._pty
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
        except Exception:
            pass
