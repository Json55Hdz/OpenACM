"""The WhatsApp webhook is public: it must check who signed a message, using the right secret."""

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openacm.web.routers import whatsapp_webhook as webhook
from openacm.web.state import _state


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(phone_id="111", text="hola"):
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_id},
        "messages": [{"id": "m1", "from": "573000000000", "type": "text", "text": {"body": text}}],
    }}]}]}


class _Channel:
    def __init__(self, secret=""):
        self.config = SimpleNamespace(app_secret=secret)
        self.handled = []

    async def handle_incoming(self, value):
        self.handled.append(value)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv(webhook.REQUIRE_SIGNATURE_ENV, raising=False)
    state = SimpleNamespace(handled=None)

    def make(global_secret="", agent=None, main=None):
        monkeypatch.setattr(_state, "config", SimpleNamespace(channels=SimpleNamespace(
            whatsapp=SimpleNamespace(app_secret=global_secret, verify_token="v"))), raising=False)
        monkeypatch.setattr(_state, "agent_channel_manager", SimpleNamespace(
            get_channel_by_phone=lambda pid: agent if pid == "111" else None), raising=False)
        monkeypatch.setattr("openacm.channels.whatsapp_cloud_channel.get_active_channel", lambda: main)
        app = FastAPI()
        webhook.register_routes(app)
        return TestClient(app)

    state.make = make
    return state


def _post(client, payload, secret=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Hub-Signature-256"] = _sign(secret, body)
    return client.post("/webhooks/whatsapp", content=body, headers=headers)


def test_a_message_signed_with_the_agents_own_secret_is_accepted(setup):
    agent = _Channel(secret="agent-secret")
    client = setup.make(global_secret="global-secret", agent=agent)
    assert _post(client, _payload(), secret="agent-secret").status_code == 200
    assert len(agent.handled) == 1


def test_a_message_signed_with_the_wrong_secret_is_rejected(setup):
    agent = _Channel(secret="agent-secret")
    client = setup.make(global_secret="global-secret", agent=agent)
    assert _post(client, _payload(), secret="somebody-else").status_code == 403
    assert agent.handled == []


def test_an_unsigned_message_is_rejected_when_a_secret_is_configured(setup):
    agent = _Channel(secret="agent-secret")
    client = setup.make(agent=agent)
    assert _post(client, _payload()).status_code == 403
    assert agent.handled == []


def test_an_agent_without_its_own_secret_uses_the_global_one(setup):
    agent = _Channel(secret="")
    client = setup.make(global_secret="global-secret", agent=agent)
    assert _post(client, _payload(), secret="global-secret").status_code == 200
    assert len(agent.handled) == 1


def test_with_no_secret_anywhere_it_still_works_but_can_be_made_strict(setup, monkeypatch):
    main = _Channel(secret="")
    client = setup.make(main=main)
    assert _post(client, _payload(phone_id="999")).status_code == 200
    assert len(main.handled) == 1

    monkeypatch.setenv(webhook.REQUIRE_SIGNATURE_ENV, "true")
    assert _post(client, _payload(phone_id="999")).status_code == 403


def test_a_body_that_is_not_json_is_a_client_error(setup):
    client = setup.make(main=_Channel())
    assert _post(client, None, raw=b"not json").status_code == 400


def test_a_payload_cannot_carry_a_change_for_a_channel_whose_secret_did_not_sign_it(setup):
    agent = _Channel(secret="agent-secret")
    main = _Channel(secret="main-secret")
    client = setup.make(global_secret="main-secret", agent=agent, main=main)
    payload = _payload(phone_id="111")
    payload["entry"][0]["changes"].append(_payload(phone_id="999")["entry"][0]["changes"][0])
    # signed with the main secret only: the change for the agent's phone must not be accepted
    assert _post(client, payload, secret="main-secret").status_code == 403
    assert agent.handled == [] and main.handled == []
