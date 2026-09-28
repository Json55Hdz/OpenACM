# Memory & RAG

OpenACM uses two complementary memory systems: **short-term conversation memory** (in-memory + SQLite, per conversation) and **long-term vector memory** (ChromaDB RAG, persistent across conversations).

---

## Short-Term Memory (Conversation Context)

Every conversation is stored in a rolling window managed by `MemoryManager`. This is the message history the LLM sees on each request.

### How It Works

- Messages are stored in-memory (fast access) and persisted to SQLite (survives restarts)
- Each conversation is keyed by `(user_id, channel_id)` — same pair = same conversation
- On first access, history is loaded from SQLite into the in-memory cache
- On `add_message()`, the new message is written to both cache and SQLite

### Limits

| Limit | Default | Config |
|-------|---------|--------|
| Max messages in context | 50 | `assistant.max_context_messages` |
| Hard token ceiling | 85% of the model's context window | built-in |

When a limit is exceeded, the oldest messages are dropped from the context (never splitting an assistant tool-call from its tool results). They remain in the database for history purposes.

The model's context window comes from LiteLLM's model database (128K is assumed when unknown); override it with `llm.model_context_overrides`.

### Per-agent memory policy

Agents with `memory_mode: session_ttl` start a fresh context when the last message of a conversation is older than `memory_ttl_hours`. Old messages are kept in SQLite but not reloaded. See [Agents](./07-agents.md#memory-policy).

### Encryption at Rest

Message content is encrypted in SQLite with **Fernet** via the same `ActivityEncryptor` used for activity data. The key is generated locally at `config/activity.key`. Messages are decrypted transparently on read.

The dashboard shows a lock icon when encryption is enabled (`GET /api/system/info` → `messages_encrypted`).

---

## Conversation Compaction

To prevent token waste, OpenACM automatically summarizes long conversations.

**Trigger:** when the estimated tokens of a conversation reach `assistant.compact_ratio` (default **0.60**) of the model's context window — so a 128K model compacts much later than a 8K one. After a compaction, it won't fire again until at least a further 10% of that threshold (minimum 1,000 tokens) has accumulated. `/compact` forces a compaction at any time.

**What happens:**
1. All messages except the system prompt and the last `compact_keep_recent` (default **6**) are extracted
2. A transcript is built (user/assistant messages, tool calls with abbreviated arguments, tool results)
3. An LLM call generates a detailed summary: what was worked on, actions taken (with exact file paths and commands), key decisions and findings, and current state (done / pending / blockers) — in the user's language
4. The old messages are replaced in-memory with the summary
5. The last messages remain intact

Compaction runs before the next LLM call; the conversation is paused while it runs. Each conversation compacts at most once at a time. A `memory.compacted` event is emitted when it finishes.

Both settings can be edited in **Configuration → Memory & RAG** (`POST /api/config/compaction`), which saves them to `config/local.yaml`:

```yaml
assistant:
  compact_ratio: 0.60
  compact_keep_recent: 6
```

---

## Context Optimization

Beyond compaction, the Brain applies additional optimizations to a copy of the messages before each LLM call (the stored history is never modified). For messages older than the last **6**:

- **Tool results** are emptied (only the `tool_call_id` is kept for structure)
- **Tool-call arguments** in assistant messages are stripped (only function name + id kept)
- **Reasoning content** from thinking models (DeepSeek R1, Kimi, o-series) is removed

Images in user messages other than the latest one are replaced with a `[IMAGE: … — already processed]` placeholder. See [Token Optimization](./20-token-optimization.md).

---

## Long-Term Memory (RAG)

The RAG (Retrieval-Augmented Generation) system lets OpenACM store and retrieve information across conversations using vector embeddings.

### Architecture

```
Agent saves note → split into chunks → embed → upsert into ChromaDB
User message     → embed → cosine search (top 5) → fragments under the distance threshold → injected into the prompt
```

**Embedding model:** `all-MiniLM-L6-v2` (sentence-transformers, runs locally)

**Vector store:** ChromaDB, persistent at `data/vectordb/`, collection `openacm_memory` (cosine distance)

**Chunking:** Chonkie `SentenceChunker` (500-character chunks, 50 overlap) with a paragraph-split fallback.

### Automatic recall

On each message the Brain queries the store (top 5) and injects up to **2** fragments whose distance is below `assistant.rag_relevance_threshold` (default **0.5**; lower = stricter) as a system message. Results are cached per conversation while consecutive messages are similar. A `memory.recall` event lights up the memory indicator in the dashboard.

### Using Long-Term Memory

#### Via Chat (Natural Language)
```
You> Remember that the production DB host is db.example.com:5432
You> What do you remember about the production database?
```

#### Via Tools

**`remember_note`** — Save information to long-term memory:
```json
{
  "tool": "remember_note",
  "arguments": {
    "note": "The production DB host is db.example.com:5432"
  }
}
```

**`search_memory`** — Retrieve relevant information:
```json
{
  "tool": "search_memory",
  "arguments": {
    "query": "production database connection",
    "max_results": 5
  }
}
```

### What to Store

Long-term memory is best for:
- Facts that span multiple sessions (preferences, project context)
- Findings from research that should be reusable
- User preferences and configuration decisions
- Notes about people, projects, or systems

It's not designed for:
- Large documents (use file system tools or an agent's knowledge base instead)
- Frequently-changing data (the indexed version becomes stale)
- Everything — be selective; retrieval is only as useful as the signal-to-noise ratio

Chunk ids are derived from a hash of the content, so saving the same note twice doesn't create duplicates. [Code Resurrection](./23-code-resurrection.md) also writes into the same store.

### Via API

```bash
# Stats: total documents, breakdown by type, folder size
curl http://localhost:47821/api/memory/stats \
  -H "Authorization: Bearer <dashboard-token>"

# Delete ALL long-term memory
curl -X DELETE http://localhost:47821/api/memory/all \
  -H "Authorization: Bearer <dashboard-token>"

# Relevance threshold
curl -X POST http://localhost:47821/api/config/rag_threshold \
  -H "Authorization: Bearer <dashboard-token>" \
  -H "Content-Type: application/json" \
  -d '{"threshold": 0.4}'
```

---

## Semantic Tool Selection

A separate, multilingual model — `paraphrase-multilingual-MiniLM-L12-v2`, shared with the LocalRouter — powers **semantic tool selection**: choosing which tools to include in each LLM call based on relevance to the user's message.

**How it works:**
1. At startup, all tool descriptions are embedded as `"name: description"` strings
2. Each incoming message is embedded
3. Cosine similarity is computed between the message and every tool embedding
4. Tools above threshold `0.28` are included in the request
5. Tools below threshold are excluded (saving tokens and reducing distraction)

**Language agnostic:** The multilingual model handles messages in Spanish, English, French, German, and 50+ other languages without any translation step.

**Always-included tools:** `send_file_to_chat`, `run_command`, `read_file`, `write_file`, `web_search`.

**Fallback:** Until the embedding model has loaded (first seconds after startup), a keyword-matching fallback is used.

---

## Data Locations

| Data | Location |
|------|---------|
| Conversation messages (SQLite) | `data/openacm.db` (table: `messages`) |
| App activity (SQLite) | `data/openacm.db` (table: `app_activities`) |
| Customer names | `data/openacm.db` (table: `customer_names`) |
| ChromaDB vector store | `data/vectordb/` |
| Encryption key | `config/activity.key` |

---

## Privacy

- Conversation content is encrypted at rest with the local key in `config/activity.key`
- ChromaDB stores plain text (vector + content) — it is local only, never sent anywhere by itself
- Recalled fragments are sent to your LLM provider as part of the prompt
- The embedding models run locally — no text is sent to external services for embedding
- To clear long-term memory: **Configuration → Memory & RAG** or `DELETE /api/memory/all`. To wipe everything: stop OpenACM and delete `data/openacm.db` and `data/vectordb/`
