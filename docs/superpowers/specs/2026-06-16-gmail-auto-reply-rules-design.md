# Gmail Auto-Reply Rules — Design Spec

**Date:** 2026-06-16
**Status:** Approved

## Overview

Independent, configurable rules that automatically reply to incoming emails when a high-confidence single-topic match is detected. Emails with multiple requests route through normal classification unchanged.

---

## Data Model

### `gmail_auto_reply_rules`

```sql
CREATE TABLE gmail_auto_reply_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    keywords     TEXT    NOT NULL DEFAULT '[]',  -- JSON string[]
    description  TEXT    NOT NULL,               -- natural language for LLM
    reply_template TEXT  NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

- **keywords**: fast pre-filter; at least one must appear in subject or body_text for the LLM to be invoked
- **description**: what the rule is about, used verbatim in the LLM prompt
- **reply_template**: exact text sent as the reply

### `gmail_auto_reply_log`

```sql
CREATE TABLE gmail_auto_reply_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id     INTEGER REFERENCES gmail_auto_reply_rules(id) ON DELETE SET NULL,
    email_id    INTEGER NOT NULL REFERENCES gmail_emails(id),
    confidence  REAL    NOT NULL,   -- 0.0–1.0 from LLM
    reasoning   TEXT    NOT NULL DEFAULT '',  -- LLM explanation, shown in UI modal
    reply_body  TEXT    NOT NULL,   -- snapshot of reply_template at send time
    sent_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

---

## Processing Flow

Triggered at the end of each processor batch, after `_upsert()` completes.

### Step 1 — Keyword filter (no LLM)

For each email in the batch:
- Skip immediately if `is_replied = 1` (already answered).
- Load all enabled rules.
- Check whether any rule's keywords appear (case-insensitive) in `subject` or `body_text`.
- Emails that match zero keywords are skipped immediately.

### Step 2 — LLM evaluation (one call per qualifying email)

**Input:** email subject + body_text (truncated to ~1500 tokens) + list of candidate rules (id, name, description).

**Structured output:**
```json
{
  "matched_rule_id": 3,       // null if no rule matches well enough
  "confidence": 0.94,         // 0.0–1.0
  "is_single_request": true,  // false → skip auto-reply
  "reasoning": "..."          // brief explanation, stored for debugging
}
```

The LLM is instructed to return `confidence < 0.90` if in doubt — the threshold is a hard gate, not a soft hint.

### Step 3 — Decision

| condition | action |
|---|---|
| `confidence >= 0.90` AND `is_single_request = true` | Send auto-reply, write log row, set `is_replied = 1` |
| `confidence < 0.90` | Skip — normal classification stands |
| `is_single_request = false` | Skip — normal classification stands |
| `matched_rule_id = null` | Skip |

Sending uses the existing Gmail API reply path (same as `POST /emails/{id}/reply`).

### New file: `auto_reply_rules.py`

Class `AutoReplyRulesEngine` with:
- `evaluate_batch(emails: list[dict]) -> None` — called by processor
- `_keyword_filter(email, rules) -> list[Rule]`
- `_llm_evaluate(email, candidate_rules) -> EvalResult`
- `_send_and_log(email, rule, result) -> None`

`processor.py` calls `AutoReplyRulesEngine.evaluate_batch(emails)` as the last step of each batch — no other changes to processor logic.

---

## API Endpoints

All prefixed under the Gmail Classifier router (`/api/gmail-classifier`).

| method | path | description |
|---|---|---|
| GET | `/auto-reply-rules` | list all rules (enabled + disabled) |
| POST | `/auto-reply-rules` | create rule |
| PUT | `/auto-reply-rules/{rule_id}` | update rule (any field) |
| DELETE | `/auto-reply-rules/{rule_id}` | delete rule |
| GET | `/auto-reply-log` | paginated log; query params: `rule_id`, `limit`, `offset` |

Request body for create/update:
```json
{
  "name": "Solicitudes de apartamento",
  "keywords": ["estado de cuenta", "apartamento", "arrendamiento"],
  "description": "El remitente pide un estado de cuenta o información sobre el apartamento",
  "reply_template": "Gracias por escribir. Para solicitudes de estado de cuenta del apartamento, por favor contacta a ...",
  "enabled": true
}
```

---

## UI

New tab **"Auto-respuestas"** inside the Gmail Classifier page.

### Rules panel

- List of rules with: name, keyword chips, enabled/disabled toggle, edit and delete buttons.
- "Nueva regla" button opens a slide-in form with fields: nombre, keywords (tag input), descripción (textarea, hint: "el LLM usa esto para confirmar si el correo aplica"), template de respuesta (textarea).
- Disabling a rule keeps it in the list but pauses execution.

### Log panel (below rules)

Table columns: fecha/hora · asunto del correo · regla aplicada · confianza (%) · botón Ver.

"Ver" opens a modal showing:
- Original email (subject, sender, snippet)
- Rule that matched
- Confidence score + reasoning
- Reply text sent

---

## Error Handling

- If the LLM call fails for an email, log a warning and skip auto-reply — do not block the rest of the batch.
- If Gmail send fails, log the error, do NOT write a log row (so the email isn't marked as replied).
- Keywords are matched with simple case-insensitive substring search — no regex, no stemming.

---

## Out of Scope

- Scheduling a delay before sending (immediate send only).
- Per-rule confidence threshold override (global 90% for all rules).
- Auto-reply for emails already marked `is_replied = 1`.
- Retry logic for failed sends.
