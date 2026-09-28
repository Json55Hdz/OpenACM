# Token Optimization

OpenACM has a multi-layer token optimization system built into its core. Every LLM call is automatically processed through a pipeline of techniques that reduce token consumption without affecting quality. This document explains each layer, where it lives in the codebase, and how they compose together.

---

## Why It Matters

Every token sent to an LLM has a cost — in money, in latency, and in context window pressure. A naive agentic system that dumps the full conversation history + all tool schemas + full tool outputs on every call will burn tokens rapidly. OpenACM approaches this problem at every layer of the pipeline:

```
User message
    │
    ▼  [Layer 1] Local Router — skip LLM entirely for known intents (0 tokens)
    │
    ▼  [Layer 2] Semantic Tool Selection — only send relevant tools (~3K saved/call)
    │
    ▼  [Layer 3] Slim Tool Schemas — strip param descriptions from schemas (40-70% schema savings)
    │
    ▼  LLM Call
    │
    ▼  Tool execution
    │
    ▼  [Layer 4] Output Compressor — smart-compress tool results before context (30-80% result savings)
    │
    ▼  [Layer 5] Old Message Stripping — null old tool results + strip arg blobs
    │
    ▼  [Layer 6] Conversation Compaction — LLM-summarize history at 60% of the context window
    │
    ▼  [Layer 7] Token Budget Cap — hard ceiling at 85% of the model's context window
```

---

## Layer 1: Local Router (Fast Path)

**File:** `src/openacm/core/local_router.py`, `src/openacm/core/fast_path.py`  
**Token savings:** 100% of LLM input+output for matched requests

The LocalRouter classifies incoming messages against a set of learned intents. When confidence is above the threshold (default: `0.88`), the Brain skips the LLM entirely and dispatches directly to a `fast_path` handler.

```python
# brain_loop.py — agentic loop entry point
_router_result = await asyncio.wait_for(asyncio.shield(_router_task), timeout=0.15)
if _router_result and _router_result.is_fast_path_eligible:
    fast_response = await self._execute_fast_path(...)
    return fast_response  # ← never touches the LLM
```

**What gets fast-pathed:**
- Conversational messages ("hola", "gracias", "ok")
- Frequently repeated intents the router has learned (e.g. "abre Blender" → `run_command start blender`)
- System info queries, time/date questions

**Passive learning:** After each agentic turn, the Brain inspects which tool was called and teaches the LocalRouter. Over time, repeated patterns are handled locally without LLM involvement.

---

## Layer 2: Semantic Tool Selection

**File:** `src/openacm/tools/registry.py`  
**Token savings:** ~1,000–5,000 tokens per call depending on tool count

Sending all registered tools to the LLM on every call is wasteful. The ToolRegistry uses `paraphrase-multilingual-MiniLM-L12-v2` embeddings (the same model as the LocalRouter) to compute cosine similarity between the user's message and each tool's description. Only tools above the threshold are included.

```
Threshold: SEMANTIC_TOOL_THRESHOLD = 0.28

"toma una captura de pantalla"
  → screenshot        similarity: 0.82  ✓ included
  → send_file_to_chat similarity: —     ✓ always included (ALWAYS_INCLUDE_TOOLS)
  → web_search        similarity: 0.09  ✗ excluded
  → gmail_send        similarity: 0.04  ✗ excluded
  → ...
```

**Conversational shortcut:** Messages ≤80 characters with no action keywords skip embedding entirely and send 0 tools (`tools=None`). This saves the full schema payload (~3K tokens) plus avoids triggering the LLM's tool-calling mode.

**Always-included tools** (regardless of similarity):
```python
ALWAYS_INCLUDE_TOOLS = {"send_file_to_chat", "run_command", "read_file", "write_file", "web_search"}
```

Tool embeddings are computed once at startup and cached in memory.

---

## Layer 3: Slim Tool Schemas

**File:** `src/openacm/tools/base.py` → `ToolDefinition.to_slim_schema()`  
**Token savings:** 40–70% of tool schema tokens

When the Brain has already selected the relevant tools via semantic similarity, it doesn't need full parameter documentation in the schema — the LLM knows which tool to use and only needs the bare structure to call it correctly.

`to_slim_schema()` strips two things:
1. **Description trimmed to the first sentence** — the LLM doesn't need the full multi-line docstring once it's selected the tool
2. **`description` fields removed from parameter properties** — the parameter names + types are sufficient for correct invocation

```python
# Full schema sent on first message (before tool selection warms up):
{
  "name": "run_command",
  "description": "[OpenACM Tool] Execute commands directly in the operating system terminal. ...(200 chars)...",
  "parameters": {
    "properties": {
      "command": {"type": "string", "description": "The shell command to execute. ..."},
      "background": {"type": "boolean", "description": "Run in background without waiting..."},
      ...
    }
  }
}

# Slim schema after semantic selection:
{
  "name": "run_command",
  "description": "[OpenACM Tool] Execute commands directly in the operating system terminal.",
  "parameters": {
    "properties": {
      "command": {"type": "string"},
      "background": {"type": "boolean"},
      ...
    }
  }
}
```

---

## Layer 4: Output Compressor

**File:** `src/openacm/core/output_compressor.py`  
**Token savings:** 30–80% of tool result tokens

Tool results are compressed before being stored in the LLM context. Unlike naive head+tail truncation, the compressor is **context-aware** — it knows which tool produced the output and applies a strategy matched to that tool's output format.

### Compressors by tool type

| Tool | Strategy |
|------|----------|
| `run_command` | Drop progress bars, pip `Collecting`/`Using cached` lines, deduplicate consecutive identical lines |
| `run_python` | Same as `run_command` |
| `read_file` | Strip decorative separators only (conservative — file content is important) |
| `web_search` | Re-emit JSON results as compact `[N] title / url / snippet` format, trim snippets to 300 chars |
| `system_info` | Drop empty `key:` lines with no value |
| everything else | Generic: collapse separator lines, strip trailing whitespace, collapse blank lines |

### Critical content is never removed

Lines matching any of these patterns are always kept, regardless of compressor:

```
error, exception, traceback, warning, fail, fatal, critical
success, done, finished, complete, result, output
installed, upgraded, removed
exit code, returncode, OK, PASS, FAIL
```

### Example

```
# pip install output — BEFORE (544 chars):
Collecting requests
  Downloading requests-2.31.0-py3-none-any.whl (62 kB)
     62.6/62.6 kB 1.2 MB/s eta 0:00:00
Collecting charset-normalizer<4,>=2
  Downloading charset_normalizer-3.3.2 (99 kB)
Using cached urllib3-2.2.1-py3-none-any.whl (121 kB)
Using cached certifi-2024.2.2-py3-none-any.whl (163 kB)
Installing collected packages: urllib3, certifi, requests
Successfully installed certifi-2024.2.2 requests-2.31.0

# AFTER compression (377 chars — 31% saved):
Downloading requests-2.31.0-py3-none-any.whl (62 kB)
     62.6/62.6 kB 1.2 MB/s eta 0:00:00
  Downloading charset_normalizer-3.3.2 (99 kB)
Installing collected packages: urllib3, certifi, requests
Successfully installed certifi-2024.2.2 requests-2.31.0
```

```
# Repeated spinner lines — BEFORE (61 chars):
Processing...
Processing...
Processing...
Processing...
Done!

# AFTER (19 chars — 69% saved):
Processing...
Done!
```

### Integration in brain_loop.py

```python
# brain_loop.py — after tool execution, before adding to memory
result_for_memory, _orig_len, _comp_len = compress_output(str(result), tool_name)
if _orig_len != _comp_len:
    log.debug("Tool output compressed", tool=tool_name,
              summary=compression_summary(_orig_len, _comp_len))

# Hard cap still applies after compression
if len(result_for_memory) > MAX_TOOL_RESULT_CHARS:  # 6000 chars
    head = result_for_memory[:3500]
    tail = result_for_memory[-1000:]
    result_for_memory = head + f"\n... [{omitted} chars omitted] ...\n" + tail
```

The compressor runs first. The hard cap (head+tail at 6000 chars) is a safety net that only triggers if compression alone wasn't enough.

---

## Layer 5: Old Message Stripping

**File:** `src/openacm/core/brain_loop.py` → `_prepare_messages_for_llm()`  
**Token savings:** Hundreds to thousands of tokens in long conversations

Before each LLM call, `_prepare_messages_for_llm()` strips redundant content from messages older than the last 6 (`_RECENT_MSG_WINDOW = 6`):

| Old message type | What gets stripped |
|------------------|--------------------|
| `tool` role (result messages) | Content set to `""` — the LLM already processed this result; only `tool_call_id` is needed to maintain conversation structure |
| `assistant` role with tool calls | `arguments` JSON blob replaced with `{}` — only the function `name` + `id` are needed for back-reference |
| Any message with `reasoning_content` | Reasoning content stripped entirely — thinking model outputs can be thousands of tokens per message |

Additionally, base64 images in user messages other than the latest one are replaced with a short `[IMAGE: … — already processed]` placeholder.

The original messages in memory are never mutated — a shallow copy is made only when a strip is needed. This means conversation history in SQLite stays complete for debugging and display.

```python
_RECENT_MSG_WINDOW = 6   # full detail kept for last N messages
_OLD_REASONING_MAX = 0   # reasoning_content stripped from all older messages
```

---

## Layer 6: Conversation Compaction

**File:** `src/openacm/core/memory.py` → `MemoryManager._compact()`  
**Token savings:** ~60–80% of old conversation tokens after trigger

When a conversation's estimated tokens reach **`compact_ratio` × the model's context window** (default `0.60`), a compaction is scheduled and runs before the next LLM call:

1. Takes all messages except the system prompt and the last `compact_keep_recent` (default 6)
2. Sends a transcript to the LLM with a structured summarization prompt (`PROMPT_COMPACT_SYSTEM` in `core/messages.py`): what was worked on, actions taken with exact paths, key decisions, current state
3. Replaces those messages with the summary
4. Keeps the recent messages verbatim for continuity

Because the trigger is relative to the real context window, a 128K model doesn't compact every few messages while a small local model compacts early. After a compaction, auto-compaction won't re-fire until at least 10% more of the threshold (min. 1,000 tokens) has accumulated. A per-conversation lock (`_compacting: set[str]`) prevents double-firing. `/compact` forces it.

---

## Layer 7: Token Budget Cap

**File:** `src/openacm/core/memory.py`  
**Token savings:** Hard ceiling — prevents context window overflow

On every message added, a token budget enforcer removes the oldest messages (never the system prompt) until the estimated total is under the ceiling:

```python
TRUNCATE_RATIO = 0.85  # never exceed 85% of the model's context window
```

`max_context_messages` (default 50) also caps the number of messages kept in context. This is the last line of defense. In practice, layers 1–6 keep conversations well under this ceiling for most use cases.

---

## Combined Effect

In a typical 30-minute session with moderate tool use, the savings stack like this:

| Layer | Scenario | Estimated savings |
|-------|----------|-------------------|
| Local Router | 30% of messages are conversational/repeated | ~15,000 tokens |
| Semantic tool selection | 25 tools registered, 3 relevant per call | ~4,000 tokens/call |
| Slim schemas | 3 tools × 60% schema reduction | ~900 tokens/call |
| Output compressor | `pip install`, verbose commands | 30–70% of result tokens |
| Old message stripping | 10+ tool calls in history | ~5,000 tokens |
| Conversation compaction | At 60% of the context window | Most of the old history, one-time |

No configuration required — all layers are active by default.

---

## Tuning

Thresholds are configurable in `config/local.yaml` (or from **Configuration** in the dashboard):

```yaml
local_router:
  enabled: true
  confidence_threshold: 0.88  # lower = more fast-paths, higher = safer

assistant:
  compact_ratio: 0.60          # fraction of the context window that triggers compaction
  compact_keep_recent: 6       # messages kept verbatim after compaction
  max_context_messages: 50     # max messages kept in context

llm:
  model_context_overrides:     # context window for models LiteLLM doesn't know
    kimi: 131072
```

The output compressor, slim schemas, semantic threshold (`SEMANTIC_TOOL_THRESHOLD` in `constants.py`) and the 85% ceiling have no config keys — they are always applied.
