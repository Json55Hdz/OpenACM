# Agent Channels — Design Spec

**Date:** 2026-06-16  
**Phase:** 2 of 3 (Agent Superpowers)  
**Approach:** Generic pluggable channel system; one active channel per agent per type

---

## Overview

Agents currently can only be connected to Telegram via a single `telegram_token` field on the `agents` table. There is no way to add WhatsApp Business (or future channels) to an agent, and the architecture is hardcoded for Telegram.

This spec replaces the hardcoded `telegram_token` field with a generic `agent_channels` table and introduces `AgentChannelManager` (replacing `AgentBotManager`) and `AgentWhatsAppChannel` to support multiple channel types per agent.

---

## Database

### New table: `agent_channels`

```sql
CREATE TABLE IF NOT EXISTS agent_channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK(type IN ('telegram', 'whatsapp')),
    config      TEXT NOT NULL DEFAULT '{}',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_channels_agent ON agent_channels(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_channels_type_active ON agent_channels(type, is_active);
```

**Field notes:**
- `config`: JSON blob; shape varies by type (see below)
- `is_active`: soft-disable without deleting; the manager only starts active channels
- Cascade delete: removing an agent stops and removes all its channels automatically

**Config JSON shape per type:**
- Telegram: `{"token": "1234:ABCD..."}`
- WhatsApp: `{"access_token": "EAAx...", "phone_number_id": "12345", "verify_token": "myhook", "app_secret": "aabbcc"}`

### Migration 28

Migration 28 auto-migrates existing `telegram_token` values:

```sql
-- Copy existing Telegram tokens into agent_channels
INSERT INTO agent_channels (agent_id, type, config)
SELECT id, 'telegram', json_object('token', telegram_token)
FROM agents
WHERE telegram_token IS NOT NULL AND telegram_token != '';

-- Clear the old column (kept for schema backward-compat; SQLite cannot DROP columns)
UPDATE agents SET telegram_token = ''
WHERE telegram_token IS NOT NULL AND telegram_token != '';
```

The `agents.telegram_token` column is retained in the schema but permanently cleared. `AgentBotManager` is removed so nothing reads it anymore.

### New database methods

```python
async def create_agent_channel(self, agent_id, type, config_json, is_active=1) -> int
async def get_agent_channels(self, agent_id) -> list[dict]
async def get_agent_channel(self, channel_id) -> dict | None
async def update_agent_channel(self, channel_id, **kwargs) -> bool  # allows: config, is_active
async def delete_agent_channel(self, channel_id) -> bool
async def get_active_channels_by_type(self, type) -> list[dict]  # for startup: load all active whatsapp/telegram channels
```

---

## Backend Architecture

### New file: `src/openacm/channels/agent_whatsapp_channel.py`

`AgentWhatsAppChannel` subclasses `WhatsAppCloudChannel` and overrides two methods:

**`start()`** — same credential validation and httpx setup as the parent, but does **not** set the `_active_channel` module-level singleton (that remains reserved for the global Brain's WhatsApp channel).

**`_respond(sender, content)`** — routes to `AgentRunner.run()` instead of `brain.process_message()`, with user-ID scoping identical to the Telegram pattern:

```python
class AgentWhatsAppChannel(WhatsAppCloudChannel):
    def __init__(self, config: WhatsAppConfig, agent_runner: AgentRunner,
                 agent: dict, event_bus: EventBus):
        super().__init__(config, brain=None, event_bus=event_bus)
        self.agent_runner = agent_runner
        self.agent = agent

    async def start(self):
        # Same as WhatsAppCloudChannel.start() but without _active_channel = self
        ...

    async def _respond(self, sender: str, content: str):
        scoped_uid = f"a{self.agent['id']}_wa_{sender}"
        response = await self.agent_runner.run(
            agent=self.agent,
            message=content,
            user_id=scoped_uid,
            channel_id=sender,
            channel_type=f"whatsapp_a{self.agent['id']}",
        )
        # Reuse parent's ATTACHMENT: parsing + send_message logic
        await self._deliver(sender, response)
```

`_deliver` is extracted from `WhatsAppCloudChannel._respond` into a shared helper so both the global channel and agent channels use the same ATTACHMENT-parsing + send logic.

### Modified: `src/openacm/channels/agent_telegram_bot.py`

`AgentBotManager` is renamed to `AgentChannelManager` and extended to manage channels of any type:

```python
class AgentChannelManager:
    _channels: dict[int, dict[str, BaseChannel]]
    # agent_id → {"telegram": AgentTelegramChannel, "whatsapp": AgentWhatsAppChannel}

    _whatsapp_by_phone: dict[str, AgentWhatsAppChannel]
    # phone_number_id → channel, for webhook routing

    async def start_all(self)          # loads agent_channels table, starts each
    async def start_channel(agent, channel_row)   # routes by type
    async def stop_channel(agent_id, type)
    async def restart_channel(agent_id, type)
    async def stop_all(self)
    def get_channel_by_phone(self, phone_number_id) -> AgentWhatsAppChannel | None
    def get_status(self) -> list[dict]
```

`AgentBrainAdapter` and `AgentTelegramChannel` remain unchanged.

`AgentChannelManager` is exposed on `_state` as `agent_channel_manager`, replacing `agent_bot_manager`.

### Modified: `src/openacm/web/routers/whatsapp_webhook.py`

Routing change in the POST handler: extract `phone_number_id` from the payload before dispatching, and prefer agent channels over the global channel:

```python
for entry in payload.get("entry", []):
    for change in entry.get("changes", []):
        value = change.get("value", {})
        phone_id = value.get("metadata", {}).get("phone_number_id", "")
        channel = (
            _state.agent_channel_manager.get_channel_by_phone(phone_id)
            or get_active_channel()   # global Brain fallback
        )
        if channel:
            await channel.handle_incoming(value)
```

**HMAC verification note:** All agent WhatsApp channels must use the same Facebook App as the global `channels.whatsapp` config (same `app_secret`). The webhook verification step uses the global `app_secret`. This is enforced by documentation, not code — Phase 2 supports one Facebook App per deployment.

---

## API Endpoints

All endpoints live in `src/openacm/web/routers/agents.py`. All require dashboard authentication.

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| `GET` | `/api/agents/{id}/channels` | — | list of channel summaries |
| `POST` | `/api/agents/{id}/channels` | `{type, config}` | created channel |
| `PATCH` | `/api/agents/{id}/channels/{cid}` | `{config?, is_active?}` | updated channel |
| `DELETE` | `/api/agents/{id}/channels/{cid}` | — | `{ok: true}` |
| `POST` | `/api/agents/{id}/channels/{cid}/restart` | — | `{ok: true, connected: bool}` |

**GET response:** Config fields masked — `token`, `access_token`, and `app_secret` show only first 8 characters + `...`. `phone_number_id` and `verify_token` returned as-is. Includes live `is_connected` boolean from `AgentChannelManager`.

**POST rules:**
- 404 if agent not found
- 400 if agent already has an active channel of the same `type`
- 422 if required config keys are missing (`token` for telegram; `access_token` + `phone_number_id` for whatsapp)
- After DB insert, calls `agent_channel_manager.start_channel(agent, row)` if agent `is_active`

**PATCH rules:**
- Config is deep-merged (send only changed keys)
- On any change, calls `agent_channel_manager.restart_channel(agent_id, type)`
- 404 if channel not found

**DELETE:** Calls `agent_channel_manager.stop_channel(agent_id, type)`, then deletes DB row.

**POST `.../restart`:** Stop + start. Returns `{"ok": true, "connected": bool}`.

---

## Frontend

### Channels tab in agent edit modal

A third tab — "📡 Channels" — added alongside "⚙ Config" and "📚 Knowledge". Only visible when editing an existing agent (not when creating).

**Tab layout:**

```
┌────────────────────────────────────────────────────┐
│  ⚙ Config  │  📚 Knowledge  │  📡 Channels          │
├────────────────────────────────────────────────────┤
│                                                    │
│  [+ Agregar canal]                                 │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │ 💬 Telegram                     ● CONECTADO  │ │
│  │    Token: 12345678...           [⟳]  [🗑]   │ │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │ 📱 WhatsApp Business        ○ DESCONECTADO   │ │
│  │    +1 415 555 2671              [⟳]  [🗑]   │ │
│  └──────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

**"+ Agregar canal" inline form:**
- Type selector: `Telegram` | `WhatsApp Business`
- Fields rendered based on selected type:
  - Telegram: `Token del bot`
  - WhatsApp: `Access Token`, `Phone Number ID`, `Verify Token`, `App Secret (opcional)`
- On save → `POST /channels` → channel appears in list

**Channel card:**
- Type icon + name + masked credential + phone number (WhatsApp only)
- Status badge: green dot "CONECTADO" / gray dot "DESCONECTADO"
- `[⟳]` restart: `POST .../restart`, re-fetches list
- `[🗑]` delete: `DELETE .../channels/{id}`

**No inline edit** — to change credentials, delete and re-add.

**WhatsApp webhook docs** — collapsible "Configuración del Webhook" box shown when any WhatsApp channel exists or when WhatsApp is selected in the add form:
- Static webhook URL: `https://tu-dominio.com/webhooks/whatsapp` with copy button
- Instructions: configure in Meta Developer Console → WhatsApp → Configuration → Webhook, subscribe to `messages`
- Three code tabs (cURL / Python / JavaScript) showing how to simulate an incoming message for testing

### Data fetching

New hook `useAgentChannels(agentId)` in `frontend/hooks/use-agents.ts`:
- `queryKey: ['agent-channels', agentId]`, `staleTime: 0`

New hook `useAgentChannelMutations(agentId)` returning `{addChannel, removeChannel, restartChannel}`.

**`ChannelItem` interface:**
```ts
interface ChannelItem {
  id: number
  agent_id: number
  type: 'telegram' | 'whatsapp'
  config: Record<string, string>   // masked by backend
  is_active: boolean
  is_connected: boolean
  created_at: string
}
```

---

## Error Handling

- Invalid channel type → 422
- Missing required config keys → 422 with field-level message
- Duplicate channel type per agent → 400 "Este agente ya tiene un canal de tipo X"
- Channel fails to connect (bad token / wrong credentials) → channel created in DB, `is_connected: false` returned; user sees "DESCONECTADO" badge
- Agent not found → 404 on all endpoints

---

## Tests

- `tests/unit/test_database.py` — `TestAgentChannels` class: CRUD, cascade delete, migration 28
- `tests/unit/test_agent_whatsapp_channel.py` — `_respond` routing, user-ID scoping, `_deliver` shared helper
- `tests/unit/test_agent_channel_manager.py` — `start_all`, `start_channel` by type, `get_channel_by_phone`, `get_status`
- `tests/unit/test_agents_channels_api.py` — all 5 endpoints: happy path + error cases

---

## Out of Scope (future phases)

- Multiple active channels of the same type per agent
- Discord, Slack, or other channel types
- Per-agent custom Facebook App (multiple app_secrets on one webhook)
- Channel-level analytics or message logs
- Auto-detect server domain for webhook URL
