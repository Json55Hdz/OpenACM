"""
LG WebOS TV driver — controls LG TVs via local WebSocket API.
First connection requires accepting the pairing prompt on the TV screen.
Client key is saved automatically for future connections.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any

import structlog

from openacm.tools.iot.base import BaseDriver, DeviceInfo

log = structlog.get_logger()

_KEYS_PATH = Path("data") / "lgtv_keys.json"


def _load_keys() -> dict:
    try:
        if _KEYS_PATH.exists():
            return json.loads(_KEYS_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_key(ip: str, client_key: str):
    keys = _load_keys()
    keys[ip] = client_key
    _KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEYS_PATH.write_text(json.dumps(keys, indent=2))


async def _connect(ip: str, timeout: float = 10.0):
    """Connect to LG TV and return client. Handles pairing automatically."""
    try:
        from aiowebostv import WebOsClient
    except ImportError:
        raise ImportError("aiowebostv not installed. Run: pip install aiowebostv")

    keys = _load_keys()
    client_key = keys.get(ip)

    client = WebOsClient(ip, client_key=client_key)
    try:
        await asyncio.wait_for(client.connect(), timeout=timeout)
        # Save new key if pairing succeeded
        if client.client_key and client.client_key != client_key:
            _save_key(ip, client.client_key)
    except asyncio.TimeoutError:
        raise TimeoutError(f"Could not connect to LG TV at {ip} (timeout {timeout}s). Is the TV on?")
    return client


class LGTVDriver(BaseDriver):

    async def turn_on(self, device: DeviceInfo, **kwargs) -> dict:
        # LG TVs can only wake via Wake-on-LAN when off
        mac = device.meta.get("mac", "")
        if mac:
            try:
                from wakeonlan import send_magic_packet
                send_magic_packet(mac)
                return {"success": True, "action": "wol_sent", "mac": mac}
            except ImportError:
                pass
        return {"success": False, "error": "TV wake requires MAC address. Set meta.mac or use iot_control with action=wol."}

    async def turn_off(self, device: DeviceInfo) -> dict:
        try:
            client = await _connect(device.ip)
            await client.power_off()
            await client.disconnect()
            return {"success": True, "action": "off"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_status(self, device: DeviceInfo) -> dict:
        try:
            client = await _connect(device.ip, timeout=5.0)
            info = {
                "on": True,
                "app": client.current_app_id,
                "volume": client.volume,
                "muted": client.muted,
                "channel": getattr(client, "current_channel", None),
                "inputs": list((client.inputs or {}).keys()),
            }
            await client.disconnect()
            device.state = info
            return {"success": True, **info}
        except Exception as e:
            return {"success": False, "error": str(e), "on": False}

    async def send_command(self, device: DeviceInfo, command: str, params: dict) -> dict:
        """
        Supported commands:
          volume_up, volume_down, mute, unmute
          channel_up, channel_down, set_channel(number)
          set_volume(level 0-100)
          launch_app(app_id)  — e.g. 'netflix', 'youtube', 'spotify'
          set_input(input_id) — e.g. 'HDMI_1', 'HDMI_2'
          send_key(key)       — e.g. 'ENTER', 'BACK', 'HOME', 'UP', 'DOWN', 'LEFT', 'RIGHT'
          toast(message)      — show notification on screen
          play, pause, stop, rewind, fast_forward
        """
        try:
            client = await _connect(device.ip)
            result = {"success": True, "command": command}

            cmd = command.lower().replace("-", "_")

            if cmd == "volume_up":
                await client.volume_up()
            elif cmd == "volume_down":
                await client.volume_down()
            elif cmd == "mute":
                await client.set_mute(True)
            elif cmd == "unmute":
                await client.set_mute(False)
            elif cmd == "set_volume":
                await client.set_volume(int(params.get("level", 50)))
            elif cmd == "channel_up":
                await client.channel_up()
            elif cmd == "channel_down":
                await client.channel_down()
            elif cmd == "set_channel":
                await client.set_channel(params.get("number"))
            elif cmd == "launch_app":
                await client.launch_app(params.get("app_id", ""))
            elif cmd == "set_input":
                await client.set_input(params.get("input_id", ""))
            elif cmd == "send_key":
                await client.send_button(params.get("key", "ENTER"))
            elif cmd == "toast":
                await client.send_message(params.get("message", "Hello from OpenACM"))
            elif cmd == "play":
                await client.play()
            elif cmd == "pause":
                await client.pause()
            elif cmd == "stop":
                await client.stop()
            elif cmd == "rewind":
                await client.rewind()
            elif cmd == "fast_forward":
                await client.fast_forward()
            else:
                result = {"success": False, "error": f"Unknown command: {command}"}

            await client.disconnect()
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}
