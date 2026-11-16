from __future__ import annotations

import asyncio
import datetime
import html
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
from openacm.utils.text import mask_secrets
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
        # Every secret anywhere in the config (channels, WhatsApp app secret, providers...) is masked
        return mask_secrets(_state.config.model_dump())

    @app.get("/api/config/model")
    async def get_current_model():
        """Get current LLM model."""
        if not _state.brain:
            return {"model": "unknown"}
        return {
            "model": _state.brain.llm_router.current_model,
            "provider": _state.brain.llm_router._current_provider,
        }

    @app.get("/api/llm/routes")
    async def get_model_routes():
        """Which model handles each kind of work (global, per workspace, per chat)."""
        if not _state.brain or not _state.config:
            return {"roles": [], "global": {}, "workspaces": {}, "chats": {}, "providers": []}
        router = _state.brain.llm_router
        status = _get_provider_status()
        providers = [
            {"id": pid, "default_model": cfg.get("default_model", ""), "configured": bool(status.get(pid, True))}
            for pid, cfg in _state.config.llm.providers.items()
        ]
        return {
            **router.routes.snapshot(),
            "providers": providers,
            "main": {"provider": router._current_provider, "model": router.current_model},
        }

    @app.get("/api/channel-access")
    async def get_channel_access():
        """Who may use the assistant from Telegram / Discord / WhatsApp, and with which tools."""
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        return _state.brain.channel_access.snapshot()

    @app.put("/api/channel-access")
    async def set_channel_access(request: Request):
        from openacm.core.channel_access import AccessError

        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        payload = await request.json()
        registry = getattr(_state.brain, "tool_registry", None)
        try:
            await _state.brain.channel_access.update(
                payload, known_tools=set(registry.tools) if registry else None
            )
        except AccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, **_state.brain.channel_access.snapshot()}

    @app.put("/api/llm/fallbacks")
    async def set_model_fallbacks(request: Request):
        """Body: {fallbacks: [{provider, model}, ...]} in the order they should be tried."""
        from openacm.core.model_routes import RouteError

        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        data = await request.json()
        try:
            saved = await _state.brain.llm_router.routes.set_fallbacks(
                data.get("fallbacks") if isinstance(data, dict) else None
            )
        except RouteError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "fallbacks": saved}

    @app.get("/api/llm/monitor")
    async def llm_monitor(days: int = 7):
        """Cost, speed and errors per model, recent errors and which providers are cooling down."""
        if not _state.database or not _state.brain:
            return {"models": [], "totals": {}, "errors_by_provider": [], "errors": [], "health": {}}
        report = await _state.database.get_llm_monitor(days)
        report["errors"] = await _state.database.get_llm_errors(days, 50)
        report["health"] = _state.brain.llm_router.provider_health()
        return report

    @app.put("/api/llm/routes")
    async def set_model_routes(request: Request):
        """Set or clear routes. Body: {scope: global|workspace|chat, id, routes: {role: {provider, model} | null}}."""
        from openacm.core.model_routes import RouteError

        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Invalid body")
        try:
            saved = await _state.brain.llm_router.routes.set_routes(
                str(data.get("scope", "")), str(data.get("id", "")), data.get("routes") or {}
            )
        except RouteError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "routes": saved}

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
            <p>{html.escape(error)}</p>
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
            <p>Check the OpenACM server logs for details.</p>
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
        whatsapp_configured = _is_real_key("WHATSAPP_ACCESS_TOKEN") or _is_real_key("WHATSAPP_BRIDGE_URL")
        return {"providers": providers, "telegram_configured": telegram_configured, "whatsapp_configured": whatsapp_configured}

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

        # Restart WhatsApp channel if its config was updated
        _whatsapp_keys = {
            "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET",
            "WHATSAPP_MODE", "WHATSAPP_BRIDGE_URL",
        }
        if _whatsapp_keys & set(updated):
            from openacm.channels.whatsapp_cloud_channel import WhatsAppCloudChannel
            from openacm.channels.whatsapp_channel import WhatsAppChannel

            # Stop and remove existing WhatsApp channels
            existing_wa = [
                ch for ch in _state.channels
                if isinstance(ch, (WhatsAppCloudChannel, WhatsAppChannel))
            ]
            for ch in existing_wa:
                asyncio.create_task(ch.stop())
                _state.channels.remove(ch)

            # Update in-memory config
            if _state.config:
                wa = _state.config.channels.whatsapp
                wa.access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "") or wa.access_token
                wa.phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "") or wa.phone_number_id
                wa.verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "") or wa.verify_token
                wa.app_secret = os.environ.get("WHATSAPP_APP_SECRET", "") or wa.app_secret
                wa.mode = os.environ.get("WHATSAPP_MODE", "") or wa.mode
                wa.bridge_url = os.environ.get("WHATSAPP_BRIDGE_URL", "") or wa.bridge_url
                if not wa.enabled:
                    if wa.mode == "cloud_api" and wa.access_token and wa.phone_number_id:
                        wa.enabled = True
                    elif wa.mode == "bridge" and wa.bridge_url:
                        wa.enabled = True

            # Create and start the new channel
            if _state.config and _state.brain and _state.event_bus and _state.config.channels.whatsapp.enabled:
                wa = _state.config.channels.whatsapp
                if wa.mode == "bridge":
                    ch = WhatsAppChannel(wa, _state.brain, _state.event_bus)
                else:
                    ch = WhatsAppCloudChannel(wa, _state.brain, _state.event_bus)
                _state.channels.append(ch)
                asyncio.create_task(ch.start())
                log.info("WhatsApp channel (re)created", mode=wa.mode)

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

    @app.get("/api/config/client-profile")
    async def get_client_profile():
        """Return the client profile (active flag + allowed pages).
        Always returns a valid object — active=False means no restrictions."""
        if not _state.config:
            return {"active": False, "name": "", "allowed_pages": []}
        p = _state.config.client_profile
        log.info("client-profile requested", active=p.active, pages=p.allowed_pages)
        return {"active": p.active, "name": p.name, "allowed_pages": p.allowed_pages}

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
            if 0.75 <= val <= 1.0:  # lower and the router would act on weak guesses
                _state.brain.local_router.confidence_threshold = val
        return {
            "status": "ok",
            "enabled": not _state.brain.local_router.observation_mode,
            "confidence_threshold": _state.brain.local_router.confidence_threshold,
        }

    @app.get("/api/config/local_router/learned")
    async def get_learned():
        """What the router has learned on its own (phrases and replayable actions)."""
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        return _state.brain.local_router.list_learned()

    @app.delete("/api/config/local_router/learned/actions/{index}")
    async def forget_learned_action(index: int):
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        if not await _state.brain.local_router.forget_action(index):
            raise HTTPException(status_code=404, detail="No such learned action")
        return {"ok": True}

    @app.post("/api/config/local_router/learned/forget_example")
    async def forget_learned_example(request: Request):
        if not _state.brain:
            raise HTTPException(status_code=503, detail="Brain not available")
        data = await request.json()
        if not await _state.brain.local_router.forget_example(str(data.get("intent", "")), str(data.get("phrase", ""))):
            raise HTTPException(status_code=404, detail="No such learned phrase")
        return {"ok": True}

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
        from openacm.core.config import _find_project_root
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
            return {"compact_ratio": 0.60, "compact_keep_recent": 6}
        return {
            "compact_ratio": getattr(_state.config.assistant, "compact_ratio", 0.60),
            "compact_keep_recent": getattr(_state.config.assistant, "compact_keep_recent", 6),
        }

    @app.post("/api/config/compaction")
    async def set_compaction_config(request: Request):
        """Update conversation auto-compaction settings and persist to config file."""
        if not _state.config:
            raise HTTPException(status_code=503, detail="Config not available")
        data = await request.json()

        if "compact_ratio" in data:
            val = float(data["compact_ratio"])
            _state.config.assistant.compact_ratio = max(0.20, min(0.95, val))
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
        cfg_data["A"]["compact_ratio"] = _state.config.assistant.compact_ratio
        cfg_data["A"]["compact_keep_recent"] = _state.config.assistant.compact_keep_recent
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg_data, f, default_flow_style=False, allow_unicode=True)

        return {
            "compact_ratio": _state.config.assistant.compact_ratio,
            "compact_keep_recent": _state.config.assistant.compact_keep_recent,
        }

    @app.post("/api/config/verbose_channels")
    async def set_verbose_channels(request: Request):
        """Set whether external channels receive tool execution logs."""
        data = await request.json()
        enabled = bool(data.get("enabled", True))
        value = "true" if enabled else "false"
        os.environ["OPENACM_VERBOSE_CHANNELS"] = value
        try:  # persist, otherwise the setting is lost on restart and tool logs come back
            from dotenv import set_key
            from openacm.core.config import _find_project_root

            env_file = _find_project_root() / "config" / ".env"
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.touch(exist_ok=True)
            set_key(str(env_file), "OPENACM_VERBOSE_CHANNELS", value)
        except Exception as e:
            log.warning("Could not persist verbose_channels", error=str(e))
        return {"status": "ok", "enabled": enabled}

    @app.get("/api/config/verbose_channels")
    async def get_verbose_channels():
        return {"enabled": os.environ.get("OPENACM_VERBOSE_CHANNELS", "true").lower() == "true"}

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

