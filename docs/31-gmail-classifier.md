# Gmail Classifier

The **Gmail Classifier** is a built-in [plugin](./24-plugins.md) (`gmail_classifier`) that reads your Gmail inbox, classifies every email into your own categories with the LLM, and helps you answer: reply suggestions, drafts, sending, auto-reply rules that learn from your edits, statistics, Excel reports and a daily digest delivered through an agent's Telegram/WhatsApp channel.

It lives at **Gmail** (`/gmail-classifier`) in the sidebar and exposes its API under `/api/gmail-classifier/*`.

---

## Setup

1. Create Google OAuth credentials and authorize OpenACM — see [Gmail Setup](./GMAIL_SETUP.md). The plugin shows its setup screen until `config/google_token.json` exists (`GET /api/gmail-classifier/auth-status`).
2. Open **Gmail** in the sidebar. On first start the plugin seeds a set of default categories (e.g. *Importantes*, *Legales*, …) that you can edit or delete.
3. Optionally import your existing Gmail labels as categories (`POST /categories/import-labels`) or let the LLM suggest the top categories from a sample of recent emails (`POST /suggest-categories`).
4. Run a first classification (**Process**) — for example over the last 30 days.

The plugin is enabled by default; disable it on the **Plugins** page if you don't use it.

---

## How Classification Works

- Emails are fetched from Gmail and sent to the LLM in **batches of 20**, using only the subject, the sender and a 200-character snippet — cheap even for large inboxes (see [LLM Pricing Reference](./LLM_PRICING_REFERENCE.md)).
- Each category has a description, a free-text **context** explaining what belongs there, **known senders** and **patterns** (e.g. `subject_contains`, `sender_domain`) that guide the model.
- Results are stored locally (`gmail_emails`); already-processed emails are skipped.
- Optional settings: `auto_mark_read`, `auto_apply_label` (create/apply the category as a Gmail label), and a default start date.
- You can re-categorize an email or a whole thread by hand.

### Scheduled processing

Set a cron expression (`POST /api/gmail-classifier/cron` with `{"schedule": "*/30 * * * *"}`) and the plugin processes new mail periodically in the background. `POST /process`, `GET /process/status` and `POST /process/stop` control a manual run.

---

## Reading and Replying

- **Threads view** with all messages of a conversation, HTML bodies (inline images resolved) and attachments
- **Suggest reply** — the LLM drafts an answer for an email
- **Drafts** — save or delete a Gmail draft
- **Reply** — send directly from OpenACM
- **Auto-reply** — enable categories for which reply suggestions are generated automatically (skipping no-reply senders), with a configurable model and timeout
- **Learning from you** — when you send or save a reply that differs meaningfully from the AI suggestion, it is stored as a **reply example** and used to write future suggestions in your style (manage them under `/reply-examples`)

---

## Statistics, Reports and Digest

| Feature | Endpoint |
|---------|----------|
| Aggregated stats for a date range | `GET /api/gmail-classifier/stats` |
| AI summary of today's inbox (counts by category + 2-3 urgent emails) | `GET /api/gmail-classifier/summary` |
| Excel report for a date range | `GET /api/gmail-classifier/export/excel` |

**Daily digest:** enable `digest_enabled`, set `digest_time`, `digest_days` (default Monday–Friday), and pick the **agent** (`digest_agent_id`) and **chat** (`digest_chat_id`) that should receive it. The summary is sent through that agent's Telegram/WhatsApp channel. `POST /summary/test-send` sends one immediately to test the configuration.

---

## Backup and Restore

`GET /api/gmail-classifier/export` downloads the plugin configuration (settings + categories) as JSON; `POST /import` restores it with a smart merge. Use it to copy your categories to another installation.

---

## API Summary

All routes are under `/api/gmail-classifier` and require the dashboard token.

| Area | Routes |
|------|--------|
| Categories | `GET/POST /categories`, `PUT/DELETE /categories/{id}`, `POST /categories/import-labels`, `POST /suggest-categories` |
| Emails & threads | `GET /emails`, `GET /threads`, `GET /threads/{id}/messages`, `PATCH /threads/{id}/category`, `PATCH /emails/{id}/read`, `PATCH /emails/{id}/category`, `GET /emails/{id}/html`, `GET /emails/{id}/attachments[/{attachment_id}]` |
| Replies | `GET /emails/{id}/suggest-reply`, `POST /emails/{id}/reply`, `POST/DELETE /emails/{id}/draft`, `GET /reply-examples`, `PUT/DELETE /reply-examples/{id}` |
| Processing | `POST /process`, `GET /process/status`, `POST /process/stop`, `POST/DELETE /cron` |
| Settings | `GET/PUT /settings`, `GET /auth-status` |
| Reports | `GET /stats`, `GET /summary`, `POST /summary/test-send`, `GET /export/excel` |
| Backup | `GET /export`, `POST /import` |
