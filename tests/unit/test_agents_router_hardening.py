"""Agent routes: ownership of knowledge items, missing agents, the chat webhook's secret."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from openacm.storage.database import Database
from openacm.web.routers import agents as agents_router
from openacm.web.state import _state


@pytest_asyncio.fixture
async def real_db():
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def client(real_db, monkeypatch):
    monkeypatch.setattr(_state, "database", real_db)
    monkeypatch.setattr(_state, "brain", MagicMock())
    monkeypatch.setattr(_state, "agent_runner", None)
    monkeypatch.setattr(_state, "agent_channel_manager", None)
    app = FastAPI()
    agents_router.register_routes(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _agent(db, name, secret="s3cret-value"):
    created = await db.create_agent(name=name, description="d", system_prompt="p", webhook_secret=secret)
    return created if isinstance(created, int) else created["id"]


class TestKnowledgeBelongsToItsAgent:
    async def test_an_agent_cannot_change_or_delete_another_agents_item(self, client, real_db):
        a, b = await _agent(real_db, "A"), await _agent(real_db, "B")
        item = await real_db.create_agent_knowledge(b, "text", "secreto de B", "contenido de B")
        kid = item if isinstance(item, int) else item["id"]

        async with client as ac:
            patched = await ac.patch(f"/api/agents/{a}/knowledge/{kid}", json={"title": "robado"})
            deleted = await ac.delete(f"/api/agents/{a}/knowledge/{kid}")

        assert patched.status_code == 404 and deleted.status_code == 404
        still = await real_db.get_agent_knowledge(b)
        assert [i["title"] for i in still] == ["secreto de B"]

    async def test_the_owner_can_still_change_and_delete_it(self, client, real_db):
        a = await _agent(real_db, "A")
        item = await real_db.create_agent_knowledge(a, "text", "t", "c")
        kid = item if isinstance(item, int) else item["id"]
        async with client as ac:
            assert (await ac.patch(f"/api/agents/{a}/knowledge/{kid}", json={"title": "nuevo"})).status_code == 200
            assert (await ac.delete(f"/api/agents/{a}/knowledge/{kid}")).status_code == 200


class TestMissingAgent:
    async def test_updating_an_agent_that_does_not_exist_is_a_404(self, client):
        async with client as ac:
            resp = await ac.put("/api/agents/999", json={"name": "x"})
        assert resp.status_code == 404


class TestChatWebhookSecret:
    async def test_the_wrong_secret_is_refused_and_the_right_one_answers(self, client, real_db):
        a = await _agent(real_db, "A")
        agent = await real_db.get_agent(a)
        with patch("openacm.core.agent_runner.AgentRunner.run", AsyncMock(return_value="hola")):
            async with client as ac:
                bad = await ac.post(f"/api/agents/{a}/chat", json={"message": "hi"}, headers={"X-Agent-Secret": "nope"})
                none = await ac.post(f"/api/agents/{a}/chat", json={"message": "hi"})
                good = await ac.post(
                    f"/api/agents/{a}/chat", json={"message": "hi"},
                    headers={"X-Agent-Secret": agent["webhook_secret"]},
                )
        assert bad.status_code == 401 and none.status_code == 401
        assert good.status_code == 200 and good.json()["response"] == "hola"


class TestChatWebhookIsReachableFromOutside:
    def test_the_auth_middleware_lets_the_agent_chat_path_through(self):
        from openacm.web.routers.system import _AGENT_CHAT_PATH

        assert _AGENT_CHAT_PATH.fullmatch("/api/agents/12/chat")
        for other in ("/api/agents/12", "/api/agents/12/chat/extra", "/api/agents/x/chat", "/api/agents/12/secret"):
            assert not _AGENT_CHAT_PATH.fullmatch(other)


    async def test_an_agent_without_a_secret_cannot_be_called_by_anyone(self, client, real_db):
        a = await _agent(real_db, "Open", secret="")
        with patch("openacm.core.agent_runner.AgentRunner.run", AsyncMock(return_value="hola")):
            async with client as ac:
                resp = await ac.post(f"/api/agents/{a}/chat", json={"message": "hi"})
        assert resp.status_code == 401


class TestChatWebhookUserIdIsUntrusted:
    async def test_the_caller_cannot_choose_another_users_memory(self, client, real_db):
        a = await _agent(real_db, "A")
        run = AsyncMock(return_value="ok")
        with patch("openacm.core.agent_runner.AgentRunner.run", run):
            async with client as ac:
                await ac.post(
                    f"/api/agents/{a}/chat",
                    json={"message": "hi", "user_id": "owner\n; ../x" + "z" * 200},
                    headers={"X-Agent-Secret": "s3cret-value"},
                )
        uid = run.await_args.kwargs["user_id"]
        assert uid.startswith(f"a{a}_hook_") and len(uid) <= 80 and "\n" not in uid and "/" not in uid
