"""
Xiaomi miio driver — controls Xiaomi/Roborock devices via LAN.
Requires device token (one-time extraction).
"""
from __future__ import annotations
import asyncio
from typing import Any

import structlog

from openacm.tools.iot.base import BaseDriver, DeviceInfo

log = structlog.get_logger()


async def _run_sync(fn, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


class MiioDriver(BaseDriver):

    def _get_device(self, device: DeviceInfo):
        token = device.meta.get("token", "")
        if not token:
            raise ValueError(f"Xiaomi device {device.id} missing token. Use iot_miio_pair to add it.")
        model = device.model.lower()
        try:
            from miio import Device, RoborockVacuum, AirPurifier, Yeelight
            if any(x in model for x in ["vacuum", "robo", "sweep", "s4", "s5", "s6", "s7"]):
                return RoborockVacuum(device.ip, token)
            if any(x in model for x in ["air", "purif"]):
                return AirPurifier(device.ip, token)
            if any(x in model for x in ["yeelight", "light", "lamp"]):
                return Yeelight(device.ip, token)
            return Device(device.ip, token)
        except ImportError:
            raise ImportError("python-miio not installed. Run: pip install python-miio")

    async def turn_on(self, device: DeviceInfo, **kwargs) -> dict:
        try:
            d = self._get_device(device)
            await _run_sync(d.on)
            return {"success": True, "action": "on"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def turn_off(self, device: DeviceInfo) -> dict:
        try:
            d = self._get_device(device)
            await _run_sync(d.off)
            return {"success": True, "action": "off"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_status(self, device: DeviceInfo) -> dict:
        try:
            d = self._get_device(device)
            status = await asyncio.wait_for(_run_sync(d.status), timeout=8.0)
            state = {}
            if hasattr(status, "data"):
                state = status.data
            elif hasattr(status, "__dict__"):
                state = {k: v for k, v in status.__dict__.items() if not k.startswith("_")}
            device.state = state
            return {"success": True, "state": state}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_command(self, device: DeviceInfo, command: str, params: dict) -> dict:
        """
        Vacuum commands: start, stop, pause, dock, locate, clean_zone, goto
        General: send_raw(method, params)
        """
        try:
            d = self._get_device(device)
            cmd = command.lower()

            if cmd == "start":
                await _run_sync(d.start)
            elif cmd == "stop":
                await _run_sync(d.stop)
            elif cmd == "pause":
                await _run_sync(d.pause)
            elif cmd == "dock" or cmd == "charge":
                await _run_sync(d.home)
            elif cmd == "locate":
                await _run_sync(d.find)
            elif cmd == "clean_zone":
                zones = params.get("zones", [])
                repeats = params.get("repeats", 1)
                await _run_sync(d.zoned_clean, zones)
            elif cmd == "goto":
                x, y = params.get("x", 0), params.get("y", 0)
                await _run_sync(d.goto, x, y)
            elif cmd == "send_raw":
                method = params.get("method", "")
                raw_params = params.get("params", [])
                result = await _run_sync(d.send, method, raw_params)
                return {"success": True, "result": result}
            elif cmd == "fan_speed":
                speed = params.get("speed", 60)
                await _run_sync(d.set_fan_speed, speed)
            else:
                return {"success": False, "error": f"Unknown miio command: {command}"}

            return {"success": True, "command": command}
        except Exception as e:
            return {"success": False, "error": str(e)}
