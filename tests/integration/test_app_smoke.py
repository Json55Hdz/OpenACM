"""
Smoke tests for the FastAPI app.

These catch NameErrors, missing imports, and broken route handlers
that unit tests can't detect because Python only resolves names at runtime.

Strategy: call create_app(), hit every route domain with at least one request,
assert we get a real HTTP response (not a 500 from a NameError/ImportError).
"""
import pytest
from fastapi.testclient import TestClient

from openacm.web.server import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Routes that work without a running brain/db (return 503 or data) ─────────

def test_app_creates_without_error():
    """create_app() itself must not raise."""
    app = create_app()
    assert app is not None


def test_ping(client):
    r = client.get("/api/ping")
    assert r.status_code != 500, f"Ping 500: {r.text}"


def test_auth_check_get(client):
    r = client.get("/api/auth/check")
    assert r.status_code != 500, f"Auth check 500: {r.text}"


def test_stats(client):
    r = client.get("/api/stats")
    assert r.status_code != 500, f"Stats 500: {r.text}"


def test_config(client):
    r = client.get("/api/config")
    assert r.status_code != 500, f"Config 500: {r.text}"


def test_config_status(client):
    r = client.get("/api/config/status")
    assert r.status_code != 500, f"Config status 500: {r.text}"


def test_config_providers(client):
    r = client.get("/api/config/providers")
    assert r.status_code != 500, f"Providers 500: {r.text}"


def test_config_custom_providers(client):
    r = client.get("/api/config/custom_providers")
    assert r.status_code != 500, f"Custom providers 500: {r.text}"


def test_config_model(client):
    r = client.get("/api/config/model")
    assert r.status_code != 500, f"Model 500: {r.text}"


def test_config_local_router(client):
    r = client.get("/api/config/local_router")
    assert r.status_code != 500, f"Local router config 500: {r.text}"


def test_config_resurrection_paths(client):
    r = client.get("/api/config/resurrection_paths")
    assert r.status_code != 500, f"Resurrection paths 500: {r.text}"


def test_system_info(client):
    r = client.get("/api/system/info")
    assert r.status_code != 500, f"System info 500: {r.text}"


def test_tools(client):
    r = client.get("/api/tools")
    assert r.status_code != 500, f"Tools 500: {r.text}"


def test_skills(client):
    r = client.get("/api/skills")
    assert r.status_code != 500, f"Skills 500: {r.text}"


def test_agents(client):
    r = client.get("/api/agents")
    assert r.status_code != 500, f"Agents 500: {r.text}"


def test_swarms(client):
    r = client.get("/api/swarms")
    assert r.status_code != 500, f"Swarms 500: {r.text}"


def test_cron_jobs(client):
    r = client.get("/api/cron/jobs")
    assert r.status_code != 500, f"Cron jobs 500: {r.text}"


def test_cron_status(client):
    r = client.get("/api/cron/status")
    assert r.status_code != 500, f"Cron status 500: {r.text}"


def test_mcp_servers(client):
    r = client.get("/api/mcp/servers")
    assert r.status_code != 500, f"MCP servers 500: {r.text}"


def test_routines(client):
    r = client.get("/api/routines")
    assert r.status_code != 500, f"Routines 500: {r.text}"


def test_activity_stats(client):
    r = client.get("/api/activity/stats")
    assert r.status_code != 500, f"Activity stats 500: {r.text}"


def test_content_queue(client):
    r = client.get("/api/content/queue")
    assert r.status_code != 500, f"Content queue 500: {r.text}"


def test_conversations(client):
    r = client.get("/api/conversations")
    assert r.status_code != 500, f"Conversations 500: {r.text}"


def test_spa_root(client):
    r = client.get("/")
    assert r.status_code != 500, f"SPA root 500: {r.text}"


def test_spa_unknown_path(client):
    r = client.get("/some/frontend/route")
    assert r.status_code != 500, f"SPA catch-all 500: {r.text}"
