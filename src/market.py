"""Market context from outside TEFAS, for the commentary tweets.

Only what can be had free and without an API key. Everything fails soft and
returns ``None``: a missing quote drops one draft, it must never take the daily
report down.

Deliberately narrow. Inflation and the lira exchange rate are not here, because
no free source was found that could be trusted to stay correct unattended, and a
wrong benchmark in a published tweet is worse than a missing one. Where a
benchmark is wanted, `tweets.py` uses TEFAS's own funds as proxies -- a gold
fund's year-to-date stands in for gold, a money-market fund's for deposits --
which is honest because that is what a reader could actually have bought.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

COINGECKO = "https://api.coingecko.com/api/v3/simple/price"
TIMEOUT = 20


def bitcoin_24h() -> Optional[dict]:
    """Bitcoin's dollar price and 24-hour move, or ``None``.

    CoinGecko's public tier needs no key and no registration.
    """
    try:
        resp = requests.get(
            COINGECKO,
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            headers={"User-Agent": "NeredeParaVar/1.0"},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            log.info("CoinGecko returned HTTP %s.", resp.status_code)
            return None
        data = resp.json().get("bitcoin") or {}
        price = data.get("usd")
        change = data.get("usd_24h_change")
        if price is None or change is None:
            return None
        return {"price": float(price), "change": float(change)}
    except (requests.RequestException, ValueError) as exc:
        log.info("Could not read the bitcoin quote: %s", exc)
        return None
