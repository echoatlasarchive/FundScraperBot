"""Telegram delivery."""

from __future__ import annotations

import logging
import time
from typing import List

import requests

from . import config, formatter

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"


def send(text: str, disable_preview: bool = True) -> None:
    """Send a report, splitting it across messages if it exceeds the size limit."""
    chunks = formatter.split_for_telegram(text)
    token = config.telegram_token()
    chat_id = config.telegram_chat_id()

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
        log.info("Sent message %d/%d (%d chars).", index, len(chunks), len(chunk))
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


def preview(text: str) -> None:
    """Print what would be sent, for local dry runs."""
    chunks: List[str] = formatter.split_for_telegram(text)
    for index, chunk in enumerate(chunks, start=1):
        print("\n{} MESAJ {}/{} ({} karakter) {}".format(
            "=" * 20, index, len(chunks), len(chunk), "=" * 20
        ))
        print(chunk)
