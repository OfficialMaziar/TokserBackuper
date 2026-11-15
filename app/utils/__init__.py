"""Utility helpers shared across services and API."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import posixpath
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.\-]+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def human_bytes(num: int | float) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} EB"


def safe_slug(value: str, fallback: str = "backup") -> str:
    slug = _SAFE_NAME.sub("_", (value or "").strip()).strip("_.")
    return slug[:80] or fallback


def sha256_file(path: str | os.PathLike, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def matches_any(rel_path: str, patterns: list[str]) -> bool:
    """Match a relative path against shell-style exclude patterns.

    Supports basename matching (``*.log``), directory names (``.git``) and
    full relative paths (``var/www/cache/*``).
    """
    if not patterns:
        return False
    rel = rel_path.replace(os.sep, "/").lstrip("./")
    name = posixpath.basename(rel)
    parts = rel.split("/")
    for raw in patterns:
        pat = raw.strip().replace(os.sep, "/")
        if not pat:
            continue
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
        # A pattern like ".git" or "node_modules" excludes the whole subtree
        if "/" not in pat and pat in parts:
            return True
        if pat.startswith("*/") and fnmatch.fnmatch(rel, pat[2:]):
            return True
    return False


def is_safe_archive_member(member: str, base: str | Path) -> bool:
    """Reject absolute paths, traversal and symlink escapes (Zip Slip)."""
    if not member or "\x00" in member:
        return False
    normalized = member.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return False
    pure = PurePosixPath(normalized)
    if any(part == ".." for part in pure.parts):
        return False
    target = (Path(base) / pure).resolve()
    try:
        base_resolved = Path(base).resolve()
    except OSError:
        return False
    try:
        target.relative_to(base_resolved)
    except ValueError:
        return False
    return True


def dir_size(path: str | Path, limit_seconds: float = 8.0) -> int:
    """Estimate directory size, stopping after ``limit_seconds``."""
    start = datetime.now(timezone.utc).timestamp()
    total = 0
    p = Path(path)
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    if not p.is_dir():
        return 0
    for root, dirs, files in os.walk(p, followlinks=False):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
        if datetime.now(timezone.utc).timestamp() - start > limit_seconds:
            break
    return total


def disk_usage(path: str | Path) -> dict[str, int]:
    try:
        usage = shutil.disk_usage(str(path))
        return {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        return {"total": 0, "used": 0, "free": 0}


def split_file(path: str | Path, max_bytes: int, out_dir: str | Path) -> list[str]:
    """Split a file into parts no larger than ``max_bytes`` (streaming)."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    with path.open("rb") as src:
        index = 1
        while True:
            part_path = out_dir / f"{path.name}.part{index:03d}"
            written = 0
            with part_path.open("wb") as dst:
                while written < max_bytes:
                    chunk = src.read(min(1024 * 1024, max_bytes - written))
                    if not chunk:
                        break
                    dst.write(chunk)
                    written += len(chunk)
            if written == 0:
                part_path.unlink(missing_ok=True)
                break
            parts.append(str(part_path))
            index += 1
            if written < max_bytes:
                break
    return parts


def format_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"
