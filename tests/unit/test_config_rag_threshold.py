"""Setting the RAG threshold from the dashboard must persist (it raised NameError before)."""
from types import SimpleNamespace

import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from openacm.web.routers import config as config_router
from openacm.web.state import _state


async def test_the_threshold_is_saved_to_local_yaml(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("openacm.core.config._find_project_root", lambda: tmp_path)
    monkeypatch.setattr(_state, "config", SimpleNamespace(assistant=SimpleNamespace(rag_relevance_threshold=0.5)))
    app = FastAPI()
    config_router.register_routes(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/config/rag_threshold", json={"threshold": 0.7})
    assert resp.status_code == 200 and resp.json() == {"threshold": 0.7}
    saved = yaml.safe_load((tmp_path / "config" / "local.yaml").read_text(encoding="utf-8"))
    assert saved["A"]["rag_relevance_threshold"] == 0.7
