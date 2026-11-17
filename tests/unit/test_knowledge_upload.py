"""Adding and removing documents of a knowledge collection from the dashboard API."""
import pytest

from openacm.tools import knowledge_tools as kt
from openacm.utils.knowledge_file import as_searchable_markdown, slug_filename


def test_slug_filename():
    assert slug_filename("Tarifas 2026 (v2).PDF") == "tarifas-2026-v2.md"
    assert slug_filename("Cobertura Médica ñandú.docx") == "cobertura-medica-nandu.md"
    assert slug_filename("../../etc/passwd") == "passwd.md"
    assert slug_filename("???.txt") == "documento.md"


def test_flat_text_is_split_into_sections_and_titled():
    text = "\n\n".join(f"Párrafo {i} " + "x" * 400 for i in range(10))
    md = as_searchable_markdown("Mi doc", text)
    assert md.startswith("# Mi doc")
    assert md.count("\n## Parte ") >= 3


def test_text_that_already_has_headings_is_kept():
    md = as_searchable_markdown("T", "# T\n\n## Uno\nhola\n\n## Dos\nchau")
    assert "Parte" not in md


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "t")


@pytest.fixture
def kb(tmp_path, monkeypatch):
    col = tmp_path / "demo"
    col.mkdir()
    monkeypatch.setattr(kt, "_knowledge_root", lambda: tmp_path)
    kt._CACHE.clear()
    return col


H = {"Authorization": "Bearer t"}


async def test_upload_search_and_delete(dashboard_token, client, kb):
    body = "# Tarifas" + chr(10) + chr(10) + "## Consulta" + chr(10) + "La consulta general cuesta quince mil pesos." + chr(10)
    res = await client.post("/api/knowledge-files/demo", files={"file": ("Tarifas 2026.md", body.encode(), "text/markdown")}, headers=H)
    assert res.status_code == 200 and res.json()["name"] == "tarifas-2026.md"
    assert "quince mil" in await kt.search_knowledge("consulta general", collection="demo")  # no restart

    # same name again: the first one is never replaced
    again = await client.post("/api/knowledge-files/demo", files={"file": ("Tarifas 2026.md", b"otro contenido distinto", "text/markdown")}, headers=H)
    assert again.json()["name"] == "tarifas-2026-2.md"
    assert "quince mil" in (kb / "tarifas-2026.md").read_text(encoding="utf-8")

    assert (await client.delete("/api/knowledge-files/demo/tarifas-2026-2.md", headers=H)).status_code == 200
    assert not (kb / "tarifas-2026-2.md").exists()
    assert (await client.delete("/api/knowledge-files/demo/tarifas-2026-2.md", headers=H)).status_code == 404


async def test_upload_rejects_unknown_collection_empty_and_oversized(dashboard_token, client, kb):
    assert (await client.post("/api/knowledge-files/nope", files={"file": ("a.md", b"x", "text/markdown")}, headers=H)).status_code == 404
    assert (await client.post("/api/knowledge-files/demo", files={"file": ("a.md", b"   ", "text/markdown")}, headers=H)).status_code == 422
    big = b"a" * (20 * 1024 * 1024 + 10)
    assert (await client.post("/api/knowledge-files/demo", files={"file": ("big.md", big, "text/markdown")}, headers=H)).status_code == 413
    assert list(kb.iterdir()) == []


async def test_delete_cannot_leave_the_collection(dashboard_token, client, kb):
    (kb.parent / "secret.md").write_text("TOP SECRET", encoding="utf-8")
    await client.delete("/api/knowledge-files/demo/..%2Fsecret.md", headers=H)
    assert (kb.parent / "secret.md").exists()


async def test_create_collection_then_use_it(dashboard_token, client, kb):
    res = await client.post("/api/knowledge-collections", json={"name": "Ventas Q1"}, headers=H)
    assert res.status_code == 200 and res.json()["collection"] == "ventas-q1"
    assert (kb.parent / "ventas-q1").is_dir()

    listing = (await client.get("/api/knowledge-files", headers=H)).json()
    assert {"collection": "ventas-q1", "files": []} in listing

    await client.post("/api/knowledge-files/ventas-q1", files={"file": ("lista.md", b"# Lista\n\n## Precio\nel plan gold cuesta cien", "text/markdown")}, headers=H)
    assert "plan gold" in await kt.search_knowledge("plan gold", collection="ventas-q1")

    assert (await client.post("/api/knowledge-collections", json={"name": "ventas-q1"}, headers=H)).status_code == 409
    for bad in ("../x", "a", "con/barra", ""):
        assert (await client.post("/api/knowledge-collections", json={"name": bad}, headers=H)).status_code == 400


async def test_unknown_collection_error_lists_the_available_ones(dashboard_token, kb):
    out = await kt.search_knowledge("algo", collection="no-existe")
    assert "not found" in out and "'demo'" in out
