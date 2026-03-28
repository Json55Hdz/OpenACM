"""
Central Command Processor — single source of truth for slash commands.

All channels (console, Telegram, web) delegate command handling here.
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class CommandResult:
    """Result of executing a slash command."""

    handled: bool
    text: str = ""
    data: dict[str, Any] | None = None


# Canonical command list shown by /help
COMMANDS_HELP = (
    "/new     — Start a new conversation (clear history)\n"
    "/clear   — Same as /new\n"
    "/reset   — Emergency reset: clears history + fixes broken tool state\n"
    "/help    — Show this help\n"
    "/model   — Show current model\n"
    "/model <name> — Switch to a different model (persisted)\n"
    "/stats   — Show usage statistics\n"
    "/export  — Export current conversation as text"
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
            case "/export":
                return await self._cmd_export(user_id, channel_id)
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
            text="🔄 Reset complete. Conversation history cleared.\nThe AI is ready for a fresh start.",
            data={"reset": True},
        )

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
                text=f"Current model: {model} (provider: {provider})",
            )

        # Change model
        router.set_model(args)
        # Persist to database
        await self._persist_model(router.current_model, router.current_provider)
        return CommandResult(
            handled=True,
            text=f"Model changed to: {router.current_model} (provider: {router.current_provider})",
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
            f"Messages: {stats.get('total_messages', 0)}\n"
            f"Messages today: {stats.get('messages_today', 0)}\n"
            f"Total tokens: {stats.get('total_tokens', 0)}\n"
            f"Tokens today: {stats.get('tokens_today', 0)}\n"
            f"Tool executions: {stats.get('total_tool_calls', 0)}\n"
            f"Active conversations (24h): {stats.get('active_conversations', 0)}\n"
            f"Session requests: {router_stats.get('total_requests', 0)}\n"
            f"Current model: {router_stats.get('current_model', 'unknown')}"
        )
        return CommandResult(handled=True, text=text, data=stats)

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
