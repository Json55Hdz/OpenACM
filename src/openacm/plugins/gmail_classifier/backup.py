"""Gmail Classifier — backup/restore helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

EXPORT_VERSION = "1.0"
_RUNTIME_KEYS = {"last_sync_at", "default_categories_seeded"}
_BOOL_KEYS = {"auto_mark_read", "auto_apply_label"}


async def export_config(db: Any) -> dict:
    """Serialize current plugin config to a portable dict."""
    # Load raw settings
    cursor = await db._db.execute("SELECT key, value FROM gmail_classifier_settings")
    raw_settings = {r["key"]: r["value"] for r in await cursor.fetchall()}

    # Load categories
    cursor = await db._db.execute(
        "SELECT id, name, description, color, icon, context, known_senders, patterns "
        "FROM gmail_categories ORDER BY id"
    )
    cat_rows = await cursor.fetchall()
    id_to_name: dict[int, str] = {r["id"]: r["name"] for r in cat_rows}

    categories = [
        {
            "name": r["name"],
            "description": r["description"] or "",
            "color": r["color"] or "#6366f1",
            "icon": r["icon"] or "Tag",
            "context": r["context"] or "",
            "known_senders": json.loads(r["known_senders"] or "[]"),
            "patterns": json.loads(r["patterns"] or "[]"),
        }
        for r in cat_rows
    ]

    # Serialize settings
    settings: dict[str, Any] = {}
    for k, v in raw_settings.items():
        if k in _RUNTIME_KEYS:
            continue
        if k in _BOOL_KEYS:
            settings[k] = v == "true"
        elif k == "autoreply_timeout_seconds":
            try:
                settings[k] = int(v)
            except (ValueError, TypeError):
                settings[k] = 60
        elif k == "autoreply_enabled_categories":
            try:
                ids = json.loads(v or "[]")
                settings[k] = [id_to_name[i] for i in ids if i in id_to_name]
            except Exception:
                settings[k] = []
        else:
            settings[k] = v or ""

    # Load reply examples
    cursor = await db._db.execute(
        "SELECT category_id, subtype_label, email_context, original_suggestion, "
        "final_response, use_count FROM gmail_reply_examples ORDER BY id"
    )
    reply_examples = [
        {
            "category_name": id_to_name[r["category_id"]],
            "subtype_label": r["subtype_label"] or "",
            "email_context": r["email_context"] or "",
            "original_suggestion": r["original_suggestion"] or "",
            "final_response": r["final_response"] or "",
            "use_count": r["use_count"] or 0,
        }
        for r in await cursor.fetchall()
        if r["category_id"] in id_to_name
    ]

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "categories": categories,
        "reply_examples": reply_examples,
    }
