"""
IoT Tools — AI interface for home automation.

Provides automatic device discovery and unified control for:
- Tuya devices (lights, switches, curtains, blinds)
- LG WebOS TVs
- Xiaomi/Roborock devices (vacuum, etc.)

Setup per driver:
- Tuya (no cloud required):
    1. iot_scan() — UDP broadcast finds device IPs + IDs
    2a. Firmware 3.1/3.2 — works immediately without a key
    2b. Firmware 3.3 — add keys via:
        • iot_tuya_import('devices.json') after running 'python -m tinytuya wizard'
        • iot_tuya_add(ip, dev_id, key, name) for individual devices
        • iot_tuya_setup(...) if you have a Tuya IoT Cloud subscription
- LG TV: auto-discovered; first iot_control triggers pairing prompt on screen
- Xiaomi: run iot_miio_pair(ip, token) per device
"""
import asyncio
import json
from pathlib import Path
from typing import Any

import structlog

from openacm.tools.base import tool
from openacm.tools.iot.registry import get_registry
from openacm.tools.iot.base import DeviceInfo
from openacm.tools.iot import discovery as _disc

log = structlog.get_logger()

# Driver singletons (lazy)
_drivers: dict[str, Any] = {}

def _get_driver(driver_name: str):
    if driver_name not in _drivers:
        if driver_name == "tuya":
            from openacm.tools.iot.drivers.tuya_driver import TuyaDriver
            _drivers["tuya"] = TuyaDriver()
        elif driver_name == "lgtv":
            from openacm.tools.iot.drivers.lgtv_driver import LGTVDriver
            _drivers["lgtv"] = LGTVDriver()
        elif driver_name == "miio":
            from openacm.tools.iot.drivers.miio_driver import MiioDriver
            _drivers["miio"] = MiioDriver()
        else:
            raise ValueError(f"Unknown driver: {driver_name}")
    return _drivers[driver_name]


def _tuya_guess_type(raw: dict) -> str:
    dps = raw.get("dps_cache", {})
    name = raw.get("name", "").lower()
    product = raw.get("product_name", "").lower()
    if any(x in name + product for x in ["curtain", "blind", "shutter", "cover", "persiana", "cortina", "roller"]):
        return "cover"
    if any(x in name + product for x in ["light", "bulb", "lamp", "rgb", "led", "strip", "tira"]):
        return "light"
    return "switch"


@tool(
    name="iot_scan",
    description=(
        "Scan the local network for IoT devices and register them. "
        "Discovers Tuya devices (lights, switches, curtains), LG TVs, and Xiaomi devices. "
        "Pass extra_subnets to also scan IoT VLANs/SSIDs if devices are on a different subnet "
        "than the server (e.g. extra_subnets=['192.168.2.0/24']). "
        "Returns a summary of found devices."
    ),
    parameters={
        "type": "object",
        "properties": {
            "extra_subnets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional subnets to scan, e.g. ['192.168.2.0/24'] for IoT VLAN.",
                "default": [],
            },
        },
        "required": [],
    },
    risk_level="low",
    category="iot",
)
async def iot_scan(extra_subnets: list[str] | None = None, **kwargs) -> str:
    registry = get_registry()
    raw_devices = await _disc.full_discovery(extra_subnets or [])

    added = []
    for raw in raw_devices:
        driver = raw.get("driver", "")
        ip = raw.get("ip", "")
        if not ip:
            continue

        if driver == "tuya":
            dev_id = raw.get("id", ip)
            device_id = f"tuya:{dev_id}"
            device_type = _tuya_guess_type(raw)
            meta = {
                "dev_id": dev_id,
                "key": raw.get("key", ""),
                "version": raw.get("version", "3.3"),
            }
            dev = DeviceInfo(
                id=device_id,
                name=raw.get("name", f"Tuya {ip}"),
                driver="tuya",
                device_type=device_type,
                ip=ip,
                model=raw.get("product_name", ""),
                meta=meta,
            )
        elif driver == "lgtv":
            device_id = f"lgtv:{ip}"
            dev = DeviceInfo(
                id=device_id,
                name=raw.get("name", f"LG TV {ip}"),
                driver="lgtv",
                device_type="tv",
                ip=ip,
                meta={},
            )
        elif driver == "miio":
            device_id = f"miio:{ip}"
            dev = DeviceInfo(
                id=device_id,
                name=raw.get("name", f"Xiaomi {ip}"),
                driver="miio",
                device_type=raw.get("device_type", "appliance"),
                ip=ip,
                model=raw.get("model", ""),
                meta={},
            )
        else:
            continue

        registry.upsert(dev)
        added.append(dev)

    # Build summary
    by_type: dict[str, list[str]] = {}
    for dev in added:
        by_type.setdefault(dev.device_type, []).append(dev.name)

    if not added:
        subnets = _disc._get_local_subnets()
        return (
            f"No IoT devices found on {subnets}.\n\n"
            "Possible reasons:\n"
            "1. Devices are on a different WiFi/VLAN — use extra_subnets=['x.x.x.0/24'] to scan it\n"
            "2. Tuya devices need tinytuya installed: pip install tinytuya\n"
            "3. Router blocks inter-SSID traffic — enable 'Allow clients in different VLANs' in router settings\n"
            "4. Devices are offline"
        )

    lines = [f"Found {len(added)} devices:\n"]
    for dtype, names in by_type.items():
        lines.append(f"  {dtype} ({len(names)}): {', '.join(names[:5])}{'...' if len(names) > 5 else ''}")

    keyless_tuya = [d for d in added if d.driver == "tuya" and not d.meta.get("key")]
    if keyless_tuya:
        lines.append(
            f"\n⚠️  {len(keyless_tuya)} Tuya device(s) found without local keys (required for firmware 3.3+).\n"
            "   • Try now (works for fw 3.1/3.2): iot_control('<device_id>', 'on')\n"
            "   • Bulk import from wizard: python -m tinytuya wizard  →  iot_tuya_import('devices.json')\n"
            "   • Add one device manually: iot_tuya_add(ip, dev_id, key, name)"
        )
    if any(d.driver == "miio" and not d.meta.get("token") for d in added):
        lines.append("⚠️  Xiaomi devices found without token. Use iot_miio_pair(ip, token) per device.")
    if any(d.driver == "lgtv" for d in added):
        lines.append("ℹ️  LG TV found. First iot_control call will show a pairing prompt on the TV screen.")

    return "\n".join(lines)


@tool(
    name="iot_devices",
    description="List all registered IoT devices. Filter by type (light, cover, tv, vacuum, switch, sensor) or driver (tuya, lgtv, miio).",
    parameters={
        "type": "object",
        "properties": {
            "device_type": {"type": "string", "description": "Filter by device type", "default": ""},
            "driver": {"type": "string", "description": "Filter by driver name", "default": ""},
        },
        "required": [],
    },
    risk_level="low",
    category="iot",
)
async def iot_devices(device_type: str = "", driver: str = "", **kwargs) -> str:
    registry = get_registry()
    devices = registry.list(device_type=device_type or None, driver=driver or None)
    if not devices:
        return "No devices registered yet. Run iot_scan() first."

    lines = [f"{len(devices)} devices registered:\n"]
    by_driver: dict[str, list[DeviceInfo]] = {}
    for d in devices:
        by_driver.setdefault(d.driver, []).append(d)

    for drv, devs in by_driver.items():
        lines.append(f"[{drv.upper()}]")
        for d in devs:
            key_ok = bool(d.meta.get("key") or d.meta.get("token") or d.driver == "lgtv")
            status = "✓" if key_ok else "⚠ needs setup"
            lines.append(f"  {d.id:40s}  {d.device_type:8s}  {d.ip:16s}  {d.name}  [{status}]")
        lines.append("")

    return "\n".join(lines)


@tool(
    name="iot_control",
    description=(
        "Control any IoT device. "
        "Actions for lights: on, off, brightness(0-100), color(r,g,b), color_temp(2700-6500K). "
        "Actions for covers/curtains: open, close, stop, position(0-100). "
        "Actions for TV: off, volume_up, volume_down, set_volume, mute, unmute, "
        "channel_up, channel_down, launch_app, set_input, send_key, toast, play, pause. "
        "Actions for vacuum: start, stop, pause, dock, locate, fan_speed, clean_zone, goto. "
        "You can address multiple devices at once with device_ids list. "
        "Use 'all_lights', 'all_covers', 'all_switches' as device_id to control all of that type."
    ),
    parameters={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device ID, name, IP, or special: 'all_lights', 'all_covers', 'all_switches'",
            },
            "action": {
                "type": "string",
                "description": "Action to perform: on, off, brightness, color, color_temp, open, close, stop, position, or TV/vacuum commands",
            },
            "params": {
                "type": "object",
                "description": "Action parameters, e.g. {'level': 80} for brightness, {'r':255,'g':0,'b':0} for color, {'position': 50} for cover",
                "default": {},
            },
        },
        "required": ["device_id", "action"],
    },
    risk_level="low",
    category="iot",
)
async def iot_control(device_id: str, action: str, params: dict | None = None, **kwargs) -> str:
    params = params or {}
    registry = get_registry()

    # Resolve device list (supports "all_lights" etc.)
    if device_id.startswith("all_"):
        dtype = device_id[4:]  # "lights" → "light" (strip trailing s if needed)
        if dtype.endswith("s"):
            dtype = dtype[:-1]
        devices = registry.list(device_type=dtype)
        if not devices:
            return f"No devices of type '{dtype}' registered."
    else:
        dev = registry.get(device_id)
        if not dev:
            return f"Device '{device_id}' not found. Run iot_devices() to see registered devices."
        devices = [dev]

    action = action.lower()
    results = []

    async def _control_one(dev: DeviceInfo) -> str:
        try:
            driver = _get_driver(dev.driver)
        except Exception as e:
            return f"{dev.name}: driver error — {e}"

        try:
            if action == "on":
                r = await driver.turn_on(dev,
                    brightness=params.get("brightness"),
                    color_temp=params.get("color_temp"),
                    color=tuple(params[k] for k in ("r", "g", "b")) if "r" in params else None,
                )
            elif action == "off":
                r = await driver.turn_off(dev)
            elif action == "brightness":
                r = await driver.set_brightness(dev, int(params.get("level", params.get("brightness", 50))))
            elif action == "color":
                r = await driver.set_color(dev, params.get("r", 255), params.get("g", 255), params.get("b", 255))
            elif action == "color_temp":
                r = await driver.set_color_temp(dev, int(params.get("kelvin", params.get("color_temp", 4000))))
            elif action == "open":
                r = await driver.open(dev, position=int(params.get("position", 100)))
            elif action == "close":
                r = await driver.close(dev)
            elif action == "stop":
                r = await driver.stop(dev)
            elif action == "position":
                r = await driver.open(dev, position=int(params.get("position", 50)))
            elif action == "status":
                r = await driver.get_status(dev)
            else:
                # Pass through to driver's send_command
                r = await driver.send_command(dev, action, params)

            # Persist updated state
            registry.upsert(dev)

            if r.get("success"):
                return f"{dev.name}: ✓ {action}"
            else:
                return f"{dev.name}: ✗ {r.get('error', 'unknown error')}"
        except Exception as e:
            return f"{dev.name}: exception — {e}"

    results = await asyncio.gather(*[_control_one(d) for d in devices])
    return "\n".join(results)


@tool(
    name="iot_status",
    description="Get current state of one or all devices of a type.",
    parameters={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Device ID, name, IP, or 'all_lights', 'all_covers', etc.",
            },
        },
        "required": ["device_id"],
    },
    risk_level="low",
    category="iot",
)
async def iot_status(device_id: str, **kwargs) -> str:
    return await iot_control(device_id, "status")


@tool(
    name="iot_tuya_setup",
    description=(
        "Cloud-based Tuya key extraction (optional — requires a paid Tuya IoT Platform account). "
        "Extracts local keys for ALL devices at once using Tuya Cloud API. "
        "If you don't have a cloud account, use iot_tuya_import() (tinytuya wizard) "
        "or iot_tuya_add() to add keys manually one device at a time. "
        "Get credentials from iot.tuya.com → Cloud → Project → API."
    ),
    parameters={
        "type": "object",
        "properties": {
            "api_key": {"type": "string", "description": "Tuya IoT Platform API Key (Client ID)"},
            "api_secret": {"type": "string", "description": "Tuya IoT Platform API Secret"},
            "api_region": {
                "type": "string",
                "description": "Region: 'eu' (Europe), 'us' (Americas), 'cn' (China), 'in' (India)",
                "default": "eu",
            },
            "tuya_username": {"type": "string", "description": "SmartLife/Tuya app account email"},
            "tuya_password": {"type": "string", "description": "SmartLife/Tuya app password"},
            "country_code": {"type": "string", "description": "Country phone prefix, e.g. '34' for Spain, '1' for USA", "default": "34"},
        },
        "required": ["api_key", "api_secret", "tuya_username", "tuya_password"],
    },
    risk_level="low",
    category="iot",
)
async def iot_tuya_setup(
    api_key: str, api_secret: str,
    tuya_username: str, tuya_password: str,
    api_region: str = "eu", country_code: str = "34",
    **kwargs,
) -> str:
    try:
        import tinytuya
    except ImportError:
        return "tinytuya not installed. Run: pip install tinytuya"

    try:
        loop = asyncio.get_event_loop()

        def _wizard():
            return tinytuya.Cloud(
                apiRegion=api_region,
                apiKey=api_key,
                apiSecret=api_secret,
                apiDeviceID=None,
            ).getdevices(verbose=False)

        cloud_devices = await asyncio.wait_for(
            loop.run_in_executor(None, _wizard), timeout=30.0
        )
    except Exception as e:
        return f"Tuya Cloud connection failed: {e}\nCheck API key/secret and region."

    if not cloud_devices:
        return "Tuya Cloud returned no devices. Ensure your SmartLife account is linked to the Cloud project."

    registry = get_registry()
    updated = 0

    for cd in cloud_devices:
        dev_id = cd.get("id", "")
        key = cd.get("key", "")
        ip = cd.get("ip", "")
        name = cd.get("name", dev_id)

        if not dev_id or not key:
            continue

        device_id = f"tuya:{dev_id}"
        existing = registry.get(device_id)

        if existing:
            existing.meta["key"] = key
            existing.meta["dev_id"] = dev_id
            if ip:
                existing.ip = ip
            registry.upsert(existing)
        else:
            # Infer type from category
            category = cd.get("category", "").lower()
            if category in ("cl", "clkg", "curtain", "wkcl"):
                device_type = "cover"
            elif category in ("dj", "dd", "xdd", "fsd", "light", "tgkg"):
                device_type = "light"
            elif category in ("kg", "switch"):
                device_type = "switch"
            else:
                device_type = "switch"

            dev = DeviceInfo(
                id=device_id,
                name=name,
                driver="tuya",
                device_type=device_type,
                ip=ip or "unknown",
                model=cd.get("model", ""),
                meta={"dev_id": dev_id, "key": key, "version": "3.3"},
            )
            registry.upsert(dev)
        updated += 1

    # Now scan to get IPs for devices that don't have one
    if any(d.ip == "unknown" for d in registry.list(driver="tuya")):
        scan_result = await iot_scan()

    return (
        f"Tuya setup complete: {updated} devices configured with local keys.\n"
        f"Run iot_scan() to discover IPs, then iot_devices() to see all devices.\n"
        f"Run iot_control('all_lights', 'on') to test!"
    )


@tool(
    name="iot_tuya_add",
    description=(
        "Manually add or update a single Tuya device with its local key. "
        "Use this after iot_scan() found a device that shows 'needs setup'. "
        "The local key (16 chars) can be obtained by: "
        "(1) running 'python -m tinytuya wizard' in a terminal, "
        "(2) from a tinytuya devices.json file, or "
        "(3) from the Tuya developer platform. "
        "Also use iot_tuya_import() to bulk-import from a wizard-generated devices.json."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ip": {"type": "string", "description": "Device IP address"},
            "dev_id": {"type": "string", "description": "Tuya device ID (e.g. bf1234abcdef56789012)"},
            "key": {"type": "string", "description": "Local key — 16-char string from tinytuya wizard"},
            "name": {"type": "string", "description": "Friendly name for the device"},
            "device_type": {
                "type": "string",
                "description": "Device type: light, cover, or switch",
                "default": "light",
            },
            "version": {
                "type": "string",
                "description": "Tuya firmware protocol version: 3.1, 3.2, or 3.3",
                "default": "3.3",
            },
        },
        "required": ["ip", "dev_id", "key", "name"],
    },
    risk_level="low",
    category="iot",
)
async def iot_tuya_add(
    ip: str, dev_id: str, key: str, name: str,
    device_type: str = "light", version: str = "3.3",
    **kwargs,
) -> str:
    registry = get_registry()
    device_id = f"tuya:{dev_id}"
    existing = registry.get(device_id)

    if existing:
        existing.ip = ip
        existing.name = name
        existing.device_type = device_type
        existing.meta["key"] = key
        existing.meta["dev_id"] = dev_id
        existing.meta["version"] = version
        registry.upsert(existing)
        action = "updated"
        dev = existing
    else:
        dev = DeviceInfo(
            id=device_id,
            name=name,
            driver="tuya",
            device_type=device_type,
            ip=ip,
            meta={"dev_id": dev_id, "key": key, "version": version},
        )
        registry.upsert(dev)
        action = "added"

    try:
        driver = _get_driver("tuya")
        status = await asyncio.wait_for(driver.get_status(dev), timeout=6.0)
        if status.get("success"):
            return (
                f"Device {action}: '{name}' ({device_id})\n"
                f"Connectivity: ✓ responding\n"
                f"DPS: {status.get('dps', {})}"
            )
        else:
            return (
                f"Device {action}: '{name}' ({device_id})\n"
                f"Connectivity: ✗ {status.get('error')}\n"
                f"Check that the key is correct and the device IP is reachable."
            )
    except Exception as e:
        return f"Device {action}: '{name}' ({device_id})\nCould not verify connectivity: {e}"


@tool(
    name="iot_tuya_import",
    description=(
        "Bulk-import Tuya device keys from a tinytuya wizard output file (devices.json). "
        "No Tuya IoT Cloud account subscription needed at runtime — only the wizard step needs it once. "
        "To generate devices.json: run 'python -m tinytuya wizard' in a terminal, "
        "enter your iot.tuya.com API credentials when prompted. "
        "The wizard writes devices.json in the current directory. "
        "After import, run iot_scan() to fill in any missing IPs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "json_path": {
                "type": "string",
                "description": "Path to devices.json from tinytuya wizard. Default: devices.json",
                "default": "devices.json",
            },
        },
        "required": [],
    },
    risk_level="low",
    category="iot",
)
async def iot_tuya_import(json_path: str = "devices.json", **kwargs) -> str:
    path = Path(json_path)
    if not path.exists():
        return (
            f"File not found: {json_path}\n\n"
            "Generate it by running the tinytuya wizard once:\n"
            "  pip install tinytuya\n"
            "  python -m tinytuya wizard\n"
            "  (enter iot.tuya.com API key + secret when prompted)\n\n"
            "Then call: iot_tuya_import('devices.json')"
        )

    try:
        devices_data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to read {json_path}: {e}"

    if not isinstance(devices_data, list):
        return f"Expected a JSON array in {json_path}, got {type(devices_data).__name__}."

    registry = get_registry()
    imported = 0
    updated = 0
    skipped = 0

    for d in devices_data:
        dev_id = d.get("id", "")
        key = d.get("key", "")
        if not dev_id or not key:
            skipped += 1
            continue

        ip = d.get("ip", "unknown")
        name = d.get("name", dev_id)
        version = str(d.get("version", "3.3"))
        slug = (name + " " + d.get("product_name", "")).lower()

        if any(x in slug for x in ["curtain", "blind", "shutter", "cover", "persiana", "cortina", "roller"]):
            dtype = "cover"
        elif any(x in slug for x in ["light", "bulb", "lamp", "rgb", "led", "strip", "tira"]):
            dtype = "light"
        else:
            dtype = "switch"

        device_id = f"tuya:{dev_id}"
        existing = registry.get(device_id)
        if existing:
            existing.meta["key"] = key
            existing.meta["version"] = version
            if ip and ip != "unknown":
                existing.ip = ip
            registry.upsert(existing)
            updated += 1
        else:
            dev = DeviceInfo(
                id=device_id,
                name=name,
                driver="tuya",
                device_type=dtype,
                ip=ip,
                model=d.get("product_name", ""),
                meta={"dev_id": dev_id, "key": key, "version": version},
            )
            registry.upsert(dev)
            imported += 1

    total = imported + updated
    if total == 0:
        return (
            f"No devices imported from {json_path} (skipped {skipped} entries without id/key).\n"
            "Make sure the file is the devices.json output from 'python -m tinytuya wizard'."
        )

    lines = [f"Import complete: {imported} new devices, {updated} updated."]
    if skipped:
        lines.append(f"({skipped} entries skipped — missing id or key)")

    needs_ip = [d for d in registry.list(driver="tuya") if d.ip in ("", "unknown")]
    if needs_ip:
        lines.append(f"\n{len(needs_ip)} device(s) have no IP yet — run iot_scan() to discover them on the network.")
    else:
        lines.append("Run iot_devices() to see all devices, then iot_control() to test!")

    return "\n".join(lines)


@tool(
    name="iot_miio_pair",
    description=(
        "Add a Xiaomi device (vacuum, purifier, etc.) by IP and token. "
        "Token can be found in: Mi Home app → Device → About → tap version 5 times, "
        "or via 'miiocli discover' command, "
        "or from router DHCP + token extractor tools."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ip": {"type": "string", "description": "Device IP address"},
            "token": {"type": "string", "description": "32-char hex token"},
            "name": {"type": "string", "description": "Friendly name", "default": "Xiaomi Device"},
            "model": {"type": "string", "description": "Model string e.g. 'rockrobo.vacuum.v1'", "default": ""},
        },
        "required": ["ip", "token"],
    },
    risk_level="low",
    category="iot",
)
async def iot_miio_pair(ip: str, token: str, name: str = "Xiaomi Device", model: str = "", **kwargs) -> str:
    from openacm.tools.iot.base import DeviceInfo
    from openacm.tools.iot.registry import get_registry

    registry = get_registry()
    device_id = f"miio:{ip}"

    model_l = model.lower()
    if any(x in model_l for x in ["vacuum", "robo", "sweep"]):
        dtype = "vacuum"
    elif any(x in model_l for x in ["air", "purif"]):
        dtype = "purifier"
    else:
        dtype = "appliance"

    dev = DeviceInfo(
        id=device_id,
        name=name,
        driver="miio",
        device_type=dtype,
        ip=ip,
        model=model,
        meta={"token": token},
    )
    registry.upsert(dev)

    # Quick connectivity test
    try:
        from openacm.tools.iot.drivers.miio_driver import MiioDriver
        driver = MiioDriver()
        status = await asyncio.wait_for(driver.get_status(dev), timeout=8.0)
        if status.get("success"):
            return f"Xiaomi device paired successfully!\nID: {device_id}\nStatus: {status.get('state', {})}"
        else:
            return f"Device saved but status check failed: {status.get('error')}\nToken may be incorrect."
    except Exception as e:
        return f"Device saved (ID: {device_id}) but couldn't verify: {e}"


@tool(
    name="iot_rename",
    description="Rename a registered IoT device or update its type.",
    parameters={
        "type": "object",
        "properties": {
            "device_id": {"type": "string"},
            "new_name": {"type": "string", "default": ""},
            "new_type": {"type": "string", "description": "light, cover, switch, tv, vacuum, etc.", "default": ""},
        },
        "required": ["device_id"],
    },
    risk_level="low",
    category="iot",
)
async def iot_rename(device_id: str, new_name: str = "", new_type: str = "", **kwargs) -> str:
    registry = get_registry()
    dev = registry.get(device_id)
    if not dev:
        return f"Device '{device_id}' not found."
    if new_name:
        dev.name = new_name
    if new_type:
        dev.device_type = new_type
    registry.upsert(dev)
    return f"Updated: {dev.id} → name='{dev.name}', type='{dev.device_type}'"
