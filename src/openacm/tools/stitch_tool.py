"""
Google Stitch Tool — generates UI from natural language descriptions.

Uses the Stitch MCP server (https://stitch.googleapis.com/mcp) to create
HTML screens directly from text prompts.

Setup:
  1. Get an API key at https://stitch.withgoogle.com/ → Settings (Profile picture → Settings → API key → Create key)
  2. Add to config/.env:  STITCH_API_KEY=your-key-here

Docs: https://stitch.withgoogle.com/docs/mcp/setup
"""

import json
import os
import secrets

import httpx
import structlog

from openacm.constants import TRUNCATE_STITCH_PREVIEW_CHARS
from openacm.tools.base import tool

log = structlog.get_logger()

STITCH_MCP_URL = "https://stitch.googleapis.com/mcp"
STITCH_CONNECT_TIMEOUT = 15


def _get_api_key() -> str:
    key = os.environ.get("STITCH_API_KEY", "")
    if not key:
        raise ValueError(
            "STITCH_API_KEY not set. Get one at stitch.withgoogle.com → Profile picture → Settings → API key → Create key, "
            "then add it to config/.env as: STITCH_API_KEY=your-key-here"
        )
    return key


def _headers() -> dict:
    """Return auth headers for the Stitch MCP API."""
    return {
        "X-Goog-Api-Key": _get_api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


async def _mcp_call(tool_name: str, arguments: dict) -> dict:
    """Call a tool on the Stitch MCP server and return the parsed result."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    # No read timeout — generation can take 30–60s for complex screens
    _timeout = httpx.Timeout(connect=STITCH_CONNECT_TIMEOUT, read=None, write=30.0, pool=5.0)
    async with httpx.AsyncClient(timeout=_timeout) as client:
        async with client.stream("POST", STITCH_MCP_URL, json=payload, headers=_headers()) as resp:
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "text/event-stream" in ct:
                return await _parse_sse(resp)
            body = await resp.aread()
            return json.loads(body)


async def _parse_sse(resp) -> dict:
    """Read SSE stream and return the last data JSON object."""
    last = None
    async for line in resp.aiter_lines():
        if line.startswith("data:"):
            try:
                last = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    if last is None:
        raise ValueError("No valid data in SSE response")
    return last


async def _create_project(title: str = "OpenACM") -> str:
    """Create a Stitch project and return its ID."""
    result = await _mcp_call("create_project", {"title": title})
    content = result.get("result", {}).get("content", [])
    for item in content:
        text = item.get("text", "") if isinstance(item, dict) else ""
        try:
            data = json.loads(text)
            name = data.get("name", "")  # "projects/1234567890"
            if name:
                return name.replace("projects/", "")
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract project ID from response: {content}")


async def _generate_screen(project_id: str, prompt: str, device: str = "DESKTOP", model: str = "GEMINI_3_1_PRO") -> dict:
    """Call generate_screen_from_text and return the screen object."""
    result = await _mcp_call("generate_screen_from_text", {
        "projectId": project_id,
        "prompt": prompt,
        "deviceType": device,
        "modelId": model,
    })

    content = result.get("result", {}).get("content", [])
    for item in content:
        text = item.get("text", "") if isinstance(item, dict) else ""
        try:
            data = json.loads(text)
            for comp in data.get("outputComponents", []):
                if "design" in comp:
                    screens = comp["design"].get("screens", [])
                    if screens:
                        return screens[0]
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No screen found in Stitch response: {content[:2]}")


async def _download_html(download_url: str) -> str:
    """Download the HTML file from Stitch's CDN."""
    timeout = httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(download_url)
        resp.raise_for_status()
        return resp.text


def _save_output(content: str, ext: str) -> str:
    """Save generated content to media dir, return file_id."""
    from openacm.security.crypto import get_media_dir

    file_id = f"{secrets.token_hex(12)}{ext}"
    dest = get_media_dir() / file_id
    dest.write_text(content, encoding="utf-8")
    return file_id


@tool(
    name="stitch_generate_ui",
    description=(
        "Generate a user interface (UI) from a natural language description using Google Stitch. "
        "Creates production-quality HTML screens. "
        "Use this when the user asks to: build a screen, design a form, create a dashboard, "
        "generate a landing page, build a UI component, or anything related to visual interfaces."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed description of the UI to generate. "
                    "Example: 'Sales dashboard with a bar chart, customer table, and KPI cards in blue tones'"
                ),
            },
            "device": {
                "type": "string",
                "description": "Target device type",
                "enum": ["DESKTOP", "MOBILE", "TABLET"],
                "default": "DESKTOP",
            },
            "model": {
                "type": "string",
                "description": "Stitch generation model. GEMINI_3_1_PRO = best quality (slower), GEMINI_3_FLASH = faster.",
                "enum": ["GEMINI_3_1_PRO", "GEMINI_3_FLASH"],
                "default": "GEMINI_3_1_PRO",
            },
        },
        "required": ["prompt"],
    },
    risk_level="low",
    category="general",
)
async def stitch_generate_ui(
    prompt: str,
    device: str = "DESKTOP",
    model: str = "GEMINI_3_1_PRO",
    **ctx,
) -> str:
    """Generate UI using Google Stitch (create project → generate screen → download HTML)."""

    log.info("Stitch generating UI", device=device, model=model, prompt_len=len(prompt))

    # Notify the UI that Stitch is working
    _event_bus = ctx.get("_event_bus")
    _user_id = ctx.get("_user_id", "user")
    _channel_id = ctx.get("_channel_id")
    _channel_type = ctx.get("_channel_type", "web")
    if _event_bus:
        from openacm.core.events import EVENT_THINKING
        await _event_bus.emit(EVENT_THINKING, {
            "status": "tool_running",
            "message": f"Generating {device.lower()} UI with Google Stitch ({model})...",
            "user_id": _user_id,
            "channel_id": _channel_id,
            "channel_type": _channel_type,
        })

    try:
        # Step 1: create a project
        log.info("Stitch: creating project")
        project_id = await _create_project("OpenACM")
        log.info("Stitch: project created", project_id=project_id)

        # Step 2: generate the screen
        log.info("Stitch: generating screen")
        screen = await _generate_screen(project_id, prompt, device, model)
        screen_title = screen.get("title", "Screen")
        log.info("Stitch: screen generated", title=screen_title)

        # Step 3: download the HTML
        html_code = screen.get("htmlCode", {})
        screenshot = screen.get("screenshot", {})
        html_url = html_code.get("downloadUrl", "")
        screenshot_url = screenshot.get("downloadUrl", "")

        if not html_url:
            return f"Stitch generated the screen but no HTML download URL was provided. Screen: {screen_title}"

        log.info("Stitch: downloading HTML")
        html_content = await _download_html(html_url)
        log.info("Stitch: HTML downloaded", size=len(html_content))

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = e.response.text[:400]
        log.error("Stitch HTTP error", status=status, body=body)
        if status == 401:
            return (
                "Stitch: invalid API key (401). "
                "Go to stitch.withgoogle.com → Profile picture → Settings → API key → Create key, "
                "then update STITCH_API_KEY in config/.env."
            )
        return f"Stitch HTTP {status}: {body}"
    except ValueError as e:
        err = str(e)
        log.warning("Stitch not configured", error=err)
        if "STITCH_API_KEY" in err:
            return (
                "Stitch is not configured yet. To use this tool:\n"
                "1. Go to stitch.withgoogle.com\n"
                "2. Click your profile picture → Settings → API key → Create key\n"
                "3. In OpenACM, go to Configuration → Google Stitch and paste the key there."
            )
        return f"Stitch error: {err}"
    except Exception as e:
        err = str(e) or repr(e)
        log.error("Stitch unexpected error", error=err, exc_type=type(e).__name__)
        return f"Stitch error ({type(e).__name__}): {err}"

    # Save and return
    try:
        file_id = _save_output(html_content, ".html")
        size_kb = len(html_content.encode()) / 1024
        result = (
            f"UI generated with Google Stitch: **{screen_title}** ({device}, {size_kb:.1f} KB)\n\n"
            f"Download: /api/media/{file_id}\n"
        )
        if screenshot_url:
            result += f"Preview image: {screenshot_url}\n"
        result += f"\n```html\n{html_content[:600]}{'...' if len(html_content) > 600 else ''}\n```"
        return result
    except Exception as e:
        log.warning("Could not save stitch output", error=str(e))
        preview = html_content[:TRUNCATE_STITCH_PREVIEW_CHARS] + ("..." if len(html_content) > TRUNCATE_STITCH_PREVIEW_CHARS else "")
        return f"UI generated with Google Stitch: **{screen_title}**\n\n```html\n{preview}\n```"
