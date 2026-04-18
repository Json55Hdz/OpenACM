"""
Tests for openacm.core.config

Covers:
  - Pydantic model defaults
  - YAML loading and deep merge
  - Environment variable interpolation
  - _find_project_root helper
"""

import os
import textwrap
from pathlib import Path

import pytest
import yaml

from openacm.constants import DEFAULT_WEB_HOST, DEFAULT_WEB_PORT, DEFAULT_WHATSAPP_BRIDGE_URL
from openacm.core.config import (
    AppConfig,
    AssistantConfig,
    WebConfig,
    WhatsAppConfig,
    LocalRouterConfig,
    _deep_merge,
    _resolve_env_vars,
    _find_project_root,
)


# ---------------------------------------------------------------------------
# Pydantic model defaults
# ---------------------------------------------------------------------------

class TestAssistantConfigDefaults:
    def test_default_name(self):
        cfg = AssistantConfig()
        assert cfg.name == "ACM"

    def test_onboarding_not_completed_by_default(self):
        cfg = AssistantConfig()
        assert cfg.onboarding_completed is False

    def test_max_context_messages_positive(self):
        cfg = AssistantConfig()
        assert cfg.max_context_messages > 0

    def test_response_timeout_positive(self):
        cfg = AssistantConfig()
        assert cfg.response_timeout > 0


class TestWebConfigDefaults:
    def test_default_host_matches_constant(self):
        cfg = WebConfig()
        assert cfg.host == DEFAULT_WEB_HOST

    def test_default_port_matches_constant(self):
        cfg = WebConfig()
        assert cfg.port == DEFAULT_WEB_PORT

    def test_auth_enabled_by_default(self):
        cfg = WebConfig()
        assert cfg.auth_enabled is True


class TestWhatsAppConfigDefaults:
    def test_bridge_url_matches_constant(self):
        cfg = WhatsAppConfig()
        assert cfg.bridge_url == DEFAULT_WHATSAPP_BRIDGE_URL


class TestLocalRouterConfigDefaults:
    def test_enabled_by_default(self):
        cfg = LocalRouterConfig()
        assert cfg.enabled is True

    def test_confidence_threshold_in_range(self):
        cfg = LocalRouterConfig()
        assert 0.0 < cfg.confidence_threshold < 1.0


class TestAppConfigDefaults:
    def test_app_config_instantiates_with_no_args(self):
        cfg = AppConfig()
        assert cfg.assistant is not None
        assert cfg.llm is not None
        assert cfg.web is not None
        assert cfg.security is not None
        assert cfg.channels is not None

    def test_resurrection_paths_empty_by_default(self):
        cfg = AppConfig()
        assert cfg.resurrection_paths == []


# ---------------------------------------------------------------------------
# _resolve_env_vars
# ---------------------------------------------------------------------------

class TestResolveEnvVars:
    def test_resolves_existing_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_KEY", "hello")
        result = _resolve_env_vars("${MY_TEST_KEY}")
        assert result == "hello"

    def test_missing_env_var_returns_empty_string(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        result = _resolve_env_vars("${NONEXISTENT_VAR_XYZ}")
        assert result == ""

    def test_plain_string_untouched(self):
        assert _resolve_env_vars("hello world") == "hello world"

    def test_resolves_inside_dict(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "secret")
        result = _resolve_env_vars({"key": "${API_KEY}", "other": "plain"})
        assert result == {"key": "secret", "other": "plain"}

    def test_resolves_inside_list(self, monkeypatch):
        monkeypatch.setenv("VAL", "42")
        result = _resolve_env_vars(["${VAL}", "static"])
        assert result == ["42", "static"]

    def test_non_string_values_pass_through(self):
        assert _resolve_env_vars(123) == 123
        assert _resolve_env_vars(True) is True
        assert _resolve_env_vars(None) is None


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_override_replaces_scalar(self):
        result = _deep_merge({"a": 1}, {"a": 2})
        assert result["a"] == 2

    def test_base_key_preserved_if_not_overridden(self):
        result = _deep_merge({"a": 1, "b": 2}, {"a": 99})
        assert result["b"] == 2

    def test_nested_dicts_merged_recursively(self):
        base = {"llm": {"provider": "openai", "model": "gpt-4"}}
        override = {"llm": {"model": "gpt-4o"}}
        result = _deep_merge(base, override)
        assert result["llm"]["provider"] == "openai"
        assert result["llm"]["model"] == "gpt-4o"

    def test_override_non_dict_replaces_dict(self):
        result = _deep_merge({"a": {"nested": 1}}, {"a": "replaced"})
        assert result["a"] == "replaced"

    def test_empty_override_returns_base_copy(self):
        base = {"x": 1}
        result = _deep_merge(base, {})
        assert result == base
        assert result is not base  # must be a copy

    def test_empty_base_returns_override(self):
        result = _deep_merge({}, {"y": 2})
        assert result == {"y": 2}


# ---------------------------------------------------------------------------
# _find_project_root
# ---------------------------------------------------------------------------

class TestFindProjectRoot:
    def test_finds_pyproject_toml(self):
        root = _find_project_root()
        assert (root / "pyproject.toml").exists()

    def test_returns_path_object(self):
        root = _find_project_root()
        assert isinstance(root, Path)


# ---------------------------------------------------------------------------
# load_config with tmp YAML files
# ---------------------------------------------------------------------------

class TestLoadConfig:
    """
    load_config also reads config/local.yaml relative to _find_project_root().
    We patch _find_project_root to point at tmp_path so the real local.yaml
    (which has personal data) is never loaded during tests.
    """

    def _load_isolated(self, monkeypatch, tmp_path, cfg_file):
        """Helper: patch project root → tmp_path and load from cfg_file."""
        import openacm.core.config as cfg_module
        monkeypatch.setattr(cfg_module, "_find_project_root", lambda: tmp_path)
        from openacm.core.config import load_config
        return load_config(config_path=cfg_file)

    def test_loads_minimal_yaml(self, monkeypatch, tmp_path):
        cfg_file = tmp_path / "default.yaml"
        cfg_file.write_text(textwrap.dedent("""\
            assistant:
              name: TestBot
        """))
        cfg = self._load_isolated(monkeypatch, tmp_path, cfg_file)
        assert cfg.assistant.name == "TestBot"

    def test_defaults_applied_for_missing_keys(self, monkeypatch, tmp_path):
        cfg_file = tmp_path / "default.yaml"
        cfg_file.write_text("assistant:\n  name: Minimal\n")
        cfg = self._load_isolated(monkeypatch, tmp_path, cfg_file)
        assert cfg.web.port == DEFAULT_WEB_PORT

    def test_empty_yaml_gives_full_defaults(self, monkeypatch, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")
        cfg = self._load_isolated(monkeypatch, tmp_path, cfg_file)
        assert isinstance(cfg, AppConfig)

    def test_nonexistent_yaml_gives_full_defaults(self, monkeypatch, tmp_path):
        import openacm.core.config as cfg_module
        monkeypatch.setattr(cfg_module, "_find_project_root", lambda: tmp_path)
        from openacm.core.config import load_config
        cfg = load_config(config_path=tmp_path / "does_not_exist.yaml")
        assert isinstance(cfg, AppConfig)

    def test_local_yaml_overrides_default(self, monkeypatch, tmp_path):
        (tmp_path / "config").mkdir()
        default_file = tmp_path / "default.yaml"
        default_file.write_text("assistant:\n  name: DefaultBot\n")
        local_file = tmp_path / "config" / "local.yaml"
        local_file.write_text("A:\n  name: LocalBot\n")

        import openacm.core.config as cfg_module
        monkeypatch.setattr(cfg_module, "_find_project_root", lambda: tmp_path)
        from openacm.core.config import load_config
        cfg = load_config(config_path=default_file)
        assert cfg.assistant.name == "LocalBot"
