"""
Who may use the assistant from an external channel, and with which tools.

The dashboard and the console are the owner's own, so they are never limited. Telegram, Discord and
WhatsApp are reachable by other people, so each message is classified before the assistant sees it:

* **owner**   - a person on the channel's owner list: everything the assistant can do.
* **guest**   - anyone else the channel lets in (``public`` mode): a limited profile only.
* **blocked** - anyone else when the channel is ``whitelist`` only: the message is ignored.

A single chat can be given its own profile (a family group, a customer chat) that replaces the
channel's guest profile for that chat. Owners are owners everywhere.

Guests never get the tools that touch the machine, the files, the accounts or the configuration:
those are not even selectable (``GRANTABLE``), so a mis-click in the dashboard cannot hand them over.
The same rules are enforced where tools are offered to the model AND where they run.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()

SETTINGS_KEY = "channel.access"

# Channels other people can reach. Everything else (dashboard, console, cron, swarms, agents
# with their own tool list) belongs to the owner or has a policy of its own.
GOVERNED_CHANNELS = ("telegram", "discord", "whatsapp")

MODES = ("public", "whitelist")
GUEST_LEVELS = ("none", "basic", "custom")
CHAT_LEVELS = ("blocked", "none", "basic", "custom", "owner")

# What a guest may ever be given. Searching the web and the owner's published knowledge base; nothing
# that runs code, reads or writes files, sends mail, posts, changes settings, or fetches an arbitrary
# URL (get_webpage could be pointed at the owner's local network).
GRANTABLE = frozenset({"web_search", "search_knowledge", "read_knowledge_file"})
PRESETS: dict[str, frozenset[str]] = {
    "none": frozenset(),
    "basic": frozenset({"web_search"}),
}

MAX_UNKNOWN = 30


class AccessError(ValueError):
    """The submitted access settings are invalid."""


@dataclass(frozen=True)
class Grant:
    talk: bool          # the assistant answers this sender at all
    owner: bool         # full permissions
    tools: frozenset[str] | None  # None = every tool; otherwise exactly these
    reason: str = ""

    def allows(self, tool_name: str) -> bool:
        return self.talk and (self.tools is None or tool_name in self.tools)


OWNER = Grant(talk=True, owner=True, tools=None, reason="owner")


def _clean_id(value: Any) -> str:
    return str(value).strip()


@dataclass
class ChannelAccess:
    data: dict[str, Any] = field(default_factory=lambda: {"channels": {}, "chats": {}})
    _database: Any = None
    unknown: list[dict[str, Any]] = field(default_factory=list)

    # ── persistence ──────────────────────────────────────────────────────────
    async def load(self, database: Any, legacy_owners: dict[str, list[str]] | None = None) -> None:
        """Read the saved settings. ``legacy_owners`` carries the old per-channel allow lists so a
        setup that already restricted who can talk keeps doing so (those people become owners)."""
        self._database = database
        try:
            raw = await database.get_setting(SETTINGS_KEY)
            if raw:
                loaded = json.loads(raw)
                for k in ("channels", "chats"):
                    if isinstance(loaded.get(k), dict):
                        self.data[k] = loaded[k]
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load channel access settings", error=str(exc))
        for channel, ids in (legacy_owners or {}).items():
            if ids and channel not in self.data["channels"]:
                self.data["channels"][channel] = {
                    "mode": "whitelist", "owners": [_clean_id(i) for i in ids],
                    "guest": {"level": "none", "tools": []},
                }

    async def _save(self) -> None:
        if self._database is not None:
            await self._database.set_setting(SETTINGS_KEY, json.dumps(self.data))

    # ── resolving ────────────────────────────────────────────────────────────
    def channel(self, channel_type: str) -> dict[str, Any]:
        """The channel's settings; a channel nobody configured lets people in as guests with no tools."""
        conf = self.data["channels"].get(channel_type) or {}
        guest = conf.get("guest") or {}
        return {
            "mode": conf.get("mode") if conf.get("mode") in MODES else "public",
            "owners": [_clean_id(o) for o in conf.get("owners", [])],
            "guest": {"level": guest.get("level") if guest.get("level") in GUEST_LEVELS else "none",
                      "tools": [t for t in guest.get("tools", []) if t in GRANTABLE]},
        }

    @staticmethod
    def _profile_tools(level: str, tools: list[str]) -> frozenset[str]:
        if level == "custom":
            return frozenset(t for t in tools if t in GRANTABLE)
        return PRESETS.get(level, frozenset())

    def resolve(self, channel_type: str, user_id: str, chat_id: str = "") -> Grant:
        if channel_type not in GOVERNED_CHANNELS:
            return OWNER
        conf = self.channel(channel_type)
        if _clean_id(user_id) in conf["owners"]:
            return OWNER
        override = self.data["chats"].get(f"{channel_type}:{_clean_id(chat_id)}")
        if override:
            level = override.get("level")
            if level == "owner":
                return Grant(True, True, None, "chat marked as owner")
            if level == "blocked":
                return Grant(False, False, frozenset(), "chat blocked")
            if level in GUEST_LEVELS:
                return Grant(True, False, self._profile_tools(level, override.get("tools", [])), "chat profile")
        if conf["mode"] == "whitelist":
            return Grant(False, False, frozenset(), "not on the list")
        g = conf["guest"]
        return Grant(True, False, self._profile_tools(g["level"], g["tools"]), "guest")

    def note_unknown(self, channel_type: str, user_id: str, chat_id: str, talked: bool) -> None:
        """Remember who writes without being an owner, so the dashboard can offer to promote them."""
        key = (channel_type, _clean_id(user_id), _clean_id(chat_id))
        now = time.time()
        for item in self.unknown:
            if (item["channel"], item["user_id"], item["chat_id"]) == key:
                item["last"], item["count"], item["talked"] = now, item["count"] + 1, talked
                return
        self.unknown.append({"channel": key[0], "user_id": key[1], "chat_id": key[2],
                             "last": now, "count": 1, "talked": talked})
        self.unknown.sort(key=lambda i: i["last"], reverse=True)
        del self.unknown[MAX_UNKNOWN:]

    def filter_tools(self, schema: list[dict[str, Any]] | None, grant: Grant) -> list[dict[str, Any]] | None:
        if schema is None or grant.tools is None:
            return schema
        return [t for t in schema if t.get("function", {}).get("name") in grant.tools]

    # ── editing ──────────────────────────────────────────────────────────────
    async def update(self, payload: dict[str, Any], known_tools: set[str] | None = None) -> None:
        """Replace the settings with a validated copy of ``payload``."""
        if not isinstance(payload, dict):
            raise AccessError("Formato inválido.")
        channels: dict[str, Any] = {}
        for name, conf in (payload.get("channels") or {}).items():
            if name not in GOVERNED_CHANNELS:
                raise AccessError(f"Canal desconocido: {name}.")
            conf = conf or {}
            mode = conf.get("mode", "public")
            if mode not in MODES:
                raise AccessError("mode debe ser public o whitelist.")
            guest = conf.get("guest") or {}
            level = guest.get("level", "none")
            if level not in GUEST_LEVELS:
                raise AccessError("El nivel de invitado debe ser none, basic o custom.")
            channels[name] = {
                "mode": mode,
                "owners": sorted({_clean_id(o) for o in conf.get("owners", []) if _clean_id(o)}),
                "guest": {"level": level, "tools": self._validate_tools(guest.get("tools", []), known_tools)},
            }
        chats: dict[str, Any] = {}
        for key, conf in (payload.get("chats") or {}).items():
            channel, _, chat_id = str(key).partition(":")
            if channel not in GOVERNED_CHANNELS or not chat_id.strip():
                raise AccessError(f"Chat inválido: {key} (usa canal:id).")
            conf = conf or {}
            level = conf.get("level")
            if level not in CHAT_LEVELS:
                raise AccessError(f"Nivel inválido para {key}.")
            chats[f"{channel}:{chat_id.strip()}"] = {
                "level": level, "tools": self._validate_tools(conf.get("tools", []), known_tools),
            }
        self.data = {"channels": channels, "chats": chats}
        await self._save()

    @staticmethod
    def _validate_tools(tools: Any, known: set[str] | None) -> list[str]:
        if not isinstance(tools, list):
            raise AccessError("tools debe ser una lista.")
        out = []
        for t in tools:
            if t not in GRANTABLE:
                raise AccessError(f"'{t}' no se puede dar a invitados (toca el equipo, archivos o cuentas).")
            if known is not None and t not in known:
                continue
            if t not in out:
                out.append(t)
        return out

    def snapshot(self) -> dict[str, Any]:
        return {
            "channels": {c: self.channel(c) for c in GOVERNED_CHANNELS},
            "chats": self.data["chats"],
            "grantable": sorted(GRANTABLE),
            "presets": {k: sorted(v) for k, v in PRESETS.items()},
            "unknown": self.unknown,
        }
