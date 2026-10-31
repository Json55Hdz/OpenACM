"""The 'Tool Logs' switch must reach the server and survive a restart."""
import os

import pytest


@pytest.fixture
def dashboard_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "t")
    return "t"


async def test_verbose_channels_setting_is_applied_and_persisted(dashboard_token, client, tmp_path, monkeypatch):
    headers = {"Authorization": f"Bearer {dashboard_token}"}
    from dotenv import dotenv_values

    import openacm.core.config as cfg

    monkeypatch.setattr(cfg, "_find_project_root", lambda: tmp_path)
    monkeypatch.setenv("OPENACM_VERBOSE_CHANNELS", "true")

    res = await client.post("/api/config/verbose_channels", json={"enabled": False}, headers=headers)
    assert res.status_code == 200
    assert os.environ["OPENACM_VERBOSE_CHANNELS"] == "false"
    assert dotenv_values(tmp_path / "config" / ".env")["OPENACM_VERBOSE_CHANNELS"] == "false"

    got = await client.get("/api/config/verbose_channels", headers=headers)
    assert got.json() == {"enabled": False}
