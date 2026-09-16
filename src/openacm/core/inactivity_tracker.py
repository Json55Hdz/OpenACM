"""
Agent Inactivity Tracker — manages timers for proactive follow-up messages.

When a customer goes silent after an agent's response, this tracker schedules
a timer (e.g. 10 minutes). If the customer does not speak before the timer expires,
it proactively sends a friendly reminder via `channel:send` and records it in memory.
"""
from __future__ import annotations

import asyncio
from typing import Any
import structlog

log = structlog.get_logger()


class AgentInactivityTracker:
    """Tracks inactivity per conversation and emits proactive follow-up nudges."""

    def __init__(self, event_bus, database=None, memory=None):
        self.event_bus = event_bus
        self.database = database
        self.memory = memory
        # (agent_id, channel_type, target_id) -> asyncio.Task
        self._timers: dict[tuple[int, str, str], asyncio.Task] = {}

    def _channel_base(self, channel_type: str) -> str:
        """Extract base channel name (e.g. 'whatsapp_a1' -> 'whatsapp')."""
        if channel_type.startswith("whatsapp"):
            return "whatsapp"
        if channel_type.startswith("telegram"):
            return "telegram"
        return channel_type

    def cancel(self, agent_id: int, channel_type: str, target_id: str) -> None:
        """Cancel any pending follow-up timer for this conversation."""
        base_ch = self._channel_base(channel_type)
        key = (agent_id, base_ch, target_id)
        task = self._timers.pop(key, None)
        if task and not task.done():
            task.cancel()
            log.info("Cancelled inactivity timer", agent_id=agent_id, channel=base_ch, target_id=target_id)

    def schedule(
        self,
        agent: dict[str, Any],
        channel_type: str,
        target_id: str,
        user_id: str,
        delay_seconds: float | None = None,
    ) -> None:
        """Schedule a follow-up timer if inactivity_timeout_minutes > 0."""
        agent_id = agent.get("id")
        if not agent_id:
            return

        timeout_minutes = agent.get("inactivity_timeout_minutes", 0)
        if (delay_seconds is None or delay_seconds <= 0) and (not timeout_minutes or timeout_minutes <= 0):
            return

        base_ch = self._channel_base(channel_type)
        # Cancel any previous timer before starting a new one
        self.cancel(agent_id, base_ch, target_id)

        seconds = delay_seconds if delay_seconds is not None else float(timeout_minutes * 60)
        key = (agent_id, base_ch, target_id)

        task = asyncio.create_task(
            self._wait_and_nudge(
                key=key,
                agent_id=agent_id,
                channel_base=base_ch,
                target_id=target_id,
                user_id=user_id,
                delay_seconds=seconds,
            )
        )
        self._timers[key] = task
        log.info(
            "Scheduled inactivity timer",
            agent_id=agent_id,
            channel=base_ch,
            target_id=target_id,
            seconds=seconds,
            minutes=round(seconds / 60, 1),
        )

    async def _wait_and_nudge(
        self,
        key: tuple[int, str, str],
        agent_id: int,
        channel_base: str,
        target_id: str,
        user_id: str,
        delay_seconds: float,
    ) -> None:
        """Wait for delay_seconds and emit follow-up nudge if still active."""
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return
        finally:
            self._timers.pop(key, None)

        # Check that agent is still valid and active
        agent = None
        if self.database:
            try:
                agent = await self.database.get_agent(agent_id)
            except Exception as exc:
                log.warning("InactivityTracker: failed to get agent", agent_id=agent_id, error=str(exc))

        if agent and not agent.get("is_active"):
            return

        # Fetch customer name if available
        customer_name = ""
        if self.database:
            try:
                customer_name = await self.database.get_customer_name(user_id, target_id) or ""
            except Exception as exc:
                log.warning("InactivityTracker: failed to get customer name", error=str(exc))

        # Format nudge message
        custom_template = (agent.get("inactivity_message") if agent else "") or ""
        if custom_template.strip():
            text = custom_template.replace("{name}", customer_name).replace("[nombre]", customer_name).replace("{nombre}", customer_name)
            text = " ".join(text.split())
        else:
            if customer_name:
                text = f"¡Hola {customer_name}! 💕 Recuerda que sigo por aquí si tienes alguna duda con tu compra o necesitas ayuda con algún celular. ¡Estoy a tu disposición! 👀"
            else:
                text = "¡Hola! 💕 Recuerda que sigo por aquí si tienes alguna duda con tu compra o necesitas ayuda con algún celular. ¡Estoy a tu disposición! 👀"

        # Emit channel:send event
        if self.event_bus:
            await self.event_bus.emit(
                "channel:send",
                {
                    "channel": channel_base,
                    "agent_id": agent_id,
                    "target_id": target_id,
                    "text": text,
                },
            )
            log.info("Inactivity follow-up sent", agent_id=agent_id, channel=channel_base, target_id=target_id)

        # Record assistant message in conversation memory so context stays consistent
        if self.memory:
            try:
                await self.memory.add_message(
                    user_id=user_id,
                    channel_id=target_id,
                    role="assistant",
                    content=text,
                )
            except Exception as exc:
                log.warning("InactivityTracker: failed to save nudge to memory", error=str(exc))

    async def stop_all(self) -> None:
        """Cancel and clean up all pending timers."""
        tasks = list(self._timers.values())
        self._timers.clear()
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
