# API Reference

OpenACM exposes a REST API and three WebSocket endpoints. All endpoints (except public ones) require authentication.

**Base URL:** `http://127.0.0.1:47821` (configurable)

---

## Authentication

All protected endpoints require a Bearer token or query parameter:

```http
Authorization: Bearer acm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Or as a query parameter:

```http
GET /api/conversations?token=acm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Public endpoints (no auth required):**
- `GET /api/ping`
- `POST /api/auth/check`
- `GET /api/config/google/callback`

---

## System

### `GET /api/ping`
Health check. Returns immediately.

```json
{ "ok": true }
```

---

### `GET /api/system/info`
System flags.

```json
{
  "messages_encrypted": true
}
```

---

### `POST /api/system/restart`
Restart the OpenACM process (replaces process image via `os.execv`). Returns before the restart completes.

```json
{ "status": "restarting" }
```

---

### `POST /api/auth/check`
Verify a dashboard token.

**Request:**
```json
{ "token": "acm_xxxxxxxx" }
```

**Response:**
```json
{ "valid": true }
```

---

## Statistics

### `GET /api/stats`
Current session statistics.

```json
{
  "total_requests": 147,
  "total_tokens": 284930,
  "total_tool_calls": 89,
  "active_conversations": 3,
  "llm_provider": "anthropic",
  "llm_model": "claude-opus-4-6",
  "uptime_seconds": 3742
}
```

---

### `GET /api/stats/history`
Daily token and request usage for the past 14 days.

```json
[
  { "date": "2025-06-01", "requests": 12, "tokens": 18400 },
  { "date": "2025-06-02", "requests": 27, "tokens": 41200 }
]
```

---

### `GET /api/stats/channels`
Per-channel message counts.

```json
[
  { "channel_id": "web", "message_count": 94 },
  { "channel_id": "telegram", "message_count": 53 }
]
```

---

## Conversations

### `GET /api/conversations`
List all conversations with metadata.

```json
[
  {
    "channel_id": "web",
    "user_id": "web_1775269582270",
    "title": "web - web_1775269582270",
    "last_message": "Take a screenshot of my desktop",
    "last_timestamp": "2025-06-03T14:22:10Z",
    "message_count": 18
  }
]
```

---

### `GET /api/conversations/{channel_id}/{user_id}`
Get conversation history.

**Query params:**
- `limit` (int, default 50) — max messages to return

```json
[
  { "role": "user", "content": "Hello!", "timestamp": "2025-06-03T14:00:00Z" },
  { "role": "assistant", "content": "Hi! How can I help?", "timestamp": "2025-06-03T14:00:01Z" }
]
```

---

### `DELETE /api/conversations/{channel_id}/{user_id}`
Delete all messages for a conversation (memory + database).

```json
{ "status": "ok", "deleted_rows": 18 }
```

---

## Chat

### `POST /api/chat/upload`
Upload a file to attach to the next message.

**Request:** `multipart/form-data` with `file` field.

**Response:**
```json
{
  "id": "upload_abc123.png",
  "name": "screenshot.png",
  "type": "image/png"
}
```

---

### `POST /api/chat/command`
Execute a slash command via REST (alternative to WebSocket).

**Request:**
```json
{
  "command": "/new",
  "user_id": "web_xxx",
  "channel_id": "web"
}
```

**Response:**
```json
{
  "handled": true,
  "text": "Conversation cleared.",
  "data": null
}
```

---

## Tools

### `GET /api/tools`
List all registered tools.

```json
[
  {
    "name": "run_command",
    "description": "Execute a system command",
    "category": "system",
    "risk_level": "high"
  }
]
```

---

### `GET /api/tools/executions`
Recent tool execution log.

**Query params:**
- `limit` (int, default 20)

```json
[
  {
    "tool_name": "web_search",
    "arguments": "{\"query\": \"latest AI news\"}",
    "result": "...",
    "success": true,
    "elapsed_ms": 1247,
    "timestamp": "2025-06-03T14:22:00Z"
  }
]
```

---

## Configuration

### `GET /api/config`
Full configuration (sensitive fields masked).

```json
{
  "llm": {
    "default_provider": "anthropic",
    "providers": { "anthropic": { "default_model": "claude-opus-4-6" } }
  },
  "security": { "execution_mode": "auto" },
  "channels": { "telegram": { "enabled": true } }
}
```

---

### `GET /api/config/model`
Current active model.

```json
{
  "provider": "anthropic",
  "model": "claude-opus-4-6",
  "display_name": "Claude Opus 4.6"
}
```

---

### `POST /api/config/model`
Switch the active LLM model.

**Request:**
```json
{
  "provider": "ollama",
  "model": "llama3.2"
}
```

---

### `GET /api/config/status`
Status of all configured providers (which have valid credentials).

```json
{
  "anthropic": true,
  "openai": false,
  "ollama": true,
  "my_custom_provider": true
}
```

---

### `GET /api/config/available_models`
List available models for each configured provider.

```json
{
  "ollama": ["llama3.2", "mistral", "codellama"],
  "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"]
}
```

---

### `GET /api/config/custom_providers`
List custom (user-defined) LLM providers.

```json
[
  {
    "id": "lmstudio_abc123",
    "name": "LM Studio",
    "base_url": "http://localhost:1234/v1",
    "default_model": "local-model",
    "api_key": ""
  }
]
```

---

### `POST /api/config/custom_providers`
Add a custom provider.

**Request:**
```json
{
  "name": "LM Studio",
  "base_url": "http://localhost:1234/v1",
  "default_model": "local-model",
  "api_key": ""
}
```

---

### `PUT /api/config/custom_providers/{id}`
Update a custom provider.

---

### `DELETE /api/config/custom_providers/{id}`
Delete a custom provider.

---

## Skills

### `GET /api/skills`
List all skills.

```json
[
  {
    "id": 1,
    "name": "blender-modeling",
    "description": "Expert 3D modeling guidance",
    "category": "custom",
    "is_active": false,
    "is_builtin": true
  }
]
```

---

### `POST /api/skills`
Create a new skill.

**Request:**
```json
{
  "name": "my-skill",
  "description": "Description of what this skill does",
  "content": "# My Skill\n\nYou are an expert in...",
  "category": "custom"
}
```

---

### `PUT /api/skills/{skill_id}`
Update a skill.

---

### `DELETE /api/skills/{skill_id}`
Delete a skill.

---

### `POST /api/skills/{skill_id}/toggle`
Toggle a skill active/inactive.

**Request:**
```json
{ "active": true }
```

---

### `POST /api/skills/generate`
Use the LLM to generate a skill from a description.

**Request:**
```json
{ "description": "Make the agent respond like a pirate" }
```

---

## Agents

### `GET /api/agents`
List all agents.

```json
[
  {
    "id": 1,
    "name": "ResearchBot",
    "description": "Searches and summarizes information",
    "system_prompt": "You are a research specialist...",
    "allowed_tools": ["web_search", "get_webpage", "remember_note"],
    "is_active": true,
    "telegram_token": "123456:ABC-..."
  }
]
```

---

### `POST /api/agents`
Create a new agent.

**Request:**
```json
{
  "name": "ResearchBot",
  "description": "Searches and summarizes information",
  "system_prompt": "You are a research specialist...",
  "allowed_tools": ["web_search", "get_webpage"],
  "telegram_token": ""
}
```

---

### `PUT /api/agents/{agent_id}`
Update an agent.

---

### `DELETE /api/agents/{agent_id}`
Delete an agent.

---

### `POST /api/agents/{agent_id}/chat`
Send a message to a specific agent.

**Request:**
```json
{
  "message": "Find the latest research on LLM agents",
  "user_id": "web"
}
```

**Response:**
```json
{ "response": "Here's what I found..." }
```

---

### `POST /api/agents/generate`
Generate an agent config from a description using the LLM.

**Request:**
```json
{ "description": "An agent specialized in Python code review" }
```

---

## MCP Servers

### `GET /api/mcp/servers`
List configured MCP servers.

```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "mcp_filesystem"],
    "connected": true,
    "tool_count": 8,
    "auto_connect": true
  }
]
```

---

### `POST /api/mcp/servers`
Add a new MCP server.

**Request:**
```json
{
  "name": "my-server",
  "transport": "stdio",
  "command": "python",
  "args": ["-m", "my_mcp_server"],
  "env": {},
  "auto_connect": false
}
```

---

### `PUT /api/mcp/servers/{server_name}`
Update MCP server config.

---

### `DELETE /api/mcp/servers/{server_name}`
Remove an MCP server (disconnects if connected).

---

### `POST /api/mcp/servers/{server_name}/connect`
Connect to an MCP server and register its tools.

```json
{ "status": "connected", "tools_registered": 8 }
```

---

### `POST /api/mcp/servers/{server_name}/disconnect`
Disconnect from an MCP server.

---

## Routines & Activity

### `GET /api/routines`
List detected automation routines.

```json
[
  {
    "id": 1,
    "name": "Morning Report",
    "description": "Check emails, weather, and calendar every morning",
    "apps": ["Outlook", "Chrome"],
    "frequency": 12,
    "confidence": 0.87,
    "last_triggered": "2025-06-03T08:00:00Z"
  }
]
```

---

### `POST /api/routines/{routine_id}/execute`
Manually trigger a detected routine.

---

### `PUT /api/routines/{routine_id}`
Update a routine (name, description, enabled).

---

### `DELETE /api/routines/{routine_id}`
Delete a detected routine.

---

### `POST /api/routines/analyze`
Trigger pattern analysis on recent activity data.

```json
{ "routines_found": 3 }
```

---

### `GET /api/activity/stats`
Activity summary statistics.

```json
{
  "total_sessions": 284,
  "total_active_ms": 28800000,
  "top_apps": [
    { "app": "Code", "total_ms": 12400000, "sessions": 94 },
    { "app": "Chrome", "total_ms": 8200000, "sessions": 112 }
  ]
}
```

---

### `GET /api/activity/sessions`
Recent activity sessions (decrypted).

**Query params:**
- `limit` (int, default 50)
- `app` (str) — filter by app name

---

### `GET /api/watcher/status`
Activity watcher status.

```json
{
  "running": true,
  "current_app": "Code",
  "session_start": "2025-06-03T14:15:00Z"
}
```

---

## Debug

### `GET /api/debug/traces`
Last 20 agentic loop traces for debugging.

```json
[
  {
    "id": "a1b2c3d4",
    "started_at": "2025-06-03T14:22:10",
    "user_message": "take a screenshot",
    "iterations": [
      {
        "iteration": 1,
        "message_count": 4,
        "context_chars": 2400,
        "llm_elapsed_ms": 834,
        "tool_calls": [
          { "tool": "take_screenshot", "result_chars": 45, "elapsed_ms": 312 }
        ]
      }
    ],
    "total_elapsed_ms": 1842,
    "outcome": "success"
  }
]
```

---

### `GET /api/terminal/history`
Recent terminal commands and outputs from tool execution.

---

## Media

### `GET /api/media`
List files in the media directory.

```json
[
  { "name": "screenshot_001.png", "size": 284920, "created": "2025-06-03T14:22:00Z" }
]
```

---

### `GET /api/media/{file_name}`
Serve a media file.

**Query params:**
- `download=true` — force download (Content-Disposition: attachment)
- `token=xxx` — auth token (alternative to header)

---

## WebSocket: Chat (`/ws/chat`)

Connect with token:
```
ws://127.0.0.1:47821/ws/chat?token=acm_xxx
```

### Client → Server

**Send a message:**
```json
{
  "message": "Take a screenshot of my screen",
  "target_user_id": "web",
  "target_channel_id": "web",
  "attachments": []
}
```

**Cancel current request** (stops the active agentic task for this channel):
```json
{
  "type": "cancel",
  "target_user_id": "web",
  "target_channel_id": "web"
}
```

### Server → Client

**Response message:**
```json
{
  "type": "response",
  "content": "Here's your screenshot!",
  "attachments": ["screenshot_1775274080.png"]
}
```

**Error:**
```json
{
  "type": "error",
  "content": "Connection to LLM failed"
}
```

**Command result:**
```json
{
  "type": "command",
  "content": "Conversation cleared."
}
```

---

## WebSocket: Events (`/ws/events`)

Connect with token:
```
ws://127.0.0.1:47821/ws/events?token=acm_xxx
```

Server-only stream. Emits real-time system events:

**Thinking status:**
```json
{
  "type": "thinking",
  "status": "processing",
  "message": "🔄 Step 2/20...",
  "iteration": 2,
  "user_id": "web_xxx",
  "channel_id": "web",
  "channel_type": "web"
}
```

**Tool called:**
```json
{
  "type": "tool.called",
  "tool": "web_search",
  "arguments": "{\"query\": \"AI news\"}",
  "user_id": "web_xxx",
  "channel_id": "web",
  "channel_type": "web"
}
```

**Tool result:**
```json
{
  "type": "tool.result",
  "tool": "web_search",
  "result": "1. OpenAI releases...",
  "user_id": "web_xxx",
  "channel_id": "web",
  "channel_type": "web"
}
```

**Message sent (partial):**
```json
{
  "type": "message.sent",
  "content": "I'll search for that now...",
  "partial": true,
  "channel_type": "web",
  "channel_id": "web"
}
```

**Memory recall:**
```json
{
  "type": "memory.recall",
  "status": "found",
  "count": 3,
  "user_id": "web_xxx",
  "channel_id": "web"
}
```

**Skill active:**
```json
{
  "type": "skill.active",
  "skills": ["blender-modeling"],
  "channel_id": "web",
  "channel_type": "web"
}
```

---

## WebSocket: Terminal (`/ws/terminal`)

Connect with token and channel:
```
ws://127.0.0.1:47821/ws/terminal?token=acm_xxx&channel=web
```

**`channel`** — the chat channel ID this terminal belongs to (e.g. `web`, `telegram-123456`). Each channel gets its own persistent PTY shell session. The session survives WebSocket reconnects, so SSH connections and running processes are not interrupted.

The terminal is a **full interactive PTY** (Windows: ConPTY via `pywinpty`; Linux/Mac: `pty` module). The frontend renders it with [xterm.js](https://xtermjs.org/) for proper ANSI color support, prompt display, and keyboard handling.

### Client → Server

**User input** (keystroke data, exactly as xterm.js produces it):
```json
{"type": "input", "data": "ls -la\n"}
```

**Signal** (Ctrl+C):
```json
{"type": "signal"}
```

**Terminal resize** (sent automatically when the panel resizes):
```json
{"type": "resize", "cols": 220, "rows": 50}
```

### Server → Client

**Shell output** (raw PTY bytes, includes ANSI escape codes):
```json
{"type": "output", "data": "\u001b[32muser@host\u001b[0m:/home/user$ "}
```

**AI tool command** (shown in magenta in the terminal):
```json
{"type": "ai_command", "tool": "run_command", "data": "npm install"}
```

**AI tool streaming output**:
```json
{"type": "ai_output", "tool": "run_command", "data": "added 142 packages in 3.2s\n"}
```

**Shell exited**:
```json
{"type": "exit", "data": "shell process exited"}
```

**Error** (e.g. PTY failed to start):
```json
{"type": "error", "data": "Failed to start shell: ..."}
```

---

## Error Codes

| HTTP Code | Meaning |
|-----------|---------|
| 200 | Success |
| 401 | Missing or invalid token |
| 403 | Forbidden (valid token but insufficient permissions) |
| 404 | Resource not found |
| 422 | Validation error (invalid request body) |
| 503 | Service not available (Brain or Database not initialized) |
