import sys

import pytest

from openacm.plugins import installer
from openacm.plugins.installer import PluginInstallError, archive_url, parse_source

TEST_TOKEN = "test-dashboard-token"


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TEST_TOKEN)
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


class TestParseSource:
    @pytest.mark.parametrize("source", [
        "https://github.com/Json55Hdz/openacm-desktop-control",
        "https://github.com/Json55Hdz/openacm-desktop-control/",
        "https://github.com/Json55Hdz/openacm-desktop-control.git",
        "  https://github.com/Json55Hdz/openacm-desktop-control  ",
    ])
    def test_accepts_github_repo_urls(self, source):
        assert parse_source(source) == ("Json55Hdz", "openacm-desktop-control")

    @pytest.mark.parametrize("source", [
        "",
        None,
        "openacm-desktop-control",
        "http://github.com/a/b",
        "https://gitlab.com/a/b",
        "https://github.com.evil.com/a/b",
        "https://github.com/a",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/..",
        "https://github.com/a/b --index-url https://evil.example",
        "https://github.com/a/b\n--extra-index-url=https://evil.example",
        "https://github.com/-a/b",
        "https://user:pass@github.com/a/b",
        "git+https://github.com/a/b",
        "C:\\some\\local\\path",
        "https://github.com/a/b?x=1",
        "https://github.com/a/b#egg=x",
    ])
    def test_rejects_everything_else(self, source):
        with pytest.raises(PluginInstallError):
            parse_source(source)

    def test_archive_url_needs_no_git(self):
        assert archive_url("a", "b") == "https://github.com/a/b/archive/HEAD.zip"


class _FakeProc:
    def __init__(self, code=0, out=b"Installed 1 package"):
        self.returncode = code
        self._out = out

    async def communicate(self):
        return self._out, None


class TestInstall:
    async def test_runs_the_installer_on_this_interpreter(self, monkeypatch):
        seen = {}

        async def fake_exec(*cmd, **kwargs):
            seen["cmd"] = list(cmd)
            return _FakeProc()

        monkeypatch.setattr(installer.shutil, "which", lambda name: None)
        monkeypatch.setattr(installer.asyncio, "create_subprocess_exec", fake_exec)
        result = await installer.install_plugin("https://github.com/a/b")
        assert seen["cmd"] == [
            sys.executable, "-m", "pip", "install", "https://github.com/a/b/archive/HEAD.zip",
        ]
        assert result["source"] == "https://github.com/a/b"
        assert "Installed" in result["output"]

    async def test_prefers_uv_when_available(self, monkeypatch):
        seen = {}

        async def fake_exec(*cmd, **kwargs):
            seen["cmd"] = list(cmd)
            return _FakeProc()

        monkeypatch.setattr(installer.shutil, "which", lambda name: "/bin/uv")
        monkeypatch.setattr(installer.asyncio, "create_subprocess_exec", fake_exec)
        await installer.install_plugin("https://github.com/a/b")
        assert seen["cmd"][:5] == ["/bin/uv", "pip", "install", "--python", sys.executable]

    async def test_bad_source_never_starts_a_process(self, monkeypatch):
        async def fake_exec(*cmd, **kwargs):
            raise AssertionError("must not run")

        monkeypatch.setattr(installer.asyncio, "create_subprocess_exec", fake_exec)
        with pytest.raises(PluginInstallError):
            await installer.install_plugin("https://evil.example/a/b")

    async def test_failure_carries_the_installer_output(self, monkeypatch):
        async def fake_exec(*cmd, **kwargs):
            return _FakeProc(code=1, out=b"error: no pyproject.toml")

        monkeypatch.setattr(installer.asyncio, "create_subprocess_exec", fake_exec)
        with pytest.raises(PluginInstallError) as err:
            await installer.install_plugin("https://github.com/a/b")
        assert err.value.status == 500
        assert "no pyproject.toml" in err.value.output


class TestInstallApi:
    async def test_requires_auth(self, auth_headers, client):
        resp = await client.post("/api/plugins/install", json={"source": "https://github.com/a/b"})
        assert resp.status_code in (401, 403)

    async def test_rejects_non_github_source(self, auth_headers, client):
        resp = await client.post(
            "/api/plugins/install", json={"source": "https://evil.example/a/b"}, headers=auth_headers
        )
        assert resp.status_code == 400
        assert "GitHub" in resp.json()["detail"]

    async def test_installs_and_asks_for_restart(self, auth_headers, client, monkeypatch):
        async def fake_exec(*cmd, **kwargs):
            return _FakeProc()

        monkeypatch.setattr(installer.asyncio, "create_subprocess_exec", fake_exec)
        resp = await client.post(
            "/api/plugins/install", json={"source": "https://github.com/a/b"}, headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "Restart" in body["message"]
