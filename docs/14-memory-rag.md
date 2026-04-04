# Memory & RAG

OpenACM uses two complementary memory systems: **short-term conversation memory** (in-memory + SQLite, per session) and **long-term vector memory** (ChromaDB RAG, persistent across sessions).

---

## Short-Term Memory (Conversation Context)

Every conversation is stored in a rolling window managed by `MemoryManager`. This is the message history the LLM sees on each request.

### How It Works

- Messages are stored in-memory (fast access) and persisted to SQLite (survives restarts)
- Each conversation is keyed by `(user_id, channel_id)` — same pair = same conversation
- On first message load, history is fetched from SQLite into the in-memory cache
- On `add_message()`, the new message is written to both cache and SQLite

### Limits

```
Max messages in context:     50
Max tokens in context:       16,000
```

When either limit is exceeded, old messages are removed from context (but remain in the database for history purposes).

### Encryption at Rest

All message content is encrypted in SQLite using **AES-256-GCM** via the same `ActivityEncryptor` used for activity data. The encryption key is derived from a master key in `config/.env`. Messages are decrypted transparently on read.

The dashboard shows a lock icon when encryption is enabled.

---

## Conversation Compaction

To prevent token waste, OpenACM automatically summarizes old conversations.

**Trigger:** When a conversation exceeds **25 non-system messages**

**What happens:**
1. All messages except the last 6 are extracted
2. A compact transcript is built (`role: content` format)
3. An LLM call generates a summary (max 500 tokens, temperature 0.3)
4. The old messages are replaced in-memory with a single `system` summary message
5. The last 6 messages remain intact

**The summary preserves:**
- Key facts and decisions made
- Important data (file paths, numbers, names)
- Outstanding tasks and questions
- The gist of what was accomplished

Compaction runs as a background task (`asyncio.create_task`) — it doesn't block the current response. Each conversation compacts at most once at a time (tracked via `_compacting` set).

**Example summary format:**
```
[CONVERSATION SUMMARY]
The user asked about disk usage and learned the /home partition is 87% full. 
Key files identified: /home/user/videos (45GB). A cleanup script was created 
at ~/cleanup.sh. User has not yet run it. Outstanding: confirm whether to 
delete the /tmp/old_backups folder.
```

---

## Context Optimization

Beyond compaction, `brain.py` applies additional optimizations to messages before sending them to the LLM:

### Old Tool Result Truncation

Tool results older than the last **8 messages** are truncated to **300 characters**. This prevents large tool outputs (file contents, search results, command output) from consuming tokens in old context where they're no longer relevant.

### Reasoning Content Stripping

For models that emit reasoning/thinking tokens (DeepSeek R1, Kimi, o1-style models), the `reasoning_content` field is stripped from messages older than the last 8. Only recent reasoning is kept.

---

## Long-Term Memory (RAG)

The RAG (Retrieval-Augmented Generation) system lets OpenACM store and retrieve information across conversations using vector embeddings.

### Architecture

```
User saves note → embed text → store in ChromaDB collection
User asks question → embed query → cosine similarity search → inject results into prompt
```

**Embedding model:** `paraphrase-multilingual-MiniLM-L12-v2` (same model used for semantic tool selection)

**Vector store:** ChromaDB (local, persistent at `data/chromadb/`)

### Using Long-Term Memory

#### Via Chat (Natural Language)
```
You> Remember that the server password is "hunter2" (just kidding, store a test fact)
You> What do I remember about server passwords?
You> Forget everything about passwords
```

#### Via Tools

**`remember_note`** — Save information to long-term memory:
```json
{
  "tool": "remember_note",
  "arguments": {
    "content": "The production DB host is db.example.com:5432",
    "tags": ["infrastructure", "database"]
  }
}
```

**`search_memory`** — Retrieve relevant information:
```json
{
  "tool": "search_memory",
  "arguments": {
    "query": "production database connection",
    "limit": 5
  }
}
```

### What to Store

Long-term memory is best for:
- Facts that span multiple sessions (credentials, preferences, project context)
- Findings from research that should be reusable
- User preferences and configuration decisions
- Notes about people, projects, or systems

It's not designed for:
- Large documents (use file system tools instead)
- Frequently-changing data (the indexed version becomes stale)
- Everything — be selective; retrieval is only as useful as the signal-to-noise ratio

### Collections

By default, all notes go into the `openacm_memory` ChromaDB collection. The collection is keyed by the note's content hash, so duplicate saves are idempotent.

### Via API

```bash
# Save a note
curl -X POST http://localhost:47821/api/memory \
  -H "Authorization: Bearer acm_xxx" \
  -H "Content-Type: application/json" \
  -d '{"content": "The API server is at api.example.com", "tags": ["infrastructure"]}'

# Search memory
curl "http://localhost:47821/api/memory/search?q=api+server&limit=5" \
  -H "Authorization: Bearer acm_xxx"

# List all notes
curl http://localhost:47821/api/memory \
  -H "Authorization: Bearer acm_xxx"

# Delete a note
curl -X DELETE http://localhost:47821/api/memory/{id} \
  -H "Authorization: Bearer acm_xxx"
```

---

## Semantic Tool Selection

The same embedding model powers **semantic tool selection** — choosing which of the 40+ available tools to include in each LLM call based on relevance to the user's message.

**How it works:**
1. At startup, all tool descriptions are embedded as `"name: description"` strings
2. Each incoming message is embedded
3. Cosine similarity is computed between the message and every tool embedding
4. Tools above threshold `0.28` are included in the request
5. Tools below threshold are excluded (saving tokens and reducing distraction)

**Language agnostic:** The multilingual model handles messages in Spanish, English, French, German, and 50+ other languages without any translation step.

**Always-included tools:** Some tools (like `send_file_to_chat`) are always included regardless of similarity score.

**Fallback:** If the embedding model fails to load, a keyword-matching fallback is used.

---

## Data Locations

| Data | Location |
|------|---------|
| Conversation messages (SQLite) | `data/openacm.db` (table: `messages`) |
| App activity (SQLite) | `data/openacm.db` (table: `app_activity`) |
| ChromaDB vector store | `data/chromadb/` |
| Encryption key | Derived from `ENCRYPTION_KEY` in `config/.env` |

---

## Privacy

- All conversation content is encrypted at rest if `ENCRYPTION_KEY` is set
- ChromaDB stores plain text (vector + content) — it is local only, never sent anywhere
- The embedding model runs locally — no text is sent to external services for embedding
- To clear all memory: delete `data/openacm.db` and `data/chromadb/` (and restart)
