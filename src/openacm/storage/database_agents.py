"""Agents, their knowledge and channels, node flows, webhooks and connections."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from openacm.constants import TRUNCATE_DB_OUTPUT_CHARS, TRUNCATE_DB_ERROR_CHARS
from openacm.utils.text import truncate

log = structlog.get_logger()


class AgentsMixin:
    """Part of Database (agents, their knowledge and channels, node flows, webhooks and connections); Database inherits it."""

    # ─── Agent Node Flows ───────────────────────────────────

    async def create_flow(
        self,
        agent_id: int,
        name: str,
        description: str = "",
        graph_json: str = '{"nodes":[],"edges":[]}',
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO flows (agent_id, name, description, graph_json) VALUES (?, ?, ?, ?)",
            (agent_id, name, description, graph_json),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_flow(self, flow_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM flows WHERE id = ?", (flow_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent_flows(self, agent_id: int, active_only: bool = False) -> list[dict[str, Any]]:
        if not self._db:
            return []
        query = "SELECT * FROM flows WHERE agent_id = ?"
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY name"
        cursor = await self._db.execute(query, (agent_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_flow(self, flow_id: int, agent_id: int | None = None, **kwargs: Any) -> bool:
        """agent_id, if given, scopes the update so a flow_id belonging to a
        different agent is never modified (returns False, not an error)."""
        if not self._db:
            return False
        allowed = {"name", "description", "graph_json", "is_active"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        query = f"UPDATE flows SET {', '.join(updates)} WHERE id = ?"
        params.append(flow_id)
        if agent_id is not None:
            query += " AND agent_id = ?"
            params.append(agent_id)
        cursor = await self._db.execute(query, params)
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_flow(self, flow_id: int, agent_id: int | None = None) -> bool:
        """agent_id, if given, scopes the delete so a flow_id belonging to a
        different agent is never removed (returns False, not an error)."""
        if not self._db:
            return False
        query = "DELETE FROM flows WHERE id = ?"
        params: list[Any] = [flow_id]
        if agent_id is not None:
            query += " AND agent_id = ?"
            params.append(agent_id)
        cursor = await self._db.execute(query, params)
        await self._db.commit()
        return cursor.rowcount > 0

    # ─── Webhook Connectors ───────────────────────────────────

    async def create_webhook_connector(
        self,
        slug: str,
        name: str,
        auth_scheme: str,
        auth_config: dict[str, Any],
        flow_id: int,
        dedupe_header: str | None = None,
    ) -> int:
        if not self._db:
            return 0
        import json
        cursor = await self._db.execute(
            "INSERT INTO webhook_connectors (slug, name, auth_scheme, auth_config, flow_id, dedupe_header) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, auth_scheme, json.dumps(auth_config), flow_id, dedupe_header),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_webhook_connector(self, connector_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM webhook_connectors WHERE id = ?", (connector_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_webhook_connector_by_slug(self, slug: str) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM webhook_connectors WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_webhook_connectors(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute("SELECT * FROM webhook_connectors ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_webhook_connector(self, connector_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        import json
        allowed = {"name", "auth_scheme", "auth_config", "flow_id", "enabled", "dedupe_header"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            if key == "auth_config" and isinstance(val, dict):
                val = json.dumps(val)
            updates.append(f"{key} = ?")
            params.append(val)
        if not updates:
            return False
        query = f"UPDATE webhook_connectors SET {', '.join(updates)} WHERE id = ?"
        params.append(connector_id)
        cursor = await self._db.execute(query, params)
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_webhook_connector(self, connector_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM webhook_connectors WHERE id = ?", (connector_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def record_webhook_connector_event(
        self,
        connector_id: int,
        dedupe_key: str | None,
        body: str,
        status: str,
        result: str | None,
        duration_ms: int,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO webhook_connector_events "
            "(connector_id, dedupe_key, body, status, result, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (connector_id, dedupe_key, body, status, result, duration_ms),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def find_webhook_connector_event_by_dedupe_key(
        self, connector_id: int, dedupe_key: str
    ) -> dict[str, Any] | None:
        if not self._db:
            return None
        # Only a successful delivery counts as "already processed". A failed
        # attempt (auth_failed / bad_request / flow_error) must NOT suppress a
        # retry — otherwise the very first failure would be cached forever and
        # replayed to every retry as if it had succeeded.
        cursor = await self._db.execute(
            "SELECT * FROM webhook_connector_events WHERE connector_id = ? AND dedupe_key = ? "
            "AND status = 'ok' ORDER BY received_at ASC LIMIT 1",
            (connector_id, dedupe_key),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_webhook_connector_events(self, connector_id: int, limit: int = 50) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM webhook_connector_events WHERE connector_id = ? "
            "ORDER BY received_at DESC LIMIT ?",
            (connector_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_webhook_connector_stats(self, connector_id: int) -> dict[str, Any]:
        if not self._db:
            return {"total": 0, "by_status": {}}
        total_cursor = await self._db.execute(
            "SELECT COUNT(*) AS c FROM webhook_connector_events WHERE connector_id = ?", (connector_id,)
        )
        total_row = await total_cursor.fetchone()
        by_status_cursor = await self._db.execute(
            "SELECT status, COUNT(*) AS c FROM webhook_connector_events "
            "WHERE connector_id = ? GROUP BY status",
            (connector_id,),
        )
        by_status_rows = await by_status_cursor.fetchall()
        return {
            "total": total_row["c"],
            "by_status": {r["status"]: r["c"] for r in by_status_rows},
        }

    # ─── Agent Connections ────────────────────────────────────

    async def create_connection(self, agent_id: int, name: str, type: str, config: str) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO connections (agent_id, name, type, config) VALUES (?, ?, ?, ?)",
            (agent_id, name, type, config),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_connection(self, connection_id: int) -> dict[str, Any] | None:
        """Includes config — for internal use by FlowExecutor only, never
        return this directly from an API list/get endpoint."""
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent_connections(self, agent_id: int) -> list[dict[str, Any]]:
        """Excludes config — safe to return from an API response."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT id, agent_id, name, type, created_at FROM connections WHERE agent_id = ? ORDER BY name",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_connection(self, connection_id: int, agent_id: int | None = None, **kwargs: Any) -> bool:
        """agent_id, if given, scopes the update so a connection_id belonging
        to a different agent is never modified (returns False, not an error)."""
        if not self._db:
            return False
        allowed = {"name", "config"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        query = f"UPDATE connections SET {', '.join(updates)} WHERE id = ?"
        params.append(connection_id)
        if agent_id is not None:
            query += " AND agent_id = ?"
            params.append(agent_id)
        cursor = await self._db.execute(query, params)
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_connection(self, connection_id: int, agent_id: int | None = None) -> bool:
        """agent_id, if given, scopes the delete so a connection_id belonging
        to a different agent is never removed (returns False, not an error)."""
        if not self._db:
            return False
        query = "DELETE FROM connections WHERE id = ?"
        params: list[Any] = [connection_id]
        if agent_id is not None:
            query += " AND agent_id = ?"
            params.append(agent_id)
        cursor = await self._db.execute(query, params)
        await self._db.commit()
        return cursor.rowcount > 0

    # ─── Agents ───────────────────────────────────────────────

    async def create_agent(
        self,
        name: str,
        description: str,
        system_prompt: str,
        allowed_tools: str = "all",
        webhook_secret: str = "",
        telegram_token: str = "",
        memory_mode: str = "persistent",
        memory_ttl_hours: int = 24,
        inactivity_timeout_minutes: int = 0,
        inactivity_message: str = "",
        show_in_chat: bool = True,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO agents (name, description, system_prompt, allowed_tools, webhook_secret, "
            "telegram_token, memory_mode, memory_ttl_hours, inactivity_timeout_minutes, inactivity_message, show_in_chat) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, system_prompt, allowed_tools, webhook_secret, telegram_token,
             memory_mode, memory_ttl_hours, inactivity_timeout_minutes, inactivity_message, 1 if show_in_chat else 0),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        if not self._db:
            return None
        cursor = await self._db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["show_in_chat"] = bool(d.get("show_in_chat", 1))
        return d

    async def get_all_agents(self) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute("SELECT * FROM agents ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["show_in_chat"] = bool(d.get("show_in_chat", 1))
            result.append(d)
        return result

    async def update_agent(self, agent_id: int, **kwargs: Any) -> bool:
        if not self._db:
            return False
        allowed = {
            "name", "description", "system_prompt", "allowed_tools", "is_active",
            "telegram_token", "memory_mode", "memory_ttl_hours",
            "inactivity_timeout_minutes", "inactivity_message", "show_in_chat",
        }
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                if key == "show_in_chat":
                    params.append(1 if val else 0)
                else:
                    params.append(val)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(agent_id)
        cursor = await self._db.execute(f"UPDATE agents SET {', '.join(updates)} WHERE id = ?", params)
        await self._db.commit()
        return bool(cursor.rowcount)  # False for an agent that does not exist

    async def delete_agent(self, agent_id: int) -> bool:
        if not self._db:
            return False
        cursor = await self._db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    # ─── Agent Knowledge ──────────────────────────────────────

    async def create_agent_knowledge(
        self,
        agent_id: int,
        type: str,
        title: str,
        content: str,
        filename: str | None = None,
    ) -> int:
        if not self._db:
            return 0
        cursor = await self._db.execute(
            "INSERT INTO agent_knowledge (agent_id, type, title, content, filename) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_id, type, title, content, filename),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_agent_knowledge(self, agent_id: int) -> list[dict[str, Any]]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM agent_knowledge WHERE agent_id = ? ORDER BY created_at ASC",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_agent_knowledge(self, kid: int, agent_id: int | None = None, **kwargs: Any) -> bool:
        """Change a knowledge item. With agent_id, only if that agent owns it."""
        if not self._db:
            return False
        allowed = {"title", "content"}
        updates, params = [], []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(val)
        if not updates:
            return False
        where, params = "id = ?", params + [kid]
        if agent_id is not None:
            where, params = where + " AND agent_id = ?", params + [agent_id]
        cursor = await self._db.execute(
            f"UPDATE agent_knowledge SET {', '.join(updates)} WHERE {where}", params
        )
        await self._db.commit()
        return bool(cursor.rowcount)

    async def delete_agent_knowledge(self, kid: int, agent_id: int | None = None) -> bool:
        """Delete a knowledge item. With agent_id, only if that agent owns it."""
        if not self._db:
            return False
        sql, params = "DELETE FROM agent_knowledge WHERE id = ?", [kid]
        if agent_id is not None:
            sql, params = sql + " AND agent_id = ?", params + [agent_id]
        cursor = await self._db.execute(sql, params)
        await self._db.commit()
        return cursor.rowcount > 0

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
