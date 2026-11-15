"""Server monitoring: CPU, memory, disk, network, uptime and service state."""
from __future__ import annotations

import os
import platform
import socket
import time
from datetime import datetime, timezone

import psutil

from app.core.config import settings
from app.core.logging import get_logger
from app.utils import disk_usage, human_bytes

log = get_logger(__name__)

_BOOT_TIME = psutil.boot_time()
_last_net: dict | None = None
_last_net_at: float | None = None


def _net_rates() -> dict[str, float]:
    global _last_net, _last_net_at
    now = time.monotonic()
    counters = psutil.net_io_counters()
    rates = {"rx_bytes_per_sec": 0.0, "tx_bytes_per_sec": 0.0}
    if _last_net and _last_net_at:
        elapsed = max(0.001, now - _last_net_at)
        rates["rx_bytes_per_sec"] = (counters.bytes_recv - _last_net["bytes_recv"]) / elapsed
        rates["tx_bytes_per_sec"] = (counters.bytes_sent - _last_net["bytes_sent"]) / elapsed
    _last_net = {"bytes_recv": counters.bytes_recv, "bytes_sent": counters.bytes_sent}
    _last_net_at = now
    return rates


def get_system_metrics() -> dict:
    cpu_percent = psutil.cpu_percent(interval=0.15)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + "\\"
    try:
        disk = psutil.disk_usage(root)
        disk_info = {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent}
    except OSError:
        disk_info = {"total": 0, "used": 0, "free": 0, "percent": 0}

    try:
        io = psutil.disk_io_counters()
        disk_io = {"read_bytes": io.read_bytes, "write_bytes": io.write_bytes} if io else {}
    except Exception:
        disk_io = {}

    try:
        load = os.getloadavg()
        load_avg = [round(x, 2) for x in load]
    except (AttributeError, OSError):
        load_avg = []

    uptime_seconds = max(0, int(time.time() - _BOOT_TIME))
    backup_disk = disk_usage(settings.backup_dir)

    return {
        "hostname": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu": {
            "percent": round(cpu_percent, 1),
            "cores": psutil.cpu_count(logical=True),
            "physical": psutil.cpu_count(logical=False),
            "load_avg": load_avg,
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "available": mem.available,
            "percent": mem.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        },
        "disk": {**disk_info, "mount": root},
        "backup_disk": backup_disk,
        "disk_io": disk_io,
        "network": _net_rates(),
        "uptime_seconds": uptime_seconds,
        "processes": len(psutil.pids()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def disk_health() -> dict:
    usage = disk_usage(settings.backup_dir)
    total = usage.get("total", 0) or 1
    percent = round(usage.get("used", 0) / total * 100, 1)
    level = "ok"
    if percent >= settings.disk_critical_percent:
        level = "critical"
    elif percent >= settings.disk_warning_percent:
        level = "warning"
    return {
        "path": settings.backup_dir,
        "total": usage.get("total", 0),
        "used": usage.get("used", 0),
        "free": usage.get("free", 0),
        "percent": percent,
        "level": level,
    }


def check_disk_alert(db) -> None:
    """Emit a low-disk notification when thresholds are crossed."""
    from app.models import SystemSetting
    from app.services.notifications import notify
    from sqlalchemy import select

    health = disk_health()
    if health["level"] == "ok":
        return
    key = f"disk_alert_state_{health['level']}"
    last = db.scalar(select(SystemSetting).where(SystemSetting.key == "disk_alert_last"))
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if last and last.value == f"{health['level']}:{bucket}":
        return
    notify(
        db,
        "low_disk_space",
        f"Low disk space ({health['level']})",
        f"Backup volume {health['path']} is {health['percent']}% full "
        f"({human_bytes(health['free'])} free).",
        level="error" if health["level"] == "critical" else "warning",
    )
    if last:
        last.value = f"{health['level']}:{bucket}"
    else:
        db.add(SystemSetting(key="disk_alert_last", value=f"{health['level']}:{bucket}"))
    db.commit()
