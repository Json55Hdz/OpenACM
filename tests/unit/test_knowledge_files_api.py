"""The dashboard can list, read and edit the Markdown files behind search_knowledge."""
import pytest

from openacm.tools import knowledge_tools as kt


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "t")
    return "t"


@pytest.fixture
def kb(tmp_path, monkeypatch):
    col = tmp_path / "demo"
    col.mkdir()
    (col / "01-a.md").write_text("# Hoja A\n\ncontenido a\n", encoding="utf-8")
    (col / "02-b.md").write_text("# Hoja B\n", encoding="utf-8")
    monkeypatch.setattr(kt, "_knowledge_root", lambda: tmp_path)
    kt._CACHE.clear()
    return col


async def test_list_read_and_edit_files(dashboard_token, client, kb):
    h = {"Authorization": "Bearer t"}

    listing = (await client.get("/api/knowledge-files", headers=h)).json()
    demo = next(c for c in listing if c["collection"] == "demo")
    assert [f["name"] for f in demo["files"]] == ["01-a.md", "02-b.md"]
    assert demo["files"][0]["title"] == "Hoja A"

    got = (await client.get("/api/knowledge-files/demo/01-a.md", headers=h)).json()
    assert "contenido a" in got["content"]

    res = await client.put("/api/knowledge-files/demo/01-a.md", json={"content": "# Hoja A\n\nnuevo\n"}, headers=h)
    assert res.status_code == 200
    assert (kb / "01-a.md").read_text(encoding="utf-8") == "# Hoja A\n\nnuevo\n"
    # the search tool sees the edit without a restart
    assert "nuevo" in await kt.search_knowledge("nuevo", collection="demo")


async def test_rejects_path_traversal_and_non_markdown(dashboard_token, client, kb):
    h = {"Authorization": "Bearer t"}
    (kb.parent / "secret.md").write_text("TOP SECRET", encoding="utf-8")
    res = await client.get("/api/knowledge-files/demo/..%2Fsecret.md", headers=h)
    assert "TOP SECRET" not in res.text
    assert (await client.put("/api/knowledge-files/demo/x.py", json={"content": "x"}, headers=h)).status_code == 400
    assert (await client.put("/api/knowledge-files/demo/nuevo.md", json={"content": "x"}, headers=h)).status_code == 404
