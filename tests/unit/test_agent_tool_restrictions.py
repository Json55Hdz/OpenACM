"""Customer-facing agents: allowed_tools is enforced at execution, files are limited to assets."""
import json
from unittest.mock import AsyncMock, MagicMock

from openacm.core.agent_runner import AgentRunner, _AgentToolRegistry
from openacm.tools.file_ops import send_file_to_chat


def _schema(*names):
    return [{"type": "function", "function": {"name": n}} for n in names]


class TestAllowedToolsEnforcement:
    async def test_disallowed_tool_is_not_executed(self):
        base = MagicMock()
        base.tools = {"send_file_to_chat": object(), "run_command": object()}
        base.execute = AsyncMock(return_value="ok")
        reg = _AgentToolRegistry(base, _schema("send_file_to_chat"), {})

        assert set(reg.tools) == {"send_file_to_chat"}
        assert "not allowed" in await reg.execute("run_command", {"command": "id"})
        base.execute.assert_not_awaited()

        assert await reg.execute("send_file_to_chat", {"path": "x"}) == "ok"

    async def test_unfiltered_registry_keeps_all_tools(self):
        base = MagicMock()
        base.tools = {"a": object(), "b": object()}
        reg = _AgentToolRegistry(base, None, {})
        assert set(reg.tools) == {"a", "b"}

    def test_malformed_policy_fails_closed(self):
        runner = AgentRunner(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        runner.tool_registry.get_tools_schema.return_value = _schema("run_command")
        assert runner._get_tools("[not json") == []

    def test_json_policy_filters_schema(self):
        runner = AgentRunner(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        runner.tool_registry.get_tools_schema.return_value = _schema("run_command", "send_file_to_chat")
        got = runner._get_tools(json.dumps(["send_file_to_chat"]))
        assert [t["function"]["name"] for t in got] == ["send_file_to_chat"]


class TestSendFileToChatAgentChannels:
    """Agent channels get a denylist (secrets/internal state), not an allowlist."""

    async def _send(self, path, channel="whatsapp_a2", **kw):
        return await send_file_to_chat(str(path), _channel_type=channel, **kw)

    async def test_blocks_config_database_and_keys(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        (tmp_path / "config").mkdir()
        (tmp_path / "data" / "vectordb").mkdir(parents=True)
        (tmp_path / "keys").mkdir()
        targets = [
            tmp_path / "config" / ".env",
            tmp_path / "config" / "local.yaml",
            tmp_path / "data" / "openacm.db",
            tmp_path / "data" / "resurrection_state.json",
            tmp_path / "data" / "vectordb" / "index.bin",
            tmp_path / "keys" / "server.pem",
            tmp_path / ".env",
        ]
        for t in targets:
            t.write_text("secret")
            out = await self._send(t)
            assert out.startswith("Error") and "ATTACHMENT:" not in out, t

    async def test_blocks_dotdot_escape_into_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        assets = tmp_path / "data" / "assets"
        assets.mkdir(parents=True)
        (tmp_path / "data" / "state.json").write_text("x")

        assert (await self._send(assets / ".." / "state.json")).startswith("Error")

    async def test_allows_screenshots_videos_and_assets(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        (tmp_path / "data" / "assets").mkdir(parents=True)
        (tmp_path / "data" / "media").mkdir(parents=True)
        (tmp_path / "workspace").mkdir()
        files = [
            tmp_path / "workspace" / "captura.png",
            tmp_path / "workspace" / "grabacion.mp4",
            tmp_path / "data" / "media" / "shot.png",
            tmp_path / "data" / "assets" / "Formato.pdf",
        ]
        for f in files:
            f.write_bytes(b"data")
            assert (await self._send(f)).startswith("ATTACHMENT:"), f

    async def test_display_name_is_embedded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        (tmp_path / "data" / "assets").mkdir(parents=True)
        f = tmp_path / "data" / "assets" / "Formato.pdf"
        f.write_bytes(b"%PDF")

        out = await self._send(f, display_name="Formato de recepcion")
        assert "__Formato_de_recepcion.pdf" in out

    async def test_owner_channels_are_not_restricted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENACM_PROJECT_ROOT", str(tmp_path))
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF")

        for channel in ("web", "telegram", "whatsapp", "console"):
            assert (await self._send(f, channel=channel)).startswith("ATTACHMENT:")
