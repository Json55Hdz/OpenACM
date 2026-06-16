# Agent Knowledge Base — Design Spec

**Date:** 2026-06-16  
**Phase:** 1 of 3 (Agent Superpowers)  
**Approach:** Simple text injection (no embeddings)

---

## Overview

Agents currently only have a `system_prompt` field to define their behavior. There is no way to attach persistent reference material (documents, policies, FAQs) that the agent can use when answering.

This spec adds a **knowledge base** per agent: a collection of text sections and uploaded files that are processed into Markdown and injected into the system prompt at chat time.

---

## Database

New table `agent_knowledge` added as a migration on top of the existing `agents` table:

```sql
CREATE TABLE IF NOT EXISTS agent_knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK(type IN ('file', 'text')),
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    filename    TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_agent ON agent_knowledge(agent_id);
```

**Field notes:**
- `type`: `'file'` for uploaded documents, `'text'` for free-form text sections
- `content`: always processed Markdown/plain text regardless of source format
- `filename`: populated only when `type = 'file'`, stores the original filename
- Cascade delete: removing an agent removes all its knowledge items automatically

---

## File Processing Pipeline

When a file is uploaded to an agent's knowledge base:

1. FastAPI receives the file via `multipart/form-data`
2. File is saved to a temporary path
3. Processing follows the same logic as `brain_multimodal.py`:
   - **Plain text formats** (`.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.yml`, `.toml`, `.xml`, `.html`, `.py`, `.js`, `.ts`): decoded directly as UTF-8
   - **Binary/office formats** (`.pdf`, `.docx`, `.xlsx`, `.pptx`): converted via `MarkItDown().convert(path).text_content`
4. Extracted text is stored in `content`
5. Temporary file is deleted

No new dependencies required — MarkItDown is already installed with docx/xlsx/pptx/audio extras.

---

## API Endpoints

All endpoints require standard dashboard authentication (same as existing agent endpoints).

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| `GET` | `/api/agents/{id}/knowledge` | — | `[{id, type, title, filename, created_at}]` |
| `POST` | `/api/agents/{id}/knowledge/text` | `{title: str, content: str}` JSON | `{id, type, title, created_at}` |
| `POST` | `/api/agents/{id}/knowledge/file` | `multipart/form-data` (file + optional title) | `{id, type, title, filename, created_at}` |
| `PATCH` | `/api/agents/{id}/knowledge/{kid}` | `{title?: str, content?: str}` JSON | `{id, type, title, updated_at}` |
| `DELETE` | `/api/agents/{id}/knowledge/{kid}` | — | `{ok: true}` |

**Notes:**
- `GET` omits `content` to avoid transferring large text over the wire unnecessarily
- `POST /file`: if no `title` is provided, defaults to the original filename without extension
- All endpoints return 404 if the agent does not exist

---

## Chat-Time Injection

In `AgentRunner.run()`, before building the LLM messages:

1. Query all `agent_knowledge` rows for the agent, ordered by `created_at ASC`
2. If no rows exist, skip injection (no overhead for agents without knowledge)
3. If rows exist, build a knowledge block:

```
## Base de conocimiento

### {title of item 1}
{content}

### {title of item 2}
{content}
```

4. Prepend this block to the agent's `system_prompt` with a blank line separator
5. **Character limit:** if the total knowledge block exceeds **40,000 characters**, truncate at that boundary and append `\n\n[Conocimiento truncado por límite de contexto]`

The rest of `AgentRunner` is unchanged — memory scoping, tool filtering, and the Brain loop all remain the same.

---

## Frontend

A new **"Knowledge"** tab is added to the agent edit modal (not the create modal — knowledge is added after the agent exists).

### Tab layout

```
┌──────────────────────────────────────────────────┐
│  ⚙ Config  │  📚 Knowledge                        │
├──────────────────────────────────────────────────┤
│                                                  │
│  [+ Agregar texto]  [↑ Subir archivo]            │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │ 📄 Manual de ventas.pdf         [FILE]  │   │
│  │    Subido hace 2 días            [🗑]    │   │
│  └──────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────┐   │
│  │ 📝 Política de devoluciones     [TEXT]  │   │
│  │    Editado hace 1 hora           [🗑]    │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ⚠ El conocimiento usa ~12,400 caracteres        │
└──────────────────────────────────────────────────┘
```

### Interactions

- **"+ Agregar texto"**: opens an inline form with `title` (input) + `content` (textarea). Save → `POST /knowledge/text` → item appears in list.
- **"↑ Subir archivo"**: opens file picker. Accepted formats: `.pdf .docx .xlsx .pptx .txt .md .csv .json .yaml`. On select → shows upload spinner → `POST /knowledge/file` → item appears in list.
- **Edit button (✏)**: opens the item inline for editing. For `text` items: editable `title` + `content` textarea → save → `PATCH /knowledge/{kid}`. For `file` items: only `title` is editable (content is fixed from the original file).
- **Delete button**: `DELETE /knowledge/{id}` → item removed from list immediately (optimistic UI).
- **Character counter**: shows total character count of all items. Yellow warning ≥ 30,000 chars. Red error ≥ 40,000 chars (matches backend truncation limit).
- **Empty state**: when no items exist, shows a friendly prompt: "Agrega documentos o secciones de texto para que tu agente tenga contexto al responder."

### Data fetching

- Knowledge list is fetched when the Knowledge tab is first opened (lazy load)
- Mutations use React Query `invalidateQueries` to keep the list fresh
- New hook `useAgentKnowledge(agentId)` added to `frontend/hooks/use-agents.ts`

---

## Error Handling

- File type not supported → 422 from backend, toast error in UI
- MarkItDown fails to parse → 422 with message "No se pudo extraer texto del archivo"
- Agent not found → 404, UI shows toast and closes tab
- Knowledge item not found on delete → treat as already deleted (idempotent)

---

## Out of Scope (future phases)

- Semantic search / embeddings (Phase 1 uses full injection)
- URL/web scraping as knowledge source
- Per-item character count display
- Reordering knowledge items
