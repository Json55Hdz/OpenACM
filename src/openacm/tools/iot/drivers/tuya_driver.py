"""
Tuya local driver — controls Tuya lights, switches, curtains/blinds via LAN.
Requires device keys (one-time extraction via iot_tuya_setup tool).
"""
from __future__ import annotations
import asyncio
from typing import Any

import structlog

from openacm.tools.iot.base import BaseDriver, DeviceInfo

log = structlog.get_logger()


def _guess_type_from_dps(dps: dict) -> str:
    """Guess device type from available data points."""
    keys = {str(k) for k in dps.keys()}
    # Curtains/covers typically have dp 1 with values open/close/stop
    if "1" in keys:
        val = str(dps.get("1", ""))
        if val in ("open", "close", "stop", "true", "false"):
            if val in ("open", "close", "stop"):
                return "cover"
    # Lights have dp 20 (on/off), 22 (brightness), 23 (color_temp), 24 (color)
    if "20" in keys or "21" in keys:
        return "light"
    # Simple switch: dp 1 = True/False
    if "1" in keys:
        return "switch"
    return "switch"


def _make_device(ip: str, dev_id: str, key: str, version: str = "3.3") -> Any:
    """Create appropriate tinytuya device object."""
    import tinytuya
    d = tinytuya.OutletDevice(dev_id=dev_id, address=ip, local_key=key, version=float(version))
    d.set_socketRetryLimit(1)
    d.set_socketTimeout(4)
    return d


async def _run_sync(fn, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


class TuyaDriver(BaseDriver):

    async def _get_device(self, device: DeviceInfo):
        meta = device.meta
        dev_id = meta.get("dev_id") or meta.get("id", "")
        key = meta.get("key", "")
        version = str(meta.get("version", "3.3"))
        if not dev_id:
            raise ValueError(f"Tuya device {device.id} has no dev_id. Run iot_scan() to rediscover it.")
        # key is optional — firmware 3.1/3.2 may work without it.
        # For 3.3+ without key, tinytuya will raise an auth error that surfaces as a useful message.
        return _make_device(device.ip, dev_id, key, version)

    async def turn_on(self, device: DeviceInfo, brightness: int | None = None,
                      color_temp: int | None = None, color: tuple | None = None, **kwargs) -> dict:
        try:
            import tinytuya
            d = await self._get_device(device)

            def _do():
                if device.device_type == "light":
                    # Standard Tuya light DPS (v2 schema): dp20=on, dp22=brightness, dp23=color_temp, dp24=color
                    d.set_value(20, True)
                    if brightness is not None:
                        # Tuya brightness: 10-1000
                        bri = max(10, min(1000, int(brightness * 10)))
                        d.set_value(22, bri)
                    if color_temp is not None:
                        # Tuya color temp: 0-1000 (0=warm, 1000=cool)
                        ct = max(0, min(1000, int((color_temp - 2700) / (6500 - 2700) * 1000)))
                        d.set_value(23, ct)
                    if color is not None:
                        r, g, b = color
                        import colorsys
                        h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                        hsv_str = f"{int(h*360):04x}{int(s*1000):04x}{int(v*1000):04x}"
                        d.set_value(24, hsv_str)
                else:
                    d.set_value(1, True)
                return {"success": True, "action": "on"}

            return await _run_sync(_do)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def turn_off(self, device: DeviceInfo) -> dict:
        try:
            d = await self._get_device(device)
            dp = 20 if device.device_type == "light" else 1

            def _do():
                d.set_value(dp, False)
                return {"success": True, "action": "off"}

            return await _run_sync(_do)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def open(self, device: DeviceInfo, position: int = 100) -> dict:
        """Open curtain/blind. position 0-100."""
        try:
            d = await self._get_device(device)

            def _do():
                # Most Tuya covers: dp1=open/close/stop, dp2=position
                if position == 100:
                    d.set_value(1, "open")
                elif position == 0:
                    d.set_value(1, "close")
                else:
                    # Try position dp (dp2 on most covers)
                    try:
                        d.set_value(2, position)
                    except Exception:
                        d.set_value(1, "open")
                return {"success": True, "action": "open", "position": position}

            return await _run_sync(_do)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self, device: DeviceInfo) -> dict:
        return await self.open(device, position=0)

    async def stop(self, device: DeviceInfo) -> dict:
        try:
            d = await self._get_device(device)
            def _do():
                d.set_value(1, "stop")
                return {"success": True, "action": "stop"}
            return await _run_sync(_do)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_status(self, device: DeviceInfo) -> dict:
        try:
            d = await self._get_device(device)
            def _do():
                return d.status()
            status = await asyncio.wait_for(_run_sync(_do), timeout=6.0)
            dps = status.get("dps", {})
            # Update device state
            device.state = dps
            return {"success": True, "dps": dps}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_command(self, device: DeviceInfo, command: str, params: dict) -> dict:
        """Send raw DPS command: command='set_dp', params={'dp': 1, 'value': True}"""
        try:
            d = await self._get_device(device)
            dp = params.get("dp")
            value = params.get("value")
            if dp is None:
                return {"success": False, "error": "params must include 'dp' key"}
            def _do():
                d.set_value(int(dp), value)
                return {"success": True}
            return await _run_sync(_do)
        except Exception as e:
            return {"success": False, "error": str(e)}
