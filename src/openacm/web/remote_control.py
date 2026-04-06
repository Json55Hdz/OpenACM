"""
Remote Control module — handles mouse/keyboard automation for remote access.

Receives commands from the mobile client via WebSocket and executes them
on the PC using pyautogui.
"""

import asyncio
import platform
from typing import Optional

import structlog

log = structlog.get_logger()

# Lazy import pyautogui to avoid import errors on headless systems
_pyautogui = None


def _get_pyautogui():
    """Lazy-load pyautogui with failsafe disabled for remote control."""
    global _pyautogui
    if _pyautogui is None:
        import pyautogui
        pyautogui.FAILSAFE = False  # Disable corner failsafe for remote use
        pyautogui.PAUSE = 0.02      # Minimal pause between actions
        _pyautogui = pyautogui
    return _pyautogui


# Track active monitor for headless streaming (1 = primary, 2 = secondary...)
_current_monitor_index = 1

def set_current_monitor(idx: int):
    global _current_monitor_index
    _current_monitor_index = int(idx)
    return {"action": "switch-monitor", "index": _current_monitor_index}

def get_current_monitor_index() -> int:
    global _current_monitor_index
    import mss
    with mss.mss() as sct:
        if _current_monitor_index >= len(sct.monitors):
            _current_monitor_index = 1
    return _current_monitor_index

def get_screen_info() -> dict:
    """Return active monitor resolution and total monitors."""
    import mss
    with mss.mss() as sct:
        idx = get_current_monitor_index()
        m = sct.monitors[idx]
        return {
            "width": m["width"], 
            "height": m["height"], 
            "index": idx, 
            "total": len(sct.monitors) - 1 # exclude monitor 0 (virtual)
        }

def _get_abs_coords(x_ratio: float, y_ratio: float) -> tuple[int, int]:
    """Calculate absolute coordinates based on current active monitor offsets."""
    import mss
    with mss.mss() as sct:
        m = sct.monitors[get_current_monitor_index()]
        return (
            m["left"] + int(x_ratio * m["width"]),
            m["top"] + int(y_ratio * m["height"])
        )


async def handle_click(
    x_ratio: float,
    y_ratio: float,
    button: str = "left",
    clicks: int = 1,
) -> dict:
    """
    Execute a mouse click at relative coordinates.

    Args:
        x_ratio: X position as ratio (0.0 - 1.0) of screen width
        y_ratio: Y position as ratio (0.0 - 1.0) of screen height
        button: 'left', 'right', or 'middle'
        clicks: Number of clicks (2 for double-click)
    """
    pg = _get_pyautogui()
    abs_x, abs_y = _get_abs_coords(x_ratio, y_ratio)

    # Run in thread to not block event loop
    await asyncio.to_thread(pg.click, abs_x, abs_y, clicks=clicks, button=button)
    log.debug("Remote click", x=abs_x, y=abs_y, button=button, clicks=clicks)
    return {"action": "click", "x": abs_x, "y": abs_y}


async def handle_move(x_ratio: float, y_ratio: float) -> dict:
    """Move cursor to relative position."""
    pg = _get_pyautogui()
    abs_x, abs_y = _get_abs_coords(x_ratio, y_ratio)

    await asyncio.to_thread(pg.moveTo, abs_x, abs_y, duration=0)
    return {"action": "move", "x": abs_x, "y": abs_y}


async def handle_drag(
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    button: str = "left",
) -> dict:
    """Drag from one point to another (relative coords)."""
    pg = _get_pyautogui()
    sx, sy = _get_abs_coords(start_x, start_y)
    ex, ey = _get_abs_coords(end_x, end_y)

    await asyncio.to_thread(pg.moveTo, sx, sy)
    await asyncio.to_thread(pg.drag, ex - sx, ey - sy, duration=0.3, button=button)
    return {"action": "drag", "start": [sx, sy], "end": [ex, ey]}


async def handle_scroll(dx: int = 0, dy: int = 0) -> dict:
    """Scroll the mouse wheel. dy>0 = scroll up, dy<0 = scroll down."""
    pg = _get_pyautogui()
    if dy != 0:
        await asyncio.to_thread(pg.scroll, dy)
    if dx != 0:
        await asyncio.to_thread(pg.hscroll, dx)
    return {"action": "scroll", "dx": dx, "dy": dy}


async def handle_type(text: str) -> dict:
    """Type text using keyboard (e.g., from voice recognition)."""
    pg = _get_pyautogui()
    # Use pyperclip + hotkey for reliable unicode typing
    try:
        import pyperclip
        await asyncio.to_thread(pyperclip.copy, text)
        if platform.system() == "Darwin":
            await asyncio.to_thread(pg.hotkey, "command", "v")
        else:
            await asyncio.to_thread(pg.hotkey, "ctrl", "v")
        log.debug("Remote type (clipboard)", length=len(text))
    except ImportError:
        # Fallback to typewrite (ASCII only)
        await asyncio.to_thread(pg.typewrite, text, interval=0.02)
        log.debug("Remote type (typewrite)", length=len(text))
    return {"action": "type", "length": len(text)}


async def handle_key(key: str) -> dict:
    """
    Press a special key or key combination.

    Examples: 'enter', 'tab', 'escape', 'ctrl+c', 'alt+tab', 'win'
    """
    pg = _get_pyautogui()
    if "+" in key:
        keys = [k.strip() for k in key.split("+")]
        # Map common names
        key_map = {"ctrl": "ctrl", "alt": "alt", "shift": "shift",
                    "win": "win", "cmd": "command", "super": "win"}
        mapped = [key_map.get(k.lower(), k.lower()) for k in keys]
        await asyncio.to_thread(pg.hotkey, *mapped)
    else:
        key_map = {
            "enter": "enter", "tab": "tab", "escape": "escape", "esc": "escape",
            "backspace": "backspace", "delete": "delete", "space": "space",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5",
            "f6": "f6", "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10",
            "f11": "f11", "f12": "f12", "win": "win", "printscreen": "printscreen",
        }
        mapped_key = key_map.get(key.lower(), key.lower())
        await asyncio.to_thread(pg.press, mapped_key)
    log.debug("Remote key", key=key)
    return {"action": "key", "key": key}


async def dispatch_command(data: dict) -> dict:
    """
    Central dispatcher for all remote control commands.

    Expected data format:
        {"type": "click", "x": 0.5, "y": 0.3, "button": "left"}
        {"type": "move", "x": 0.5, "y": 0.3}
        {"type": "scroll", "dy": -3}
        {"type": "type", "text": "hello world"}
        {"type": "key", "key": "enter"}
        {"type": "key", "key": "alt+tab"}
        {"type": "drag", "startX": 0.1, "startY": 0.1, "endX": 0.5, "endY": 0.5}
        {"type": "switch-monitor", "index": 2}
        {"type": "screen_info"}
    """
    cmd_type = data.get("type", "")

    try:
        if cmd_type == "click":
            return await handle_click(
                data.get("x", 0.5),
                data.get("y", 0.5),
                data.get("button", "left"),
                data.get("clicks", 1),
            )
        elif cmd_type == "move":
            return await handle_move(data.get("x", 0.5), data.get("y", 0.5))
        elif cmd_type == "scroll":
            return await handle_scroll(data.get("dx", 0), data.get("dy", 0))
        elif cmd_type == "type":
            return await handle_type(data.get("text", ""))
        elif cmd_type == "key":
            return await handle_key(data.get("key", ""))
        elif cmd_type == "drag":
            return await handle_drag(
                data.get("startX", 0), data.get("startY", 0),
                data.get("endX", 0), data.get("endY", 0),
                data.get("button", "left"),
            )
        elif cmd_type == "switch-monitor":
            return set_current_monitor(data.get("index", 1))
        elif cmd_type == "screen_info":
            return get_screen_info()
        else:
            return {"error": f"Unknown command type: {cmd_type}"}
    except Exception as e:
        log.error("Remote control error", type=cmd_type, error=str(e))
        return {"error": str(e)}
