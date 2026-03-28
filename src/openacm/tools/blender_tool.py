"""
Blender Tool — create 3D models by executing bpy (Blender Python API) scripts headlessly.

The AI writes bpy code; this tool wraps it in a safe execution template,
runs Blender in background mode (no GUI), and saves the output file to
data/media/ for download via /api/media/.

Requirements:
  - Blender installed and accessible (or BLENDER_PATH env var set)
  - pip install -e . (google-api-python-client etc. not needed here)

Usage by AI:
  Call blender_run_script with a bpy script. The following are pre-available:
    - clear_scene()
    - setup_camera(location, rotation_deg)
    - add_light(type, location, energy)
    - apply_smooth_shading(obj=None)
  OUTPUT_PATH and OUTPUT_FORMAT are injected — DO NOT export manually.
"""

import asyncio
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


# ─── Blender discovery ────────────────────────────────────────────────────────

def _find_blender() -> str | None:
    """Return the path to the Blender executable, or None if not found."""

    # 1. User-defined env override
    env_path = os.environ.get("BLENDER_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path

    # 2. System PATH
    found = shutil.which("blender")
    if found:
        return found

    system = platform.system()

    # 3. Well-known platform-specific locations
    if system == "Windows":
        search_roots = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Programs",
        ]
        for root in search_roots:
            bf_dir = root / "Blender Foundation"
            if bf_dir.is_dir():
                candidates = sorted(
                    bf_dir.glob("Blender */blender.exe"), reverse=True
                )
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
            "/usr/bin/blender",
            "/usr/local/bin/blender",
            "/opt/blender/blender",
            str(Path.home() / "blender" / "blender"),
            "/snap/bin/blender",
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
    "Windows": "Download installer from https://www.blender.org/download/ or set BLENDER_PATH env var.",
    "Darwin":  "Install via https://www.blender.org/download/ or 'brew install --cask blender'.",
    "Linux":   "Run: sudo apt install blender  OR  sudo snap install blender --classic",
}


def _not_found_msg() -> str:
    hint = _INSTALL_HINTS.get(platform.system(), "See https://www.blender.org/download/")
    return (
        "Blender is not installed or not found on this system.\n\n"
        f"Install hint: {hint}\n\n"
        "After installing, you may also set the BLENDER_PATH environment variable "
        "to the full path of the blender executable if it is not on the system PATH."
    )


# ─── Script wrapper ───────────────────────────────────────────────────────────

def _build_script(user_code: str, output_path: str, output_format: str) -> str:
    """
    Wrap the AI's bpy code with imports, helpers, and auto-export logic.
    Uses exec() to preserve the user code's indentation exactly.
    """
    safe_output = output_path.replace("\\", "/")
    fmt = output_format.upper()

    # The user code is embedded as a raw string inside exec(); triple-backtick
    # delimiters are replaced to avoid breaking the string literal.
    safe_user_code = user_code.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')

    return textwrap.dedent(f'''\
        import bpy
        import sys
        import math
        import traceback
        from pathlib import Path
        from mathutils import Vector, Euler

        # ── Injected by OpenACM blender_tool ────────────────────────────
        OUTPUT_PATH = r"{safe_output}"
        OUTPUT_FORMAT = "{fmt}"
        # ────────────────────────────────────────────────────────────────

        # ── Helper library ───────────────────────────────────────────────

        def clear_scene():
            """Remove all objects and orphan mesh data from the default scene."""
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            for block in list(bpy.data.meshes):
                bpy.data.meshes.remove(block)
            for block in list(bpy.data.lights):
                bpy.data.lights.remove(block)

        def setup_camera(location=(7, -7, 5), rotation_deg=(63, 0, 47)):
            """Add a camera and set it as the active scene camera."""
            bpy.ops.object.camera_add(location=location)
            cam = bpy.context.active_object
            cam.rotation_euler = Euler(
                [math.radians(d) for d in rotation_deg], 'XYZ'
            )
            bpy.context.scene.camera = cam
            return cam

        def add_light(light_type='SUN', location=(4, 1, 6), energy=3.0):
            """Add a light. light_type: 'SUN'|'POINT'|'SPOT'|'AREA'."""
            bpy.ops.object.light_add(type=light_type, location=location)
            light = bpy.context.active_object
            light.data.energy = energy
            return light

        def apply_smooth_shading(obj=None):
            """Apply smooth shading to a mesh object or all mesh objects."""
            targets = [obj] if obj else [
                o for o in bpy.context.scene.objects if o.type == 'MESH'
            ]
            for target in targets:
                bpy.context.view_layer.objects.active = target
                bpy.ops.object.shade_smooth()

        def add_material(obj, name="Material", color=(0.8, 0.4, 0.1, 1.0)):
            """Create a basic PBR material and assign it to obj."""
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = color
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)
            return mat

        def apply_modifier(obj, modifier_type, **settings):
            """Add and apply a modifier. modifier_type e.g. 'SUBSURF', 'BEVEL', 'BOOLEAN'."""
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new(name=modifier_type, type=modifier_type)
            for k, v in settings.items():
                setattr(mod, k, v)
            bpy.ops.object.modifier_apply(modifier=mod.name)
            return obj

        # ── User script (exec for clean indentation handling) ────────────
        _user_code = """
{user_code}
"""

        try:
            exec(compile(_user_code, "<blender_ai_script>", "exec"), globals())
        except SystemExit:
            raise
        except Exception as _err:
            print(f"[blender_tool] SCRIPT ERROR: {{_err}}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

        # ── Auto-export ──────────────────────────────────────────────────
        _out = Path(OUTPUT_PATH)
        _out.parent.mkdir(parents=True, exist_ok=True)

        try:
            if OUTPUT_FORMAT == 'GLB':
                bpy.ops.export_scene.gltf(
                    filepath=str(_out),
                    export_format='GLB',
                    use_selection=False,
                )
            elif OUTPUT_FORMAT == 'OBJ':
                # Blender 3.x+
                try:
                    bpy.ops.wm.obj_export(
                        filepath=str(_out),
                        export_selected_objects=False,
                    )
                except AttributeError:
                    bpy.ops.export_scene.obj(filepath=str(_out))
            elif OUTPUT_FORMAT == 'STL':
                bpy.ops.export_mesh.stl(
                    filepath=str(_out),
                    use_selection=False,
                )
            elif OUTPUT_FORMAT == 'BLEND':
                bpy.ops.wm.save_as_mainfile(filepath=str(_out))
            print(f"[blender_tool] Exported: {{_out}}")
        except Exception as _export_err:
            print(f"[blender_tool] EXPORT ERROR: {{_export_err}}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(2)
    ''').replace("{user_code}", user_code)


# ─── Tools ────────────────────────────────────────────────────────────────────

@tool(
    name="blender_run_script",
    description=(
        "Execute a Blender Python (bpy) script headlessly to create or modify 3D models. "
        "Write bpy code as if running inside Blender's Python console. "
        "Pre-defined helpers: clear_scene(), setup_camera(location, rotation_deg), "
        "add_light(light_type, location, energy), apply_smooth_shading(obj), "
        "add_material(obj, name, color_rgba), apply_modifier(obj, type, **settings). "
        "OUTPUT_PATH and OUTPUT_FORMAT are already injected — DO NOT call export functions yourself. "
        "Do NOT import bpy — it is already imported. "
        "Returns a download link to the generated 3D file (.glb by default)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": (
                    "Pure bpy Python code. bpy, math, mathutils are pre-imported. "
                    "Helpers available: clear_scene(), setup_camera(), add_light(), "
                    "apply_smooth_shading(), add_material(), apply_modifier(). "
                    "Do NOT call export functions. OUTPUT_PATH is injected."
                ),
            },
            "output_format": {
                "type": "string",
                "description": "3D export format: glb (default, universal), obj, stl (for printing), blend (native).",
                "enum": ["glb", "obj", "stl", "blend"],
                "default": "glb",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to allow Blender to run. Default 120. Complex scenes may need 300.",
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
    """Run a bpy script in Blender's background mode and return the output file."""
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

    try:
        wrapped = _build_script(script, str(tmp_output), output_format)
        script_file.write_text(wrapped, encoding="utf-8")

        log.info("Running Blender", exe=blender_exe, format=output_format, timeout=timeout)

        proc = await asyncio.create_subprocess_exec(
            blender_exe,
            "--background",
            "--python", str(script_file),
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
            return (
                f"Error: Blender timed out after {timeout}s.\n"
                "Try a simpler script, reduce geometry complexity, or increase timeout."
            )

        stdout_text = stdout_b.decode("utf-8", errors="replace")
        stderr_text = stderr_b.decode("utf-8", errors="replace")

        log.info(
            "Blender finished",
            exit_code=proc.returncode,
            output_lines=stdout_text.count("\n"),
        )

        if proc.returncode != 0:
            combined = (stdout_text + "\n" + stderr_text).strip()
            # Show the most relevant tail (skip Blender's verbose startup noise)
            lines = [l for l in combined.splitlines() if l.strip()]
            relevant = "\n".join(lines[-40:])
            return (
                f"Error: Blender exited with code {proc.returncode}.\n\n"
                f"Output (last 40 lines):\n{relevant}"
            )

        if not tmp_output.exists():
            combined = (stdout_text + "\n" + stderr_text).strip()
            lines = [l for l in combined.splitlines() if l.strip()]
            return (
                "Error: Blender ran but did not produce an output file.\n\n"
                "Output:\n" + "\n".join(lines[-20:])
            )

        # Save to data/media/ (encrypted)
        try:
            from openacm.security.crypto import save_encrypted
            dest_path = Path("data/media") / file_name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            raw_bytes = tmp_output.read_bytes()
            save_encrypted(raw_bytes, dest_path)
            file_size = len(raw_bytes)
        except Exception as e:
            log.error("Failed to save blender output", error=str(e))
            return f"Error saving output file: {e}"

        return (
            f"ATTACHMENT:{file_name}\n"
            f"3D model created successfully!\n"
            f"Format: {output_format.upper()}  |  Size: {file_size:,} bytes\n"
            f"Download: /api/media/{file_name}"
        )

    except Exception as exc:
        log.error("blender_run_script unexpected error", error=str(exc))
        return f"Unexpected error running Blender: {exc}"

    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@tool(
    name="blender_info",
    description=(
        "Check if Blender is installed on this system and get its version. "
        "Call this before blender_run_script if you are unsure whether Blender is available."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    risk_level="low",
    category="blender",
)
async def blender_info(**kwargs) -> str:
    """Return info about the available Blender installation."""
    blender_exe = _find_blender()
    if not blender_exe:
        return _not_found_msg()

    try:
        proc = await asyncio.create_subprocess_exec(
            blender_exe, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        version_text = stdout_b.decode("utf-8", errors="replace").strip()
        version_line = next(
            (l for l in version_text.splitlines() if l.startswith("Blender")),
            version_text.splitlines()[0] if version_text else "unknown",
        )
    except Exception as e:
        version_line = f"(could not read version: {e})"

    # Get bundled Python version
    bpy_python = "unknown"
    try:
        proc2 = await asyncio.create_subprocess_exec(
            blender_exe,
            "--background",
            "--python-expr",
            "import sys; print('BPY_PYTHON:', sys.version.split()[0])",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out2_b, _ = await asyncio.wait_for(proc2.communicate(), timeout=20.0)
        out2 = out2_b.decode("utf-8", errors="replace")
        for line in out2.splitlines():
            if "BPY_PYTHON:" in line:
                bpy_python = line.split("BPY_PYTHON:")[-1].strip()
                break
    except Exception:
        pass

    return (
        f"Blender found: {blender_exe}\n"
        f"Version: {version_line}\n"
        f"Bundled Python: {bpy_python}\n"
        f"Status: Ready — use blender_run_script to create 3D models"
    )
