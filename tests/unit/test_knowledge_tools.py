"""Tests for the knowledge-base search tools."""

import pytest

from openacm.tools import knowledge_tools as kt


@pytest.fixture
def kb(tmp_path, monkeypatch):
    col = tmp_path / "demo"
    col.mkdir()
    (col / "01-bog-eps.md").write_text(
        "# Bog EPS\n\n## Registros\n\n"
        "### Ecografía de abdomen total — Bogotá · EPS · Imágenes _(fila 7)_\n"
        "- **Código Bukeala**: 881201\n- **Clínica Norte › Volante**: No requiere\n\n"
        "### Resonancia de rodilla — Bogotá · EPS · Imágenes _(fila 8)_\n- **Código Bukeala**: 883101\n",
        encoding="utf-8",
    )
    (col / "02-cali-mp.md").write_text(
        "# Cali MP\n\n## Registros\n\n"
        "### Ecografía de abdomen total — Cali · MP · Imágenes _(fila 3)_\n- **Código Bukeala**: 881201\n- Requiere volante\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kt, "_knowledge_root", lambda: tmp_path)
    kt._CACHE.clear()
    return col


async def test_search_ignores_accents_and_case(kb):
    out = await kt.search_knowledge("ECOGRAFIA ABDOMEN", collection="demo")
    assert "Bogotá" in out and "Cali" in out


async def test_filtro_restricts_by_city_and_plan(kb):
    out = await kt.search_knowledge("ecografia abdomen", filtro="Cali MP", collection="demo")
    assert "Cali" in out and "Bogotá" not in out


async def test_search_by_code(kb):
    out = await kt.search_knowledge("883101", collection="demo")
    assert "Resonancia de rodilla" in out and "Ecografía" not in out


async def test_output_fits_llm_budget_and_lists_omitted_records(tmp_path, monkeypatch):
    """brain_loop cuts tool results over 6000 chars in the middle; the tool must stay under it
    and say which records did not fit instead of letting the middle vanish silently."""
    col = tmp_path / "big"
    col.mkdir()
    body = "".join(f"### Radiografia de torax variante {i} — Bogotá · EPS _(fila {i})_\n- obs: " + "x" * 1800 + "\n\n" for i in range(8))
    (col / "01-big.md").write_text("# Big\n\n## Registros\n\n" + body, encoding="utf-8")
    monkeypatch.setattr(kt, "_knowledge_root", lambda: tmp_path)
    kt._CACHE.clear()

    out = await kt.search_knowledge("radiografia torax", collection="big", max_results=8)

    assert len(out) <= 5800
    assert "variante" in out and "not shown" in out.lower()
    assert "chars omitted" not in out


async def test_exact_phrase_outranks_partial_word_matches(tmp_path, monkeypatch):
    """Looking up one unit by name must put the record that contains that exact name first,
    not records that only share generic words like 'centro medico'."""
    col = tmp_path / "units"
    col.mkdir()
    (col / "01-units.md").write_text(
        "# Units\n\n"
        "### Lista A\n- Centro Medico Norte\n- Centro Medico Sur\n- Centro Medico Este\n- Centro Medico Oeste\n\n"
        "### Lista B\n- Centro Medico Kennedy Bomberos\n- Otro lugar\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kt, "_knowledge_root", lambda: tmp_path)
    kt._CACHE.clear()

    out = await kt.search_knowledge("Centro Medico Kennedy Bomberos", collection="units")

    assert out.index("Lista B") < out.index("Lista A")


async def test_no_results_message(kb):
    out = await kt.search_knowledge("tomografia craneo", collection="demo")
    assert out.startswith("No results")


async def test_unknown_collection_and_path_traversal(kb):
    assert "not found" in await kt.search_knowledge("x", collection="nope")
    assert "not found" in await kt.search_knowledge("x", collection="../demo")
    assert "invalid" in (await kt.read_knowledge_file("../secret.md", collection="demo"))


async def test_read_knowledge_file_pages(kb):
    out = await kt.read_knowledge_file("02-cali-mp.md", collection="demo")
    assert "Cali · MP" in out and "[end of file]" in out
