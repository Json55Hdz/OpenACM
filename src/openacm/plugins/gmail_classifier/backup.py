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
            settings[k] = v

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


async def import_config(db: Any, data: dict) -> dict:
    """Smart-merge a backup dict into the current plugin config."""
    if data.get("version") != EXPORT_VERSION:
        raise ValueError(f"Unsupported backup version: {data.get('version')!r}")

    categories_updated = 0
    categories_created = 0
    examples_added = 0
    settings_updated = 0

    try:
        # ── Step 1: merge categories ──────────────────────────────────────────
        name_to_id: dict[str, int] = {}

        for cat in data.get("categories") or []:
            name = (cat.get("name") or "").strip()
            if not name or name.lower() == "otros":
                continue

            senders_json = json.dumps(cat.get("known_senders") or [], ensure_ascii=False)
            patterns_json = json.dumps(cat.get("patterns") or [], ensure_ascii=False)

            cursor = await db._db.execute(
                "SELECT id FROM gmail_categories WHERE lower(name) = lower(?)", (name,)
            )
            existing = await cursor.fetchone()

            if existing:
                await db._db.execute(
                    "UPDATE gmail_categories "
                    "SET description=?, color=?, icon=?, context=?, known_senders=?, patterns=? "
                    "WHERE id=?",
                    (
                        cat.get("description") or "",
                        cat.get("color") or "#6366f1",
                        cat.get("icon") or "Tag",
                        cat.get("context") or "",
                        senders_json,
                        patterns_json,
                        existing["id"],
                    ),
                )
                name_to_id[name.lower()] = existing["id"]
                categories_updated += 1
            else:
                cursor = await db._db.execute(
                    "INSERT INTO gmail_categories "
                    "(name, description, color, icon, context, known_senders, patterns) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        cat.get("description") or "",
                        cat.get("color") or "#6366f1",
                        cat.get("icon") or "Tag",
                        cat.get("context") or "",
                        senders_json,
                        patterns_json,
                    ),
                )
                name_to_id[name.lower()] = cursor.lastrowid
                categories_created += 1

        # Index all pre-existing categories for example/autoreply resolution
        cursor = await db._db.execute("SELECT id, name FROM gmail_categories")
        for row in await cursor.fetchall():
            name_to_id.setdefault(row["name"].lower(), row["id"])

        # ── Step 2: merge settings ────────────────────────────────────────────
        for k, v in (data.get("settings") or {}).items():
            if k in _RUNTIME_KEYS:
                continue

            if k == "autoreply_enabled_categories":
                names_list = v if isinstance(v, list) else []
                ids = [name_to_id[n.lower()] for n in names_list if n.lower() in name_to_id]
                db_value = json.dumps(ids)
            elif k in _BOOL_KEYS:
                db_value = "true" if v else "false"
            elif k == "autoreply_timeout_seconds":
                try:
                    db_value = str(int(v))
                except (ValueError, TypeError):
                    db_value = "60"
            else:
                db_value = str(v) if v is not None else ""

            await db._db.execute(
                "INSERT INTO gmail_classifier_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, db_value),
            )
            settings_updated += 1

        # ── Step 3: merge reply examples ──────────────────────────────────────
        for ex in data.get("reply_examples") or []:
            cat_name = (ex.get("category_name") or "").lower()
            cat_id = name_to_id.get(cat_name)
            if not cat_id:
                continue

            subtype = ex.get("subtype_label") or ""
            final_resp = ex.get("final_response") or ""

            cursor = await db._db.execute(
                "SELECT id FROM gmail_reply_examples "
                "WHERE category_id=? AND subtype_label=? AND final_response=? AND source_email_id IS NULL",
                (cat_id, subtype, final_resp),
            )
            if await cursor.fetchone():
                continue

            await db._db.execute(
                "INSERT INTO gmail_reply_examples "
                "(category_id, subtype_label, email_context, original_suggestion, final_response, use_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cat_id,
                    subtype,
                    ex.get("email_context") or "",
                    ex.get("original_suggestion") or "",
                    final_resp,
                    ex.get("use_count") or 0,
                ),
            )
            examples_added += 1

        await db._db.commit()

    except Exception:
        await db._db.rollback()
        raise

    return {
        "categories_updated": categories_updated,
        "categories_created": categories_created,
        "examples_added": examples_added,
        "settings_updated": settings_updated,
    }
