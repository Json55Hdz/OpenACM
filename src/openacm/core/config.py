"""
Configuration system for OpenACM.

Loads config from YAML + environment variables + .env file,
validated with Pydantic models.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv


# ─── Config Models ───────────────────────────────────────────


class AssistantConfig(BaseModel):
    """Assistant personality and behavior."""

    name: str = "ACM"
    system_prompt: str = "You are ACM, a helpful AI assistant."
    max_context_messages: int = 50
    max_tool_iterations: int = 20  # Aumentado para tareas complejas con múltiples tools
    response_timeout: int = 120


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    default_provider: str = "ollama"
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    timeout: float = 0  # seconds to wait for any LLM response; 0 = no timeout


class SecurityConfig(BaseModel):
    """Security policies."""

    execution_mode: str = "confirmation"  # confirmation | auto | yolo
    whitelisted_commands: list[str] = Field(default_factory=list)
    blocked_patterns: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=list)
    max_command_timeout: int = 120  # seconds; 0 = no limit. Default 2 min prevents hung UAC/sudo dialogs
    max_output_length: int = 50000


class WebConfig(BaseModel):
    """Web dashboard configuration."""

    host: str = "127.0.0.1"
    port: int = 47821
    auth_enabled: bool = True


class DiscordConfig(BaseModel):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    command_prefix: str = "!"
    respond_to_mentions: bool = True
    respond_to_dms: bool = True
    allowed_guilds: list[str] = Field(default_factory=list)


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "http://localhost:3001"
    rate_limit_per_minute: int = 20


class ChannelsConfig(BaseModel):
    """All channels configuration."""

    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)


class StorageConfig(BaseModel):
    """Storage configuration."""

    database_path: str = "data/openacm.db"
    workspace_path: str = "workspace"  # default save location for AI-generated files
    log_conversations: bool = True
    log_tool_executions: bool = True


class LocalRouterConfig(BaseModel):
    """Local intent router configuration."""

    enabled: bool = True
    observation_mode: bool = False  # False = fast-path active; True = classify only, no execution
    confidence_threshold: float = 0.88


class AppConfig(BaseModel):
    """Root application configuration."""

    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    local_router: LocalRouterConfig = Field(default_factory=LocalRouterConfig)


# ─── Config Loading ──────────────────────────────────────────


def _find_project_root() -> Path:
    """Find the project root by looking for pyproject.toml."""
    current = Path.cwd()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


def _resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ${ENV_VAR} references in config values."""
    if isinstance(data, str):
        if data.startswith("${") and data.endswith("}"):
            env_key = data[2:-1]
            return os.environ.get(env_key, "")
        return data
    elif isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    return data


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """
    Load configuration from YAML file + environment variables.

    Priority: env vars > .env file > YAML config > defaults
    """
    root = _find_project_root()

    # Load .env file
    env_file = root / "config" / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    # Load YAML config
    if config_path is None:
        config_path = root / "config" / "default.yaml"
    else:
        config_path = Path(config_path)

    data = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    # Resolve environment variables in values
    data = _resolve_env_vars(data)

    # Map YAML structure to config models
    # The YAML uses "A" for assistant config
    config_data = {}

    if "A" in data:
        config_data["assistant"] = data["A"]
    if "llm" in data:
        config_data["llm"] = data["llm"]
    if "security" in data:
        config_data["security"] = data["security"]
    if "web" in data:
        config_data["web"] = data["web"]
    if "channels" in data:
        channels_data = data["channels"]
        # Inject tokens from env
        if "discord" in channels_data:
            if not channels_data["discord"].get("token"):
                # SECURITY: POR DISEÑO - Carga segura de API keys desde variables de entorno
                channels_data["discord"]["token"] = os.environ.get("DISCORD_TOKEN", "")
        if "telegram" in channels_data:
            if not channels_data["telegram"].get("token"):
                # SECURITY: POR DISEÑO - Carga segura de API keys desde variables de entorno
                channels_data["telegram"]["token"] = os.environ.get("TELEGRAM_TOKEN", "")
        config_data["channels"] = channels_data
    if "storage" in data:
        config_data["storage"] = data["storage"]
    if "local_router" in data:
        config_data["local_router"] = data["local_router"]

    # Make paths absolute relative to project root
    config = AppConfig(**config_data)
    if not Path(config.storage.database_path).is_absolute():
        config.storage.database_path = str(root / config.storage.database_path)
    if not Path(config.storage.workspace_path).is_absolute():
        config.storage.workspace_path = str(root / config.storage.workspace_path)

    # Auto-enable Telegram if token is available from env but channel is not enabled yet
    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    if telegram_token and ":" in telegram_token and not config.channels.telegram.enabled:
        config.channels.telegram.token = telegram_token
        config.channels.telegram.enabled = True

    # Auto-inject CLI providers for any detected binary not already in config.
    # This means the user only needs to install the CLI — no YAML editing required.
    _auto_detect_cli_providers(config)

    return config


def _auto_detect_cli_providers(config: "AppConfig") -> None:
    """Detect installed CLI binaries and inject them as providers if not already configured."""
    import shutil

    # Known CLI presets: provider_id -> config dict
    _CLI_PRESETS: dict[str, dict] = {
        "cli_claude": {
            "type": "cli",
            "binary": "claude",
            "args": ["--print"],
            "default_model": "claude",
            "timeout": 300,
        },
        "cli_gemini": {
            "type": "cli",
            "binary": "gemini",
            "args": ["--yolo", "-p"],
            "default_model": "gemini",
            "timeout": 300,
        },
        "cli_opencode": {
            "type": "cli",
            "binary": "opencode",
            "args": ["run", "--format", "json"],
            "input_mode": "arg",      # message passed as positional arg, not stdin
            "output_format": "jsonl", # parse JSON event stream
            "default_model": "opencode",
            "timeout": 300,
        },
    }

    for provider_id, preset in _CLI_PRESETS.items():
        # Skip if explicitly configured by the user (allows overriding args/timeout)
        if provider_id in config.llm.providers:
            continue
        # Auto-add only if binary is on PATH
        if shutil.which(preset["binary"]):
            config.llm.providers[provider_id] = preset
