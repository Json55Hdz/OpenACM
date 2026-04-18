"""
Browser Agent — web navigation and automation via Playwright.

Allows the AI to open pages, click elements, fill forms, and extract info.
"""

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any, Optional

import structlog

from openacm.constants import TRUNCATE_BROWSER_PAGE_CHARS, TRUNCATE_BROWSER_HTML_CHARS
from openacm.tools.base import tool

log = structlog.get_logger()

# Global Playwright state
_playwright = None
_browser = None
_context = None
_page = None


async def _get_or_create_page():
    """Get the active Playwright page, initializing if necessary."""
    global _playwright, _browser, _context, _page

    if _page and not _page.is_closed():
        return _page

    try:
        from playwright.async_api import async_playwright

        if not _playwright:
            _playwright = await async_playwright().start()

        if not _browser:
            try:
                _browser = await _playwright.chromium.launch(headless=True)
            except Exception as e:
                # If chromium is missing, try to install it
                if "Executable doesn't exist" in str(e) or "install" in str(e).lower():
                    log.warning("Chromium not found, installing automatically...")
                    process = await asyncio.create_subprocess_exec(
                        "playwright", "install", "chromium"
                    )
                    await process.wait()
                    _browser = await _playwright.chromium.launch(headless=True)
                else:
                    raise

        if not _context:
            _context = await _browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

        if not _page or _page.is_closed():
            _page = await _context.new_page()

        return _page
    except Exception as e:
        log.error("Failed to initialize Playwright", error=str(e))
        raise


async def stop_browser():
    """Gracefully shutdown Playwright resources."""
    global _playwright, _browser, _context, _page
    try:
        if _page and not _page.is_closed():
            await _page.close()
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _playwright:
            await _playwright.stop()
    except Exception as e:
        log.error("Error shutting down browser", error=str(e))
    finally:
        _page = _context = _browser = _playwright = None


@tool(
    name="browser_agent",
    description=(
        "Powerful web automation tool. It opens a persistent, invisible browser that "
        "can navigate sites, render JavaScript, click buttons, fill forms, take screenshots, "
        "and extract text. The browser stays open between tool calls so you can do multi-step tasks."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["goto", "read_page", "click", "fill", "screenshot", "extract_html"],
                "description": "What to do in the browser.",
            },
            "url": {
                "type": "string",
                "description": "Used only for 'goto'. The full URL to navigate to.",
            },
            "selector": {
                "type": "string",
                "description": "Used for 'click', 'fill', or 'extract_html'. The CSS selector of the target element.",
            },
            "value": {
                "type": "string",
                "description": "Used for 'fill'. The text space to type into the element.",
            },
        },
        "required": ["action"],
    },
    risk_level="high",
    category="web",
)
async def browser_agent(
    action: str, url: str = "", selector: str = "", value: str = "", **kwargs
) -> str:
    """Execute a Playwright browser action."""
    try:
        page = await _get_or_create_page()

        if action == "goto":
            if not url:
                return "Error: 'url' parameter is required for 'goto' action."
            if not url.startswith("http"):
                url = "https://" + url
            try:
                # Usar timeout más largo (60s) y wait_until más flexible
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # Esperar un poco más para que cargue el contenido dinámico
                await asyncio.sleep(2)
                title = await page.title()
                return f"✅ Navigated to {url}. Page title: '{title}'. Use 'read_page' or 'screenshot' to see content."
            except Exception as e:
                if "timeout" in str(e).lower():
                    # Si hay timeout, intentar con la página que tengamos
                    title = await page.title()
                    return f"⚠️ Partially loaded {url} (timeout). Page title: '{title}'. The page may still be usable."
                raise

        elif action == "read_page":
            # Extract readable text from body
            text = await page.evaluate(r"""() => {
                // Remove scripts and styles
                const elements = document.querySelectorAll('script, style, noscript, svg, img');
                elements.forEach(el => el.remove());
                return document.body.innerText;
            }""")
            if not text:
                return "⚠️ Page body is empty or not loaded yet."

            # Truncate length natively for LLMs
            if len(text) > TRUNCATE_BROWSER_PAGE_CHARS:
                text = text[:TRUNCATE_BROWSER_PAGE_CHARS] + "\n\n[... content truncated due to length ...]"
            return f"📄 Page text content:\n\n{text}"

        elif action == "click":
            if not selector:
                return "Error: 'selector' parameter is required for 'click'."
            await page.click(selector, timeout=10000)
            await page.wait_for_load_state("networkidle", timeout=5000)
            return f"✅ Clicked element matching selector: '{selector}'."

        elif action == "fill":
            if not selector or value == "":
                return "Error: Both 'selector' and 'value' parameters are required for 'fill'."
            await page.fill(selector, str(value), timeout=10000)
            return f"✅ Filled element '{selector}' with value '{value}'."

        elif action == "screenshot":
            from openacm.security.crypto import save_encrypted, get_media_dir
            file_id = secrets.token_hex(16)
            file_name = f"browser_{file_id}.png"
            dest_path = get_media_dir() / file_name

            screenshot_bytes = await page.screenshot(full_page=False)
            save_encrypted(screenshot_bytes, dest_path)

            return (
                f"ATTACHMENT:{file_name}\n"
                f"✅ Browser screenshot taken. A preview will appear automatically in the chat."
            )

        elif action == "extract_html":
            if not selector:
                return "Error: 'selector' parameter is required for 'extract_html'."
            html = await page.inner_html(selector, timeout=10000)
            return f"📄 HTML content of '{selector}':\n\n{html[:TRUNCATE_BROWSER_HTML_CHARS]}"

        else:
            return f"Error: Unknown action '{action}'."

    except Exception as e:
        log.error("Browser action failed", action=action, error=str(e))
        return f"Error during '{action}': {str(e)}"
