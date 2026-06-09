# Gmail Classifier — Export / Import Configuration

**Date:** 2026-06-08  
**Status:** Approved

## Overview

Add export and import functionality for Gmail Classifier preferences and configuration. Users can download a JSON backup of their settings, categories, and learned reply examples, and restore or migrate them via a smart merge that preserves existing data.

## Scope

**Included in export/import:**
- Settings (auto_mark_read, auto_apply_label, cron_schedule, since_date_default, autoreply_model, autoreply_timeout_seconds, autoreply_enabled_categories)
- Categories (name, description, color, icon, context, known_senders, patterns)
- Reply examples (subtype_label, email_context, original_suggestion, final_response, use_count)

**Excluded:**
- Emails (Gmail is source of truth)
- OAuth credentials (google_credentials.json / google_token.json)
- Embeddings (binary blobs; regenerated lazily on next use)
- Runtime state keys: last_sync_at, default_categories_seeded

## Export File Format

Filename: `gmail-classifier-backup-YYYY-MM-DD.json`

```json
{
  "version": "1.0",
  "exported_at": "2026-06-08T14:30:00",
  "settings": {
    "auto_mark_read": true,
    "auto_apply_label": false,
    "cron_schedule": "0 8 * * *",
    "since_date_default": "2026-01-01",
    "autoreply_model": "claude-sonnet-4-6",
    "autoreply_timeout_seconds": 60,
    "autoreply_enabled_categories": ["Importantes", "Legales"]
  },
  "categories": [
    {
      "name": "Importantes",
      "description": "Correos de alta prioridad",
      "color": "#ef4444",
      "icon": "Star",
      "context": "Contexto para el LLM...",
      "known_senders": ["boss@company.com"],
      "patterns": [{"type": "subject_contains", "value": "urgente"}]
    }
  ],
  "reply_examples": [
    {
      "category_name": "Importantes",
      "subtype_label": "solicitud de información",
      "email_context": "Asunto: ...",
      "original_suggestion": "...",
      "final_response": "...",
      "use_count": 5
    }
  ]
}
```

**Key design decisions:**
- `autoreply_enabled_categories` is exported as category **names** (not IDs) so the import can remap correctly even if IDs differ between environments.
- `reply_examples.category_name` follows the same pattern.
- `version` field allows future schema migrations without breaking older backup files.

## Backend

### New file: `src/openacm/plugins/gmail_classifier/backup.py`

Two pure async functions:

**`export_config(db) → dict`**
- Reads all settings from `gmail_classifier_settings`
- Reads all categories from `gmail_categories`
- Reads all reply examples from `gmail_reply_examples`
- Resolves category IDs → names for `autoreply_enabled_categories` and `reply_examples`
- Returns the dict matching the format above

**`import_config(db, data: dict) → dict`**
- Validates `data["version"]` == "1.0"; raises `ValueError` if unknown version
- Executes all writes in a single DB transaction (atomicity: all-or-nothing)
- Returns summary: `{ "categories_updated", "categories_created", "examples_added", "settings_updated" }`

Import merge logic (in order):

1. **Settings upsert**: for each key in `data["settings"]`, upsert into `gmail_classifier_settings`. Skip `last_sync_at` and `default_categories_seeded`. For `autoreply_enabled_categories`, resolve names → IDs using the post-merge category state.

2. **Category merge**: for each category in `data["categories"]`:
   - Lookup by name (case-insensitive)
   - If found → UPDATE all fields (description, color, icon, context, known_senders, patterns)
   - If not found → INSERT
   - Category "Otros" is never modified or deleted
   - Build a `name → id` map after all upserts for use in step 3

3. **Reply examples**: for each example in `data["reply_examples"]`:
   - Resolve `category_name → category_id` using the map from step 2; skip if category not found
   - Dedup check: skip if a row already exists with the same `(category_id, subtype_label)` where `source_email_id IS NULL` (i.e., an imported example, not a learned one)
   - INSERT without embedding (NULL); embedding will be generated lazily on next similarity search

### New endpoints in `router.py`

```
GET  /gmail-classifier/export
```
- Calls `export_config(db)`
- Returns `Response` with `Content-Type: application/json` and `Content-Disposition: attachment; filename="gmail-classifier-backup-YYYY-MM-DD.json"`

```
POST /gmail-classifier/import
```
- Accepts `multipart/form-data` with field `file` (the JSON backup)
- Parses and validates JSON; returns 400 on parse error or unknown version
- Calls `import_config(db, data)`
- Returns 200 with the summary dict

## Frontend

### New tab in `PluginSettings.tsx`

Add a third tab **"Backup"** alongside "General" and "Auto-respuesta".

**Export block:**
- Button: "Descargar configuración"
- On click: `GET /export` → triggers browser file download
- While loading: spinner on button, disabled state

**Import block:**
- Hidden `<input type="file" accept=".json">` triggered by button "Importar configuración"
- After file selection: show filename + "Confirmar importación" button
- On confirm: `POST /import` with `multipart/form-data`
- On success: show inline summary:
  ```
  ✓ Importación completa
  • 3 categorías actualizadas, 1 creada
  • 12 ejemplos de respuesta agregados
  • 7 settings actualizados
  ```
- On error: show error message in red (JSON inválido, versión incompatible, etc.)

State management: `useState` local within the Backup tab component (loading, selectedFile, result, error). No global store changes needed.

After a successful import, the parent `PluginSettings` component reloads settings from the API (it already does this on open) so the UI reflects the merged state without a full page reload.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| File is not valid JSON | 400 response, frontend shows "El archivo no es un JSON válido" |
| Unknown version | 400 response, frontend shows "Versión de backup no compatible" |
| Category name collision with "Otros" | Silently skipped (not an error) |
| Reply example references unknown category | Silently skipped, not counted in summary |
| DB error mid-import | Transaction rolled back, 500 response, frontend shows generic error |

## Out of Scope

- Exporting emails or email bodies
- Merging strategies other than "by name" (e.g., by ID)
- Versioning/history of backups
- Scheduled automatic backups
