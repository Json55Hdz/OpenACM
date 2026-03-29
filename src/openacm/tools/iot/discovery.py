"""
IoT Device Discovery — mDNS, SSDP, and targeted port scanning.
Finds Tuya, LG TV, Xiaomi, and other devices automatically.
"""
from __future__ import annotations
import asyncio
import ipaddress
import socket
import struct
import json
from typing import Any

import structlog

log = structlog.get_logger()


_SKIP_PREFIXES = ("127.", "169.254.")  # loopback + APIPA link-local (huge, useless for IoT)

def _get_local_subnets() -> list[str]:
    """Detect local network subnets from active interfaces."""
    subnets = []
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family != socket.AF_INET:
                    continue
                if any(addr.address.startswith(p) for p in _SKIP_PREFIXES):
                    continue
                try:
                    net = ipaddress.IPv4Network(f"{addr.address}/{addr.netmask}", strict=False)
                    if net.num_addresses <= 1024:  # only /22 or smaller (real LAN subnets)
                        subnets.append(str(net))
                except Exception:
                    pass
    except Exception as e:
        log.warning("Subnet detection failed", error=str(e))
        subnets = ["192.168.1.0/24"]
    return list(set(subnets)) or ["192.168.1.0/24"]


async def _tcp_probe(ip: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if port is open on ip."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def scan_subnet_ports(subnet: str, ports: list[int], timeout: float = 1.0, max_concurrent: int = 20) -> list[dict]:
    """Scan a subnet for open IoT ports. Returns list of {ip, port}."""
    network = ipaddress.IPv4Network(subnet, strict=False)
    hosts = [str(h) for h in network.hosts()]
    results = []
    sem = asyncio.Semaphore(max_concurrent)

    async def probe(ip: str, port: int):
        async with sem:
            if await _tcp_probe(ip, port, timeout):
                results.append({"ip": ip, "port": port})

    tasks = [probe(ip, port) for ip in hosts for port in ports]
    await asyncio.gather(*tasks, return_exceptions=True)
    return results


async def discover_tuya_devices(subnets: list[str]) -> list[dict]:
    """Find Tuya devices using tinytuya's UDP broadcast scan."""
    found = []
    try:
        import tinytuya
        loop = asyncio.get_event_loop()

        def _scan():
            # tinytuya.deviceScan returns {ip: {...}} dict
            return tinytuya.deviceScan(verbose=False, maxretry=3)

        devices = await asyncio.wait_for(
            loop.run_in_executor(None, _scan), timeout=15.0
        )
        if devices:
            for ip, d in devices.items():
                found.append({
                    "driver": "tuya",
                    "ip": ip,
                    "id": d.get("gwId", d.get("id", ip)),
                    "name": d.get("name", d.get("gwId", "Tuya Device")),
                    "product_name": d.get("productName", ""),
                    "version": str(d.get("version", "3.3")),
                    "key": d.get("key", ""),
                    "dps_cache": d.get("dps", {}),
                })
    except ImportError:
        log.warning("tinytuya not installed — skipping Tuya discovery")
    except asyncio.TimeoutError:
        log.warning("Tuya UDP scan timed out after 15s")
    except Exception as e:
        log.warning("Tuya scan failed", error=str(e))
    return found


async def discover_lgtv(subnets: list[str]) -> list[dict]:
    """Find LG WebOS TVs by scanning port 3000."""
    found = []
    all_open = []
    for subnet in subnets:
        results = await scan_subnet_ports(subnet, [3000], timeout=0.8)
        all_open.extend(results)

    for r in all_open:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://{r['ip']}:3000/")
                # LG TVs respond with specific headers or body
                if "webOS" in resp.text or resp.status_code in (200, 400, 403):
                    found.append({
                        "driver": "lgtv",
                        "ip": r["ip"],
                        "name": "LG TV",
                        "device_type": "tv",
                    })
        except Exception:
            # Port open but couldn't confirm — still include as candidate
            found.append({
                "driver": "lgtv",
                "ip": r["ip"],
                "name": "LG TV (unconfirmed)",
                "device_type": "tv",
            })
    return found


async def discover_miio_devices(subnets: list[str]) -> list[dict]:
    """Discover Xiaomi miio devices via UDP broadcast."""
    found = []
    try:
        from miio import Discovery
        # miio sends a broadcast ping and collects responses
        loop = asyncio.get_event_loop()
        devices = await loop.run_in_executor(None, lambda: Discovery.discover_mdns())
        for ip, info in (devices or {}).items():
            found.append({
                "driver": "miio",
                "ip": ip,
                "name": getattr(info, "name", "Xiaomi Device"),
                "model": getattr(info, "model", ""),
                "device_type": _guess_miio_type(getattr(info, "model", "")),
            })
    except ImportError:
        log.warning("python-miio not installed — skipping Xiaomi discovery")
    except Exception as e:
        log.warning("miio discovery failed", error=str(e))
    return found


def _guess_miio_type(model: str) -> str:
    model = model.lower()
    if any(x in model for x in ["vacuum", "robo", "sweep"]):
        return "vacuum"
    if any(x in model for x in ["light", "lamp", "bulb", "yeelight"]):
        return "light"
    if any(x in model for x in ["air", "purif"]):
        return "purifier"
    if any(x in model for x in ["humidif"]):
        return "humidifier"
    return "appliance"


async def full_discovery(extra_subnets: list[str] | None = None) -> list[dict]:
    """Run all discovery methods and return combined raw results."""
    subnets = _get_local_subnets()
    if extra_subnets:
        subnets = list(set(subnets + extra_subnets))

    log.info("IoT discovery starting", subnets=subnets)

    tuya_task = discover_tuya_devices(subnets)
    lgtv_task = discover_lgtv(subnets)
    miio_task = discover_miio_devices(subnets)

    results = await asyncio.gather(tuya_task, lgtv_task, miio_task, return_exceptions=True)

    combined = []
    for r in results:
        if isinstance(r, list):
            combined.extend(r)
        elif isinstance(r, Exception):
            log.warning("Discovery partial failure", error=str(r))

    log.info("IoT discovery complete", found=len(combined))
    return combined
