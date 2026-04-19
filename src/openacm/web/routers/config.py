from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import structlog
import yaml
from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    Request, UploadFile, File, Form, HTTPException,
)
from fastapi.responses import HTMLResponse, FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles


from openacm.web.state import _state
from openacm.web.broadcast import broadcast_event, _safe_ws_send, _broadcast_to_terminal
from openacm.web.server import (
    _load_custom_providers, _save_custom_providers, _apply_custom_providers,
    _make_provider_id, _get_custom_providers_path,
)
from openacm.constants import DEFAULT_OLLAMA_BASE_URL, DEFAULT_WEB_PORT

import httpx

log = structlog.get_logger()

_NO_KEY_PROVIDERS = {"ollama"}


def _is_cli_provider_id(provider_id: str) -> bool:
    if not _state.config:
        return False
    return _state.config.llm.providers.get(provider_id, {}).get("type") == "cli"


def _is_real_key(env_var: str) -> bool:
    val = os.environ.get(env_var, "").strip()
    if not val:
        return False
    lower = val.lower()
    if lower.startswith("your-") or lower.startswith("your_"):
        return False
    if "here" in lower and ("-" in lower or "_" in lower):
        return False
    if lower in ("change-me", "change-me-please", "changeme", "placeholder"):
        return False
    return True


def _get_provider_status() -> dict[str, bool]:
    if not _state.config:
        return {}
    result: dict[str, bool] = {}
    for provider_id in _state.config.llm.providers:
        if provider_id in _NO_KEY_PROVIDERS or _is_cli_provider_id(provider_id):
            result[provider_id] = True
        elif provider_id in _state.custom_provider_ids:
            result[provider_id] = True
        else:
            env_var = f"{provider_id.upper()}_API_KEY"
            result[provider_id] = _is_real_key(env_var)
    return result


def _find_env_path() -> Path:
    from openacm.core.config import _find_project_root
    return _find_project_root() / "config" / ".env"


def register_routes(app: FastAPI) -> None:
    # ─── API: Config ──────────────────────────────────────────

    @app.get("/api/config")
    async def get_config():
        """Get current configuration (sanitized)."""
        if not _state.config:
            return {}
        config_dict = _state.config.model_dump()
        # Remove sensitive data
        for provider in config_dict.get("llm", {}).get("providers", {}).values():
            if "api_key" in provider:
                provider["api_key"] = "***"
        if "token" in config_dict.get("channels", {}).get("discord", {}):
            config_dict["channels"]["discord"]["token"] = (
                "***" if config_dict["channels"]["discord"]["token"] else ""
            )
        if "token" in config_dict.get("channels", {}).get("telegram", {}):
            config_dict["channels"]["telegram"]["token"] = (
                "***" if config_dict["channels"]["telegram"]["token"] else ""
            )
        return config_dict

    @app.get("/api/config/model")
    async def get_current_model():
        """Get current LLM model."""
        if not _state.brain:
            return {"model": "unknown"}
        return {
            "model": _state.brain.llm_router.current_model,
            "provider": _state.brain.llm_router._current_provider,
        }

    @app.get("/api/config/model-params")
    async def get_model_params(provider: str = "", model: str = ""):
        """Get stored params for a provider+model (or current if omitted)."""
        if not _state.brain:
            return {}
        if provider and model:
            provider_cfg = _state.config.llm.providers.get(provider, {}) if _state.config else {}
            return provider_cfg.get("model_params", {}).get(model, {})
        # Current model
        return _state.brain.llm_router._get_model_params()

    @app.patch("/api/config/model-params")
    async def set_model_params(request: Request):
        """Save params for a provider+model."""
        if not _state.brain or not _state.config:
            raise HTTPException(503, "Not ready")
        data = await request.json()
        provider = data.get("provider", "")
        model = data.get("model", "")
        if not provider or not model:
            raise HTTPException(400, "provider and model required")
        params = {k: data[k] for k in ("temperature", "max_tokens", "top_p") if k in data}
        _state.brain.llm_router.set_model_params(provider, model, params)
        # Persist to DB
        if _state.database:
            all_mp = {p: cfg.get("model_params", {}) for p, cfg in _state.config.llm.providers.items() if cfg.get("model_params")}
            await _state.database.set_setting("llm.model_params", json.dumps(all_mp))
        return {"ok": True}

    @app.get("/api/config/status")
    async def get_config_status():
        """Check if essential configuration is missing (e.g. LLM API Key)."""
        if not _state.config or not _state.brain:
            return {"needs_setup": True}
        # Check if ANY provider has a real key configured (derived dynamically from config)
        provider_statuses = _get_provider_status()
        # Ollama alone doesn't count as "configured" — but API-key providers and CLI providers do
        keyed_configured = any(
            ok for pid, ok in provider_statuses.items() if pid not in _NO_KEY_PROVIDERS
        )
        if not keyed_configured:
            return {"needs_setup": True, "provider": _state.brain.llm_router._current_provider}
        return {"needs_setup": False}

    # Pending OAuth2 flow state (flow object keyed by state string)
    _google_oauth_flows: dict[str, Any] = {}

    @app.get("/api/config/google")
    async def get_google_status():
        """Check if Google credentials and OAuth token exist."""
        from openacm.core.config import _find_project_root
        root = _find_project_root()
        creds_path = root / "config" / "google_credentials.json"
        token_path = root / "config" / "google_token.json"
        return {
            "credentials_exist": creds_path.exists(),
            "token_exist": token_path.exists(),
        }

    @app.post("/api/config/google")
    async def save_google_credentials(request: Request):
        """Save Google OAuth2 credentials JSON file."""
        from openacm.core.config import _find_project_root

        data = await request.json()
        credentials_json = data.get("credentials_json", "")
        if not credentials_json:
            raise HTTPException(status_code=400, detail="credentials_json required")

        try:
            parsed = json.loads(credentials_json) if isinstance(credentials_json, str) else credentials_json
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

        root = _find_project_root()
        creds_path = root / "config" / "google_credentials.json"
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        with open(creds_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2)

        return {"status": "ok"}

    @app.delete("/api/config/google")
    async def delete_google_credentials():
        """Remove Google credentials and token (disconnect)."""
        from openacm.core.config import _find_project_root
        root = _find_project_root()
        for fname in ("google_credentials.json", "google_token.json"):
            p = root / "config" / fname
            if p.exists():
                p.unlink()
        # Clear cached credentials in the tools module too
        try:
            import openacm.tools.google_services as _gs
            _gs._credentials_cache = None
        except Exception:
            pass
        return {"status": "ok"}

    @app.post("/api/config/google/start_auth")
    async def start_google_auth(request: Request):
        """
        Begin the OAuth2 authorization flow.
        Returns the Google authorization URL to open in a browser tab.
        The redirect_uri points back to this server's /api/config/google/callback endpoint.
        """
        from openacm.core.config import _find_project_root
        SCOPES = [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError:
            raise HTTPException(status_code=500, detail="google-auth-oauthlib not installed. Run: pip install -e .")

        root = _find_project_root()
        creds_path = root / "config" / "google_credentials.json"
        if not creds_path.exists():
            raise HTTPException(status_code=400, detail="Upload google_credentials.json first")

        port = _state.config.web.port if _state.config else DEFAULT_WEB_PORT
        redirect_uri = f"http://localhost:{port}/api/config/google/callback"

        flow = Flow.from_client_secrets_file(
            str(creds_path),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        _google_oauth_flows[state] = flow
        return {"url": auth_url, "state": state}

    @app.get("/api/config/google/callback")
    async def google_oauth_callback(request: Request):
        """
        Receives the OAuth2 callback from Google after the user authorizes.
        Exchanges the authorization code for tokens and saves them.
        Returns a friendly HTML page so the user can close the tab.
        """
        from openacm.core.config import _find_project_root
        state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        error = request.query_params.get("error", "")

        if error:
            return HTMLResponse(f"""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#f87171">
            <h2>❌ Google Authorization Failed</h2>
            <p>{error}</p>
            <p>You can close this tab.</p>
            </body></html>""")

        flow = _google_oauth_flows.pop(state, None)
        if not flow:
            return HTMLResponse("""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#f87171">
            <h2>❌ Invalid or expired authorization session</h2>
            <p>Please try again from the OpenACM settings.</p>
            <p>You can close this tab.</p>
            </body></html>""")

        try:
            flow.fetch_token(code=code)
            creds = flow.credentials

            root = _find_project_root()
            token_path = root / "config" / "google_token.json"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

            # Invalidate the in-memory credentials cache so next call reloads
            try:
                import openacm.tools.google_services as _gs
                _gs._credentials_cache = None
            except Exception:
                pass

            log.info("Google OAuth2 token saved successfully")
        except Exception as e:
            log.error("Google OAuth2 token exchange failed", error=str(e))
            return HTMLResponse(f"""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#f87171">
            <h2>❌ Token Exchange Failed</h2>
            <p>{e}</p>
            <p>You can close this tab.</p>
            </body></html>""")

        return HTMLResponse("""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#34d399">
        <h2>✅ Google Connected Successfully!</h2>
        <p style="color:#94a3b8">Gmail, Calendar, Drive and YouTube are now available.</p>
        <p style="color:#64748b">You can close this tab and return to OpenACM.</p>
        <script>setTimeout(()=>window.close(),3000)</script>
        </body></html>""")

    @app.get("/api/config/providers")
    async def get_provider_status():
        """Return boolean status for each LLM provider (no keys exposed)."""
        providers = _get_provider_status()
        telegram_configured = _is_real_key("TELEGRAM_TOKEN")
        stitch_configured = _is_real_key("STITCH_API_KEY")
        return {"providers": providers, "telegram_configured": telegram_configured, "stitch_configured": stitch_configured}

    @app.post("/api/config/setup")
    async def post_config_setup(request: Request):
        """Update API keys in .env and memory."""
        data = await request.json()
        from dotenv import set_key

        env_path = _find_env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure the file exists (set_key requires it)
        if not env_path.exists():
            env_path.touch()

        updated = []
        for key, value in data.items():
            if value and isinstance(value, str):
                safe_key = key.upper()
                set_key(str(env_path), safe_key, value)
                os.environ[safe_key] = value
                updated.append(safe_key)

        # Restart Telegram bot if its token was updated
        if "TELEGRAM_TOKEN" in updated:
            from openacm.channels.telegram_channel import TelegramChannel

            new_token = os.environ.get("TELEGRAM_TOKEN", "")

            # Stop and remove ALL existing Telegram channel instances first
            # (prevents stale duplicates accumulating across wizard re-runs)
            existing = [ch for ch in _state.channels if isinstance(ch, TelegramChannel)]
            for ch in existing:
                asyncio.create_task(ch.stop())
                _state.channels.remove(ch)

            # Create a fresh channel with the new token
            if _state.config and _state.brain and _state.event_bus and new_token:
                _state.config.channels.telegram.enabled = True
                _state.config.channels.telegram.token = new_token
                ch = TelegramChannel(
                    _state.config.channels.telegram, _state.brain, _state.event_bus, _state.database
                )
                _state.channels.append(ch)
                asyncio.create_task(ch.start())
                log.info("Telegram bot (re)created with updated token")

        return {"status": "ok", "updated": updated}

    # ─── Custom Providers CRUD ────────────────────────────────

    @app.get("/api/config/custom_providers")
    async def get_custom_providers_list():
        """List user-defined custom OpenAI-compatible providers (api_key masked)."""
        providers = _load_custom_providers()
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "base_url": p["base_url"],
                "default_model": p.get("default_model", ""),
                "suggested_models": p.get("suggested_models", []),
                "has_key": bool(p.get("api_key", "")),
            }
            for p in providers
        ]

    @app.post("/api/config/custom_providers")
    async def add_custom_provider(request: Request):
        """Add a new custom OpenAI-compatible provider."""
        data = await request.json()
        name = (data.get("name") or "").strip()
        base_url = (data.get("base_url") or "").strip()
        if not name or not base_url:
            raise HTTPException(status_code=400, detail="name and base_url are required")

        providers = _load_custom_providers()
        pid = _make_provider_id(name, providers)
        provider = {
            "id": pid,
            "name": name,
            "base_url": base_url.rstrip("/"),
            "api_key": (data.get("api_key") or "").strip(),
            "default_model": (data.get("default_model") or "").strip(),
            "suggested_models": data.get("suggested_models") or [],
        }
        providers.append(provider)
        _save_custom_providers(providers)
        _apply_custom_providers([provider])
        log.info("Custom provider added", id=pid, name=name)
        return {"status": "ok", "id": pid}

    @app.put("/api/config/custom_providers/{provider_id}")
    async def update_custom_provider(provider_id: str, request: Request):
        """Update an existing custom provider."""
        data = await request.json()
        providers = _load_custom_providers()
        for i, p in enumerate(providers):
            if p["id"] == provider_id:
                if "name" in data:
                    p["name"] = data["name"].strip()
                if "base_url" in data:
                    p["base_url"] = data["base_url"].strip().rstrip("/")
                if data.get("api_key"):
                    p["api_key"] = data["api_key"].strip()
                if "default_model" in data:
                    p["default_model"] = data["default_model"].strip()
                if "suggested_models" in data:
                    p["suggested_models"] = data["suggested_models"]
                providers[i] = p
                _save_custom_providers(providers)
                _apply_custom_providers([p])
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="Provider not found")

    @app.delete("/api/config/custom_providers/{provider_id}")
    async def delete_custom_provider(provider_id: str):
        """Remove a custom provider."""
        providers = _load_custom_providers()
        new_providers = [p for p in providers if p["id"] != provider_id]
        if len(new_providers) == len(providers):
            raise HTTPException(status_code=404, detail="Provider not found")
        _save_custom_providers(new_providers)
        _state.custom_provider_ids.discard(provider_id)
        if _state.config and provider_id in _state.config.llm.providers:
            del _state.config.llm.providers[provider_id]
        env_key = f"{provider_id.upper()}_API_KEY"
        os.environ.pop(env_key, None)
        log.info("Custom provider deleted", id=provider_id)
        return {"status": "ok"}

    @app.get("/api/config/local_router")
    async def get_local_router_config():
        """Get LocalRouter configuration and live stats."""
        if not _state.brain:
            return {"enabled": False}
        stats = _state.brain.local_router.get_stats()
        return {
            "enabled": not _state.brain.local_router.observation_mode,
            "observation_mode": _state.brain.local_router.observation_mode,
            "confidence_threshold": _state.brain.local_router.confidence_threshold,
            **stats,
        }

    @app.post("/api/config/local_router")
    async def set_local_router_config(request: Request):
        """Update LocalRouter settings at runtime (no restart needed)."""
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        data = await request.json()
        if "enabled" in data:
            _state.brain.local_router.observation_mode = not bool(data["enabled"])
        if "confidence_threshold" in data:
            val = float(data["confidence_threshold"])
            if 0.5 <= val <= 1.0:
                _state.brain.local_router.confidence_threshold = val
        return {
            "status": "ok",
            "enabled": not _state.brain.local_router.observation_mode,
            "confidence_threshold": _state.brain.local_router.confidence_threshold,
        }

    # ─── Code Resurrection API ────────────────────────────────

    @app.get("/api/config/resurrection_paths")
    async def get_resurrection_paths():
        """Get current Code Resurrection paths and watcher status."""
        if not _state.config:
            return {"paths": [], "indexed_files": 0}
        paths = list(getattr(_state.config, "resurrection_paths", []))
        # Read progress from state file
        indexed_count = 0
        try:
            state_file = Path("data/resurrection_state.json")
            if state_file.exists():
                with open(state_file, "r") as f:
                    indexed_count = len(json.load(f))
        except Exception:
            pass
        return {"paths": paths, "indexed_files": indexed_count}

    @app.post("/api/config/resurrection_paths")
    async def add_resurrection_path_api(request: Request):
        """Add a path to Code Resurrection."""
        if not _state.config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()
        new_path = data.get("path", "").strip()
        if not new_path:
            raise HTTPException(status_code=400, detail="path is required")
        p = Path(new_path).resolve()
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=400, detail=f"Path does not exist or is not a directory: {new_path}")
        str_path = str(p)
        if str_path not in _state.config.resurrection_paths:
            _state.config.resurrection_paths.append(str_path)
            # Persist to YAML
            try:
                from openacm.core.config import _find_project_root
                config_file = _find_project_root() / "config" / "local.yaml"
                cfg_data = {}
                if config_file.exists():
                    with open(config_file, "r", encoding="utf-8") as f:
                        cfg_data = yaml.safe_load(f) or {}
                cfg_data["resurrection_paths"] = list(_state.config.resurrection_paths)
                config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(config_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)
            except Exception as e:
                log.warning("Failed to persist resurrection paths", error=str(e))
        return {"paths": list(_state.config.resurrection_paths)}

    @app.delete("/api/config/resurrection_paths")
    async def remove_resurrection_path_api(request: Request):
        """Remove a path from Code Resurrection."""
        if not _state.config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()
        rm_path = data.get("path", "").strip()
        if not rm_path:
            raise HTTPException(status_code=400, detail="path is required")
        _state.config.resurrection_paths = [p for p in _state.config.resurrection_paths if p != rm_path]
        # Persist to YAML
        try:
            from openacm.core.config import _find_project_root
            config_file = _find_project_root() / "config" / "local.yaml"
            cfg_data = {}
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg_data = yaml.safe_load(f) or {}
            cfg_data["resurrection_paths"] = list(_state.config.resurrection_paths)
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            log.warning("Failed to persist resurrection paths", error=str(e))
        return {"paths": list(_state.config.resurrection_paths)}

    @app.get("/api/config/rag_threshold")
    async def get_rag_threshold():
        """Get the current RAG relevance threshold."""
        if not _state.config:
            return {"threshold": 0.5}
        return {"threshold": getattr(_state.config.assistant, "rag_relevance_threshold", 0.5)}

    @app.post("/api/config/rag_threshold")
    async def set_rag_threshold(request: Request):
        """Set the RAG relevance threshold and persist to config.yaml."""
        if not _state.config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()
        threshold = float(data.get("threshold", 0.5))
        threshold = max(0.1, min(0.95, threshold))  # clamp to [0.1, 0.95]
        _state.config.assistant.rag_relevance_threshold = threshold
        # Persist to yaml
        root = _find_project_root()
        config_file = root / "config" / "local.yaml"
        cfg_data = {}
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f) or {}
        if "A" not in cfg_data:
            cfg_data["A"] = {}
        cfg_data["A"]["rag_relevance_threshold"] = threshold
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)
        return {"threshold": threshold}

    @app.get("/api/config/compaction")
    async def get_compaction_config():
        """Get conversation auto-compaction settings."""
        if not _state.config:
            return {"compact_threshold": 25, "compact_keep_recent": 6}
        return {
            "compact_threshold": getattr(_state.config.assistant, "compact_threshold", 25),
            "compact_keep_recent": getattr(_state.config.assistant, "compact_keep_recent", 6),
        }

    @app.post("/api/config/compaction")
    async def set_compaction_config(request: Request):
        """Update conversation auto-compaction settings and persist to config file."""
        if not _state.config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()

        if "compact_threshold" in data:
            val = int(data["compact_threshold"])
            _state.config.assistant.compact_threshold = max(5, min(200, val))
        if "compact_keep_recent" in data:
            val = int(data["compact_keep_recent"])
            _state.config.assistant.compact_keep_recent = max(2, min(20, val))

        # Persist to config file
        from openacm.core.config import _find_project_root
        root = _find_project_root()
        config_file = root / "config" / "local.yaml"
        cfg_data: dict = {}
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f) or {}
        if "A" not in cfg_data:
            cfg_data["A"] = {}
        cfg_data["A"]["compact_threshold"] = _state.config.assistant.compact_threshold
        cfg_data["A"]["compact_keep_recent"] = _state.config.assistant.compact_keep_recent
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)

        return {
            "compact_threshold": _state.config.assistant.compact_threshold,
            "compact_keep_recent": _state.config.assistant.compact_keep_recent,
        }

    @app.post("/api/config/verbose_channels")
    async def set_verbose_channels(request: Request):
        """Set whether external channels receive tool execution logs."""
        data = await request.json()
        enabled = data.get("enabled", True)
        os.environ["OPENACM_VERBOSE_CHANNELS"] = "true" if enabled else "false"
        return {"status": "ok", "enabled": enabled}

    @app.get("/api/ollama/status")
    async def get_ollama_status():
        """Check if Ollama is running and return installed models."""
        import httpx
        base = DEFAULT_OLLAMA_BASE_URL
        if _state.config:
            base = _state.config.llm.providers.get("ollama", {}).get("base_url", base)
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {"running": True, "models": models}
        except Exception:
            pass
        return {"running": False, "models": []}

    @app.get("/api/cli/status")
    async def get_cli_status(binary: str = "claude"):
        """Check if a CLI binary is installed and on PATH."""
        import shutil
        available = shutil.which(binary) is not None
        return {"binary": binary, "available": available}

    _DEBUG_MODE_FILE = Path("data/debug_mode")

    def _read_debug_mode() -> bool:
        try:
            return _DEBUG_MODE_FILE.read_text().strip() == "true"
        except Exception:
            return False

    def _write_debug_mode(enabled: bool):
        _DEBUG_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEBUG_MODE_FILE.write_text("true" if enabled else "false")

    def _apply_debug_mode(enabled: bool):
        import logging as _logging
        level = _logging.DEBUG if enabled else _logging.INFO
        root = _logging.getLogger()
        root.setLevel(level)
        # Must also update all handlers — they filter independently
        for handler in root.handlers:
            handler.setLevel(level)
        for name in ("openacm", "uvicorn", "fastapi"):
            _logging.getLogger(name).setLevel(level)

    @app.get("/api/config/debug_mode")
    async def get_debug_mode():
        """Return current debug mode state."""
        return {"enabled": _read_debug_mode()}

    @app.post("/api/config/debug_mode")
    async def set_debug_mode(request: Request):
        """Toggle debug mode — enables DEBUG-level logging when ON."""
        data = await request.json()
        enabled = bool(data.get("enabled", False))
        _write_debug_mode(enabled)
        _apply_debug_mode(enabled)
        log.info("Debug mode changed", enabled=enabled, log_level="DEBUG" if enabled else "INFO")
        return {"status": "ok", "enabled": enabled}

