# Gmail Classifier Export/Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Backup tab to the Gmail Classifier Settings modal with export (JSON download) and smart-merge import of settings, categories, and reply examples.

**Architecture:** New `backup.py` in the plugin with two pure async functions (`export_config`, `import_config`). Two new FastAPI endpoints (`GET /export`, `POST /import`) in `router.py`. Frontend adds a third "Backup" tab to `PluginSettings.tsx` with download + file-upload UI.

**Tech Stack:** Python/aiosqlite (backend), FastAPI with `UploadFile`, Next.js/React with `useRef` for the file input, `URL.createObjectURL` for browser-triggered download.

---

## File map

| Action | Path |
|--------|------|
| **Create** | `src/openacm/plugins/gmail_classifier/backup.py` |
| **Modify** | `src/openacm/plugins/gmail_classifier/router.py` |
| **Modify** | `frontend/app/gmail-classifier/components/PluginSettings.tsx` |
| **Create** | `tests/unit/test_gmail_backup.py` |

---

### Task 1: `backup.py` — `export_config`

**Files:**
- Create: `src/openacm/plugins/gmail_classifier/backup.py`
- Test: `tests/unit/test_gmail_backup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_gmail_backup.py
"""Unit tests for Gmail Classifier backup/restore."""
import json
import pytest
from openacm.plugins.gmail_classifier.backup import export_config


@pytest.mark.asyncio
async def test_export_has_required_top_level_keys(db):
    result = await export_config(db)
    assert result["version"] == "1.0"
    assert "exported_at" in result
    assert "settings" in result
    assert "categories" in result
    assert "reply_examples" in result


@pytest.mark.asyncio
async def test_export_excludes_runtime_setting_keys(db):
    # Insert a runtime key and a regular key
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/unit/test_gmail_backup.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `backup.py` doesn't exist yet.

- [ ] **Step 3: Create `backup.py` with `export_config`**

```python
# src/openacm/plugins/gmail_classifier/backup.py
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
```

- [ ] **Step 4: Run export tests to confirm they pass**

```
pytest tests/unit/test_gmail_backup.py::test_export_has_required_top_level_keys tests/unit/test_gmail_backup.py::test_export_excludes_runtime_setting_keys tests/unit/test_gmail_backup.py::test_export_categories_have_parsed_json_fields tests/unit/test_gmail_backup.py::test_export_autoreply_enabled_categories_as_names tests/unit/test_gmail_backup.py::test_export_reply_examples_use_category_name -v
```

Expected: All 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/backup.py tests/unit/test_gmail_backup.py
git commit -m "feat: gmail classifier backup.py export_config"
```

---

### Task 2: `backup.py` — `import_config`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/backup.py`
- Modify: `tests/unit/test_gmail_backup.py`

- [ ] **Step 1: Add failing tests for `import_config`**

Append to `tests/unit/test_gmail_backup.py`:

```python
from openacm.plugins.gmail_classifier.backup import import_config


@pytest.mark.asyncio
async def test_import_raises_for_unknown_version(db):
    with pytest.raises(ValueError, match="Unsupported backup version"):
        await import_config(db, {"version": "99.0", "settings": {}, "categories": [], "reply_examples": []})


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
    # "Otros" already exists from migration seeding; it should not be updated
    assert result["categories_updated"] == 0
    assert result["categories_created"] == 0

    cursor = await db._db.execute("SELECT description FROM gmail_categories WHERE name='Otros'")
    row = await cursor.fetchone()
    # description stays as it was (not "should be ignored")
    assert (row["description"] or "") != "should be ignored"


@pytest.mark.asyncio
async def test_import_upserts_settings_skips_runtime_keys(db):
    data = {
        "version": "1.0",
        "settings": {
            "auto_mark_read": True,
            "last_sync_at": "2026-01-01",  # runtime key — should be skipped
        },
        "categories": [],
        "reply_examples": [],
    }
    result = await import_config(db, data)
    assert result["settings_updated"] == 1  # only auto_mark_read

    cursor = await db._db.execute(
        "SELECT value FROM gmail_classifier_settings WHERE key='auto_mark_read'"
    )
    row = await cursor.fetchone()
    assert row["value"] == "true"

    cursor = await db._db.execute(
        "SELECT value FROM gmail_classifier_settings WHERE key='last_sync_at'"
    )
    assert await cursor.fetchone() is None


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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

    # Second import of same example — should be deduped
    result2 = await import_config(db, data)
    assert result2["examples_added"] == 0

    cursor = await db._db.execute(
        "SELECT COUNT(*) as n FROM gmail_reply_examples WHERE category_id=? AND subtype_label='consulta'",
        (cat_id,),
    )
    row = await cursor.fetchone()
    assert row["n"] == 1


@pytest.mark.asyncio
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/unit/test_gmail_backup.py -k "import" -v
```

Expected: `ImportError` — `import_config` not defined yet.

- [ ] **Step 3: Add `import_config` to `backup.py`**

Append after `export_config` in `src/openacm/plugins/gmail_classifier/backup.py`:

```python
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

        # Also index all pre-existing categories (not imported) for example resolution
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
                db_value = str(int(v))
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

            cursor = await db._db.execute(
                "SELECT id FROM gmail_reply_examples "
                "WHERE category_id=? AND subtype_label=? AND source_email_id IS NULL",
                (cat_id, subtype),
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
                    ex.get("final_response") or "",
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
```

- [ ] **Step 4: Run all backup tests**

```
pytest tests/unit/test_gmail_backup.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/backup.py tests/unit/test_gmail_backup.py
git commit -m "feat: gmail classifier backup.py import_config with smart merge"
```

---

### Task 3: FastAPI endpoints in `router.py`

**Files:**
- Modify: `src/openacm/plugins/gmail_classifier/router.py` (append two endpoints at the bottom)

- [ ] **Step 1: Update the `fastapi` import at the top of `router.py`**

Find the existing line:
```python
from fastapi import APIRouter, HTTPException
```
Replace it with:
```python
from fastapi import APIRouter, HTTPException, UploadFile
```

- [ ] **Step 2: Append the two endpoints at the end of `router.py`**

After the last endpoint (`export_excel`, around line 908):

```python
# ─── Config Backup / Restore ─────────────────────────────────────────────────

@router.get("/export")
async def export_config_endpoint():
    """Download plugin configuration as a JSON backup file."""
    import datetime
    from fastapi import Response
    from openacm.plugins.gmail_classifier.backup import export_config as _export_config
    db = _require_db()
    data = await _export_config(db)
    today = datetime.date.today().isoformat()
    filename = f"gmail-classifier-backup-{today}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_config_endpoint(file: UploadFile):
    """Import configuration from a JSON backup file (smart merge)."""
    from openacm.plugins.gmail_classifier.backup import import_config as _import_config
    db = _require_db()
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"El archivo no es un JSON válido: {exc}")
    try:
        summary = await _import_config(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al importar: {exc}")
    return summary
```

- [ ] **Step 2: Verify the app starts without import errors**

```
python -c "from openacm.plugins.gmail_classifier.router import router; print('OK', len(router.routes), 'routes')"
```

Expected output: `OK 28 routes` (was 26, now +2).

- [ ] **Step 3: Run the full existing test suite to confirm no regressions**

```
pytest tests/unit/test_gmail_classifier.py tests/unit/test_gmail_backup.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/openacm/plugins/gmail_classifier/router.py
git commit -m "feat: gmail classifier GET /export and POST /import endpoints"
```

---

### Task 4: Frontend — Backup tab in `PluginSettings.tsx`

**Files:**
- Modify: `frontend/app/gmail-classifier/components/PluginSettings.tsx`

- [ ] **Step 1: Update the `MainTab` type and `TABS` array**

Find and replace:
```tsx
type MainTab = 'general' | 'auto-respuesta';
```
with:
```tsx
type MainTab = 'general' | 'auto-respuesta' | 'backup';
```

Find and replace:
```tsx
  const TABS: { id: MainTab; label: string }[] = [
    { id: 'general', label: 'General' },
    { id: 'auto-respuesta', label: 'Auto-respuesta' },
  ];
```
with:
```tsx
  const TABS: { id: MainTab; label: string }[] = [
    { id: 'general', label: 'General' },
    { id: 'auto-respuesta', label: 'Auto-respuesta' },
    { id: 'backup', label: 'Backup' },
  ];
```

- [ ] **Step 2: Add Backup tab state variables and `useRef`**

At the top of `PluginSettings.tsx`, add `useRef` to the React import:
```tsx
import { useState, useEffect, useRef } from 'react';
```

Inside the `PluginSettings` component, after the existing `const [loadingExamples, ...]` block, add:

```tsx
  // Backup tab state
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [exporting, setExporting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    categories_updated: number;
    categories_created: number;
    examples_added: number;
    settings_updated: number;
  } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
```

- [ ] **Step 3: Add backup handler functions**

Inside the component, after `saveTimeout`, add:

```tsx
  async function handleExport() {
    setExporting(true);
    try {
      const res = await fetch(`${API}/export`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) return;
      const blob = await res.blob();
      const today = new Date().toISOString().slice(0, 10);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `gmail-classifier-backup-${today}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setImportResult(null);
    setImportError(null);
  }

  async function handleImport() {
    if (!selectedFile) return;
    setImporting(true);
    setImportResult(null);
    setImportError(null);
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const res = await fetch(`${API}/import`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (res.ok) {
        setImportResult(await res.json());
        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
      } else {
        const err = await res.json().catch(() => ({}));
        setImportError(err.detail || 'Error al importar el archivo');
      }
    } catch {
      setImportError('Error de red al importar');
    } finally {
      setImporting(false);
    }
  }
```

- [ ] **Step 4: Add the Backup tab content**

Inside the `<div className="overflow-y-auto flex-1">` block, after the closing `}` of the `auto-respuesta` tab block (just before `</div>`), add:

```tsx
            {/* ── Backup tab ── */}
            {activeTab === 'backup' && (
              <div className="px-5 py-4 space-y-6">
                {/* Export */}
                <div>
                  <h3 className="text-[13px] font-semibold text-[var(--acm-fg)] mb-1">Exportar configuración</h3>
                  <p className="text-[11px] text-[var(--acm-fg-4)] mb-3">
                    Descarga un archivo JSON con tus categorías, settings y ejemplos de respuesta aprendidos.
                  </p>
                  <button
                    onClick={handleExport}
                    disabled={exporting}
                    className="btn-secondary text-[12px] py-[7px] px-3 min-w-[170px]"
                  >
                    {exporting ? 'Descargando…' : 'Descargar configuración'}
                  </button>
                </div>

                <div className="acm-rule" />

                {/* Import */}
                <div>
                  <h3 className="text-[13px] font-semibold text-[var(--acm-fg)] mb-1">Importar configuración</h3>
                  <p className="text-[11px] text-[var(--acm-fg-4)] mb-3">
                    Combina un backup con tu configuración actual. Las categorías existentes se actualizan
                    por nombre; los ejemplos nuevos se agregan sin duplicar.
                  </p>

                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json"
                    className="hidden"
                    onChange={handleFileSelect}
                  />

                  {!selectedFile ? (
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      className="btn-secondary text-[12px] py-[7px] px-3"
                    >
                      Seleccionar archivo…
                    </button>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-[12px] text-[var(--acm-fg-3)]">
                        Archivo: <span className="font-medium">{selectedFile.name}</span>
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={handleImport}
                          disabled={importing}
                          className="btn-primary text-[12px] py-[7px] px-3 min-w-[150px]"
                        >
                          {importing ? 'Importando…' : 'Confirmar importación'}
                        </button>
                        <button
                          onClick={() => { setSelectedFile(null); setImportResult(null); setImportError(null); }}
                          className="btn-secondary text-[12px] py-[7px] px-3"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  )}

                  {importResult && (
                    <div className="mt-4 rounded p-3 bg-[var(--acm-elev)] border border-[var(--acm-border)] text-[12px]">
                      <p className="font-medium text-[var(--acm-fg)] mb-2">✓ Importación completa</p>
                      <ul className="space-y-1 text-[var(--acm-fg-3)]">
                        <li>• {importResult.categories_updated} categorías actualizadas, {importResult.categories_created} creadas</li>
                        <li>• {importResult.examples_added} ejemplos de respuesta agregados</li>
                        <li>• {importResult.settings_updated} settings actualizados</li>
                      </ul>
                    </div>
                  )}

                  {importError && (
                    <p className="mt-3 text-[12px] text-red-400">{importError}</p>
                  )}
                </div>
              </div>
            )}
```

- [ ] **Step 5: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/gmail-classifier/components/PluginSettings.tsx
git commit -m "feat: gmail classifier settings — Backup tab with export/import UI"
```

---

### Task 5: Full verification

- [ ] **Step 1: Run all tests**

```
pytest tests/unit/test_gmail_classifier.py tests/unit/test_gmail_backup.py tests/unit/test_gmail_stats.py tests/unit/test_gmail_excel.py -v
```

Expected: All tests PASS with no warnings about the new files.

- [ ] **Step 2: Start the dev server and verify the Backup tab appears**

```
uv run openacm
```

Navigate to `http://localhost:47821` → Gmail Classifier → Settings icon → confirm three tabs: General, Auto-respuesta, Backup.

- [ ] **Step 3: Test export flow**
1. Click "Backup" tab
2. Click "Descargar configuración"
3. Confirm a `gmail-classifier-backup-YYYY-MM-DD.json` file downloads
4. Open the file and confirm it has `version`, `settings`, `categories`, `reply_examples`

- [ ] **Step 4: Test import flow**
1. Click "Seleccionar archivo…"
2. Pick the exported file
3. Click "Confirmar importación"
4. Confirm the success summary appears with counts

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "chore: gmail classifier export/import — final integration verified"
```
