"""
System Info Tool — get information about the current system.
"""

import platform
from datetime import datetime, timezone

import psutil

from openacm.tools.base import tool


@tool(
    name="system_info",
    description=(
        "Get information about the current system: OS, CPU, RAM, disk usage, "
        "network interfaces, running processes, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "description": (
                    "Level of detail: 'summary' (default), 'cpu', 'memory', "
                    "'disk', 'network', 'processes', 'full'"
                ),
                "default": "summary",
                "enum": ["summary", "cpu", "memory", "disk", "network", "processes", "full"],
            },
        },
        "required": [],
    },
    risk_level="low",
    category="system",
)
async def system_info(detail: str = "summary", **kwargs) -> str:
    """Get system information."""
    sections = []

    if detail in ("summary", "full"):
        sections.append(_get_summary())
    if detail in ("cpu", "full"):
        sections.append(_get_cpu_info())
    if detail in ("memory", "full"):
        sections.append(_get_memory_info())
    if detail in ("disk", "full"):
        sections.append(_get_disk_info())
    if detail in ("network", "full"):
        sections.append(_get_network_info())
    if detail in ("processes", "full"):
        sections.append(_get_process_info())
    
    if not sections:
        sections.append(_get_summary())

    return "\n\n".join(sections)


def _get_summary() -> str:
    """Get a summary of system info."""
    uname = platform.uname()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/") if platform.system() != "Windows" else psutil.disk_usage("C:\\")
    cpu_percent = psutil.cpu_percent(interval=0.5)
    boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)

    return (
        f"🖥️ System Summary\n"
        f"  OS: {uname.system} {uname.release} ({uname.machine})\n"
        f"  Hostname: {uname.node}\n"
        f"  Python: {platform.python_version()}\n"
        f"  CPU: {psutil.cpu_count()} cores @ {cpu_percent}% usage\n"
        f"  RAM: {_fmt(mem.used)} / {_fmt(mem.total)} ({mem.percent}% used)\n"
        f"  Disk: {_fmt(disk.used)} / {_fmt(disk.total)} ({disk.percent}% used)\n"
        f"  Boot time: {boot_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )


def _get_cpu_info() -> str:
    """Get CPU details."""
    cpu_freq = psutil.cpu_freq()
    per_cpu = psutil.cpu_percent(interval=0.5, percpu=True)
    
    lines = [
        f"🔧 CPU Info",
        f"  Physical cores: {psutil.cpu_count(logical=False)}",
        f"  Logical cores: {psutil.cpu_count()}",
    ]
    if cpu_freq:
        lines.append(f"  Frequency: {cpu_freq.current:.0f} MHz")
    lines.append(f"  Per-core usage: {', '.join(f'{p}%' for p in per_cpu)}")
    return "\n".join(lines)


def _get_memory_info() -> str:
    """Get memory details."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return (
        f"💾 Memory Info\n"
        f"  RAM: {_fmt(mem.used)} / {_fmt(mem.total)} ({mem.percent}%)\n"
        f"  Available: {_fmt(mem.available)}\n"
        f"  Swap: {_fmt(swap.used)} / {_fmt(swap.total)} ({swap.percent}%)"
    )


def _get_disk_info() -> str:
    """Get disk usage for all partitions."""
    lines = ["💿 Disk Info"]
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            lines.append(
                f"  {partition.mountpoint} ({partition.fstype}): "
                f"{_fmt(usage.used)} / {_fmt(usage.total)} ({usage.percent}%)"
            )
        except PermissionError:
            lines.append(f"  {partition.mountpoint}: (access denied)")
    return "\n".join(lines)


def _get_network_info() -> str:
    """Get network interface info."""
    lines = ["🌐 Network Info"]
    addrs = psutil.net_if_addrs()
    for iface, addr_list in addrs.items():
        for addr in addr_list:
            if addr.family.name == "AF_INET":
                lines.append(f"  {iface}: {addr.address}")
    return "\n".join(lines)


def _get_process_info() -> str:
    """Get top processes by memory usage."""
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
        try:
            info = proc.info
            processes.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # Sort by memory usage
    processes.sort(key=lambda p: p.get("memory_percent", 0) or 0, reverse=True)
    
    lines = ["📊 Top Processes (by memory)"]
    for proc in processes[:15]:
        name = proc.get("name", "?")
        pid = proc.get("pid", "?")
        mem = proc.get("memory_percent", 0) or 0
        cpu = proc.get("cpu_percent", 0) or 0
        lines.append(f"  [{pid}] {name}: RAM {mem:.1f}%, CPU {cpu:.1f}%")
    return "\n".join(lines)


def _fmt(bytes_val: int) -> str:
    """Format bytes to human readable."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}PB"
