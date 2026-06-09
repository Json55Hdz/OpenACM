"""Unit tests for Gmail Classifier backup/restore."""
import json
import pytest
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


from openacm.plugins.gmail_classifier.backup import import_config


async def test_import_raises_for_unknown_version(db):
    with pytest.raises(ValueError, match="Unsupported backup version"):
        await import_config(db, {"version": "99.0", "settings": {}, "categories": [], "reply_examples": []})


async def test_import_creates_new_category(db):
    data = {
        "version": "1.0",
        "settings": {},
        "categories": [
            {"name": "Trabajo", "description": "desc", "color": "#ff0000",
             "icon": "Star", "context": "ctx", "known_senders": [], "patterns": []}
        ],
        "reply_examples": [],
    }
    result = await import_config(db, data)
    assert result["categories_created"] == 1
    assert result["categories_updated"] == 0

    cursor = await db._db.execute("SELECT name FROM gmail_categories WHERE name='Trabajo'")
    assert await cursor.fetchone() is not None


async def test_import_updates_existing_category_by_name(db):
    await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name, description) VALUES (?, ?)",
        ("Trabajo", "vieja"),
    )
    await db._db.commit()

    data = {
        "version": "1.0",
        "settings": {},
        "categories": [
            {"name": "Trabajo", "description": "nueva", "color": "#00ff00",
             "icon": "Tag", "context": "", "known_senders": [], "patterns": []}
        ],
        "reply_examples": [],
    }
    result = await import_config(db, data)
    assert result["categories_updated"] == 1
    assert result["categories_created"] == 0

    cursor = await db._db.execute("SELECT description FROM gmail_categories WHERE name='Trabajo'")
    row = await cursor.fetchone()
    assert row["description"] == "nueva"


async def test_import_skips_otros_category(db):
    data = {
        "version": "1.0",
        "settings": {},
        "categories": [
            {"name": "Otros", "description": "should be ignored",
             "color": "#ff0000", "icon": "Tag", "context": "", "known_senders": [], "patterns": []}
        ],
        "reply_examples": [],
    }
    result = await import_config(db, data)
    assert result["categories_updated"] == 0
    assert result["categories_created"] == 0

    cursor = await db._db.execute("SELECT description FROM gmail_categories WHERE name='Otros'")
    row = await cursor.fetchone()
    assert (row["description"] or "") != "should be ignored"


async def test_import_upserts_settings_skips_runtime_keys(db):
    data = {
        "version": "1.0",
        "settings": {
            "auto_mark_read": True,
            "last_sync_at": "2026-01-01",
        },
        "categories": [],
        "reply_examples": [],
    }
    result = await import_config(db, data)
    assert result["settings_updated"] == 1

    cursor = await db._db.execute(
        "SELECT value FROM gmail_classifier_settings WHERE key='auto_mark_read'"
    )
    row = await cursor.fetchone()
    assert row["value"] == "true"

    cursor = await db._db.execute(
        "SELECT value FROM gmail_classifier_settings WHERE key='last_sync_at'"
    )
    assert await cursor.fetchone() is None


async def test_import_autoreply_categories_resolved_to_ids(db):
    cursor = await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name) VALUES (?)", ("Importantes",)
    )
    cat_id = cursor.lastrowid
    await db._db.commit()

    data = {
        "version": "1.0",
        "settings": {"autoreply_enabled_categories": ["Importantes"]},
        "categories": [],
        "reply_examples": [],
    }
    await import_config(db, data)

    cursor = await db._db.execute(
        "SELECT value FROM gmail_classifier_settings WHERE key='autoreply_enabled_categories'"
    )
    row = await cursor.fetchone()
    ids = json.loads(row["value"])
    assert cat_id in ids


async def test_import_adds_reply_examples_without_duplicates(db):
    cursor = await db._db.execute(
        "INSERT OR IGNORE INTO gmail_categories (name) VALUES (?)", ("Legal",)
    )
    cat_id = cursor.lastrowid
    await db._db.commit()

    example = {
        "category_name": "Legal",
        "subtype_label": "consulta",
        "email_context": "Asunto: contrato",
        "original_suggestion": "Hola",
        "final_response": "Estimado",
        "use_count": 2,
    }
    data = {"version": "1.0", "settings": {}, "categories": [], "reply_examples": [example]}

    result1 = await import_config(db, data)
    assert result1["examples_added"] == 1

    result2 = await import_config(db, data)
    assert result2["examples_added"] == 0

    cursor = await db._db.execute(
        "SELECT COUNT(*) as n FROM gmail_reply_examples WHERE category_id=? AND subtype_label='consulta'",
        (cat_id,),
    )
    row = await cursor.fetchone()
    assert row["n"] == 1


async def test_import_returns_summary_counts(db):
    data = {
        "version": "1.0",
        "settings": {"auto_mark_read": False, "cron_schedule": ""},
        "categories": [
            {"name": "Nueva", "description": "", "color": "#6366f1",
             "icon": "Tag", "context": "", "known_senders": [], "patterns": []}
        ],
        "reply_examples": [],
    }
    result = await import_config(db, data)
    assert isinstance(result["categories_created"], int)
    assert isinstance(result["categories_updated"], int)
    assert isinstance(result["examples_added"], int)
    assert isinstance(result["settings_updated"], int)
