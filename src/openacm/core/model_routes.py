"""
Model routes: use a different model for different kinds of work.

Instead of one model for everything, the owner can say, for example, "think and plan with the
big model, run the tool steps with the fast one, and do housekeeping with the cheap one".

Roles
    orchestrator  the first reply to each message: understanding, planning, deciding
    tools         the follow-up steps after a tool has run (reading results, calling the next tool)
    background    housekeeping the owner never reads: compacting history, learning, summaries

Scopes (the most specific one that sets a role wins)
    chat        one conversation (set with /route in the chat)
    workspace   every conversation pinned to a folder with /workspace
    global      everything else

A role nobody sets simply uses the main model (the one chosen in Configuration), so the default
behaviour of OpenACM does not change until a route is set. Agents and swarms are not routed:
they have their own model settings.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from openacm.core.llm_router import LLMRouter

log = structlog.get_logger()

SETTINGS_KEY = "llm.routes"

ROLES: dict[str, dict[str, str]] = {
    "orchestrator": {
        "label": "Orquestación",
        "hint": "La primera respuesta a cada mensaje: entender, planear y decidir qué hacer.",
    },
    "tools": {
        "label": "Herramientas",
        "hint": "Los pasos que siguen después de ejecutar una herramienta (leer el resultado, llamar a la siguiente).",
    },
    "background": {
        "label": "Segundo plano",
        "hint": "Tareas internas que no ves: compactar el historial, aprender rutinas, resúmenes.",
    },
}

# (conversation key "channel:user", pinned workspace path or "") of the message being handled.
# Set by the Brain per message; each message runs in its own task so it never leaks.
route_scope: ContextVar[tuple[str, str] | None] = ContextVar("route_scope", default=None)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class RouteError(ValueError):
    pass


def chat_key(channel_id: str, user_id: str) -> str:
    return f"{channel_id}:{user_id}"


class ModelRoutes:
    def __init__(self, router: "LLMRouter"):
        self._router = router
        self._database: Any = None
        self.data: dict[str, Any] = {"global": {}, "workspaces": {}, "chats": {}}

    # ── persistence ──────────────────────────────────────────────────────────
    async def load(self, database: Any) -> None:
        self._database = database
        try:
            raw = await database.get_setting(SETTINGS_KEY)
            if raw:
                loaded = json.loads(raw)
                for scope in ("global", "workspaces", "chats"):
                    if isinstance(loaded.get(scope), dict):
                        self.data[scope] = loaded[scope]
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load model routes", error=str(exc))

    async def _save(self) -> None:
        if self._database is not None:
            await self._database.set_setting(SETTINGS_KEY, json.dumps(self.data))

    # ── validation ───────────────────────────────────────────────────────────
    def _clean_route(self, value: Any) -> dict[str, str] | None:
        if value in (None, "", {}):
            return None
        if not isinstance(value, dict):
            raise RouteError("Cada ruta debe ser {provider, model}.")
        provider = str(value.get("provider", "")).strip()
        model = str(value.get("model", "")).strip()
        if provider not in self._router.config.providers:
            raise RouteError(f"El proveedor '{provider}' no está configurado.")
        if len(model) > 200 or _CONTROL.search(model):
            raise RouteError("Nombre de modelo inválido.")
        return {"provider": provider, "model": model}

    # ── editing ──────────────────────────────────────────────────────────────
    async def set_routes(self, scope: str, scope_id: str, routes: dict[str, Any]) -> dict[str, Any]:
        """Replace the roles named in `routes` (None / empty clears one) for a scope."""
        if scope not in ("global", "workspace", "chat"):
            raise RouteError("scope debe ser global, workspace o chat.")
        scope_id = str(scope_id or "").strip()
        if scope == "workspace" and scope_id:
            from pathlib import Path

            try:
                scope_id = str(Path(scope_id).resolve())  # same form /workspace stores
            except (OSError, ValueError):
                raise RouteError("Ruta de workspace inválida.")
        if scope != "global" and (not scope_id or len(scope_id) > 400 or _CONTROL.search(scope_id)):
            raise RouteError("Falta el identificador del workspace o del chat.")
        if not isinstance(routes, dict):
            raise RouteError("routes debe ser un objeto.")
        cleaned: dict[str, dict[str, str] | None] = {}
        for role, value in routes.items():
            if role not in ROLES:
                raise RouteError(f"Rol desconocido: {role}")
            cleaned[role] = self._clean_route(value)

        bucket = self._bucket(scope, scope_id, create=True)
        for role, route in cleaned.items():
            if route is None:
                bucket.pop(role, None)
            else:
                bucket[role] = route
        self._prune()
        await self._save()
        return dict(self._bucket(scope, scope_id, create=False) or {})

    def _bucket(self, scope: str, scope_id: str, create: bool) -> dict[str, Any] | None:
        if scope == "global":
            return self.data["global"]
        store = self.data["workspaces" if scope == "workspace" else "chats"]
        if scope_id not in store and create:
            store[scope_id] = {}
        return store.get(scope_id)

    def _prune(self) -> None:
        for name in ("workspaces", "chats"):
            self.data[name] = {k: v for k, v in self.data[name].items() if v}

    async def clear(self, scope: str, scope_id: str = "") -> None:
        bucket = self._bucket(scope, scope_id, create=False)
        if bucket:
            bucket.clear()
            self._prune()
            await self._save()

    # ── resolving ────────────────────────────────────────────────────────────
    def resolve(self, role: str) -> tuple[str, str | None] | None:
        """(provider, model) to use for this role in the current message, or None = main model."""
        if role not in ROLES:
            return None
        key, workspace = route_scope.get() or ("", "")
        for bucket in (
            self.data["chats"].get(key) if key else None,
            self.data["workspaces"].get(workspace) if workspace else None,
            self.data["global"],
        ):
            route = (bucket or {}).get(role)
            if route and route.get("provider") in self._router.config.providers:
                return route["provider"], (route.get("model") or None)
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "roles": [{"id": k, **v} for k, v in ROLES.items()],
            "global": self.data["global"],
            "workspaces": self.data["workspaces"],
            "chats": self.data["chats"],
        }
