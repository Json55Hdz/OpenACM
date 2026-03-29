"""
Blender Tool — Interactive 3D modeling via a live Blender session.

Architecture
─────────────────────────────────────────────────────────────
1. blender_start()  → Launches Blender (with GUI) and loads the
                       OpenACM Bridge addon, which starts an HTTP
                       server on port 7395 inside Blender.

2. blender_exec()   → POSTs bpy code to the bridge. The bridge
                       executes it on Blender's main thread (thread-
                       safe) and returns stdout + optional viewport
                       screenshot encoded as base64.

3. blender_export() → Sends export code to the bridge, reads the
                       resulting file, encrypts it, and returns a
                       /api/media/ download link.

4. blender_stop()   → Gracefully quits Blender.

The AI workflow
─────────────────────────────────────────────────────────────
  blender_start()
  blender_exec("clear_scene(); bpy.ops.mesh.primitive_cylinder_add(...)")
  blender_exec("...", screenshot=True)   # returns viewport screenshot
  blender_exec("apply_modifier(bpy.context.active_object, 'SUBSURF', levels=2)")
  blender_export("glb")
  blender_stop()

The tool also exposes blender_info() (check installation) and
blender_run_script() (legacy batch mode, no GUI needed).
"""

import asyncio
import base64
import os
import platform
import secrets
import shutil
import tempfile
import textwrap
from pathlib import Path

import structlog

from openacm.tools.base import tool

log = structlog.get_logger()

# ── Bridge state (per OpenACM process) ──────────────────────────────────────
_blender_process: asyncio.subprocess.Process | None = None
_bridge_port: int = 7395
_addon_tmp_dir: str | None = None  # cleanup on stop

# ─────────────────────────────────────────────────────────────────────────────
# Blender discovery
# ─────────────────────────────────────────────────────────────────────────────

def _find_blender() -> str | None:
    env_path = os.environ.get("BLENDER_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path

    found = shutil.which("blender")
    if found:
        return found

    system = platform.system()

    if system == "Windows":
        search_roots = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Programs",
        ]
        for root in search_roots:
            bf_dir = root / "Blender Foundation"
            if bf_dir.is_dir():
                candidates = sorted(bf_dir.glob("Blender */blender.exe"), reverse=True)
                if candidates:
                    return str(candidates[0])

    elif system == "Darwin":
        for p in [
            Path("/Applications/Blender.app/Contents/MacOS/Blender"),
            Path.home() / "Applications/Blender.app/Contents/MacOS/Blender",
        ]:
            if p.is_file():
                return str(p)

    else:  # Linux
        candidates = [
            "/usr/bin/blender", "/usr/local/bin/blender", "/opt/blender/blender",
            str(Path.home() / "blender" / "blender"), "/snap/bin/blender",
        ]
        local_share = Path.home() / ".local" / "share"
        if local_share.is_dir():
            for d in sorted(local_share.glob("blender-*"), reverse=True):
                candidates.insert(0, str(d / "blender"))
        for p in candidates:
            if Path(p).is_file():
                return p

    return None


_INSTALL_HINTS = {
    "Windows": "Download from https://www.blender.org/download/ and install, or set BLENDER_PATH env var.",
    "Darwin":  "Install via https://www.blender.org/download/ or 'brew install --cask blender'.",
    "Linux":   "Run: sudo apt install blender  OR  sudo snap install blender --classic",
}


def _not_found_msg() -> str:
    hint = _INSTALL_HINTS.get(platform.system(), "See https://www.blender.org/download/")
    return (
        "Blender is not installed or not found.\n\n"
        f"{hint}\n\n"
        "After installing, set BLENDER_PATH to the blender executable if it is not on PATH."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bridge addon source (written to a temp file and loaded by Blender)
# ─────────────────────────────────────────────────────────────────────────────

_BRIDGE_ADDON = '''\
"""
OpenACM Bridge Addon — HTTP server inside Blender for remote bpy execution.
Loaded automatically by blender_start(). Do not edit by hand.
"""
import bpy
import threading
import json
import queue
import base64
import tempfile
import os
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

_PORT = 7395
_exec_q: queue.Queue = queue.Queue()
_res_q: queue.Queue = queue.Queue()
_server: HTTPServer | None = None

# ── Pre-defined helpers available in every exec() call ───────────────────────

_HELPERS = """
import bpy, math, mathutils
from mathutils import Vector, Euler, Matrix

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for m in list(bpy.data.meshes): bpy.data.meshes.remove(m)
    for l in list(bpy.data.lights): bpy.data.lights.remove(l)

def setup_camera(location=(7, -7, 5), rotation_deg=(63, 0, 47)):
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.rotation_euler = Euler([math.radians(d) for d in rotation_deg], 'XYZ')
    bpy.context.scene.camera = cam
    return cam

def add_light(light_type='SUN', location=(4, 1, 6), energy=3.0):
    bpy.ops.object.light_add(type=light_type, location=location)
    l = bpy.context.active_object
    l.data.energy = energy
    return l

def apply_smooth_shading(obj=None):
    targets = [obj] if obj else [o for o in bpy.context.scene.objects if o.type == 'MESH']
    for t in targets:
        bpy.context.view_layer.objects.active = t
        bpy.ops.object.shade_smooth()

def add_material(obj, name="Mat", color=(0.8, 0.5, 0.1, 1.0)):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
    if obj.data.materials: obj.data.materials[0] = mat
    else: obj.data.materials.append(mat)
    return mat

def apply_modifier(obj, mod_type, **kw):
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new(name=mod_type, type=mod_type)
    for k, v in kw.items(): setattr(mod, k, v)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj

def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
"""

# ── HTTP handler ──────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # silence default logs

    def do_GET(self):
        if self.path == '/ping':
            self._json({"ok": True})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode())
        _exec_q.put(body)
        try:
            result = _res_q.get(timeout=120)
        except Exception:
            result = {"success": False, "error": "timeout"}
        self._json(result)

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

# ── Main-thread timer ─────────────────────────────────────────────────────────

def _tick():
    """Executed on Blender's main thread every 50ms. Processes one queued command."""
    try:
        if not _exec_q.empty():
            item = _exec_q.get_nowait()
            code = item.get("code", "")
            want_ss = item.get("screenshot", False)

            captured = []

            class _Cap:
                def write(self, s): captured.append(str(s))
                def flush(self): pass

            old_out = sys.stdout
            sys.stdout = _Cap()
            try:
                g = {}
                exec(compile(_HELPERS, "<helpers>", "exec"), g)
                exec(compile(code, "<openacm>", "exec"), g)
                sys.stdout = old_out
                result = {"success": True, "output": "".join(captured)}
            except Exception as e:
                sys.stdout = old_out
                result = {
                    "success": False,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "output": "".join(captured),
                }

            if want_ss:
                try:
                    tmp = tempfile.mktemp(suffix=".png")
                    scene = bpy.context.scene
                    old_fp = scene.render.filepath
                    old_fmt = scene.render.image_settings.file_format
                    scene.render.filepath = tmp
                    scene.render.image_settings.file_format = "PNG"
                    scene.render.resolution_x = 800
                    scene.render.resolution_y = 600
                    bpy.ops.render.opengl(write_still=True)
                    scene.render.filepath = old_fp
                    scene.render.image_settings.file_format = old_fmt
                    if os.path.exists(tmp):
                        with open(tmp, "rb") as f:
                            result["screenshot_b64"] = base64.b64encode(f.read()).decode()
                        os.unlink(tmp)
                except Exception as ss_err:
                    result["screenshot_error"] = str(ss_err)

            _res_q.put(result)
    except Exception:
        pass
    return 0.05  # reschedule every 50ms

# ── Addon register/unregister ─────────────────────────────────────────────────

def register():
    global _server
    _server = HTTPServer(("127.0.0.1", _PORT), _Handler)
    t = threading.Thread(target=_server.serve_forever, daemon=True)
    t.start()
    bpy.app.timers.register(_tick, persistent=True)
    print(f"[OpenACM Bridge] Listening on http://127.0.0.1:{_PORT}")

def unregister():
    if _server:
        _server.shutdown()
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:
        pass
'''

_STARTUP_SCRIPT = '''\
import bpy, sys, os, importlib.util

# Load the bridge addon from the given path
addon_path = r"{addon_path}"
spec = importlib.util.spec_from_file_location("openacm_bridge", addon_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.register()

print("[OpenACM] Bridge addon loaded. Blender is ready.")
'''


# ─────────────────────────────────────────────────────────────────────────────
# Internal HTTP helper
# ─────────────────────────────────────────────────────────────────────────────

async def _bridge_post(payload: dict, timeout: float = 60.0) -> dict:
    """POST JSON to the bridge and return the parsed response."""
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"http://127.0.0.1:{_bridge_port}/",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _bridge_ping(retries: int = 30, interval: float = 1.0) -> bool:
    """Return True when the bridge is ready, False after retries."""
    import httpx
    for _ in range(retries):
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"http://127.0.0.1:{_bridge_port}/ping")
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool(
    name="blender_start",
    description=(
        "Open Blender with an interactive GUI and load the OpenACM bridge so the AI "
        "can send live bpy commands. Call this first before blender_exec or blender_export. "
        "Blender will appear on screen. Returns 'ready' when the bridge is up."
    ),
    parameters={
        "type": "object",
        "properties": {
            "startup_code": {
                "type": "string",
                "description": (
                    "Optional bpy code to run immediately after Blender starts. "
                    "E.g., 'clear_scene(); setup_camera(); add_light()' to prepare the scene."
                ),
                "default": "",
            },
        },
        "required": [],
    },
    risk_level="medium",
    category="blender",
)
async def blender_start(startup_code: str = "", **kwargs) -> str:
    """Launch Blender with the OpenACM bridge addon."""
    global _blender_process, _addon_tmp_dir

    blender_exe = _find_blender()
    if not blender_exe:
        return _not_found_msg()

    # If already running, check if it's alive
    if _blender_process is not None:
        if _blender_process.returncode is None:
            # Still running — check bridge
            if await _bridge_ping(retries=3, interval=0.5):
                return "Blender is already running and the bridge is active. Use blender_exec to send commands."
        _blender_process = None

    # Write addon + startup script to a temp directory
    tmp_dir = tempfile.mkdtemp(prefix="openacm_blender_")
    _addon_tmp_dir = tmp_dir

    addon_path = Path(tmp_dir) / "openacm_bridge_addon.py"
    addon_path.write_text(_BRIDGE_ADDON, encoding="utf-8")

    # Build startup script content
    startup_body = _STARTUP_SCRIPT.replace("{addon_path}", str(addon_path).replace("\\", "/"))
    if startup_code.strip():
        # Append user startup code (helpers available via globals set in bridge)
        startup_body += textwrap.dedent(f"""
import time
time.sleep(0.5)  # let bridge start
""")

    startup_script = Path(tmp_dir) / "startup.py"
    startup_script.write_text(startup_body, encoding="utf-8")

    log.info("Launching Blender", exe=blender_exe)

    _blender_process = await asyncio.create_subprocess_exec(
        blender_exe,
        "--python", str(startup_script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Wait for bridge to be ready (up to 30 seconds)
    ready = await _bridge_ping(retries=30, interval=1.0)

    if not ready:
        if _blender_process.returncode is not None:
            stdout_b, stderr_b = await _blender_process.communicate()
            err = stderr_b.decode("utf-8", errors="replace")[-1000:]
            return f"Blender failed to start.\n\nError:\n{err}"
        return "Blender started but bridge is not responding. It may still be loading — try blender_exec in a few seconds."

    # Run startup code if provided
    if startup_code.strip():
        result = await _bridge_post({"code": startup_code}, timeout=30.0)
        if not result.get("success"):
            return f"Blender started but startup code failed: {result.get('error', '?')}"

    return (
        "Blender is open and the bridge is active.\n"
        "Use blender_exec(code) to run bpy commands.\n"
        "Use take_screenshot() to see the viewport.\n"
        "Use blender_export(format) when done."
    )


@tool(
    name="blender_exec",
    description=(
        "Execute bpy Python code in the running Blender instance. "
        "blender_start() must be called first. "
        "Pre-available helpers: clear_scene(), setup_camera(location, rotation_deg), "
        "add_light(type, location, energy), apply_smooth_shading(obj), "
        "add_material(obj, name, color_rgba), apply_modifier(obj, type, **kw), "
        "select_only(obj). "
        "bpy, math, mathutils, Vector, Euler, Matrix are already imported. "
        "Set screenshot=true to get a rendered viewport image of the result."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "bpy Python code to execute in the live Blender session.",
            },
            "screenshot": {
                "type": "boolean",
                "description": "Render the viewport after execution and return a screenshot. Default false.",
                "default": False,
            },
        },
        "required": ["code"],
    },
    risk_level="medium",
    category="blender",
)
async def blender_exec(code: str, screenshot: bool = False, **kwargs) -> str:
    """Execute bpy code in the running Blender and optionally return a viewport screenshot."""
    if _blender_process is None or _blender_process.returncode is not None:
        return "Blender is not running. Call blender_start() first."

    try:
        result = await _bridge_post(
            {"code": code, "screenshot": screenshot},
            timeout=60.0,
        )
    except Exception as e:
        return f"Bridge communication error: {e}\nIs Blender still open?"

    lines = []
    if result.get("output", "").strip():
        lines.append(f"Output:\n{result['output'].strip()}")

    if not result.get("success"):
        err = result.get("error", "unknown error")
        tb = result.get("traceback", "")
        return f"Error: {err}\n{tb}\n" + "\n".join(lines)

    lines.append("Code executed successfully.")

    # Handle viewport screenshot
    if screenshot and result.get("screenshot_b64"):
        try:
            from openacm.security.crypto import save_encrypted
            from openacm.security.crypto import get_media_dir
            file_id = secrets.token_hex(12)
            file_name = f"blender_view_{file_id}.png"
            dest = get_media_dir() / file_name
            raw = base64.b64decode(result["screenshot_b64"])
            save_encrypted(raw, dest)
            lines.append(f"ATTACHMENT:{file_name}")
            lines.append(f"Viewport screenshot: /api/media/{file_name}")
        except Exception as e:
            lines.append(f"(screenshot save failed: {e})")
    elif screenshot and result.get("screenshot_error"):
        lines.append(f"(screenshot failed: {result['screenshot_error']})")

    return "\n".join(lines)


@tool(
    name="blender_export",
    description=(
        "Export the current Blender scene to a 3D file and return a download link. "
        "blender_start() must be called first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "output_format": {
                "type": "string",
                "description": "Export format: glb (universal, default), obj, stl (3D printing), blend (native).",
                "enum": ["glb", "obj", "stl", "blend"],
                "default": "glb",
            },
        },
        "required": [],
    },
    risk_level="medium",
    category="blender",
)
async def blender_export(output_format: str = "glb", **kwargs) -> str:
    """Export the current scene from live Blender and return a download link."""
    if _blender_process is None or _blender_process.returncode is not None:
        return "Blender is not running. Call blender_start() first."

    output_format = output_format.lower()
    if output_format not in {"glb", "obj", "stl", "blend"}:
        output_format = "glb"

    file_id = secrets.token_hex(12)
    file_name = f"blender_{file_id}.{output_format}"
    tmp_out = Path(tempfile.gettempdir()) / file_name
    safe_path = str(tmp_out).replace("\\", "/")

    export_ops = {
        "glb": f"bpy.ops.export_scene.gltf(filepath=r'{safe_path}', export_format='GLB')",
        "obj": f"bpy.ops.wm.obj_export(filepath=r'{safe_path}') if hasattr(bpy.ops.wm, 'obj_export') else bpy.ops.export_scene.obj(filepath=r'{safe_path}')",
        "stl": f"bpy.ops.export_mesh.stl(filepath=r'{safe_path}')",
        "blend": f"bpy.ops.wm.save_as_mainfile(filepath=r'{safe_path}')",
    }

    code = f"import bpy\n{export_ops[output_format]}"

    try:
        result = await _bridge_post({"code": code}, timeout=60.0)
    except Exception as e:
        return f"Bridge error during export: {e}"

    if not result.get("success"):
        return f"Export failed: {result.get('error', '?')}\n{result.get('traceback', '')}"

    if not tmp_out.exists():
        return "Export command ran but no file was produced. Check format compatibility."

    try:
        from openacm.security.crypto import save_encrypted, get_media_dir
        dest = get_media_dir() / file_name
        raw = tmp_out.read_bytes()
        save_encrypted(raw, dest)
        tmp_out.unlink(missing_ok=True)
        return (
            f"ATTACHMENT:{file_name}\n"
            f"Exported {output_format.upper()} successfully ({len(raw):,} bytes).\n"
            f"Download: /api/media/{file_name}"
        )
    except Exception as e:
        return f"Failed to save export: {e}"


@tool(
    name="blender_stop",
    description="Close the running Blender session. Call when finished modeling.",
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="blender",
)
async def blender_stop(**kwargs) -> str:
    """Quit Blender gracefully."""
    global _blender_process, _addon_tmp_dir

    if _blender_process is None or _blender_process.returncode is not None:
        _blender_process = None
        return "Blender is not running."

    # Try graceful quit via bridge
    try:
        await _bridge_post({"code": "bpy.ops.wm.quit_blender()"}, timeout=5.0)
    except Exception:
        pass

    # Wait briefly, then force kill
    try:
        await asyncio.wait_for(_blender_process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        _blender_process.kill()
        await _blender_process.wait()

    _blender_process = None

    # Cleanup temp files
    if _addon_tmp_dir:
        shutil.rmtree(_addon_tmp_dir, ignore_errors=True)
        _addon_tmp_dir = None

    return "Blender closed."


@tool(
    name="blender_info",
    description=(
        "Check if Blender is installed and get its version. "
        "Also shows whether a live session is currently active."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="blender",
)
async def blender_info(**kwargs) -> str:
    """Return Blender installation info and session status."""
    blender_exe = _find_blender()
    if not blender_exe:
        return _not_found_msg()

    session_status = "No active session"
    if _blender_process is not None and _blender_process.returncode is None:
        bridge_alive = await _bridge_ping(retries=3, interval=0.5)
        session_status = "Active session — bridge " + ("responsive" if bridge_alive else "not responding")

    try:
        proc = await asyncio.create_subprocess_exec(
            blender_exe, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        ver_text = stdout_b.decode("utf-8", errors="replace").strip()
        version_line = next(
            (l for l in ver_text.splitlines() if l.startswith("Blender")),
            ver_text.splitlines()[0] if ver_text else "unknown",
        )
    except Exception as e:
        version_line = f"(could not read: {e})"

    return (
        f"Blender: {blender_exe}\n"
        f"Version: {version_line}\n"
        f"Session: {session_status}\n\n"
        f"Interactive workflow:\n"
        f"  1. blender_start()          → opens Blender + bridge\n"
        f"  2. blender_exec(code)       → run bpy commands live\n"
        f"  3. take_screenshot()        → see the viewport\n"
        f"  4. blender_export('glb')    → download the model\n"
        f"  5. blender_stop()           → close Blender"
    )


@tool(
    name="blender_run_script",
    description=(
        "Run a complete bpy script in Blender's BACKGROUND mode (no GUI). "
        "Use this for fully autonomous generation when you don't need to see the viewport. "
        "For interactive modeling with visual feedback, use blender_start + blender_exec instead. "
        "Pre-available: clear_scene(), setup_camera(), add_light(), apply_smooth_shading(), "
        "add_material(), apply_modifier(). OUTPUT_PATH is injected — do NOT export manually."
    ),
    parameters={
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "bpy code. Do not import bpy. Do not call export. Helpers are pre-defined.",
            },
            "output_format": {
                "type": "string",
                "enum": ["glb", "obj", "stl", "blend"],
                "default": "glb",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds. Default 120.",
                "default": 120,
            },
        },
        "required": ["script"],
    },
    risk_level="medium",
    category="blender",
)
async def blender_run_script(
    script: str,
    output_format: str = "glb",
    timeout: int = 120,
    **kwargs,
) -> str:
    """Batch mode: run bpy script headlessly and return the output file."""
    blender_exe = _find_blender()
    if not blender_exe:
        return _not_found_msg()

    output_format = output_format.lower()
    if output_format not in {"glb", "obj", "stl", "blend"}:
        output_format = "glb"

    file_id = secrets.token_hex(12)
    file_name = f"blender_{file_id}.{output_format}"
    tmp_dir = Path(tempfile.mkdtemp(prefix="openacm_blender_"))
    tmp_output = tmp_dir / file_name
    script_file = tmp_dir / "script.py"

    safe_out = str(tmp_output).replace("\\", "/")
    fmt = output_format.upper()

    # Helpers + user code + auto-export
    full_script = textwrap.dedent(f"""\
        import bpy, math, sys, traceback, os
        from pathlib import Path
        from mathutils import Vector, Euler, Matrix

        OUTPUT_PATH = r"{safe_out}"
        OUTPUT_FORMAT = "{fmt}"

        def clear_scene():
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            for m in list(bpy.data.meshes): bpy.data.meshes.remove(m)

        def setup_camera(location=(7,-7,5), rotation_deg=(63,0,47)):
            bpy.ops.object.camera_add(location=location)
            cam = bpy.context.active_object
            cam.rotation_euler = Euler([math.radians(d) for d in rotation_deg],'XYZ')
            bpy.context.scene.camera = cam
            return cam

        def add_light(light_type='SUN', location=(4,1,6), energy=3.0):
            bpy.ops.object.light_add(type=light_type, location=location)
            l = bpy.context.active_object
            l.data.energy = energy
            return l

        def apply_smooth_shading(obj=None):
            targets = [obj] if obj else [o for o in bpy.context.scene.objects if o.type=='MESH']
            for t in targets:
                bpy.context.view_layer.objects.active = t
                bpy.ops.object.shade_smooth()

        def add_material(obj, name="Mat", color=(0.8,0.5,0.1,1.0)):
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf: bsdf.inputs["Base Color"].default_value = color
            if obj.data.materials: obj.data.materials[0] = mat
            else: obj.data.materials.append(mat)
            return mat

        def apply_modifier(obj, mod_type, **kw):
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new(name=mod_type, type=mod_type)
            for k,v in kw.items(): setattr(mod, k, v)
            bpy.ops.object.modifier_apply(modifier=mod.name)
            return obj

        # ── User code ────────────────────────────────────────────────────
        _code = {repr(script)}
        try:
            exec(compile(_code, "<blender_ai>", "exec"), globals())
        except Exception as e:
            print(f"SCRIPT ERROR: {{e}}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

        # ── Auto-export ──────────────────────────────────────────────────
        _out = Path(OUTPUT_PATH)
        _out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if OUTPUT_FORMAT == 'GLB':
                bpy.ops.export_scene.gltf(filepath=str(_out), export_format='GLB')
            elif OUTPUT_FORMAT == 'OBJ':
                try: bpy.ops.wm.obj_export(filepath=str(_out))
                except: bpy.ops.export_scene.obj(filepath=str(_out))
            elif OUTPUT_FORMAT == 'STL':
                bpy.ops.export_mesh.stl(filepath=str(_out))
            elif OUTPUT_FORMAT == 'BLEND':
                bpy.ops.wm.save_as_mainfile(filepath=str(_out))
            print(f"Exported: {{_out}}")
        except Exception as e:
            print(f"EXPORT ERROR: {{e}}", file=sys.stderr)
            sys.exit(2)
    """)

    try:
        script_file.write_text(full_script, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            blender_exe, "--background", "--python", str(script_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: Blender timed out after {timeout}s."

        stdout_t = stdout_b.decode("utf-8", errors="replace")
        stderr_t = stderr_b.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            combined = (stdout_t + "\n" + stderr_t).strip()
            lines = [l for l in combined.splitlines() if l.strip()]
            return f"Error (exit {proc.returncode}):\n" + "\n".join(lines[-40:])

        if not tmp_output.exists():
            return "Error: Blender ran but produced no output file."

        from openacm.security.crypto import save_encrypted, get_media_dir
        dest = get_media_dir() / file_name
        raw = tmp_output.read_bytes()
        save_encrypted(raw, dest)

        return (
            f"ATTACHMENT:{file_name}\n"
            f"3D model created! Format: {output_format.upper()}, Size: {len(raw):,} bytes\n"
            f"Download: /api/media/{file_name}"
        )

    except Exception as exc:
        return f"Unexpected error: {exc}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
