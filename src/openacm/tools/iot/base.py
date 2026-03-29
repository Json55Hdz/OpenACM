"""
Base IoT device interface — all drivers implement this.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceInfo:
    id: str                        # unique: driver:ip or driver:mac
    name: str
    driver: str                    # "tuya", "lgtv", "miio", "manual"
    device_type: str               # "light", "cover", "tv", "vacuum", "switch", "sensor", "camera"
    ip: str
    model: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)  # driver-specific config (keys, tokens, etc.)
    reachable: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "driver": self.driver,
            "device_type": self.device_type,
            "ip": self.ip,
            "model": self.model,
            "state": self.state,
            "meta": self.meta,
            "reachable": self.reachable,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceInfo":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BaseDriver(ABC):
    """Every IoT driver must implement this interface."""

    @abstractmethod
    async def turn_on(self, device: DeviceInfo, **kwargs) -> dict:
        """Turn device on. kwargs: brightness(0-100), color_temp(2700-6500), color(r,g,b)"""

    @abstractmethod
    async def turn_off(self, device: DeviceInfo) -> dict:
        """Turn device off."""

    async def set_brightness(self, device: DeviceInfo, brightness: int) -> dict:
        return await self.turn_on(device, brightness=brightness)

    async def set_color(self, device: DeviceInfo, r: int, g: int, b: int) -> dict:
        return await self.turn_on(device, color=(r, g, b))

    async def set_color_temp(self, device: DeviceInfo, kelvin: int) -> dict:
        return await self.turn_on(device, color_temp=kelvin)

    async def open(self, device: DeviceInfo, position: int = 100) -> dict:
        """Open cover/curtain to position (0=closed, 100=fully open)."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support open()")

    async def close(self, device: DeviceInfo) -> dict:
        """Close cover/curtain."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support close()")

    async def stop(self, device: DeviceInfo) -> dict:
        """Stop cover/curtain movement."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support stop()")

    async def get_status(self, device: DeviceInfo) -> dict:
        """Return current device state dict."""
        raise NotImplementedError

    async def send_command(self, device: DeviceInfo, command: str, params: dict) -> dict:
        """Send arbitrary command — driver-specific."""
        raise NotImplementedError
