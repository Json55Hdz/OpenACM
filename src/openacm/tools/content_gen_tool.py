"""
Content Generation Tool.

LLM-driven content pipeline:

  capture_content_moment    — Take a screenshot RIGHT NOW when something interesting happens.
                              Call this when you detect a content-worthy moment in conversation.
  generate_content_for_moment — Analyse the captured screenshot with vision, then produce
                              platform-specific post drafts and queue them for user approval.
  list_content_moments      — Browse previously captured moments.
  generate_meme             — Pillow overlay (local) or image-gen API.
  create_slideshow_video    — ffmpeg slideshow from a list of screenshots.
  check_content_deps        — Install Pillow, ffmpeg, praw if missing.

WHEN TO CALL capture_content_moment:
  • User solves a problem they described earlier ("it works!", "done!", "fixed it!")
  • A tool execution produces a visually interesting result
  • A feature is demonstrated or completed
  • Something funny/meme-worthy happens
  • A tutorial-worthy moment (step-by-step process visible on screen)
  • User expresses excitement or satisfaction about something they built

DO NOT call it for every message — only for genuinely interesting moments.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from openacm.tools.base import tool

if TYPE_CHECKING:
    from openacm.storage.database import Database
    from openacm.watchers.content_session_watcher import ContentSessionWatcher
    from openacm.core.llm_router import LLMRouter

log = structlog.get_logger()

# Injected at startup by app.py
_database: "Database | None" = None
_content_watcher: "ContentSessionWatcher | None" = None
_llm_router: "LLMRouter | None" = None

# Max image size (pixels wide) sent to vision API to keep token cost low
_VISION_MAX_WIDTH = 1024


# ── Dependency checker ─────────────────────────────────────────────────────


@tool(
    name="check_content_deps",
    description=(
        "Check if required content-generation dependencies are installed "
        "(Pillow, ffmpeg, praw) and install any that are missing. "
        "Call this before generate_meme or create_slideshow_video."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="medium",
    category="content",
)
async def check_content_deps(**kwargs) -> str:
    results = []
    for pkg, import_name in [("Pillow", "PIL"), ("requests", "requests"), ("praw", "praw"), ("mss", "mss")]:
        try:
            __import__(import_name)
            results.append(f"✓ {pkg}")
        except ImportError:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                capture_output=True, text=True,
            )
            results.append(f"✓ {pkg} (just installed)" if r.returncode == 0 else f"✗ {pkg} — {r.stderr[:80]}")

    results.append("✓ ffmpeg" if _check_ffmpeg() else ("✓ ffmpeg (just installed)" if _install_ffmpeg() else "✗ ffmpeg — install manually: winget install ffmpeg"))
    return "\n".join(results)


def _check_ffmpeg() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _install_ffmpeg() -> bool:
    for cmd in [
        ["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent"],
        ["choco", "install", "ffmpeg", "-y"],
        ["scoop", "install", "ffmpeg"],
        ["brew", "install", "ffmpeg"],
        ["apt-get", "install", "-y", "ffmpeg"],
    ]:
        try:
            if subprocess.run(cmd, capture_output=True, timeout=120).returncode == 0 and _check_ffmpeg():
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


# ── Main: capture a content moment ────────────────────────────────────────


@tool(
    name="capture_content_moment",
    description=(
        "📸 Capture the current screen as a content moment for social media.\n\n"
        "Call this when you detect a genuinely interesting moment: problem solved, "
        "feature completed, impressive result, funny situation, or tutorial-worthy step.\n\n"
        "This takes ONE screenshot of the active window and queues it for content generation. "
        "Returns a moment_id that you can pass to generate_content_for_moment."
    ),
    parameters={
        "type": "object",
        "properties": {
            "context": {
                "type": "string",
                "description": (
                    "Why is this moment interesting? What just happened? "
                    "This becomes the basis for the social post. Be specific: "
                    "e.g. 'Fixed the WebSocket reconnection bug that was causing dropped messages' "
                    "or 'The AI just controlled the smart TV to pause the movie automatically'."
                ),
            },
            "moment_type": {
                "type": "string",
                "enum": ["achievement", "problem_solved", "demo", "progress", "funny", "tutorial"],
                "description": "Type of moment — affects post tone and framing.",
                "default": "achievement",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topic tags, e.g. ['python', 'AI', 'bug-fix']",
                "default": [],
            },
            "generate_immediately": {
                "type": "boolean",
                "description": (
                    "If true, immediately generate social post drafts using vision analysis "
                    "and queue them for approval. If false, just capture — you can call "
                    "generate_content_for_moment later."
                ),
                "default": True,
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string", "enum": ["facebook", "reddit"]},
                "description": "Platforms to generate posts for (only used when generate_immediately=true).",
                "default": ["facebook", "reddit"],
            },
        },
        "required": ["context"],
    },
    risk_level="low",
    category="content",
)
async def capture_content_moment(
    context: str,
    moment_type: str = "achievement",
    tags: list[str] | None = None,
    generate_immediately: bool = True,
    platforms: list[str] | None = None,
    **kwargs,
) -> str:
    watcher = _content_watcher or kwargs.get("_content_watcher")
    if not watcher:
        return "Error: ContentSessionWatcher not available"

    meta = await watcher.capture_now(context=context, moment_type=moment_type, tags=tags or [])
    moment_id = meta["moment_id"]

    lines = [f"📸 Moment captured! ID: `{moment_id}`"]
    if meta.get("image_path"):
        lines.append(f"Screenshot: {meta['image_path']}")
    if meta.get("capture_error"):
        lines.append(f"⚠ Screenshot failed: {meta['capture_error']} (content can still be generated from context)")

    if generate_immediately:
        lines.append("")
        gen_result = await _generate_posts_for_moment(
            meta=meta,
            platforms=platforms or ["facebook", "reddit"],
        )
        lines.append(gen_result)

    return "\n".join(lines)


# ── Generate content from a moment ────────────────────────────────────────


@tool(
    name="generate_content_for_moment",
    description=(
        "Generate social media post drafts for a previously captured moment. "
        "Uses vision AI to analyse the screenshot, then writes platform-specific copy. "
        "Posts are queued for your approval — nothing is published automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "moment_id": {
                "type": "string",
                "description": "Moment ID returned by capture_content_moment.",
            },
            "platforms": {
                "type": "array",
                "items": {"type": "string", "enum": ["facebook", "reddit"]},
                "description": "Platforms to generate posts for.",
                "default": ["facebook", "reddit"],
            },
            "extra_context": {
                "type": "string",
                "description": "Additional context to include when writing the post.",
                "default": "",
            },
        },
        "required": ["moment_id"],
    },
    risk_level="low",
    category="content",
)
async def generate_content_for_moment(
    moment_id: str,
    platforms: list[str] | None = None,
    extra_context: str = "",
    **kwargs,
) -> str:
    watcher = _content_watcher or kwargs.get("_content_watcher")
    if not watcher:
        return "Error: ContentSessionWatcher not available"

    meta = watcher.get_moment(moment_id)
    if not meta:
        return f"Error: moment `{moment_id}` not found"

    if extra_context:
        meta = {**meta, "context": meta["context"] + "\n\nAdditional context: " + extra_context}

    return await _generate_posts_for_moment(meta=meta, platforms=platforms or ["facebook", "reddit"])


# ── Internal: vision analysis + post writing ──────────────────────────────


async def _analyse_screenshot_vision(img_path: str) -> str:
    """
    Use the LLM router (vision model) to describe what's on screen.
    Falls back to an empty string if vision is not available.
    """
    router = _llm_router
    if not router or not img_path or not Path(img_path).exists():
        return ""

    try:
        from PIL import Image as _Image
    except ImportError:
        return ""

    try:
        # Resize to keep token cost reasonable
        img = _Image.open(img_path).convert("RGB")
        if img.width > _VISION_MAX_WIDTH:
            ratio = _VISION_MAX_WIDTH / img.width
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Describe what you see on this screen in 2-4 sentences. "
                            "Focus on what the developer is working on, any results visible, "
                            "code, UI, terminal output, or error messages. "
                            "Be specific and technical — this description will be used "
                            "to write a social media post about the work."
                        ),
                    },
                ],
            }
        ]

        result = await router.chat(messages)
        return result.get("content", "").strip()

    except Exception as exc:
        log.debug("Vision analysis failed", error=str(exc))
        return ""


async def _generate_posts_for_moment(meta: dict, platforms: list[str]) -> str:
    """
    Core: analyse screenshot + write posts for each platform + queue for approval.
    Returns a summary string.
    """
    db = _database
    context = meta.get("context", "")
    moment_id = meta["moment_id"]
    moment_type = meta.get("moment_type", "achievement")
    img_path = meta.get("image_path")
    tags = meta.get("tags", [])
    active_title = meta.get("active_title", "")

    # Step 1: vision analysis
    vision_desc = await _analyse_screenshot_vision(img_path) if img_path else ""

    # Step 2: build full context for the writer
    full_context = context
    if vision_desc:
        full_context += f"\n\nWhat's visible on screen: {vision_desc}"
    if active_title:
        full_context += f"\n\nActive window: {active_title}"

    # Step 3: generate copy per platform
    queued_ids: list[int] = []
    summaries: list[str] = []

    for platform in platforms:
        post = await _write_post(platform=platform, context=full_context, moment_type=moment_type, tags=tags)

        if db:
            media = [img_path] if img_path else []
            item_id = await db.create_content_item(
                platform=platform,
                content_type="post",
                title=post["title"],
                body=post["body"],
                media_paths=json.dumps(media),
                metadata=json.dumps({
                    "moment_id": moment_id,
                    "moment_type": moment_type,
                    "tags": tags,
                    "vision_description": vision_desc,
                    "subreddit": post.get("subreddit", ""),
                    "hashtags": post.get("hashtags", []),
                }),
                swarm_id=None,
            )
            queued_ids.append(item_id)
            summaries.append(f"  • {platform.upper()} → queued (ID {item_id}): \"{post['title'][:60]}\"")
        else:
            # No DB: just log the generated content
            summaries.append(f"  • {platform.upper()} (not saved — DB unavailable):\n{post['title']}\n{post['body'][:200]}")

    result_lines = [f"✅ Generated {len(summaries)} post draft(s) for moment `{moment_id}`:"]
    result_lines.extend(summaries)
    if queued_ids:
        result_lines.append("\nOpen the /content page in the dashboard to review and approve before publishing.")
    return "\n".join(result_lines)


async def _write_post(platform: str, context: str, moment_type: str, tags: list[str]) -> dict:
    """
    Ask the LLM to write a social media post. Falls back to a template if no router.
    """
    router = _llm_router

    tone_map = {
        "achievement":    "proud and celebratory, behind-the-scenes dev vibe",
        "problem_solved": "relieved and technical, 'we fixed the bug' energy",
        "demo":           "excited demo energy, showing off what it can do",
        "progress":       "progress update, building in public style",
        "funny":          "self-deprecating and funny, dev humour",
        "tutorial":       "educational, step-by-step, helpful",
    }
    tone = tone_map.get(moment_type, "casual and engaging")

    platform_guides = {
        "facebook": (
            "Facebook Page post. 1-3 short paragraphs. Conversational, behind-the-scenes dev feel. "
            "End with a question to drive comments. Include 3-5 hashtags at the end."
        ),
        "reddit": (
            "Reddit self-post. Write a punchy title (< 80 chars) and a genuine body. "
            "Reddit hates marketing speak — be honest, technical, and interesting. "
            "Include a suggested subreddit (e.g. r/programming, r/SideProject, r/MachineLearning)."
        ),
    }
    guide = platform_guides.get(platform, "Short social media post, casual tone.")

    if router:
        prompt = (
            f"Write a {platform} post about this development moment.\n\n"
            f"Platform guidelines: {guide}\n"
            f"Tone: {tone}\n"
            f"Tags/topics: {', '.join(tags) if tags else 'general dev'}\n\n"
            f"Context:\n{context}\n\n"
            f"Return ONLY a JSON object with keys: "
            f"\"title\" (short headline or Reddit title), "
            f"\"body\" (the post body), "
            f"and for Reddit also \"subreddit\" (e.g. 'r/SideProject')."
            f"For Facebook also \"hashtags\" (list of 3-5 strings without #)."
        )
        try:
            result = await router.chat([{"role": "user", "content": prompt}])
            raw = result.get("content", "").strip()
            # Extract JSON from possible markdown code fence
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as exc:
            log.debug("Post writer LLM failed", error=str(exc))

    # Fallback template
    return {
        "title": f"[{moment_type.replace('_', ' ').title()}] {context[:60]}",
        "body": context,
        "hashtags": tags,
        "subreddit": "r/SideProject",
    }


# ── Browse captured moments ────────────────────────────────────────────────


@tool(
    name="list_content_moments",
    description=(
        "List previously captured content moments. "
        "Optionally filter by date (YYYY-MM-DD). Returns metadata for each moment."
    ),
    parameters={
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "Date to filter (YYYY-MM-DD). Leave empty for recent moments.",
                "default": "",
            },
            "limit": {
                "type": "integer",
                "description": "Max moments to return.",
                "default": 10,
            },
        },
        "required": [],
    },
    risk_level="low",
    category="content",
)
async def list_content_moments(date: str = "", limit: int = 10, **kwargs) -> str:
    watcher = _content_watcher or kwargs.get("_content_watcher")
    if not watcher:
        return "Error: ContentSessionWatcher not available"

    moments = watcher.list_moments(date_str=date or None, limit=limit)
    if not moments:
        return f"No moments captured yet{' for ' + date if date else ''}."

    lines = [f"📋 {len(moments)} moment(s):\n"]
    for m in moments:
        has_img = "📸" if m.get("image_path") else "📝"
        lines.append(
            f"{has_img} `{m['moment_id']}` [{m['moment_type']}] {m['timestamp'][:16]}\n"
            f"   {m['context'][:80]}\n"
            f"   App: {m.get('active_title', '?')[:50]}"
        )
    return "\n".join(lines)


# ── Meme generator ─────────────────────────────────────────────────────────


@tool(
    name="generate_meme",
    description=(
        "Generate a meme image from a screenshot or blank template. "
        "Two modes: 'local' (Pillow, free) or 'api' (image-gen API). "
        "Returns the path to the generated image."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["local", "api"], "default": "local"},
            "top_text": {"type": "string", "default": ""},
            "bottom_text": {"type": "string", "default": ""},
            "base_image_path": {"type": "string", "default": ""},
            "api_prompt": {"type": "string", "default": ""},
            "output_filename": {"type": "string", "default": ""},
        },
        "required": [],
    },
    risk_level="low",
    category="content",
)
async def generate_meme(
    mode: str = "local",
    top_text: str = "",
    bottom_text: str = "",
    base_image_path: str = "",
    api_prompt: str = "",
    output_filename: str = "",
    **kwargs,
) -> str:
    import time as _time
    workspace = Path(os.environ.get("OPENACM_WORKSPACE", "workspace"))
    out_dir = workspace / "content" / "memes"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = output_filename or f"meme_{int(_time.time())}.png"
    out_path = out_dir / fname

    if mode == "api":
        return await _generate_meme_api(api_prompt or f"{top_text} {bottom_text}", out_path)
    return _generate_meme_local(top_text, bottom_text, base_image_path, out_path)


def _generate_meme_local(top: str, bottom: str, base: str, out: Path) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return "Error: Pillow not installed. Run check_content_deps first."

    W, H = 800, 600
    if base and Path(base).exists():
        img = Image.open(base).convert("RGB").resize((W, H))
    else:
        img = Image.new("RGB", (W, H), color=(30, 30, 30))

    draw = ImageDraw.Draw(img)
    font_size = 52
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/Impact.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    def draw_outlined(text: str, y_frac: float):
        if not text:
            return
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2
        y = int(H * y_frac)
        for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text((x + ox, y + oy), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=(255, 255, 255))

    draw_outlined(top.upper(), 0.04)
    draw_outlined(bottom.upper(), 0.82)
    img.save(out, format="PNG")
    return f"Meme generated: {out}"


async def _generate_meme_api(prompt: str, out: Path) -> str:
    import requests as _req
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        stab_key = os.environ.get("STABILITY_API_KEY", "")
        if stab_key:
            return await _generate_stability(prompt, out, stab_key)
        return "Error: no image-gen API key (set OPENAI_API_KEY or STABILITY_API_KEY)"
    r = _req.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"prompt": prompt, "n": 1, "size": "1024x1024", "model": "dall-e-3"},
        timeout=60,
    )
    if not r.ok:
        return f"Image gen API error: {r.text[:300]}"
    url = r.json()["data"][0]["url"]
    out.write_bytes(_req.get(url, timeout=30).content)
    return f"Meme generated via API: {out}"


async def _generate_stability(prompt: str, out: Path, api_key: str) -> str:
    import requests as _req
    r = _req.post(
        "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        json={"text_prompts": [{"text": prompt}], "width": 1024, "height": 1024},
        timeout=60,
    )
    if not r.ok:
        return f"Stability API error: {r.text[:300]}"
    out.write_bytes(base64.b64decode(r.json()["artifacts"][0]["base64"]))
    return f"Meme generated via Stability: {out}"


# ── Slideshow video ────────────────────────────────────────────────────────


@tool(
    name="create_slideshow_video",
    description=(
        "Create a short MP4 slideshow from a list of screenshot paths using ffmpeg. "
        "Good for showing a before/after or step-by-step process as a single video post."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Absolute paths to PNG/JPG images in order.",
            },
            "duration_per_image": {"type": "number", "default": 3.0},
            "output_filename": {"type": "string", "default": ""},
            "add_caption": {"type": "string", "default": ""},
        },
        "required": ["image_paths"],
    },
    risk_level="medium",
    category="content",
)
async def create_slideshow_video(
    image_paths: list[str],
    duration_per_image: float = 3.0,
    output_filename: str = "",
    add_caption: str = "",
    **kwargs,
) -> str:
    if not image_paths:
        return "Error: no image paths provided"
    if not _check_ffmpeg():
        return "Error: ffmpeg not found. Run check_content_deps to install it."

    import time as _time
    workspace = Path(os.environ.get("OPENACM_WORKSPACE", "workspace"))
    out_dir = workspace / "content" / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = output_filename or f"slideshow_{int(_time.time())}.mp4"
    out_path = out_dir / fname

    concat_file = out_dir / f"_concat_{int(_time.time())}.txt"
    lines_txt = []
    valid_paths = [p for p in image_paths if Path(p).exists()]
    for p in valid_paths:
        lines_txt += [f"file '{p}'", f"duration {duration_per_image}"]
    if not lines_txt:
        return "Error: none of the image paths exist"
    lines_txt.append(f"file '{valid_paths[-1]}'")
    concat_file.write_text("\n".join(lines_txt))

    vf = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
    if add_caption:
        safe = add_caption.replace("'", "\\'").replace(":", "\\:")
        vf += f",drawtext=text='{safe}':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=h-60:box=1:boxcolor=black@0.5"

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
           "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", str(out_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        concat_file.unlink(missing_ok=True)
        if r.returncode == 0:
            size_mb = out_path.stat().st_size / (1024 * 1024)
            return f"Video created: {out_path} ({size_mb:.1f} MB, {len(valid_paths)} frames)"
        return f"ffmpeg error: {r.stderr[-500:]}"
    except subprocess.TimeoutExpired:
        return "Error: ffmpeg timed out"


# ── Content approval queue ─────────────────────────────────────────────────


@tool(
    name="queue_content_for_approval",
    description=(
        "Manually queue a post for user approval. "
        "Prefer capture_content_moment (which queues automatically) for standard flow."
    ),
    parameters={
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["facebook", "reddit"]},
            "content_type": {"type": "string", "enum": ["post", "meme", "video"]},
            "title": {"type": "string"},
            "body": {"type": "string", "default": ""},
            "media_paths": {"type": "array", "items": {"type": "string"}, "default": []},
            "metadata": {"type": "object", "default": {}},
        },
        "required": ["platform", "content_type", "title"],
    },
    risk_level="low",
    category="content",
)
async def queue_content_for_approval(
    platform: str,
    content_type: str,
    title: str,
    body: str = "",
    media_paths: list[str] | None = None,
    metadata: dict | None = None,
    **kwargs,
) -> str:
    db = _database or kwargs.get("_database")
    if not db:
        return "Error: database not available"
    item_id = await db.create_content_item(
        platform=platform, content_type=content_type, title=title, body=body,
        media_paths=json.dumps(media_paths or []),
        metadata=json.dumps(metadata or {}), swarm_id=None,
    )
    return f"✓ Queued (ID: {item_id}). Open /content to review."


@tool(
    name="list_pending_approvals",
    description="List content items waiting for user approval.",
    parameters={"type": "object", "properties": {}, "required": []},
    risk_level="low",
    category="content",
)
async def list_pending_approvals(**kwargs) -> str:
    db = _database or kwargs.get("_database")
    if not db:
        return "Error: database not available"
    items = await db.get_content_queue(status="pending", limit=20)
    if not items:
        return "No pending content in the approval queue."
    lines = [f"📋 {len(items)} pending:\n"]
    for item in items:
        lines.append(
            f"  [{item['id']}] {item['platform'].upper()} {item['content_type']} "
            f"— \"{item['title'][:60]}\" ({item['created_at'][:10]})"
        )
    return "\n".join(lines)
