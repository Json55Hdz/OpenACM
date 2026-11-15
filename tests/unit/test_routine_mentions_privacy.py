"""The OS watcher's routines describe the OWNER's computer. They must never be appended to
an agent's reply to a customer, nor consumed there so the owner never sees them."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from openacm.core.brain import Brain
from openacm.core.config import AssistantConfig

ROUTINE = {"id": 1, "name": "Trabajo de diseño", "description": "d", "apps": '[{"app_name": "Photoshop"}]', "confidence": 0.9}


def _brain(is_agent, mock_llm_router):
    memory = MagicMock()
    memory.database = SimpleNamespace(
        get_unmentioned_routines=AsyncMock(return_value=[ROUTINE]),
        mark_routines_mentioned=AsyncMock(),
    )
    brain = Brain(config=AssistantConfig(is_agent=is_agent), llm_router=mock_llm_router,
                  memory=memory, event_bus=MagicMock(), tool_registry=MagicMock())
    return brain, memory.database


async def test_an_agents_reply_does_not_get_the_owners_routines(mock_llm_router):
    brain, db = _brain(True, mock_llm_router)
    out = await brain._run_workflow_hook("u", "c", "hola", [], "Claro, te ayudo.", "telegram")
    assert out == "Claro, te ayudo."
    db.mark_routines_mentioned.assert_not_awaited()


async def test_a_swarm_workers_reply_does_not_get_them_either(mock_llm_router):
    brain, db = _brain(False, mock_llm_router)
    out = await brain._run_workflow_hook("u", "c", "tarea", [], "listo", "swarm")
    assert out == "listo"
    db.mark_routines_mentioned.assert_not_awaited()


async def test_the_owners_own_chat_still_gets_them(mock_llm_router):
    brain, db = _brain(False, mock_llm_router)
    out = await brain._run_workflow_hook("u", "c", "hola", [], "Hola.", "web")
    assert "Photoshop" in out
    db.mark_routines_mentioned.assert_awaited_once()


class TestWorkflowConfirmationIsOnlyAnAnswer:
    def _check(self, text, mock_llm_router):
        brain, _ = _brain(False, mock_llm_router)
        return brain._check_workflow_confirmation(text)

    def test_plain_answers(self, mock_llm_router):
        for text in ("sí", "Dale!", "ok, créalo", "Sí, por favor", "claro que sí"):
            assert self._check(text, mock_llm_router) == "yes", text
        for text in ("no", "No gracias", "cancelar", "no, ok"):
            assert self._check(text, mock_llm_router) == "no", text

    def test_a_message_that_says_more_is_not_an_answer(self, mock_llm_router):
        for text in ("ok, y qué hora es en Tokio?", "dale pero antes dime mi agenda", "no sé qué decir", "quiero ver mis correos"):
            assert self._check(text, mock_llm_router) == "unknown", text
