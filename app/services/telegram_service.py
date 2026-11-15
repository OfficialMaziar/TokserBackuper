"""Telegram Bot API integration.

Implements:
  * connection / message tests
  * HTML-formatted notifications
  * document upload with automatic splitting of large archives
  * per-part retry and honest aggregate status
  * support for a self-hosted local Bot API server (larger limits)
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.utils import format_duration, human_bytes, split_file

log = get_logger(__name__)

# Telegram cloud Bot API hard limit for bot uploads.
CLOUD_MAX_UPLOAD = 50 * 1024 * 1024
# Keep a safety margin under the documented 50 MB limit.
SAFE_CLOUD_LIMIT = 49 * 1024 * 1024


class TelegramError(RuntimeError):
    pass


@dataclass
class SendResult:
    ok: bool
    message: str
    parts_total: int = 0
    parts_sent: int = 0
    failed_parts: list[int] = field(default_factory=list)


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, api_base: str | None = None):
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.api_base = (api_base or settings.telegram_api_base).rstrip("/")
        self.timeout = settings.telegram_timeout_seconds

    @property
    def _url(self) -> str:
        return f"{self.api_base}/bot{self.bot_token}"

    def _check(self) -> None:
        if not self.bot_token:
            raise TelegramError("Bot token is not configured")
        if ":" not in self.bot_token:
            raise TelegramError("Bot token format is invalid")

    def get_me(self) -> dict:
        self._check()
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(f"{self._url}/getMe")
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or not data.get("ok"):
            raise TelegramError(data.get("description") or f"HTTP {resp.status_code}")
        return data.get("result", {})

    def send_message(self, text: str, parse_mode: str = "HTML") -> dict:
        self._check()
        if not self.chat_id:
            raise TelegramError("Chat ID is not configured")
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{self._url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text[:4096],
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or not data.get("ok"):
            raise TelegramError(data.get("description") or f"HTTP {resp.status_code}")
        return data.get("result", {})

    def _max_upload(self) -> int:
        # A self-hosted local Bot API server allows up to 2 GB.
        if "api.telegram.org" in self.api_base:
            return min(SAFE_CLOUD_LIMIT, settings.telegram_max_upload_bytes)
        return max(SAFE_CLOUD_LIMIT, settings.telegram_max_upload_bytes)

    def _send_document_once(self, path: str, caption: str) -> dict:
        self._check()
        with open(path, "rb") as fh:
            files = {"document": (os.path.basename(path), fh, "application/octet-stream")}
            data = {"chat_id": self.chat_id, "caption": caption[:1024]}
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self._url}/sendDocument", data=data, files=files)
        payload = resp.json() if resp.content else {}
        if resp.status_code != 200 or not payload.get("ok"):
            raise TelegramError(payload.get("description") or f"HTTP {resp.status_code}")
        return payload.get("result", {})

    def send_document(self, path: str, caption: str = "") -> SendResult:
        path = str(path)
        if not os.path.isfile(path):
            return SendResult(False, "File not found", 0, 0)
        size = os.path.getsize(path)
        max_size = self._max_upload()
        retries = max(1, settings.telegram_upload_retries)

        parts: list[str] = [path]
        temp_dir: str | None = None
        if size > max_size:
            temp_dir = tempfile.mkdtemp(prefix="tbm_tg_")
            try:
                parts = split_file(path, max_size, temp_dir)
            except Exception as exc:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return SendResult(False, f"Failed to split archive: {exc}", 0, 0)

        sent = 0
        failed: list[int] = []
        last_error = ""
        try:
            for index, part in enumerate(parts, start=1):
                part_caption = caption
                if len(parts) > 1:
                    part_caption = f"{caption}\nPart {index}/{len(parts)}"[:1024]
                ok = False
                for attempt in range(1, retries + 1):
                    try:
                        self._send_document_once(part, part_caption)
                        ok = True
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        log.warning(
                            "Telegram upload part %s/%s attempt %s failed: %s",
                            index, len(parts), attempt, exc,
                        )
                        if attempt < retries:
                            time.sleep(min(30, 2 ** attempt))
                if ok:
                    sent += 1
                else:
                    failed.append(index)
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

        total = len(parts)
        if sent == total:
            return SendResult(True, f"Sent {sent}/{total} part(s)", total, sent)
        return SendResult(
            False,
            f"Uploaded {sent}/{total} part(s). Last error: {last_error}",
            total,
            sent,
            failed,
        )


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------
def format_backup_report(
    *,
    status: str,
    job_name: str,
    archive_name: str,
    archive_size: int,
    duration: float,
    started_at: str = "",
    error: str = "",
) -> str:
    icon = {"success": "✅", "failed": "❌", "partial": "⚠️"}.get(status, "ℹ️")
    lines = [
        "<b>Tokser Backup Manager</b>",
        f"Backup Status: <b>{status.upper()}</b> {icon}",
        f"Job: <b>{_esc(job_name)}</b>",
    ]
    if started_at:
        lines.append(f"Date: {started_at}")
    if archive_name:
        lines.append(f"Archive: <code>{_esc(archive_name)}</code>")
    if archive_size:
        lines.append(f"Size: {human_bytes(archive_size)}")
    if duration:
        lines.append(f"Duration: {format_duration(duration)}")
    if error:
        lines.append(f"Error: <code>{_esc(error[:500])}</code>")
    lines.append("<i>TokserTeam</i>")
    return "\n".join(lines)


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
