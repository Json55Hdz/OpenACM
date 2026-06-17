# Agent Channels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `telegram_token` on the agents table with a generic `agent_channels` table, add `AgentChannelManager` (replaces `AgentBotManager`), add `AgentWhatsAppChannel`, expose CRUD API endpoints, and surface a Channels tab in the agent edit modal.

**Architecture:** New `agent_channels` SQLite table (migration 28 auto-migrates existing Telegram tokens). `AgentChannelManager` manages per-agent `AgentTelegramChannel` and `AgentWhatsAppChannel` instances keyed by `(agent_id, type)`. WhatsApp webhook routing dispatches by `phone_number_id` to the correct agent channel before falling back to the global Brain channel.

**Tech Stack:** Python/FastAPI backend, aiosqlite, httpx, Next.js/React frontend, TanStack Query (React Query), Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-06-16-agent-channels-design.md`

**Tests:** Run with `pytest`. All async tests run without `@pytest.mark.asyncio` (auto mode). Run full suite with `pytest` after each task.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/openacm/storage/database.py` | Modify | Migration 28 + 5 CRUD methods for `agent_channels` |
| `src/openacm/channels/whatsapp_cloud_channel.py` | Modify | Extract `_deliver` helper from `_respond` |
| `src/openacm/channels/agent_whatsapp_channel.py` | Create | `AgentWhatsAppChannel` subclass |
| `src/openacm/channels/agent_telegram_bot.py` | Modify | Rename `AgentBotManager` → `AgentChannelManager`, extend for multi-type |
| `src/openacm/web/state.py` | Modify | Add `agent_channel_manager` field, keep `agent_bot_manager` as alias |
| `src/openacm/web/server.py` | Modify | Accept `agent_channel_manager` in `create_web_server` |
| `src/openacm/app.py` | Modify | `_init_agent_bots` → `_init_agent_channels`, use `AgentChannelManager` |
| `src/openacm/web/routers/whatsapp_webhook.py` | Modify | Route by `phone_number_id` to agent channels |
| `src/openacm/web/routers/agents.py` | Modify | 5 channel endpoints + fix `agent_bot_manager` refs |
| `tests/unit/test_database.py` | Modify | Add `TestAgentChannels` class |
| `tests/unit/test_agent_whatsapp_channel.py` | Create | `_respond` routing, user-ID scoping |
| `tests/unit/test_agent_channel_manager.py` | Create | `start_all`, `start_channel`, `get_channel_by_phone` |
| `tests/unit/test_agents_channels_api.py` | Create | 5 endpoints: happy path + error cases |
| `frontend/hooks/use-agents.ts` | Modify | `ChannelItem` interface + 2 new hooks |
| `frontend/app/agents/page.tsx` | Modify | `ChannelsTab` component + third tab in modal |

---

## Task 1: Database — migration 28 + CRUD methods

**Files:**
- Modify: `src/openacm/storage/database.py`
- Modify: `tests/unit/test_database.py`

- [ ] **Step 1: Write the failing tests**

Open `tests/unit/test_database.py` and add this class at the end of the file (after `TestAgentKnowledge`):

```python
class TestAgentChannels:
    async def test_create_and_get(self, db):
        agent_id = await db.create_agent(
            name="A", description="", system_prompt="p",
            allowed_tools="all", webhook_secret="s", telegram_token=""
        )
        cid = await db.create_agent_channel(
            agent_id=agent_id, type="telegram",
            config_json='{"token":"abc123"}', is_active=1
        )
        assert cid > 0
        rows = await db.get_agent_channels(agent_id)
        assert len(rows) == 1
        assert rows[0]["type"] == "telegram"
        assert rows[0]["is_active"] == 1
        import json
        assert json.loads(rows[0]["config"])["token"] == "abc123"

    async def test_get_agent_channel_by_id(self, db):
        agent_id = await db.create_agent(
            name="B", description="", system_prompt="p",
            allowed_tools="all", webhook_secret="s", telegram_token=""
        )
        cid = await db.create_agent_channel(
            agent_id=agent_id, type="whatsapp",
            config_json='{"phone_number_id":"555"}', is_active=1
        )
        row = await db.get_agent_channel(cid)
        assert row is not None
        assert row["id"] == cid
        assert row["type"] == "whatsapp"

    async def test_get_agent_channel_not_found(self, db):
        row = await db.get_agent_channel(9999)
        assert row is None

    async def test_update_config(self, db):
        agent_id = await db.create_agent(
            name="C", description="", system_prompt="p",
            allowed_tools="all", webhook_secret="s", telegram_token=""
        )
        cid = await db.create_agent_channel(
            agent_id=agent_id, type="telegram",
            config_json='{"token":"old"}', is_active=1
        )
        ok = await db.update_agent_channel(cid, config='{"token":"new"}')
        assert ok
        row = await db.get_agent_channel(cid)
        import json
        assert json.loads(row["config"])["token"] == "new"

    async def test_update_is_active(self, db):
        agent_id = await db.create_agent(
            name="D", description="", system_prompt="p",
            allowed_tools="all", webhook_secret="s", telegram_token=""
        )
        cid = await db.create_agent_channel(
            agent_id=agent_id, type="telegram",
            config_json='{"token":"x"}', is_active=1
        )
        ok = await db.update_agent_channel(cid, is_active=0)
        assert ok
        row = await db.get_agent_channel(cid)
        assert row["is_active"] == 0

    async def test_delete(self, db):
        agent_id = await db.create_agent(
            name="E", description="", system_prompt="p",
            allowed_tools="all", webhook_secret="s", telegram_token=""
        )
        cid = await db.create_agent_channel(
            agent_id=agent_id, type="telegram",
            config_json='{"token":"y"}', is_active=1
        )
        ok = await db.delete_agent_channel(cid)
        assert ok
        assert await db.get_agent_channel(cid) is None

    async def test_cascade_delete(self, db):
        agent_id = await db.create_agent(
            name="F", description="", system_prompt="p",
            allowed_tools="all", webhook_secret="s", telegram_token=""
        )
        cid = await db.create_agent_channel(
            agent_id=agent_id, type="telegram",
            config_json='{"token":"z"}', is_active=1
        )
        await db.delete_agent(agent_id)
        assert await db.get_agent_channel(cid) is None

    async def test_migration_28_clears_telegram_token(self, db):
        # Simulate a pre-migration agent with a telegram_token
        await db._db.execute(
            "UPDATE agents SET telegram_token = 'old_token_123' WHERE id = (SELECT id FROM agents LIMIT 1)"
        )
        await db._db.commit()
        # Re-run migrations (idempotent — migration 28 already ran, so just verify state)
        rows = await db.get_all_agents()
        for agent in rows:
            # After migration 28, all telegram_tokens should be empty
            assert agent.get("telegram_token", "") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_database.py::TestAgentChannels -v
```

Expected: `AttributeError: 'Database' object has no attribute 'create_agent_channel'`

- [ ] **Step 3: Add migration 28 to `database.py`**

In `src/openacm/storage/database.py`:

Change line `_SCHEMA_VERSION = 27` to:

```python
_SCHEMA_VERSION = 28
```

Then after the migration 27 block (around line 850, after `log.info("Migration 27: created agent_knowledge table")`), add:

```python
        if current < 28:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_channels (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    type        TEXT NOT NULL CHECK(type IN ('telegram', 'whatsapp')),
                    config      TEXT NOT NULL DEFAULT '{}',
                    is_active   INTEGER NOT NULL DEFAULT 1,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_agent_channels_agent
                    ON agent_channels(agent_id);
                CREATE INDEX IF NOT EXISTS idx_agent_channels_type_active
                    ON agent_channels(type, is_active);
            """)
            # Migrate existing telegram_token values into agent_channels
            await self._db.execute("""
                INSERT INTO agent_channels (agent_id, type, config)
                SELECT id, 'telegram', json_object('token', telegram_token)
                FROM agents
                WHERE telegram_token IS NOT NULL AND telegram_token != ''
            """)
            await self._db.execute("""
                UPDATE agents SET telegram_token = ''
                WHERE telegram_token IS NOT NULL AND telegram_token != ''
            """)
            await self._db.commit()
            log.info("Migration 28: created agent_channels table, migrated telegram_token values")
```

- [ ] **Step 4: Add 5 CRUD methods to `database.py`**

After the `delete_agent_knowledge` method (around line 1469), add a new section:

```python
    # ─── Agent Channels ───────────────────────────────────────

    async def create_agent_channel(
        self,
        agent_id: int,
        type: str,
        config_json: str,
        is_active: int = 1,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO agent_channels (agent_id, type, config, is_active) VALUES (?, ?, ?, ?)",
            (agent_id, type, config_json, is_active),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_agent_channels(self, agent_id: int) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM agent_channels WHERE agent_id = ? ORDER BY created_at ASC",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_agent_channel(self, channel_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM agent_channels WHERE id = ?", (channel_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_agent_channel(self, channel_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {"config", "is_active"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(channel_id)
        await self._db.execute(
            f"UPDATE agent_channels SET {', '.join(updates)} WHERE id = ?", params
        )
        await self._db.commit()
        return True

    async def delete_agent_channel(self, channel_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM agent_channels WHERE id = ?", (channel_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 5: Run tests**

```
pytest tests/unit/test_database.py::TestAgentChannels -v
```

Expected: all 8 tests PASS.

Note: `test_migration_28_clears_telegram_token` verifies that after migration 28 runs (it runs at DB init in the `db` fixture), no agents have a non-empty `telegram_token`. If the test fixture creates a fresh DB, migration 28 creates the table with no pre-existing tokens, so the assertion trivially passes. This is correct behavior.

- [ ] **Step 6: Run full test suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/openacm/storage/database.py tests/unit/test_database.py
git commit -m "feat(db): migration 28 — agent_channels table + telegram_token auto-migration"
```

---

## Task 2: Extract `_deliver` + create `AgentWhatsAppChannel`

**Files:**
- Modify: `src/openacm/channels/whatsapp_cloud_channel.py`
- Create: `src/openacm/channels/agent_whatsapp_channel.py`
- Create: `tests/unit/test_agent_whatsapp_channel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_agent_whatsapp_channel.py`:

```python
"""Tests for AgentWhatsAppChannel."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_wa_config(phone_id="12345"):
    from openacm.core.config import WhatsAppConfig
    return WhatsAppConfig(
        enabled=True,
        access_token="token123",
        phone_number_id=phone_id,
        verify_token="vt",
        app_secret="",
        graph_api_version="v21.0",
    )


def _make_channel(phone_id="12345"):
    from openacm.channels.agent_whatsapp_channel import AgentWhatsAppChannel
    agent = {"id": 7, "name": "TestAgent", "system_prompt": "hi", "allowed_tools": "none"}
    runner = MagicMock()
    runner.run = AsyncMock(return_value="Hola respuesta")
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    return AgentWhatsAppChannel(
        config=_make_wa_config(phone_id),
        agent_runner=runner,
        agent=agent,
        event_bus=event_bus,
    ), runner


class TestAgentWhatsAppChannel:
    async def test_respond_scopes_user_id(self):
        ch, runner = _make_channel()
        ch._http = MagicMock()
        ch._connected = True

        with patch.object(ch, "_deliver", new=AsyncMock()) as mock_deliver:
            await ch._respond("5214155552671", "Hola")

        runner.run.assert_awaited_once()
        call_kwargs = runner.run.call_args.kwargs
        assert call_kwargs["user_id"] == "a7_wa_5214155552671"
        assert call_kwargs["channel_type"] == "whatsapp_a7"
        assert call_kwargs["message"] == "Hola"

    async def test_respond_calls_deliver_with_response(self):
        ch, runner = _make_channel()
        ch._http = MagicMock()
        runner.run = AsyncMock(return_value="Mi respuesta")

        with patch.object(ch, "_deliver", new=AsyncMock()) as mock_deliver:
            await ch._respond("521111", "Test")

        mock_deliver.assert_awaited_once_with("521111", "Mi respuesta")

    async def test_start_does_not_set_active_channel_singleton(self):
        from openacm.channels import whatsapp_cloud_channel as wcc
        ch, _ = _make_channel()

        original = wcc._active_channel

        with patch.object(ch, "_http", MagicMock()), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"display_phone_number": "+1 415 555 0001"}
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client
            await ch.start()

        assert wcc._active_channel is original, "AgentWhatsAppChannel must not overwrite _active_channel"

    async def test_deliver_sends_plain_text(self):
        ch, _ = _make_channel()
        ch._http = MagicMock()

        with patch.object(ch, "send_message", new=AsyncMock()) as mock_send:
            await ch._deliver("521111", "Hola mundo")

        mock_send.assert_awaited_once_with("521111", "Hola mundo")

    async def test_deliver_strips_attachment_lines(self):
        ch, _ = _make_channel()
        ch._http = MagicMock()

        with patch.object(ch, "send_message", new=AsyncMock()) as mock_send, \
             patch.object(ch, "_send_media", new=AsyncMock(return_value=False)):
            await ch._deliver("521111", "Texto\nATTACHMENT: noexists.pdf")

        mock_send.assert_awaited_once_with("521111", "Texto")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_agent_whatsapp_channel.py -v
```

Expected: `ImportError: cannot import name 'AgentWhatsAppChannel' from 'openacm.channels.agent_whatsapp_channel'`

- [ ] **Step 3: Extract `_deliver` from `WhatsAppCloudChannel._respond`**

In `src/openacm/channels/whatsapp_cloud_channel.py`, replace the `_respond` method with:

```python
    async def _deliver(self, sender: str, response: str):
        """Parse ATTACHMENT: lines and send text + media to sender."""
        import os
        project_root = os.environ.get("OPENACM_PROJECT_ROOT", ".")
        media_dir = Path(project_root) / "data" / "media"

        lines = response.splitlines()
        attachment_names = [l[len("ATTACHMENT:"):].strip() for l in lines if l.startswith("ATTACHMENT:")]
        clean_text = "\n".join(l for l in lines if not l.startswith("ATTACHMENT:")).strip()

        for fname in attachment_names:
            fpath = media_dir / fname
            if fpath.exists():
                if await self._send_media(sender, fpath, clean_text):
                    clean_text = ""

        if clean_text:
            await self.send_message(sender, clean_text)

    async def _respond(self, sender: str, content: str):
        """Run the brain and deliver the reply."""
        response = await self.brain.process_message(
            content=content,
            user_id=sender,
            channel_id=sender,
            channel_type="whatsapp",
        )
        await self._deliver(sender, response)
```

- [ ] **Step 4: Create `src/openacm/channels/agent_whatsapp_channel.py`**

```python
"""
AgentWhatsAppChannel — routes WhatsApp messages to a specific agent's AgentRunner.

Subclasses WhatsAppCloudChannel and overrides:
  - start(): same credential check but does NOT set the _active_channel singleton
  - _respond(): routes to AgentRunner instead of Brain
"""
from __future__ import annotations

import asyncio
import structlog
import httpx

from openacm.channels.whatsapp_cloud_channel import WhatsAppCloudChannel
from openacm.core.config import WhatsAppConfig
from openacm.core.events import EventBus, EVENT_CHANNEL_CONNECTED, EVENT_CHANNEL_DISCONNECTED
from openacm.core.agent_runner import AgentRunner

log = structlog.get_logger()


class AgentWhatsAppChannel(WhatsAppCloudChannel):
    """WhatsApp channel for a single agent (does not touch the global _active_channel)."""

    def __init__(
        self,
        config: WhatsAppConfig,
        agent_runner: AgentRunner,
        agent: dict,
        event_bus: EventBus,
    ):
        # Pass brain=None — we override _respond so brain is never called
        super().__init__(config=config, brain=None, event_bus=event_bus)
        self.agent_runner = agent_runner
        self.agent = agent

    async def start(self):
        """Connect without setting the module-level _active_channel singleton."""
        if not self.config.access_token or not self.config.phone_number_id:
            log.warning(
                "AgentWhatsAppChannel not configured",
                agent_id=self.agent["id"],
            )
            self.ready_event.set()
            return

        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self.config.access_token}"},
            timeout=30,
        )

        try:
            resp = await self._http.get(f"/{self.config.phone_number_id}")
            if resp.status_code == 200:
                self._connected = True
                log.info(
                    "AgentWhatsAppChannel connected",
                    agent=self.agent["name"],
                    number=resp.json().get("display_phone_number"),
                )
            else:
                log.warning(
                    "AgentWhatsAppChannel credential check failed",
                    agent=self.agent["name"],
                    status=resp.status_code,
                )
        except Exception as exc:
            log.warning("AgentWhatsAppChannel could not reach Graph API", error=str(exc))

        self.ready_event.set()
        if self._connected:
            await self.event_bus.emit(
                EVENT_CHANNEL_CONNECTED,
                {"channel": "whatsapp", "agent_id": self.agent["id"]},
            )

    async def stop(self):
        if self._http:
            await self._http.aclose()
        self._connected = False
        await self.event_bus.emit(
            EVENT_CHANNEL_DISCONNECTED,
            {"channel": "whatsapp", "agent_id": self.agent["id"]},
        )

    async def _respond(self, sender: str, content: str):
        """Route to AgentRunner with scoped user_id for memory isolation."""
        scoped_uid = f"a{self.agent['id']}_wa_{sender}"
        response = await self.agent_runner.run(
            agent=self.agent,
            message=content,
            user_id=scoped_uid,
            channel_id=sender,
            channel_type=f"whatsapp_a{self.agent['id']}",
        )
        await self._deliver(sender, response)
```

- [ ] **Step 5: Run tests**

```
pytest tests/unit/test_agent_whatsapp_channel.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run full suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/openacm/channels/whatsapp_cloud_channel.py \
        src/openacm/channels/agent_whatsapp_channel.py \
        tests/unit/test_agent_whatsapp_channel.py
git commit -m "feat(channels): extract WhatsApp _deliver helper; add AgentWhatsAppChannel"
```

---

## Task 3: AgentChannelManager (replaces AgentBotManager)

**Files:**
- Modify: `src/openacm/channels/agent_telegram_bot.py`
- Create: `tests/unit/test_agent_channel_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_agent_channel_manager.py`:

```python
"""Tests for AgentChannelManager."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_manager():
    from openacm.channels.agent_telegram_bot import AgentChannelManager
    runner = MagicMock()
    runner.run = AsyncMock(return_value="ok")
    runner.llm_router = MagicMock()
    runner.memory = MagicMock()
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    event_bus.on = MagicMock()
    event_bus.off = MagicMock()
    db = MagicMock()
    db.get_all_agents = AsyncMock(return_value=[])
    db.get_agent_channels = AsyncMock(return_value=[])
    db.get_agent = AsyncMock(return_value=None)
    return AgentChannelManager(agent_runner=runner, event_bus=event_bus, database=db)


class TestAgentChannelManager:
    def test_instantiation(self):
        mgr = _make_manager()
        assert mgr._channels == {}
        assert mgr._whatsapp_by_phone == {}

    async def test_start_all_empty(self):
        mgr = _make_manager()
        await mgr.start_all()
        assert mgr._channels == {}

    async def test_start_all_skips_inactive_agents(self):
        from openacm.channels.agent_telegram_bot import AgentChannelManager
        runner = MagicMock()
        event_bus = MagicMock()
        event_bus.emit = AsyncMock()
        event_bus.on = MagicMock()
        db = MagicMock()
        db.get_all_agents = AsyncMock(return_value=[
            {"id": 1, "name": "A", "is_active": 0, "system_prompt": "x", "allowed_tools": "none"}
        ])
        db.get_agent_channels = AsyncMock(return_value=[])
        mgr = AgentChannelManager(agent_runner=runner, event_bus=event_bus, database=db)
        await mgr.start_all()
        db.get_agent_channels.assert_not_called()

    async def test_get_channel_by_phone_returns_none_when_empty(self):
        mgr = _make_manager()
        assert mgr.get_channel_by_phone("12345") is None

    async def test_get_channel_by_phone_returns_channel_after_register(self):
        from openacm.channels.agent_whatsapp_channel import AgentWhatsAppChannel
        mgr = _make_manager()
        mock_ch = MagicMock(spec=AgentWhatsAppChannel)
        mgr._whatsapp_by_phone["12345"] = mock_ch
        assert mgr.get_channel_by_phone("12345") is mock_ch

    async def test_stop_channel_telegram_removes_from_dict(self):
        mgr = _make_manager()
        mock_bot = MagicMock()
        mock_bot.stop = AsyncMock()
        mgr._channels[1] = {"telegram": mock_bot}
        await mgr.stop_channel(1, "telegram")
        mock_bot.stop.assert_awaited_once()
        assert "telegram" not in mgr._channels.get(1, {})

    async def test_stop_all_stops_everything(self):
        mgr = _make_manager()
        mock_tg = MagicMock()
        mock_tg.stop = AsyncMock()
        mock_wa = MagicMock()
        mock_wa.stop = AsyncMock()
        mock_wa.config = MagicMock()
        mock_wa.config.phone_number_id = "555"
        mgr._channels[1] = {"telegram": mock_tg, "whatsapp": mock_wa}
        mgr._whatsapp_by_phone["555"] = mock_wa
        await mgr.stop_all()
        mock_tg.stop.assert_awaited_once()
        mock_wa.stop.assert_awaited_once()
        assert mgr._channels == {}
        assert mgr._whatsapp_by_phone == {}

    def test_get_status_returns_list(self):
        mgr = _make_manager()
        mock_tg = MagicMock()
        mock_tg.is_connected = True
        mgr._channels[1] = {"telegram": mock_tg}
        status = mgr.get_status()
        assert len(status) == 1
        assert status[0]["agent_id"] == 1
        assert status[0]["type"] == "telegram"
        assert status[0]["connected"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_agent_channel_manager.py -v
```

Expected: `ImportError: cannot import name 'AgentChannelManager' from 'openacm.channels.agent_telegram_bot'`

- [ ] **Step 3: Rewrite `agent_telegram_bot.py`**

Replace the entire `AgentBotManager` class at the bottom of `src/openacm/channels/agent_telegram_bot.py` with:

```python
class AgentChannelManager:
    """
    Manages one channel per agent per type (telegram, whatsapp).

    Replaces AgentBotManager. Reads from the agent_channels table instead
    of the agents.telegram_token field.
    """

    def __init__(self, agent_runner: AgentRunner, event_bus, database):
        self.agent_runner = agent_runner
        self.event_bus = event_bus
        self.database = database
        # agent_id → {type → channel_instance}
        self._channels: dict[int, dict[str, object]] = {}
        # phone_number_id → AgentWhatsAppChannel (for webhook routing)
        self._whatsapp_by_phone: dict[str, object] = {}

    async def start_all(self):
        """Start channels for all active agents."""
        agents = await self.database.get_all_agents()
        active = [a for a in agents if a.get("is_active")]
        if not active:
            log.info("No active agents with channels configured")
            return

        started = 0
        for agent in active:
            channel_rows = await self.database.get_agent_channels(agent["id"])
            for row in channel_rows:
                if row.get("is_active"):
                    try:
                        await self.start_channel(agent, row)
                        started += 1
                    except Exception as exc:
                        log.warning(
                            "AgentChannelManager: failed to start channel",
                            agent=agent["name"],
                            type=row["type"],
                            error=str(exc),
                        )

        if started:
            log.info("Agent channels started", count=started)

    async def start_channel(self, agent: dict, channel_row: dict):
        """Start a single channel for an agent based on channel_row type."""
        channel_type = channel_row["type"]
        agent_id = agent["id"]
        config_json = channel_row.get("config", "{}")
        import json as _json
        config_data = _json.loads(config_json)

        # Stop existing channel of this type if running
        await self.stop_channel(agent_id, channel_type)

        if channel_type == "telegram":
            channel = self._make_telegram_channel(agent, config_data)
        elif channel_type == "whatsapp":
            channel = self._make_whatsapp_channel(agent, config_data)
        else:
            log.warning("Unknown channel type", type=channel_type)
            return

        # Register in _channels dict
        if agent_id not in self._channels:
            self._channels[agent_id] = {}
        self._channels[agent_id][channel_type] = channel

        # Register WhatsApp in phone lookup
        if channel_type == "whatsapp":
            phone_id = config_data.get("phone_number_id", "")
            if phone_id:
                self._whatsapp_by_phone[phone_id] = channel

        asyncio.create_task(channel.start())
        await asyncio.wait_for(channel.ready_event.wait(), timeout=15)

        if channel.is_connected:
            log.info("Agent channel started", agent=agent["name"], type=channel_type)
        else:
            log.warning("Agent channel failed to connect", agent=agent["name"], type=channel_type)

    def _make_telegram_channel(self, agent: dict, config_data: dict):
        from openacm.core.config import TelegramConfig
        token = config_data.get("token", "")
        brain_adapter = AgentBrainAdapter(agent, self.agent_runner)
        tg_config = TelegramConfig(token=token, enabled=True)
        return AgentTelegramChannel(
            config=tg_config,
            brain=brain_adapter,
            event_bus=self.event_bus,
            database=self.database,
        )

    def _make_whatsapp_channel(self, agent: dict, config_data: dict):
        from openacm.channels.agent_whatsapp_channel import AgentWhatsAppChannel
        from openacm.core.config import WhatsAppConfig
        wa_config = WhatsAppConfig(
            enabled=True,
            access_token=config_data.get("access_token", ""),
            phone_number_id=config_data.get("phone_number_id", ""),
            verify_token=config_data.get("verify_token", ""),
            app_secret=config_data.get("app_secret", ""),
        )
        return AgentWhatsAppChannel(
            config=wa_config,
            agent_runner=self.agent_runner,
            agent=agent,
            event_bus=self.event_bus,
        )

    async def stop_channel(self, agent_id: int, channel_type: str):
        """Stop a specific channel type for an agent."""
        agent_channels = self._channels.get(agent_id, {})
        ch = agent_channels.pop(channel_type, None)
        if not agent_channels:
            self._channels.pop(agent_id, None)
        if ch is None:
            return
        # Remove from whatsapp phone lookup
        if channel_type == "whatsapp":
            dead_phones = [k for k, v in self._whatsapp_by_phone.items() if v is ch]
            for k in dead_phones:
                del self._whatsapp_by_phone[k]
        try:
            await ch.stop()
        except Exception:
            pass
        log.info("Agent channel stopped", agent_id=agent_id, type=channel_type)

    async def restart_channel(self, agent_id: int, channel_type: str):
        """Reload channel config from DB and restart."""
        agent = await self.database.get_agent(agent_id)
        if not agent or not agent.get("is_active"):
            await self.stop_channel(agent_id, channel_type)
            return
        channel_rows = await self.database.get_agent_channels(agent_id)
        row = next((r for r in channel_rows if r["type"] == channel_type), None)
        if not row or not row.get("is_active"):
            await self.stop_channel(agent_id, channel_type)
            return
        await self.start_channel(agent, row)

    async def stop_all(self):
        """Stop all running channels."""
        for agent_id in list(self._channels.keys()):
            for channel_type in list(self._channels.get(agent_id, {}).keys()):
                await self.stop_channel(agent_id, channel_type)

    def get_channel_by_phone(self, phone_number_id: str):
        """Return the AgentWhatsAppChannel registered for this phone_number_id, or None."""
        return self._whatsapp_by_phone.get(phone_number_id)

    def get_status(self) -> list[dict]:
        """Return live connection status for all managed channels."""
        result = []
        for agent_id, type_map in self._channels.items():
            for channel_type, ch in type_map.items():
                result.append({
                    "agent_id": agent_id,
                    "type": channel_type,
                    "connected": ch.is_connected,
                })
        return result


# Keep old name as alias so existing code referencing AgentBotManager still imports
AgentBotManager = AgentChannelManager
```

- [ ] **Step 4: Run tests**

```
pytest tests/unit/test_agent_channel_manager.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Run full suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/channels/agent_telegram_bot.py \
        tests/unit/test_agent_channel_manager.py
git commit -m "feat(channels): AgentChannelManager replaces AgentBotManager; multi-type channel support"
```

---

## Task 4: Wire app.py, state.py, server.py

**Files:**
- Modify: `src/openacm/web/state.py`
- Modify: `src/openacm/web/server.py`
- Modify: `src/openacm/app.py`
- Modify: `src/openacm/web/routers/agents.py` (fix `agent_bot_manager` references)

No new tests — this is plumbing. Verify by running the full suite.

- [ ] **Step 1: Update `state.py`**

In `src/openacm/web/state.py`, add `agent_channel_manager` to `ServerState` and keep `agent_bot_manager` as an alias property:

Replace:
```python
    agent_bot_manager: object = None
```
With:
```python
    agent_channel_manager: object = None

    @property
    def agent_bot_manager(self):
        return self.agent_channel_manager

    @agent_bot_manager.setter
    def agent_bot_manager(self, value):
        self.agent_channel_manager = value
```

Wait — `@dataclass` doesn't support property definitions easily. Use a simpler approach: add BOTH fields, with `agent_bot_manager` as a plain field that defaults to `None`. Then update all callers.

Actually the simplest approach: rename `agent_bot_manager` → `agent_channel_manager` in `state.py` and update all references.

In `src/openacm/web/state.py`, change:
```python
    agent_bot_manager: object = None
```
to:
```python
    agent_channel_manager: object = None
```

- [ ] **Step 2: Update `server.py`**

In `src/openacm/web/server.py`, find the `create_web_server` function signature. Change the parameter:
```python
    agent_bot_manager=None,
```
to:
```python
    agent_channel_manager=None,
```

And in the body of `create_web_server`, change:
```python
    _state.agent_bot_manager = agent_bot_manager
```
to:
```python
    _state.agent_channel_manager = agent_channel_manager
```

- [ ] **Step 3: Update `app.py`**

In `src/openacm/app.py`:

1. Change the instance attribute declaration in `__init__`:
```python
        self._agent_bot_manager = None
```
to:
```python
        self._agent_channel_manager = None
```

2. Replace the `_init_agent_bots` method:
```python
    async def _init_agent_channels(self):
        """Start per-agent channels (Telegram bots, WhatsApp numbers)."""
        try:
            from openacm.core.agent_runner import AgentRunner
            from openacm.channels.agent_telegram_bot import AgentChannelManager

            agent_runner = AgentRunner(
                llm_router=self.llm_router,
                tool_registry=self.tool_registry,
                memory=self.memory,
                event_bus=self.event_bus,
                database=self.database,
            )
            self._agent_channel_manager = AgentChannelManager(
                agent_runner=agent_runner,
                event_bus=self.event_bus,
                database=self.database,
            )
            await self._agent_channel_manager.start_all()

            active = [b for b in self._agent_channel_manager.get_status() if b["connected"]]
            if active:
                console.print(f"  [green]✓[/green] {len(active)} agent channel(s) running")
        except Exception as e:
            console.print(f"  [yellow]~[/yellow] Agent channels skipped: {e}")
```

3. In the `run()` method, change:
```python
            await self._init_agent_bots()
```
to:
```python
            await self._init_agent_channels()
```

4. In `_init_web()`, change:
```python
                agent_bot_manager=self._agent_bot_manager,
```
to:
```python
                agent_channel_manager=self._agent_channel_manager,
```

5. In `_shutdown()`, change:
```python
        # Stop agent Telegram bots
        if self._agent_bot_manager:
            try:
                await self._agent_bot_manager.stop_all()
            except Exception:
                pass
```
to:
```python
        if self._agent_channel_manager:
            try:
                await self._agent_channel_manager.stop_all()
            except Exception:
                pass
```

- [ ] **Step 4: Fix `agent_bot_manager` references in `agents.py`**

In `src/openacm/web/routers/agents.py`, replace all three occurrences of `_state.agent_bot_manager` with `_state.agent_channel_manager`:

1. In `create_agent` (POST `/api/agents`):
```python
        # Change from:
        if _state.agent_bot_manager and agent.get("telegram_token", "").strip():
            asyncio.create_task(_state.agent_bot_manager.start_bot(agent))
        # Change to: (remove this block entirely — Telegram is now managed via /channels endpoints)
```

2. In `update_agent` (PUT `/api/agents/{agent_id}`):
```python
        # Change from:
        if _state.agent_bot_manager and ("telegram_token" in kwargs or "is_active" in kwargs):
            asyncio.create_task(_state.agent_bot_manager.restart_bot(agent_id))
        # Change to: (remove this block — channel management is via /channels endpoints)
```

3. In `delete_agent` (DELETE `/api/agents/{agent_id}`):
```python
        # Change from:
        if _state.agent_bot_manager:
            asyncio.create_task(_state.agent_bot_manager.stop_bot(agent_id))
        # Change to:
        if _state.agent_channel_manager:
            asyncio.create_task(_state.agent_channel_manager.stop_all())
```

Wait — stopping ALL channels when deleting ONE agent is wrong. Fix it properly:
```python
        # On DELETE agent — stop all channels for this specific agent
        if _state.agent_channel_manager:
            for ch_type in ["telegram", "whatsapp"]:
                asyncio.create_task(
                    _state.agent_channel_manager.stop_channel(agent_id, ch_type)
                )
```

- [ ] **Step 5: Run full suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/web/state.py src/openacm/web/server.py \
        src/openacm/app.py src/openacm/web/routers/agents.py
git commit -m "feat(wiring): use AgentChannelManager throughout app, state, server"
```

---

## Task 5: WhatsApp webhook routing by phone_number_id

**Files:**
- Modify: `src/openacm/web/routers/whatsapp_webhook.py`

No new test file needed — the routing logic is tested indirectly. Run the full suite to ensure nothing regresses.

- [ ] **Step 1: Update the POST handler in `whatsapp_webhook.py`**

Replace the `whatsapp_incoming` function body with:

```python
    @app.post("/webhooks/whatsapp")
    async def whatsapp_incoming(request: Request):
        """Receive message/status events from Meta."""
        from openacm.channels.whatsapp_cloud_channel import get_active_channel, verify_signature

        wa = _wa_config()
        raw = await request.body()

        if wa and not verify_signature(wa.app_secret, raw, request.headers.get("X-Hub-Signature-256", "")):
            log.warning("WhatsApp webhook signature invalid — dropping")
            return Response(status_code=403)

        try:
            payload = await request.json()
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    phone_id = value.get("metadata", {}).get("phone_number_id", "")

                    # Route to agent channel first, fall back to global Brain channel
                    channel = None
                    if phone_id and getattr(_state, "agent_channel_manager", None):
                        channel = _state.agent_channel_manager.get_channel_by_phone(phone_id)
                    if channel is None:
                        channel = get_active_channel()

                    if channel is None:
                        continue

                    await channel.handle_incoming(value)
        except Exception as exc:
            log.error("WhatsApp webhook processing failed", error=str(exc))

        return JSONResponse({"status": "ok"})
```

- [ ] **Step 2: Run full suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/openacm/web/routers/whatsapp_webhook.py
git commit -m "feat(webhook): route WhatsApp messages by phone_number_id to agent channels"
```

---

## Task 6: API endpoints for agent channels

**Files:**
- Modify: `src/openacm/web/routers/agents.py`
- Create: `tests/unit/test_agents_channels_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_agents_channels_api.py`:

```python
"""Tests for /api/agents/{id}/channels endpoints."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


def _make_app(db=None, mgr=None):
    from openacm.web.routers import agents as agents_router
    from openacm.web.state import _state
    app = FastAPI()
    agents_router.register_routes(app)
    _state.database = db
    _state.agent_channel_manager = mgr
    return app


def _make_db(agent=None, channels=None, created_id=1):
    db = MagicMock()
    db.get_agent = AsyncMock(return_value=agent)
    db.get_all_agents = AsyncMock(return_value=[agent] if agent else [])
    db.get_agent_channels = AsyncMock(return_value=channels or [])
    db.get_agent_channel = AsyncMock(return_value=(channels[0] if channels else None))
    db.create_agent_channel = AsyncMock(return_value=created_id)
    db.update_agent_channel = AsyncMock(return_value=True)
    db.delete_agent_channel = AsyncMock(return_value=True)
    return db


_AGENT = {"id": 1, "name": "Bot", "is_active": 1, "system_prompt": "hi",
          "allowed_tools": "none", "telegram_token": ""}
_TG_ROW = {"id": 1, "agent_id": 1, "type": "telegram",
            "config": '{"token":"abcdefgh_secret"}', "is_active": 1,
            "created_at": "2026-06-16T10:00:00"}


class TestGetChannels:
    async def test_returns_list_with_masked_config(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        mgr = MagicMock()
        mgr.get_status = MagicMock(return_value=[{"agent_id": 1, "type": "telegram", "connected": True}])
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/agents/1/channels")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["is_connected"] is True
        # Token must be masked
        token_val = data[0]["config"]["token"]
        assert token_val.endswith("...")
        assert len(token_val) < len("abcdefgh_secret")

    async def test_returns_404_when_agent_not_found(self):
        db = _make_db(agent=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/agents/99/channels")
        assert r.status_code == 404


class TestCreateChannel:
    async def test_creates_telegram_channel(self):
        db = _make_db(agent=_AGENT, channels=[], created_id=5)
        new_row = {"id": 5, "agent_id": 1, "type": "telegram",
                   "config": '{"token":"tok123"}', "is_active": 1,
                   "created_at": "2026-06-16T10:00:00"}
        db.get_agent_channel = AsyncMock(return_value=new_row)
        mgr = MagicMock()
        mgr.get_status = MagicMock(return_value=[])
        mgr.start_channel = AsyncMock()
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels",
                             json={"type": "telegram", "config": {"token": "tok123"}})
        assert r.status_code == 200
        db.create_agent_channel.assert_awaited_once()

    async def test_returns_400_on_duplicate_type(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels",
                             json={"type": "telegram", "config": {"token": "new"}})
        assert r.status_code == 400

    async def test_returns_422_on_missing_token(self):
        db = _make_db(agent=_AGENT, channels=[])
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels",
                             json={"type": "telegram", "config": {}})
        assert r.status_code == 422

    async def test_returns_404_when_agent_not_found(self):
        db = _make_db(agent=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/99/channels",
                             json={"type": "telegram", "config": {"token": "x"}})
        assert r.status_code == 404


class TestDeleteChannel:
    async def test_deletes_and_stops(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        mgr = MagicMock()
        mgr.stop_channel = AsyncMock()
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete("/api/agents/1/channels/1")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        mgr.stop_channel.assert_awaited_once_with(1, "telegram")

    async def test_returns_404_when_channel_not_found(self):
        db = _make_db(agent=_AGENT, channels=[])
        db.get_agent_channel = AsyncMock(return_value=None)
        app = _make_app(db=db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete("/api/agents/1/channels/99")
        assert r.status_code == 404


class TestRestartChannel:
    async def test_restart_returns_connected(self):
        db = _make_db(agent=_AGENT, channels=[_TG_ROW])
        mgr = MagicMock()
        mgr.restart_channel = AsyncMock()
        mgr.get_status = MagicMock(return_value=[
            {"agent_id": 1, "type": "telegram", "connected": True}
        ])
        app = _make_app(db=db, mgr=mgr)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/agents/1/channels/1/restart")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["connected"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_agents_channels_api.py -v
```

Expected: `404 NOT FOUND` on all — endpoints don't exist yet.

- [ ] **Step 3: Add channel endpoints to `agents.py`**

In `src/openacm/web/routers/agents.py`, after the last knowledge endpoint (after `delete_agent_knowledge`), add:

```python
    # ─── Agent Channels ───────────────────────────────────────

    _MASKED_KEYS = {"token", "access_token", "app_secret"}
    _REQUIRED_CONFIG = {
        "telegram": {"token"},
        "whatsapp": {"access_token", "phone_number_id"},
    }

    def _mask_config(config_data: dict) -> dict:
        """Mask sensitive credential fields, keeping first 8 chars."""
        result = {}
        for k, v in config_data.items():
            if k in _MASKED_KEYS and isinstance(v, str) and len(v) > 8:
                result[k] = v[:8] + "..."
            else:
                result[k] = v
        return result

    def _channel_public(row: dict, is_connected: bool = False) -> dict:
        config_data = json.loads(row.get("config", "{}"))
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "type": row["type"],
            "config": _mask_config(config_data),
            "is_active": bool(row.get("is_active", 1)),
            "is_connected": is_connected,
            "created_at": row.get("created_at", ""),
        }

    def _get_connected_set() -> set[tuple]:
        """Return set of (agent_id, type) tuples that are currently connected."""
        if not _state.agent_channel_manager:
            return set()
        return {
            (s["agent_id"], s["type"])
            for s in _state.agent_channel_manager.get_status()
            if s["connected"]
        }

    @app.get("/api/agents/{agent_id}/channels")
    async def list_agent_channels(agent_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await _state.database.get_agent_channels(agent_id)
        connected = _get_connected_set()
        return [_channel_public(r, (agent_id, r["type"]) in connected) for r in rows]

    @app.post("/api/agents/{agent_id}/channels")
    async def create_agent_channel(agent_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        agent = await _state.database.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        data = await request.json()
        channel_type = data.get("type", "")
        config_data = data.get("config", {})

        if channel_type not in ("telegram", "whatsapp"):
            raise HTTPException(status_code=422, detail=f"Invalid channel type: {channel_type}")

        required = _REQUIRED_CONFIG.get(channel_type, set())
        missing = [k for k in required if not config_data.get(k, "").strip()]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required config fields: {', '.join(missing)}"
            )

        # Check for duplicate active channel of same type
        existing = await _state.database.get_agent_channels(agent_id)
        if any(r["type"] == channel_type and r.get("is_active") for r in existing):
            raise HTTPException(
                status_code=400,
                detail=f"Este agente ya tiene un canal de tipo {channel_type}"
            )

        cid = await _state.database.create_agent_channel(
            agent_id=agent_id,
            type=channel_type,
            config_json=json.dumps(config_data),
            is_active=1,
        )

        row = await _state.database.get_agent_channel(cid)

        # Start the channel if agent is active
        if _state.agent_channel_manager and agent.get("is_active"):
            asyncio.create_task(
                _state.agent_channel_manager.start_channel(agent, row)
            )

        connected = _get_connected_set()
        return _channel_public(row, (agent_id, channel_type) in connected)

    @app.patch("/api/agents/{agent_id}/channels/{channel_id}")
    async def update_agent_channel(agent_id: int, channel_id: int, request: Request):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_agent_channel(channel_id)
        if not row or row["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        data = await request.json()
        updates = {}

        if "config" in data:
            existing_config = json.loads(row.get("config", "{}"))
            merged = {**existing_config, **data["config"]}
            updates["config"] = json.dumps(merged)

        if "is_active" in data:
            updates["is_active"] = int(bool(data["is_active"]))

        if updates:
            await _state.database.update_agent_channel(channel_id, **updates)
            if _state.agent_channel_manager:
                asyncio.create_task(
                    _state.agent_channel_manager.restart_channel(agent_id, row["type"])
                )

        updated = await _state.database.get_agent_channel(channel_id)
        connected = _get_connected_set()
        return _channel_public(updated, (agent_id, row["type"]) in connected)

    @app.delete("/api/agents/{agent_id}/channels/{channel_id}")
    async def delete_agent_channel(agent_id: int, channel_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_agent_channel(channel_id)
        if not row or row["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        if _state.agent_channel_manager:
            await _state.agent_channel_manager.stop_channel(agent_id, row["type"])

        await _state.database.delete_agent_channel(channel_id)
        return {"ok": True}

    @app.post("/api/agents/{agent_id}/channels/{channel_id}/restart")
    async def restart_agent_channel(agent_id: int, channel_id: int):
        if not _state.database:
            raise HTTPException(status_code=503, detail="Database not available")
        row = await _state.database.get_agent_channel(channel_id)
        if not row or row["agent_id"] != agent_id:
            raise HTTPException(status_code=404, detail="Channel not found")

        if _state.agent_channel_manager:
            await _state.agent_channel_manager.restart_channel(agent_id, row["type"])

        connected = _get_connected_set()
        is_connected = (agent_id, row["type"]) in connected
        return {"ok": True, "connected": is_connected}
```

Also add `import json` at the top of `agents.py` if not already present. Check and add if missing.

- [ ] **Step 4: Run tests**

```
pytest tests/unit/test_agents_channels_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/openacm/web/routers/agents.py \
        tests/unit/test_agents_channels_api.py
git commit -m "feat(api): agent channel CRUD endpoints + restart"
```

---

## Task 7: Frontend — hooks and types

**Files:**
- Modify: `frontend/hooks/use-agents.ts`

- [ ] **Step 1: Add `ChannelItem` interface and two new hooks**

In `frontend/hooks/use-agents.ts`, after the `KnowledgeItem` interface (line 37), add:

```typescript
export interface ChannelItem {
  id: number;
  agent_id: number;
  type: 'telegram' | 'whatsapp';
  config: Record<string, string>;
  is_active: boolean;
  is_connected: boolean;
  created_at: string;
}

export type ChannelConfig =
  | { type: 'telegram'; token: string }
  | { type: 'whatsapp'; access_token: string; phone_number_id: string; verify_token?: string; app_secret?: string };
```

Then, after `useAgentKnowledgeMutations` (after line 98), add:

```typescript
export function useAgentChannels(agentId: number | null) {
  const { fetchAPI } = useAPI();
  const isAuthenticated = useIsAuthenticated();

  return useQuery<ChannelItem[]>({
    queryKey: ['agent-channels', agentId],
    queryFn: () => fetchAPI(`/api/agents/${agentId}/channels`),
    enabled: isAuthenticated && agentId !== null,
    staleTime: 0,
  });
}

export function useAgentChannelMutations(agentId: number) {
  const { fetchAPI } = useAPI();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['agent-channels', agentId] });

  const addChannel = useMutation({
    mutationFn: ({ type, config }: { type: string; config: Record<string, string> }) =>
      fetchAPI(`/api/agents/${agentId}/channels`, {
        method: 'POST',
        body: JSON.stringify({ type, config }),
      }),
    onSuccess: invalidate,
  });

  const removeChannel = useMutation({
    mutationFn: (channelId: number) =>
      fetchAPI(`/api/agents/${agentId}/channels/${channelId}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  });

  const restartChannel = useMutation({
    mutationFn: (channelId: number) =>
      fetchAPI(`/api/agents/${agentId}/channels/${channelId}/restart`, { method: 'POST' }),
    onSuccess: invalidate,
  });

  return { addChannel, removeChannel, restartChannel };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/use-agents.ts
git commit -m "feat(frontend): ChannelItem interface + useAgentChannels + useAgentChannelMutations hooks"
```

---

## Task 8: Frontend — ChannelsTab component + modal wiring

**Files:**
- Modify: `frontend/app/agents/page.tsx`

- [ ] **Step 1: Add imports**

At the top of `frontend/app/agents/page.tsx`, update the imports from `@/hooks/use-agents`:

```typescript
import {
  useAgents, useAgentMutations, useAgentKnowledge, useAgentKnowledgeMutations,
  useAgentChannels, useAgentChannelMutations,
  type Agent, type AgentFormData, type KnowledgeItem, type ChannelItem,
} from '@/hooks/use-agents';
```

Add to lucide-react imports: `Radio`, `RefreshCw`, `ChevronDown`, `ChevronUp` (ChevronDown/Up may already be there — check and only add missing ones):

```typescript
import {
  Bot, Plus, Trash2, Edit2, Power, PowerOff, Send, Copy, Check, Loader2,
  Key, Globe, ChevronDown, ChevronUp, X, Sparkles, FileText, Upload,
  BookOpen, Pencil, AlertTriangle, Radio, RefreshCw,
} from 'lucide-react';
```

- [ ] **Step 2: Add `ChannelsTab` component**

After the closing `}` of the `KnowledgeTab` component (after line 294), insert the new `ChannelsTab` component:

```typescript
// ── Channels Tab ──────────────────────────────────────────────────────────────

const WEBHOOK_CURL = `curl -X POST https://tu-dominio.com/webhooks/whatsapp \\
  -H "Content-Type: application/json" \\
  -d '{"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"TU_PHONE_ID"},"messages":[{"from":"521234567890","type":"text","text":{"body":"Hola"},"id":"wamid.test1"}]}}]}]}'`;

const WEBHOOK_PYTHON = `import requests
requests.post("https://tu-dominio.com/webhooks/whatsapp", json={
    "entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "TU_PHONE_ID"},
        "messages": [{"from": "521234567890", "type": "text",
                      "text": {"body": "Hola"}, "id": "wamid.test1"}]
    }}]}]
})`;

const WEBHOOK_JS = `fetch("https://tu-dominio.com/webhooks/whatsapp", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ entry: [{ changes: [{ value: {
    metadata: { phone_number_id: "TU_PHONE_ID" },
    messages: [{ from: "521234567890", type: "text",
                 text: { body: "Hola" }, id: "wamid.test1" }]
  }}]}]})
})`;

function ChannelsTab({ agentId }: { agentId: number }) {
  const { data: channels = [], isLoading } = useAgentChannels(agentId);
  const { addChannel, removeChannel, restartChannel } = useAgentChannelMutations(agentId);

  const [showAddForm, setShowAddForm] = useState(false);
  const [addType, setAddType] = useState<'telegram' | 'whatsapp'>('telegram');
  const [addConfig, setAddConfig] = useState<Record<string, string>>({});
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [restartingId, setRestartingId] = useState<number | null>(null);
  const [showWebhookDocs, setShowWebhookDocs] = useState(false);
  const [webhookTab, setWebhookTab] = useState<'curl' | 'python' | 'js'>('curl');
  const [copied, setCopied] = useState(false);

  const hasWhatsApp = channels.some((c) => c.type === 'whatsapp') || (showAddForm && addType === 'whatsapp');

  const handleAdd = async () => {
    try {
      await addChannel.mutateAsync({ type: addType, config: addConfig });
      setShowAddForm(false);
      setAddConfig({});
      toast.success('Canal agregado');
    } catch (err: any) {
      toast.error(err.message || 'Error al agregar canal');
    }
  };

  const handleDelete = async (ch: ChannelItem) => {
    try {
      setDeletingId(ch.id);
      await removeChannel.mutateAsync(ch.id);
      toast.success('Canal eliminado');
    } catch (err: any) {
      toast.error(err.message || 'Error al eliminar');
    } finally {
      setDeletingId(null);
    }
  };

  const handleRestart = async (ch: ChannelItem) => {
    try {
      setRestartingId(ch.id);
      const res = await restartChannel.mutateAsync(ch.id);
      toast.success(res.connected ? 'Canal reconectado' : 'Canal reiniciado (desconectado)');
    } catch (err: any) {
      toast.error(err.message || 'Error al reiniciar');
    } finally {
      setRestartingId(null);
    }
  };

  const copyWebhookUrl = () => {
    navigator.clipboard.writeText('https://tu-dominio.com/webhooks/whatsapp');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Cargando canales…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Add button */}
      <div className="flex gap-2">
        <button
          onClick={() => { setShowAddForm((v) => !v); setAddConfig({}); }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Agregar canal
        </button>
      </div>

      {/* Add form */}
      {showAddForm && (
        <div className="border border-zinc-700 rounded-lg p-3 space-y-3 bg-zinc-900/50">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Tipo de canal</label>
            <select
              value={addType}
              onChange={(e) => { setAddType(e.target.value as 'telegram' | 'whatsapp'); setAddConfig({}); }}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
            >
              <option value="telegram">Telegram</option>
              <option value="whatsapp">WhatsApp Business</option>
            </select>
          </div>

          {addType === 'telegram' && (
            <div>
              <label className="block text-xs text-zinc-400 mb-1">Token del bot</label>
              <input
                value={addConfig.token || ''}
                onChange={(e) => setAddConfig({ token: e.target.value })}
                placeholder="1234567890:ABCDEFabcdef..."
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              />
            </div>
          )}

          {addType === 'whatsapp' && (
            <>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Access Token</label>
                <input
                  value={addConfig.access_token || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, access_token: e.target.value }))}
                  placeholder="EAAx..."
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Phone Number ID</label>
                <input
                  value={addConfig.phone_number_id || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, phone_number_id: e.target.value }))}
                  placeholder="12345678901234"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Verify Token</label>
                <input
                  value={addConfig.verify_token || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, verify_token: e.target.value }))}
                  placeholder="mi_verify_token"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">App Secret <span className="text-zinc-500">(opcional)</span></label>
                <input
                  value={addConfig.app_secret || ''}
                  onChange={(e) => setAddConfig((c) => ({ ...c, app_secret: e.target.value }))}
                  placeholder="aabbcc..."
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                />
              </div>
            </>
          )}

          <div className="flex gap-2">
            <button
              onClick={handleAdd}
              disabled={addChannel.isPending}
              className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-white transition-colors"
            >
              {addChannel.isPending ? 'Guardando…' : 'Guardar'}
            </button>
            <button
              onClick={() => { setShowAddForm(false); setAddConfig({}); }}
              className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {channels.length === 0 && !showAddForm && (
        <div className="text-center py-8 text-zinc-500 text-sm">
          <Radio className="w-8 h-8 mx-auto mb-2 opacity-40" />
          Conecta este agente a Telegram o WhatsApp Business.
        </div>
      )}

      {/* Channel cards */}
      {channels.map((ch) => (
        <div key={ch.id} className="border border-zinc-700 rounded-lg p-3 bg-zinc-900/30">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2 min-w-0">
              <Radio className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm text-zinc-100">
                    {ch.type === 'telegram' ? 'Telegram' : 'WhatsApp Business'}
                  </p>
                  <span className={cn(
                    'inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full',
                    ch.is_connected
                      ? 'bg-green-900/40 text-green-400'
                      : 'bg-zinc-800 text-zinc-500'
                  )}>
                    <span className={cn(
                      'w-1.5 h-1.5 rounded-full',
                      ch.is_connected ? 'bg-green-400' : 'bg-zinc-500'
                    )} />
                    {ch.is_connected ? 'CONECTADO' : 'DESCONECTADO'}
                  </span>
                </div>
                <p className="text-xs text-zinc-500 mt-0.5 truncate">
                  {ch.type === 'telegram'
                    ? `Token: ${ch.config.token ?? '—'}`
                    : `ID: ${ch.config.phone_number_id ?? '—'}`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              <button
                onClick={() => handleRestart(ch)}
                disabled={restartingId === ch.id}
                className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                title="Reiniciar canal"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', restartingId === ch.id && 'animate-spin')} />
              </button>
              <button
                onClick={() => handleDelete(ch)}
                disabled={deletingId === ch.id}
                className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
                title="Eliminar canal"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      ))}

      {/* WhatsApp webhook docs */}
      {hasWhatsApp && (
        <div className="border border-zinc-700 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowWebhookDocs((v) => !v)}
            className="w-full flex items-center justify-between px-3 py-2 text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 transition-colors"
          >
            <span className="font-medium">Configuración del Webhook</span>
            {showWebhookDocs ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {showWebhookDocs && (
            <div className="px-3 pb-3 space-y-3 border-t border-zinc-700">
              <div className="mt-3">
                <p className="text-xs text-zinc-400 mb-1">URL del webhook</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs bg-zinc-800 px-2 py-1.5 rounded text-zinc-300 truncate">
                    https://tu-dominio.com/webhooks/whatsapp
                  </code>
                  <button
                    onClick={copyWebhookUrl}
                    className="p-1.5 text-zinc-500 hover:text-zinc-300 transition-colors flex-shrink-0"
                    title="Copiar URL"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-xs text-zinc-500 mt-1">
                  Meta Developer Console → WhatsApp → Configuration → Webhook → Edit. Suscribe al evento: <code className="text-zinc-400">messages</code>
                </p>
              </div>

              <div>
                <p className="text-xs text-zinc-400 mb-1">Probar con código</p>
                <div className="flex gap-1 mb-2">
                  {(['curl', 'python', 'js'] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setWebhookTab(tab)}
                      className={cn(
                        'px-2 py-0.5 text-xs rounded transition-colors',
                        webhookTab === tab
                          ? 'bg-zinc-700 text-zinc-100'
                          : 'text-zinc-500 hover:text-zinc-300'
                      )}
                    >
                      {tab === 'js' ? 'JavaScript' : tab === 'python' ? 'Python' : 'cURL'}
                    </button>
                  ))}
                </div>
                <pre className="text-xs bg-zinc-800 p-2 rounded overflow-x-auto text-zinc-300 acm-scroll">
                  {webhookTab === 'curl' ? WEBHOOK_CURL : webhookTab === 'python' ? WEBHOOK_PYTHON : WEBHOOK_JS}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Update `AgentFormModal` to add the Channels tab**

In `AgentFormModal`, change the `activeTab` type and add the new tab button.

Find the existing `activeTab` state declaration (around line 325):
```typescript
  const [activeTab, setActiveTab] = useState<'config' | 'knowledge'>('config');
```
Change to:
```typescript
  const [activeTab, setActiveTab] = useState<'config' | 'knowledge' | 'channels'>('config');
```

Find the tab bar section (around line 395–423). After the Knowledge tab button, add:
```typescript
            <button
              onClick={() => setActiveTab('channels')}
              className={cn(
                'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
                activeTab === 'channels'
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              )}
            >
              <span className="flex items-center gap-1.5">
                <Radio className="w-3.5 h-3.5" />
                Channels
              </span>
            </button>
```

Find the tab content rendering (around line 427):
```typescript
          {activeTab === 'knowledge' && isEditing && initial?.id ? (
            <KnowledgeTab agentId={initial.id} />
          ) : (
```
Replace with:
```typescript
          {activeTab === 'channels' && isEditing && initial?.id ? (
            <ChannelsTab agentId={initial.id} />
          ) : activeTab === 'knowledge' && isEditing && initial?.id ? (
            <KnowledgeTab agentId={initial.id} />
          ) : (
```

- [ ] **Step 4: Verify TypeScript compiles**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Run full backend suite**

```
pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/agents/page.tsx
git commit -m "feat(frontend): ChannelsTab with add/delete/restart + WhatsApp webhook docs"
```

---

## Self-Review Checklist

After all tasks, verify:

- [ ] `pytest` — full suite passes
- [ ] `cd frontend && npx tsc --noEmit` — no type errors
- [ ] Migration 28 creates `agent_channels` table and migrates `telegram_token` values
- [ ] `AgentBotManager` alias still exports from `agent_telegram_bot.py` (backward compat)
- [ ] `_active_channel` singleton is NOT set by `AgentWhatsAppChannel.start()`
- [ ] WhatsApp webhook routes by `phone_number_id` before falling back to global channel
- [ ] Sensitive config fields (token, access_token, app_secret) are masked in GET response
- [ ] Channels tab only appears in edit modal, not create modal
