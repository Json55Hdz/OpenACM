"""
Social Media Tool — post content to Facebook and Reddit.

Self-installs missing Python deps (praw, requests) at first use.
Credentials are stored encrypted in the social_credentials DB table.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import structlog

from openacm.tools.base import tool

if TYPE_CHECKING:
    from openacm.storage.database import Database

log = structlog.get_logger()

# Injected from app.py after init
_database: "Database | None" = None


def _ensure_pkg(pkg: str, import_name: str | None = None) -> bool:
    """Install a pip package if not already importable. Returns True on success."""
    import_name = import_name or pkg
    try:
        __import__(import_name)
        return True
    except ImportError:
        log.info("Installing missing package", pkg=pkg)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True
        log.error("Failed to install package", pkg=pkg, error=result.stderr[:300])
        return False


# ── Credential management ──────────────────────────────────────────────────


@tool(
    name="save_social_credentials",
    description=(
        "Save OAuth/API credentials for a social media platform (facebook or reddit). "
        "For Facebook: provide page_id, page_access_token. "
        "For Reddit: provide client_id, client_secret, username, password, user_agent."
    ),
    parameters={
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": ["facebook", "reddit"],
                "description": "The social media platform",
            },
            "credentials": {
                "type": "object",
                "description": (
                    "Credential fields. Facebook: {page_id, page_access_token}. "
                    "Reddit: {client_id, client_secret, username, password, user_agent}"
                ),
            },
        },
        "required": ["platform", "credentials"],
    },
    risk_level="medium",
    category="social",
)
async def save_social_credentials(platform: str, credentials: dict, **kwargs) -> str:
    db = _database or kwargs.get("_database")
    if not db:
        return "Error: database not available"
    creds_json = json.dumps(credentials)
    await db.save_social_credentials(platform, creds_json, verified=False)
    return f"Credentials saved for {platform}. Run verify_social_credentials to test them."


@tool(
    name="verify_social_credentials",
    description="Verify that stored credentials for a platform actually work (makes a test API call).",
    parameters={
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["facebook", "reddit"]},
        },
        "required": ["platform"],
    },
    risk_level="low",
    category="social",
)
async def verify_social_credentials(platform: str, **kwargs) -> str:
    db = _database or kwargs.get("_database")
    if not db:
        return "Error: database not available"
    row = await db.get_social_credentials(platform)
    if not row:
        return f"No credentials found for {platform}."
    creds = json.loads(row["credentials"])

    if platform == "facebook":
        ok, msg = await _verify_facebook(creds)
    elif platform == "reddit":
        ok, msg = await _verify_reddit(creds)
    else:
        return f"Unknown platform: {platform}"

    if ok:
        await db.save_social_credentials(platform, json.dumps(creds), verified=True)
        return f"✓ {platform} credentials verified: {msg}"
    return f"✗ {platform} verification failed: {msg}"


async def _verify_facebook(creds: dict) -> tuple[bool, str]:
    if not _ensure_pkg("requests"):
        return False, "Could not install requests"
    import requests
    token = creds.get("page_access_token", "")
    if not token:
        return False, "page_access_token missing"
    r = requests.get("https://graph.facebook.com/me", params={"access_token": token}, timeout=10)
    if r.ok:
        name = r.json().get("name", "?")
        return True, f"Authenticated as '{name}'"
    return False, r.json().get("error", {}).get("message", r.text[:200])


async def _verify_reddit(creds: dict) -> tuple[bool, str]:
    if not _ensure_pkg("praw"):
        return False, "Could not install praw"
    import praw
    try:
        reddit = praw.Reddit(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            username=creds["username"],
            password=creds["password"],
            user_agent=creds.get("user_agent", "OpenACM/1.0"),
        )
        me = reddit.user.me()
        return True, f"Authenticated as u/{me.name}"
    except Exception as e:
        return False, str(e)[:200]


# ── Posting tools ──────────────────────────────────────────────────────────


@tool(
    name="post_to_facebook",
    description=(
        "Publish a post (text and/or image) to a Facebook Page. "
        "Credentials must be saved first via save_social_credentials. "
        "On success, marks the content_queue item as published."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Post text/caption"},
            "image_path": {
                "type": "string",
                "description": "Absolute path to an image file (optional)",
                "default": "",
            },
            "content_queue_id": {
                "type": "integer",
                "description": "ID of the content_queue row to mark as published",
                "default": 0,
            },
        },
        "required": ["message"],
    },
    risk_level="high",
    category="social",
)
async def post_to_facebook(
    message: str,
    image_path: str = "",
    content_queue_id: int = 0,
    **kwargs,
) -> str:
    db = _database or kwargs.get("_database")
    if not db:
        return "Error: database not available"

    if not _ensure_pkg("requests"):
        return "Error: could not install 'requests' package"

    import requests

    row = await db.get_social_credentials("facebook")
    if not row:
        return "No Facebook credentials saved. Call save_social_credentials first."
    creds = json.loads(row["credentials"])
    token = creds.get("page_access_token", "")
    page_id = creds.get("page_id", "me")

    try:
        if image_path:
            url = f"https://graph.facebook.com/{page_id}/photos"
            with open(image_path, "rb") as f:
                r = requests.post(
                    url,
                    data={"caption": message, "access_token": token},
                    files={"source": f},
                    timeout=30,
                )
        else:
            url = f"https://graph.facebook.com/{page_id}/feed"
            r = requests.post(
                url,
                data={"message": message, "access_token": token},
                timeout=30,
            )

        if r.ok:
            post_id = r.json().get("id", "?")
            if db and content_queue_id:
                await db.update_content_status(content_queue_id, "published")
            return f"✓ Posted to Facebook. Post ID: {post_id}"
        else:
            err = r.json().get("error", {}).get("message", r.text[:300])
            if db and content_queue_id:
                await db.update_content_status(
                    content_queue_id, "failed", {"publish_error": err}
                )
            return f"✗ Facebook post failed: {err}"

    except Exception as e:
        return f"✗ Facebook post error: {e}"


@tool(
    name="post_to_reddit",
    description=(
        "Submit a post (link or text/self-post) to a Reddit subreddit. "
        "Credentials must be saved first via save_social_credentials. "
        "On success, marks the content_queue item as published."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subreddit": {"type": "string", "description": "Subreddit name (without r/)"},
            "title": {"type": "string", "description": "Post title"},
            "text": {
                "type": "string",
                "description": "Self-post body text (markdown). Leave empty for link post.",
                "default": "",
            },
            "url": {
                "type": "string",
                "description": "URL for link post. Leave empty for text post.",
                "default": "",
            },
            "content_queue_id": {
                "type": "integer",
                "description": "ID of the content_queue row to mark as published",
                "default": 0,
            },
        },
        "required": ["subreddit", "title"],
    },
    risk_level="high",
    category="social",
)
async def post_to_reddit(
    subreddit: str,
    title: str,
    text: str = "",
    url: str = "",
    content_queue_id: int = 0,
    **kwargs,
) -> str:
    db = _database or kwargs.get("_database")
    if not db:
        return "Error: database not available"

    if not _ensure_pkg("praw"):
        return "Error: could not install 'praw' package"

    import praw

    row = await db.get_social_credentials("reddit")
    if not row:
        return "No Reddit credentials saved. Call save_social_credentials first."
    creds = json.loads(row["credentials"])

    try:
        reddit = praw.Reddit(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            username=creds["username"],
            password=creds["password"],
            user_agent=creds.get("user_agent", "OpenACM/1.0"),
        )
        sub = reddit.subreddit(subreddit)
        if url:
            submission = sub.submit(title, url=url)
        else:
            submission = sub.submit(title, selftext=text or "")

        post_url = f"https://reddit.com{submission.permalink}"
        if db and content_queue_id:
            await db.update_content_status(content_queue_id, "published")
        return f"✓ Posted to r/{subreddit}. URL: {post_url}"

    except Exception as e:
        err_str = str(e)[:300]
        if db and content_queue_id:
            await db.update_content_status(
                content_queue_id, "failed", {"publish_error": err_str}
            )
        return f"✗ Reddit post failed: {err_str}"
