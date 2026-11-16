"""
Central Command Processor — single source of truth for slash commands.

All channels (console, Telegram, web) delegate command handling here.
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

from openacm.core.messages import (
    MSG_CMD_RESET,
    MSG_CMD_NO_LLM,
    MSG_CMD_TOO_FEW,
    MSG_CMD_COMPACT_HEADER,
    MSG_CMD_COMPACT_FAILED,
    MSG_STEPS_CURRENT,
    MSG_STEPS_DEFAULT,
    MSG_STEPS_INVALID,
    MSG_STEPS_OFF,
    MSG_STEPS_SET,
    STEPS_UNLIMITED,
)

log = structlog.get_logger()


@dataclass
class CommandResult:
    """Result of executing a slash command."""

    handled: bool
    text: str = ""
    data: dict[str, Any] | None = None


# Canonical command list shown by /help
COMMANDS_HELP = (
    "**Available commands**\n\n"
    "- `/new` · `/clear` — Start a new conversation\n"
    "- `/reset` — Emergency reset: clears history + fixes broken tool state\n"
    "- `/compact` — Summarize old messages to free up context window\n"
    "- `/workspace <path>` — Pin a working directory for this conversation\n"
    "- `/workspace` — Show the current pinned workspace (or clear it with `/workspace clear`)\n"
    "- `/help` — Show this help\n"
    "- `/model` — Show current model\n"
    "- `/model <name>` — Switch to a different model (persisted)\n"
    "- `/route` - Show which model each kind of work uses in this chat\n"
    "- `/route <orchestrator|tools|background> <provider/model>` - Use another model for that work in this chat (`clear` to undo)\n"
    "- `/stats` — Show usage statistics\n"
    "- `/export` — Export current conversation as text"
)


class CommandProcessor:
    """Process slash commands for any channel."""

    def __init__(self, brain: Any, database: Any):
        self.brain = brain
        self.database = database

    async def handle(
        self, cmd: str, args: str, user_id: str, channel_id: str
    ) -> CommandResult:
        """Process a slash command and return the result."""
        cmd = cmd.lower().strip()

        match cmd:
            case "/new" | "/clear":
                return await self._cmd_clear(user_id, channel_id)
            case "/reset":
                return await self._cmd_reset(user_id, channel_id)
            case "/help":
                return self._cmd_help()
            case "/model":
                return await self._cmd_model(args.strip())
            case "/stats":
                return await self._cmd_stats()
            case "/compact":
                return await self._cmd_compact(user_id, channel_id)
            case "/export":
                return await self._cmd_export(user_id, channel_id)
            case "/probe":
                return await self._cmd_probe()
            case "/steps":
                return await self._cmd_steps(args.strip(), user_id, channel_id)
            case "/workspace":
                return await self._cmd_workspace(args.strip(), user_id, channel_id)
            case "/route":
                return await self._cmd_route(args.strip(), user_id, channel_id)
            case _:
                return CommandResult(handled=False)

    # ── Individual commands ───────────────────────────────────

    async def _cmd_clear(self, user_id: str, channel_id: str) -> CommandResult:
        await self.brain.memory.clear(user_id, channel_id)
        return CommandResult(handled=True, text="Conversation cleared.")

    async def _cmd_reset(self, user_id: str, channel_id: str) -> CommandResult:
        """Emergency reset: wipes conversation memory to fix broken LLM state."""
        await self.brain.memory.clear(user_id, channel_id)
        return CommandResult(
            handled=True,
            text=MSG_CMD_RESET,
            data={"reset": True},
        )

    async def _cmd_probe(self) -> CommandResult:
        """Re-test what the current model accepts (image / audio input)."""
        router = self.brain.llm_router
        caps = await router.capabilities.probe(force=True)
        return CommandResult(
            handled=True,
            text=(
                f"`{router.current_model}` (provider: `{router.current_provider}`) — "
                f"{router.capabilities.describe()}\n\n_{caps.get('note', '')}_"
            ),
            data={"capabilities": caps},
        )

    async def _cmd_steps(self, args: str, user_id: str, channel_id: str) -> CommandResult:
        """Show or set the per-chat tool-step limit (overrides max_tool_iterations)."""
        default = self.brain.config.max_tool_iterations
        limits = self.brain._step_limits
        key = (user_id, channel_id)
        arg = args.lower()
        if not arg:
            current = await self.brain._resolve_step_limit(user_id, channel_id)
            shown = "no limit" if current >= STEPS_UNLIMITED else str(current)
            return CommandResult(handled=True, text=MSG_STEPS_CURRENT.format(limit=shown, default=default))
        if arg in ("default", "reset"):
            value, text = None, MSG_STEPS_DEFAULT.format(default=default)
        elif arg in ("off", "none", "unlimited", "0", "sin", "infinito"):
            value, text = STEPS_UNLIMITED, MSG_STEPS_OFF
        elif arg.isdigit() and int(arg) > 0:
            value = int(arg)
            text = MSG_STEPS_SET.format(limit=value)
        else:
            return CommandResult(handled=True, text=MSG_STEPS_INVALID)
        limits[key] = value
        if self.database:
            try:
                await self.database.set_setting(
                    self.brain.step_limit_key(user_id, channel_id), str(value or "")
                )
            except Exception as e:
                log.warning("Could not persist step limit", error=str(e))
        return CommandResult(handled=True, text=text, data={"max_steps": value})

    @staticmethod
    def _cmd_help() -> CommandResult:
        return CommandResult(handled=True, text=COMMANDS_HELP)

    async def _cmd_model(self, args: str) -> CommandResult:
        router = self.brain.llm_router
        if not args:
            model = router.current_model
            provider = router.current_provider
            return CommandResult(
                handled=True,
                text=f"Current model: `{model}` (provider: `{provider}`) — {router.capabilities.describe()}",
            )

        # Change model
        router.set_model(args)
        # Persist to database
        await self._persist_model(router.current_model, router.current_provider)
        # Measure image/audio input now so the answer can say what this model can do.
        try:
            await router.capabilities.probe()
        except Exception as e:  # noqa: BLE001
            log.warning("Capability probe failed", error=str(e))
        return CommandResult(
            handled=True,
            text=(
                f"Model changed to `{router.current_model}` (provider: `{router.current_provider}`) — "
                f"{router.capabilities.describe()}"
            ),
        )

    async def _persist_model(self, model: str, provider: str) -> None:
        if not self.database:
            return
        try:
            await self.database.set_setting("llm.current_model", model)
            await self.database.set_setting("llm.current_provider", provider)
        except Exception as e:
            log.warning("Could not persist model setting", error=str(e))

    async def _cmd_stats(self) -> CommandResult:
        if not self.database:
            return CommandResult(handled=True, text="Database not available.")

        stats = await self.database.get_stats()
        router_stats = self.brain.llm_router.get_stats()

        text = (
            f"**Usage stats**\n\n"
            f"| Metric | Value |\n"
            f"|---|---|\n"
            f"| Messages (total) | {stats.get('total_messages', 0)} |\n"
            f"| Messages today | {stats.get('messages_today', 0)} |\n"
            f"| Tokens (total) | {stats.get('total_tokens', 0):,} |\n"
            f"| Tokens today | {stats.get('tokens_today', 0):,} |\n"
            f"| Tool executions | {stats.get('total_tool_calls', 0)} |\n"
            f"| Active conversations (24h) | {stats.get('active_conversations', 0)} |\n"
            f"| Session requests | {router_stats.get('total_requests', 0)} |\n"
            f"| Current model | `{router_stats.get('current_model', 'unknown')}` |"
        )
        return CommandResult(handled=True, text=text, data=stats)

    async def _cmd_compact(self, user_id: str, channel_id: str) -> CommandResult:
        """Force immediate compaction of the current conversation."""
        mem = self.brain.memory
        if not mem._llm_router:
            return CommandResult(handled=True, text=MSG_CMD_NO_LLM)

        msgs = await mem.get_messages(user_id, channel_id)
        non_system = [m for m in msgs if m.get("role") != "system"]
        if len(non_system) < 4:
            return CommandResult(
                handled=True,
                text=MSG_CMD_TOO_FEW,
            )

        # Force compaction regardless of threshold
        key = mem._key(user_id, channel_id)
        mem._needs_compact.discard(key)  # avoid double-fire with auto-compact
        try:
            summary_text = await mem._compact(user_id, channel_id, force=True)
        except Exception as e:
            return CommandResult(
                handled=True,
                text=MSG_CMD_COMPACT_FAILED.format(error=e),
            )
        finally:
            # Always reset the auto-compact baseline after a manual attempt so the
            # countdown restarts from the current message count (not the old one).
            # This prevents auto-compact from immediately re-firing after /compact.
            post_msgs = await mem.get_messages(user_id, channel_id)
            post_non_system = len([m for m in post_msgs if m.get("role") != "system"])
            mem._compact_baseline[key] = post_non_system
            mem._needs_compact.discard(key)

        new_msgs = await mem.get_messages(user_id, channel_id)
        new_count = len([m for m in new_msgs if m.get("role") != "system"])

        header = MSG_CMD_COMPACT_HEADER.format(before=len(non_system), after=new_count)
        body = summary_text if summary_text else "(no summary produced)"
        return CommandResult(
            handled=True,
            text=header + body,
            data={"compact": True},
        )

    async def _cmd_route(self, args: str, user_id: str, channel_id: str) -> CommandResult:
        """Show or change which model handles each kind of work in THIS conversation."""
        from openacm.core.model_routes import ROLES, RouteError, chat_key, route_scope

        router = self.brain.llm_router
        key = chat_key(channel_id, user_id)
        parts = args.split()

        def describe() -> str:
            token = route_scope.set((key, self.brain.memory.get_conversation_workspace(user_id, channel_id) or ""))
            try:
                lines = []
                for role, meta in ROLES.items():
                    hit = router.routes.resolve(role)
                    use = f"{hit[0]}/{hit[1] or 'default'}" if hit else f"main model ({router._current_provider}/{router.current_model})"
                    lines.append(f"- **{role}** ({meta['label']}): `{use}`")
                return "\n".join(lines)
            finally:
                route_scope.reset(token)

        try:
            if not parts:
                return CommandResult(
                    handled=True,
                    text="Models in this chat:\n" + describe()
                    + "\n\nChange: `/route <orchestrator|tools|background> <provider/model>` - undo: `/route <role> clear` or `/route clear`",
                )
            if parts[0].lower() == "clear":
                await router.routes.clear("chat", key)
                return CommandResult(handled=True, text="This chat now follows the workspace/global settings.\n" + describe())
            role = parts[0].lower()
            if role not in ROLES or len(parts) != 2:
                return CommandResult(handled=True, text="Usage: `/route <orchestrator|tools|background> <provider/model>` or `/route <role> clear`")
            if parts[1].lower() == "clear":
                await router.routes.set_routes("chat", key, {role: None})
            else:
                provider, _, model = parts[1].partition("/")
                await router.routes.set_routes("chat", key, {role: {"provider": provider, "model": model}})
            return CommandResult(handled=True, text="Updated.\n" + describe())
        except RouteError as exc:
            return CommandResult(handled=True, text=f"Warning: {exc}")

    async def _cmd_workspace(self, path: str, user_id: str, channel_id: str) -> CommandResult:
        """Pin, clear, or show the workspace for this conversation."""
        from openacm.core.acm_context import _resolve_workspace
        mem = self.brain.memory

        # Show current
        if not path:
            current = mem.get_conversation_workspace(user_id, channel_id)
            if current:
                return CommandResult(
                    handled=True,
                    text=f"📁 Workspace for this conversation: `{current}`\nUse `/workspace clear` to revert to the default.",
                )
            return CommandResult(
                handled=True,
                text=f"📁 No workspace pinned for this conversation.\nDefault workspace: `{_resolve_workspace()}`\nUse `/workspace <path>` to pin one.",
            )

        # Clear
        if path.lower() == "clear":
            mem.clear_conversation_workspace(user_id, channel_id)
            return CommandResult(
                handled=True,
                text=f"📁 Workspace pin removed. Back to default: `{_resolve_workspace()}`",
            )

        # Set — resolve to absolute path
        from pathlib import Path
        resolved = str(Path(path).resolve())
        mem.set_conversation_workspace(user_id, channel_id, resolved)
        # Bust the system-prompt cache so the new workspace appears on the next message
        key = f"{channel_id}:{user_id}"
        self.brain._system_prompt_hash.pop(key, None)
        log.info("Conversation workspace set", user_id=user_id, channel_id=channel_id, path=resolved)
        return CommandResult(
            handled=True,
            text=f"📁 Workspace set to `{resolved}` for this conversation.\nThe AI will use this path for all file operations from now on.",
        )

    async def _cmd_export(self, user_id: str, channel_id: str) -> CommandResult:
        messages = await self.brain.memory.get_messages(user_id, channel_id)
        if not messages:
            return CommandResult(handled=True, text="No messages to export.")

        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "system":
                continue
            if isinstance(content, list):
                # Multimodal content — extract text parts
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            lines.append(f"[{role.upper()}] {content}")

        export_text = "\n\n".join(lines)
        return CommandResult(
            handled=True,
            text=f"Exported {len(lines)} messages.",
            data={"export": export_text, "message_count": len(lines)},
        )
