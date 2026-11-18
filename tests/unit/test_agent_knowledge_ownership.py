"""Each agent searches only the knowledge collections assigned to it."""
import pytest

from openacm.core.config import AssistantConfig
from openacm.tools import knowledge_tools as kt


class _Brain:
    def __init__(self, is_agent, collections=None):
        self.config = AssistantConfig(is_agent=is_agent, knowledge_collections=collections)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    for name, fact in (("ventas", "El plan oro cuesta cien"), ("rrhh", "Las vacaciones son quince dias")):
        col = tmp_path / name
        col.mkdir()
        (col / "doc.md").write_text(f"# Doc {name}\n\n## Dato\n{fact}\n", encoding="utf-8")
    monkeypatch.setattr(kt, "_knowledge_root", lambda: tmp_path)
    kt._CACHE.clear()


async def test_agent_reaches_only_its_own_collection(kb):
    ventas = _Brain(True, ["ventas"])
    # no collection named: it uses its own
    assert "plan oro" in await kt.search_knowledge("plan oro", _brain=ventas)
    # naming the other agent's collection is refused, and the refusal does not leak the content
    refused = await kt.search_knowledge("vacaciones", collection="rrhh", _brain=ventas)
    assert "not one of this agent's" in refused and "quince" not in refused
    # reading a file from it is refused too
    assert "not one of this agent's" in await kt.read_knowledge_file("doc.md", collection="rrhh", _brain=ventas)
    assert "Las vacaciones" not in await kt.read_knowledge_file("doc.md", collection="rrhh", _brain=ventas)


async def test_agent_without_collections_gets_nothing(kb):
    out = await kt.search_knowledge("plan oro", _brain=_Brain(True, []))
    assert out.startswith("Error") and "no knowledge collections" in out and "plan oro" not in out.split("collections")[0]


async def test_main_assistant_is_not_restricted(kb):
    main = _Brain(False)
    assert "vacaciones" in (await kt.search_knowledge("vacaciones", collection="rrhh", _brain=main)).lower()


def test_parse_collections():
    assert kt.parse_collections('["a", "b"]') == ["a", "b"]
    assert kt.parse_collections(None) == [] and kt.parse_collections("nonsense") == []
    assert kt.parse_collections(["x"]) == ["x"]


async def _make_agents(db):
    a = await db.create_agent(name="A", description="", system_prompt="a")
    b = await db.create_agent(name="B", description="", system_prompt="b")
    return a, b


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "t")


async def test_api_assigns_collections_and_one_agent_per_collection(dashboard_token, client, db, kb):
    h = {"Authorization": "Bearer t"}
    a, b = await _make_agents(db)

    ok = await client.put(f"/api/agents/{a}", json={"knowledge_collections": ["ventas"]}, headers=h)
    assert ok.status_code == 200
    agents = {x["id"]: x for x in (await client.get("/api/agents", headers=h)).json()}
    assert agents[a]["knowledge_collections"] == ["ventas"] and agents[b]["knowledge_collections"] == []

    # a collection belongs to ONE agent
    clash = await client.put(f"/api/agents/{b}", json={"knowledge_collections": ["ventas"]}, headers=h)
    assert clash.status_code == 409
    assert (await client.put(f"/api/agents/{b}", json={"knowledge_collections": ["rrhh"]}, headers=h)).status_code == 200

    # unknown collection / wrong shape are rejected
    assert (await client.put(f"/api/agents/{b}", json={"knowledge_collections": ["nope"]}, headers=h)).status_code == 404
    assert (await client.put(f"/api/agents/{b}", json={"knowledge_collections": "rrhh"}, headers=h)).status_code == 400

    # un-assigning frees it for someone else
    await client.put(f"/api/agents/{a}", json={"knowledge_collections": []}, headers=h)
    assert (await client.put(f"/api/agents/{b}", json={"knowledge_collections": ["rrhh", "ventas"]}, headers=h)).status_code == 200


async def test_migration_keeps_an_existing_agents_collection(db, kb, monkeypatch, tmp_path):
    (tmp_path / "colsanitas").mkdir()
    sibling = await db.create_agent(name="Asesor Citas Colsanitas", description="", system_prompt="Usa colsanitas")
    other = await db.create_agent(name="Otro", description="", system_prompt="un agente cualquiera")
    await db._db.execute("UPDATE agents SET knowledge_collections = '[]'")
    await db._db.execute("UPDATE settings SET value = '43' WHERE key = 'schema_version'")
    await db._db.commit()

    await db._run_migrations()

    assert (await db.get_agent(sibling))["knowledge_collections"] == '["colsanitas"]'
    assert (await db.get_agent(other))["knowledge_collections"] == "[]"
