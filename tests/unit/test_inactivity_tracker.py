import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from openacm.core.inactivity_tracker import AgentInactivityTracker
from openacm.core.events import EventBus
from openacm.storage.database import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def mock_memory():
    memory = MagicMock()
    memory.add_message = AsyncMock()
    return memory


class TestInactivityTracker:
    async def test_schedule_and_fire_default_message(self, db, event_bus, mock_memory):
        tracker = AgentInactivityTracker(event_bus=event_bus, database=db, memory=mock_memory)

        agent_id = await db.create_agent(
            name="TestBot",
            description="",
            system_prompt="You are a test bot",
            inactivity_timeout_minutes=10,
        )
        agent = await db.get_agent(agent_id)

        received_events = []
        async def on_channel_send(event_type, data):
            received_events.append(data)

        event_bus.on("channel:send", on_channel_send)

        # Schedule with delay_seconds=0.05 for fast test
        tracker.schedule(
            agent=agent,
            channel_type="whatsapp_a1",
            target_id="573001234567",
            user_id="a1_wa_573001234567",
            delay_seconds=0.05,
        )

        assert (agent_id, "whatsapp", "573001234567") in tracker._timers

        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        ev = received_events[0]
        assert ev["channel"] == "whatsapp"
        assert ev["agent_id"] == agent_id
        assert ev["target_id"] == "573001234567"
        assert "¡Hola!" in ev["text"]

        # Verifying message was stored in memory
        mock_memory.add_message.assert_called_once_with(
            user_id="a1_wa_573001234567",
            channel_id="573001234567",
            role="assistant",
            content=ev["text"],
        )

        # Timer task should be cleaned up
        assert (agent_id, "whatsapp", "573001234567") not in tracker._timers

    async def test_schedule_and_fire_custom_template_with_name(self, db, event_bus, mock_memory):
        tracker = AgentInactivityTracker(event_bus=event_bus, database=db, memory=mock_memory)

        agent_id = await db.create_agent(
            name="CeluBot",
            description="",
            system_prompt="Prompt",
            inactivity_timeout_minutes=5,
            inactivity_message="¡Hola {name}! ¿Aún estás por aquí? Cuéntame si necesitas ayuda con algún equipo.",
        )
        agent = await db.get_agent(agent_id)

        # Save customer name
        await db.set_customer_name("a1_wa_573001234567", "573001234567", "Cristian")

        received_events = []
        async def on_channel_send(event_type, data):
            received_events.append(data)

        event_bus.on("channel:send", on_channel_send)

        tracker.schedule(
            agent=agent,
            channel_type="whatsapp_a1",
            target_id="573001234567",
            user_id="a1_wa_573001234567",
            delay_seconds=0.05,
        )

        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0]["text"] == "¡Hola Cristian! ¿Aún estás por aquí? Cuéntame si necesitas ayuda con algún equipo."

    async def test_cancel_before_expiry(self, db, event_bus, mock_memory):
        tracker = AgentInactivityTracker(event_bus=event_bus, database=db, memory=mock_memory)

        agent_id = await db.create_agent(
            name="TestBot",
            description="",
            system_prompt="Prompt",
            inactivity_timeout_minutes=10,
        )
        agent = await db.get_agent(agent_id)

        received_events = []
        async def on_channel_send(event_type, data):
            received_events.append(data)

        event_bus.on("channel:send", on_channel_send)

        tracker.schedule(
            agent=agent,
            channel_type="whatsapp_a1",
            target_id="573001234567",
            user_id="a1_wa_573001234567",
            delay_seconds=0.1,
        )

        # User speaks before timer expires -> cancel
        tracker.cancel(agent_id, "whatsapp_a1", "573001234567")

        await asyncio.sleep(0.15)

        assert len(received_events) == 0
        mock_memory.add_message.assert_not_called()

    async def test_zero_timeout_does_not_schedule(self, db, event_bus, mock_memory):
        tracker = AgentInactivityTracker(event_bus=event_bus, database=db, memory=mock_memory)

        agent_id = await db.create_agent(
            name="TestBot",
            description="",
            system_prompt="Prompt",
            inactivity_timeout_minutes=0,
        )
        agent = await db.get_agent(agent_id)

        tracker.schedule(
            agent=agent,
            channel_type="whatsapp_a1",
            target_id="573001234567",
            user_id="a1_wa_573001234567",
        )

        assert len(tracker._timers) == 0

    async def test_inactive_agent_does_not_nudge(self, db, event_bus, mock_memory):
        tracker = AgentInactivityTracker(event_bus=event_bus, database=db, memory=mock_memory)

        agent_id = await db.create_agent(
            name="TestBot",
            description="",
            system_prompt="Prompt",
            inactivity_timeout_minutes=10,
        )
        agent = await db.get_agent(agent_id)

        received_events = []
        async def on_channel_send(event_type, data):
            received_events.append(data)

        event_bus.on("channel:send", on_channel_send)

        tracker.schedule(
            agent=agent,
            channel_type="whatsapp_a1",
            target_id="573001234567",
            user_id="a1_wa_573001234567",
            delay_seconds=0.05,
        )

        # Deactivate agent
        await db.update_agent(agent_id, is_active=0)

        await asyncio.sleep(0.1)

        assert len(received_events) == 0
