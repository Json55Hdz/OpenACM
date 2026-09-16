import pytest
from openacm.web.state import _state

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    return TEST_TOKEN


@pytest.fixture
def auth_headers(dashboard_token):
    return {"Authorization": f"Bearer {dashboard_token}"}


@pytest.mark.asyncio
async def test_api_conversations_grouping_and_naming(dashboard_token, client, auth_headers, db):
    _state.db = db

    # 1. Create an agent
    agent_id = await db.create_agent(
        name="Celubot",
        description="Agente de Celumovil Store",
        system_prompt="Test agent prompt",
        allowed_tools="save_customer_name",
    )

    # 2. Add normal messages
    await db.log_message("web_user1", "web", "user", "Hola desde la web")
    await db.log_message("web_user1", "web", "assistant", "Hola! En que te ayudo?")

    # 3. Add agent WhatsApp message
    # WhatsApp agent pattern: user_id=a{agent_id}_wa_{sender_phone}, channel_id=sender_phone
    phone = "573144574598"
    wa_user_id = f"a{agent_id}_wa_{phone}"
    await db.log_message(wa_user_id, phone, "user", "Hola Celubot")
    await db.log_message(wa_user_id, phone, "assistant", "Hola! Como te llamas?")

    # 4. Save customer name
    await db.set_customer_name(wa_user_id, phone, "Json")

    # 5. Call /api/conversations
    res = await client.get("/api/conversations", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2

    # Map by channel_id
    by_channel = {c["channel_id"]: c for c in data}

    # Normal web conversation
    web_conv = by_channel["web"]
    assert web_conv["is_agent"] is False
    assert web_conv["channel_type"] == "web"
    assert web_conv["title"] == "Web Chat (web_user1)"
    assert web_conv["last_message"] == "Hola! En que te ayudo?"

    # Agent WhatsApp conversation
    agent_conv = by_channel[phone]
    assert agent_conv["is_agent"] is True
    assert agent_conv["agent_id"] == agent_id
    assert agent_conv["agent_name"] == "Celubot"
    assert agent_conv["channel_type"] == "whatsapp"
    assert agent_conv["customer_name"] == "Json"
    assert agent_conv["title"] == "573144574598 (Json)"
    assert agent_conv["last_message"] == "Hola! Como te llamas?"
    assert agent_conv["show_in_chat"] is True


@pytest.mark.asyncio
async def test_api_conversations_show_in_chat_toggle(dashboard_token, client, auth_headers, db):
    _state.db = db

    # 1. Create an agent with show_in_chat default True
    agent_id = await db.create_agent(
        name="AgentWithToggle",
        description="Toggle test agent",
        system_prompt="Prompt",
    )
    agent = await db.get_agent(agent_id)
    assert agent["show_in_chat"] is True

    # 2. Add message for this agent
    phone = "573001112233"
    wa_user_id = f"a{agent_id}_wa_{phone}"
    await db.log_message(wa_user_id, phone, "user", "Hello agent")
    await db.log_message(wa_user_id, phone, "assistant", "Hello user")

    # 3. /api/conversations should include it
    res = await client.get("/api/conversations", headers=auth_headers)
    assert res.status_code == 200
    convs = res.json()
    assert any(c["agent_id"] == agent_id for c in convs)

    # 4. Turn off show_in_chat via PUT /api/agents/{agent_id}
    put_res = await client.put(
        f"/api/agents/{agent_id}",
        json={"show_in_chat": False},
        headers=auth_headers,
    )
    assert put_res.status_code == 200
    assert put_res.json()["show_in_chat"] is False

    # 5. /api/conversations should now filter it out
    res2 = await client.get("/api/conversations", headers=auth_headers)
    assert res2.status_code == 200
    convs2 = res2.json()
    assert not any(c["agent_id"] == agent_id for c in convs2)

    # 6. /api/conversations?include_hidden=true includes it
    res3 = await client.get("/api/conversations?include_hidden=true", headers=auth_headers)
    assert res3.status_code == 200
    convs3 = res3.json()
    assert any(c["agent_id"] == agent_id for c in convs3)
