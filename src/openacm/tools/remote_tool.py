"""
Remote Control Tool — allows the AI to manage remote desktop sessions.

Provides tools for:
- Starting/checking remote control sessions
- Opening a tunnel for external access (pyngrok)
- Getting connection URLs for mobile access
"""

import os
import platform
import asyncio
import socket
import webbrowser
from typing import Literal

from openacm.tools.base import tool

# Global tunnel reference
_ngrok_tunnel = None


@tool(
    name="remote_control",
    description=(
        "MANDATORY: You MUST run this tool with action='start' if the user says 'Inicia control remoto', "
        "'share screen', 'control my PC', or wants to use their phone/gym to control the desktop natively. "
        "DO NOT SUGGEST Windows Remote Desktop or Anydesk. This tool generates the ngrok tunnel automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Action to perform: "
                    "'start' - Start remote session (opens host page, creates tunnel), "
                    "'stop' - Stop remote session (closes tunnel), "
                    "'status' - Check if session is active, "
                    "'url' - Get the mobile access URL"
                ),
                "enum": ["start", "stop", "status", "url"],
            },
            "use_tunnel": {
                "type": "boolean",
                "description": "Whether to create an ngrok tunnel for external access (outside local network). Default true.",
                "default": True,
            },
        },
        "required": ["action"],
    },
    risk_level="high",
    category="general",
)
async def remote_control(
    action: Literal["start", "stop", "status", "url"] = "start",
    use_tunnel: bool = True,
    _brain=None,
    **kwargs,
) -> str:
    """
    Manage OpenACM remote desktop control session for mobile access.
    
    If the user asks for 'control remoto' or to connect to their PC via phone, ALWAYS run this tool with action='start'.
    """
    global _ngrok_tunnel

    # Determine local server port
    port = 47821
    if _brain and hasattr(_brain, "config") and _brain.config:
        port = getattr(_brain.config.web, "port", 47821)

    # Get dashboard token
    token = os.environ.get("DASHBOARD_TOKEN", "")

    if action == "start":
        return await _start_session(port, token, use_tunnel)
    elif action == "stop":
        return await _stop_session()
    elif action == "status":
        return await _get_status(port, token)
    elif action == "url":
        return await _get_url(port, token)
    else:
        return f"Unknown action: {action}. Use: start, stop, status, url"


async def _start_session(port: int, token: str, use_tunnel: bool, auto_open: bool = True) -> str:
    """Start a remote control session."""
    global _ngrok_tunnel

    results = []

    # 1. Open the host page in the default browser (only if requested by AI, not by the API to avoid loop)
    host_url = f"http://localhost:{port}/remote/host?token={token}"
    if auto_open:
        try:
            await asyncio.to_thread(webbrowser.open, host_url)
            results.append("✅ Host page opened in browser.")
        except Exception as e:
            results.append(f"⚠️ Could not auto-open browser: {e}")
            results.append(f"   Open manually: {host_url}")

    # 2. Get local IP
    local_ip = _get_local_ip()
    local_url = f"http://{local_ip}:{port}/remote?token={token}"
    results.append(f"\n📱 **Local URL (same WiFi):**\n`{local_url}`")

    # 3. Create tunnel if requested
    if use_tunnel:
        try:
            from pyngrok import ngrok, conf
            
            # Check if ngrok authtoken is set
            ngrok_token = os.environ.get("NGROK_AUTHTOKEN", "")
            if ngrok_token:
                conf.get_default().auth_token = ngrok_token
                
            # Close existing tunnel if any
            if _ngrok_tunnel:
                try:
                    ngrok.disconnect(_ngrok_tunnel.public_url)
                except Exception:
                    pass
            
            _ngrok_tunnel = await asyncio.to_thread(
                ngrok.connect, port, "http",
                bind_tls=True,
            )
            tunnel_url = _ngrok_tunnel.public_url
            mobile_url = f"{tunnel_url}/remote?token={token}"
            results.append(f"\n🌐 **URL Pública (funciona desde cualquier lugar):**\n`{mobile_url}`")
            results.append("\n_Nota: Si usas ngrok sin cuenta, deberás darle al botón 'Visit Site' la primera vez que abras el enlace._")
        except Exception as e:
            results.append(f"\n⚠️ Error al crear túnel (¿quizás límite de ngrok?): {e}")
            results.append("Puedes usar la URL Local si estás en el mismo WiFi o configurar tu NGROK_AUTHTOKEN.")

    results.append("\n**Instructions:**")
    results.append("1. On the PC browser, click 'Iniciar Captura' and select your screen")
    results.append("2. On your phone, open the URL above")
    results.append("3. You can now see and control your PC from your phone!")

    return "\n".join(results)


async def _stop_session() -> str:
    """Stop the remote control session."""
    global _ngrok_tunnel

    if _ngrok_tunnel:
        try:
            from pyngrok import ngrok
            await asyncio.to_thread(ngrok.disconnect, _ngrok_tunnel.public_url)
            _ngrok_tunnel = None
            return "✅ Sesión remota detenida. Túnel cerrado."
        except Exception as e:
            _ngrok_tunnel = None
            return f"⚠️ Error al cerrar túnel: {e}."
    return "ℹ️ No hay túnel activo. Las páginas locales siguen disponibles."


async def _get_status(port: int, token: str) -> str:
    """Check remote session status."""
    global _ngrok_tunnel

    import httpx
    results = ["**Remote Control Status:**"]

    # Check API status
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://localhost:{port}/api/remote/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                host = "🟢 Connected" if data.get("host_connected") else "🔴 Not connected"
                clients = data.get("clients_connected", 0)
                results.append(f"- Host: {host}")
                results.append(f"- Mobile clients: {clients}")
            else:
                results.append("- API: unavailable")
    except Exception:
        results.append("- API: unavailable (server not running?)")

    # Tunnel
    global _ngrok_tunnel
    if _ngrok_tunnel:
        results.append(f"- Tunnel: 🟢 Active ({_ngrok_tunnel.public_url})")
    else:
        results.append("- Tunnel: 🔴 Not active")

    return "\n".join(results)


async def _get_url(port: int, token: str) -> str:
    """Get the access URLs."""
    global _ngrok_tunnel

    local_ip = _get_local_ip()
    local_url = f"http://{local_ip}:{port}/remote?token={token}"
    result = f"📱 **URL Local (mismo WiFi):**\n`{local_url}`"

    if _ngrok_tunnel:
        mobile_url = f"{_ngrok_tunnel.public_url}/remote?token={token}"
        result += f"\n\n🌐 **URL Pública (desde cualquier lugar):**\n`{mobile_url}`"

    return result


def _get_local_ip() -> str:
    """Get the local network IP address."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"
