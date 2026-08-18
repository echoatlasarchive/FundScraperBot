"""Telegram delivery."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import requests

from . import config, formatter

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"


def send(blocks, disable_preview: bool = True, chat_id: Optional[str] = None) -> None:
    """Send a report, packing its blocks into as few messages as fit.

    Accepts the block list a report builder returns, or a plain string.
    ``chat_id`` defaults to the owner's private chat.
    """
    chunks = formatter.split_for_telegram(blocks)
    token = config.telegram_token()
    chat_id = chat_id or config.telegram_chat_id()

    for index, chunk in enumerate(chunks, start=1):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        resp = requests.post(API.format(token=token), json=payload, timeout=30)
        if resp.status_code != 200:
            # Never let the token reach the logs.
            raise RuntimeError(
                "Telegram rejected message {}/{}: HTTP {} {}".format(
                    index, len(chunks), resp.status_code, resp.text[:300]
                )
            )
        log.info(
            "Sent message %d/%d (%d chars) to %s.",
            index, len(chunks), len(chunk), chat_id,
        )
        if index < len(chunks):
            time.sleep(0.5)


def send_alert(message: str) -> None:
    """Best-effort failure notice; never raises."""
    try:
        send("🚨 <b>Fon botu hatası</b>\n\n<pre>{}</pre>".format(
            formatter.esc(message[:1500])
        ))
    except Exception as exc:  # noqa: BLE001 - alerting must not mask the original error
        log.error("Could not deliver alert: %s", exc)


def preview(blocks) -> None:
    """Print what would be sent, for local dry runs."""
    chunks: List[str] = formatter.split_for_telegram(blocks)
    for index, chunk in enumerate(chunks, start=1):
        print("\n{} MESAJ {}/{} ({} karakter) {}".format(
            "=" * 20, index, len(chunks), len(chunk), "=" * 20
        ))
        print(chunk)
