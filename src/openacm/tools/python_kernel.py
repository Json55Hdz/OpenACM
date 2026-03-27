"""
Python Kernel — interactive code execution using Jupyter.

Allows the AI to execute Python code, maintain variables in memory,
install dependencies, and generate plots visually.
"""

import asyncio
import secrets
import base64
from pathlib import Path

import structlog
from openacm.tools.base import tool

log = structlog.get_logger()

# Global Kernel State
_kernel_manager = None
_kernel_client = None


async def _get_or_create_kernel():
    """Get or start the Jupyter kernel."""
    global _kernel_manager, _kernel_client
    if _kernel_manager and _kernel_manager.is_alive():
        return _kernel_manager, _kernel_client

    try:
        from jupyter_client import KernelManager

        _kernel_manager = KernelManager(kernel_name="python3")
        _kernel_manager.start_kernel()
        _kernel_client = _kernel_manager.client()
        _kernel_client.start_channels()

        # Give it a second to boot
        await asyncio.sleep(1.5)
        log.info("Jupyter kernel started")
        return _kernel_manager, _kernel_client
    except Exception as e:
        log.error("Failed to start Jupyter kernel", error=str(e))
        raise


async def stop_kernel():
    """Gracefully shutdown the Jupyter kernel."""
    global _kernel_manager, _kernel_client
    try:
        if _kernel_client:
            _kernel_client.stop_channels()
        if _kernel_manager and _kernel_manager.is_alive():
            _kernel_manager.shutdown_kernel()
    except Exception as e:
        log.error("Failed to stop kernel", error=str(e))
    finally:
        _kernel_manager = _kernel_client = None


@tool(
    name="run_python",
    description=(
        "Powerful interactive Python environment. Code executed here runs in a persistent "
        "Jupyter-like kernel. Variables, functions, and imports are saved in memory between calls. "
        "If you generate plots (e.g. using matplotlib), they will be automatically captured "
        "and rendered to the user. You can use this for math, data analysis, or scripting."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute. Can be multiple lines.",
            },
            "reset": {
                "type": "boolean",
                "description": "If true, restarts the kernel (clearing all variables) before running.",
                "default": False,
            },
        },
        "required": ["code"],
    },
    risk_level="high",  # Arbitrary Python execution is high risk
)
async def run_python(code: str, reset: bool = False, **kwargs) -> str:
    """Execute Python code interactively."""
    global _kernel_manager, _kernel_client
    try:
        import queue
        from openacm.security.crypto import save_encrypted

        if reset:
            await stop_kernel()

        km, kc = await _get_or_create_kernel()

        # Execute the code
        msg_id = kc.execute(code)

        output_parts = []
        media_files = []

        # Collect results
        status_idle = False

        while not status_idle:
            try:
                # Need awaitable or thread for queue.get if it blocks heavily,
                # but timeout=1 handles it in chunks
                msg = await asyncio.to_thread(kc.get_iopub_msg, timeout=2)

                # Check if this msg belongs to our execution
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue

                msg_type = msg["msg_type"]
                content = msg["content"]

                if msg_type == "status" and content.get("execution_state") == "idle":
                    status_idle = True

                elif msg_type == "stream":
                    text = content.get("text", "")
                    output_parts.append(text)

                elif msg_type == "error":
                    # Execution threw an error
                    err_name = content.get("ename", "Error")
                    err_value = content.get("evalue", "")
                    tb = "\n".join(content.get("traceback", []))

                    # Remove ANSI colors from jupyter traceback for clean text
                    import re

                    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
                    tb_clean = ansi_escape.sub("", tb)
                    output_parts.append(f"❌ {err_name}: {err_value}\n{tb_clean}")

                elif msg_type in ["display_data", "execute_result"]:
                    data = content.get("data", {})

                    # Priority 1: Images
                    if "image/png" in data:
                        png_b64 = data["image/png"]
                        # SECURITY: POR DISEÑO - Decodifica imágenes matplotlib del kernel
                        raw_bytes = base64.b64decode(png_b64)

                        file_id = secrets.token_hex(16)
                        file_name = f"plot_{file_id}.png"
                        dest_path = Path("data/media") / file_name

                        save_encrypted(raw_bytes, dest_path)
                        media_files.append(file_name)

                    # Priority 2: Text representation
                    elif "text/plain" in data:
                        output_parts.append(data["text/plain"])

            except queue.Empty:
                # If we timeout without getting idle, assume it's stuck or we missed it
                output_parts.append("\n[Execution interrupted or timed out reading stream]")
                break

        # Format the final response
        final_text = "".join(output_parts).strip()

        # If no text but images were produced
        if not final_text and not media_files:
            return "✅ Code executed successfully. (No output generated)"

        result = []
        if final_text:
            result.append("📄 Output:\n```text\n" + final_text + "\n```")

        if media_files:
            result.append(
                "✅ Generated plots/images! You MUST include these URLs in your message so the user can see them:"
            )
            for m in media_files:
                result.append(f"/api/media/{m}")

        return "\n\n".join(result)

    except Exception as e:
        log.error("run_python execution failed", error=str(e))
        return f"Error executing python: {str(e)}"
