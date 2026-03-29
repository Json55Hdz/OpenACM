"""
IoT Device Registry — in-memory store with JSON persistence.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

import structlog

from openacm.tools.iot.base import DeviceInfo

log = structlog.get_logger()

_REGISTRY_PATH = Path("data") / "iot_devices.json"


class DeviceRegistry:
    def __init__(self):
        self._devices: dict[str, DeviceInfo] = {}
        self._load()

    def _load(self):
        try:
            if _REGISTRY_PATH.exists():
                data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
                for d in data:
                    dev = DeviceInfo.from_dict(d)
                    self._devices[dev.id] = dev
                log.info("IoT registry loaded", count=len(self._devices))
        except Exception as e:
            log.warning("IoT registry load failed", error=str(e))

    def save(self):
        try:
            _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = [d.to_dict() for d in self._devices.values()]
            _REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning("IoT registry save failed", error=str(e))

    def upsert(self, device: DeviceInfo):
        self._devices[device.id] = device
        self.save()

    def get(self, device_id: str) -> DeviceInfo | None:
        # Try exact match first, then prefix/name match
        if device_id in self._devices:
            return self._devices[device_id]
        # fuzzy: by name (case-insensitive) or partial id
        q = device_id.lower()
        for dev in self._devices.values():
            if q in dev.name.lower() or q in dev.id.lower() or q == dev.ip:
                return dev
        return None

    def list(self, device_type: str | None = None, driver: str | None = None) -> list[DeviceInfo]:
        devs = list(self._devices.values())
        if device_type:
            devs = [d for d in devs if d.device_type == device_type]
        if driver:
            devs = [d for d in devs if d.driver == driver]
        return devs

    def remove(self, device_id: str):
        self._devices.pop(device_id, None)
        self.save()

    def __len__(self):
        return len(self._devices)


# Singleton
_registry: DeviceRegistry | None = None

def get_registry() -> DeviceRegistry:
    global _registry
    if _registry is None:
        _registry = DeviceRegistry()
    return _registry
