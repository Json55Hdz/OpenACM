"""Unit tests for Gmail Classifier backup/restore."""
import json
from openacm.plugins.gmail_classifier.backup import export_config


async def test_export_has_required_top_level_keys(db):
    result = await export_config(db)
    assert result["version"] == "1.0"
    assert "exported_at" in result
    assert "settings" in result
    assert "categories" in result
    assert "reply_examples" in result


async def test_export_excludes_runtime_setting_keys(db):
    await db._db.execute(
        "INSERT OR REPLACE INTO gmail_classifier_settings (key, value) VALUES (?, ?)",
        ("last_sync_at", "2026-06-01T00:00:00"),
    )
    await db._db.execute(
        "INSERT OR REPLACE INTO gmail_classifier_settings (key, value) VALUES (?, ?)",
        ("auto_mark_read", "true"),
    )
    await db._db.commit()

    result = await export_config(db)
    assert "last_sync_at" not in result["settings"]
    assert "default_categories_seeded" not in result["settings"]
    assert result["settings"]["auto_mark_read"] is True


async def test_export_categories_have_parsed_json_fields(db):
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories "
        "(name, description, color, icon, context, known_senders, patterns) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Trabajo", "desc", "#ff0000", "Star", "ctx",
         '["boss@co.com"]', '[{"type":"subject_contains","value":"urgente"}]'),
    )
    await db._db.commit()

    result = await export_config(db)
    cats = [c for c in result["categories"] if c["name"] == "Trabajo"]
    assert len(cats) == 1
    cat = cats[0]
    assert cat["known_senders"] == ["boss@co.com"]
    assert cat["patterns"] == [{"type": "subject_contains", "value": "urgente"}]


async def test_export_autoreply_enabled_categories_as_names(db):
    cursor = await db._db.execute(
        "INSERT INTO gmail_categories (name) VALUES (?)", ("Importantes",)
    )
    cat_id = cursor.lastrowid
    await db._db.execute(
        "INSERT OR REPLACE INTO gmail_classifier_settings (key, value) VALUES (?, ?)",
        ("autoreply_enabled_categories", json.dumps([cat_id])),
    )
    await db._db.commit()

    result = await export_config(db)
    assert "Importantes" in result["settings"]["autoreply_enabled_categories"]


async def test_export_reply_examples_use_category_name(db):
    cursor = await db._db.execute(
        "INSERT INTO gmail_categories (name) VALUES (?)", ("Legal",)
    )
    cat_id = cursor.lastrowid
    await db._db.execute(
        "INSERT INTO gmail_reply_examples "
        "(category_id, subtype_label, email_context, original_suggestion, final_response, use_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cat_id, "consulta", "Asunto: ...", "Hola", "Estimado", 3),
    )
    await db._db.commit()

    result = await export_config(db)
    examples = [e for e in result["reply_examples"] if e["category_name"] == "Legal"]
    assert len(examples) == 1
    assert examples[0]["subtype_label"] == "consulta"
    assert examples[0]["use_count"] == 3
