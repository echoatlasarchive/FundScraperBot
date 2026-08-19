"""Client for the TEFAS fund API (www.tefas.gov.tr/api/funds/*).

Notes on the upstream service, learned the hard way:

* The legacy ``/api/DB/Bind*`` endpoints (BindHistoryInfo, BindComparisonFundReturns,
  ...) are retired -- they answer 404 ``ERR-006 Method not found or disabled``.
  Every third-party library built on them is dead. Only ``/api/funds/*`` works.
* The HTML pages sit behind an F5/Shape bot wall and return a JS challenge, so the
  access token cannot be scraped from them. The API layer itself is not protected
  and accepts a long-lived static bearer token.
* There is no historical endpoint. ``fonBilgiGetir`` returns a *current snapshot*
  only, which is why we persist a snapshot per day and diff locally.
* The service resets connections under concurrency. Requests are issued
  sequentially with a small delay and retried on transport errors.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict, Iterable, List, Optional

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.tefas.gov.tr/api/funds/"
LANDING_URL = "https://www.tefas.gov.tr/tr/fon-getirileri"

# Long-lived token used by the public web app. Overridable via TEFAS_TOKEN in
# case it is rotated upstream.
FALLBACK_TOKEN = "ST-tefaswebwse3irfmSBj4iRAzGPbAlS94Se"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Fund universes. YAT = securities mutual funds (TEFAS), EMK = pension funds (BEFAS).
FUND_TYPES = ("YAT", "EMK")

REQUEST_DELAY_S = 0.25
MAX_RETRIES = 4


class TefasError(RuntimeError):
    """Raised when the API is reachable but refuses to serve usable data."""


class TefasClient:
    def __init__(self, token: Optional[str] = None, delay: float = REQUEST_DELAY_S):
        self.token = token or self._resolve_token()
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "*/*",
                "Authorization": "Bearer {}".format(self.token),
                "Content-Type": "application/json",
                "Origin": "https://www.tefas.gov.tr",
                "Referer": LANDING_URL,
                "User-Agent": USER_AGENT,
            }
        )

    # -- token ---------------------------------------------------------------

    @staticmethod
    def _resolve_token() -> str:
        env_token = os.environ.get("TEFAS_TOKEN", "").strip()
        if env_token:
            log.info("Using TEFAS token from environment.")
            return env_token

        scraped = TefasClient._scrape_token()
        if scraped:
            log.info("Scraped a fresh TEFAS token from the landing page.")
            return scraped

        log.info("Falling back to the built-in TEFAS token.")
        return FALLBACK_TOKEN

    @staticmethod
    def _scrape_token() -> Optional[str]:
        """Best effort. Normally blocked by the bot wall, kept for the day it isn't."""
        try:
            resp = requests.get(
                LANDING_URL, headers={"User-Agent": USER_AGENT}, timeout=30
            )
            if resp.status_code != 200:
                return None
            for pattern in (r"Bearer\s+(ST-[A-Za-z0-9]+)", r"[\"'](ST-[A-Za-z0-9]{10,})[\"']"):
                match = re.search(pattern, resp.text)
                if match:
                    return match.group(1)
        except requests.RequestException as exc:
            log.debug("Token scrape failed: %s", exc)
        return None

    # -- transport -----------------------------------------------------------

    def _post(self, method: str, payload: dict) -> List[dict]:
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.post(BASE_URL + method, json=payload, timeout=60)
            except requests.RequestException as exc:
                last_error = exc
                # The service drops connections when it thinks we are going too
                # fast. Back off progressively.
                time.sleep(self.delay * attempt * 4)
                continue

            if resp.status_code == 401:
                raise TefasError(
                    "TEFAS rejected the bearer token (HTTP 401). It has most likely "
                    "been rotated upstream -- set TEFAS_TOKEN to a fresh value."
                )
            if resp.status_code == 404 and "ERR-006" in resp.text:
                raise TefasError("TEFAS endpoint '{}' no longer exists.".format(method))
            if resp.status_code != 200:
                last_error = TefasError(
                    "HTTP {} from {}".format(resp.status_code, method)
                )
                time.sleep(self.delay * attempt * 4)
                continue

            try:
                body = resp.json()
            except ValueError as exc:
                last_error = exc
                time.sleep(self.delay * attempt * 4)
                continue

            if body.get("errorMessage"):
                raise TefasError(
                    "TEFAS '{}' returned an error: {}".format(method, body["errorMessage"])
                )

            time.sleep(self.delay)
            return body.get("resultList") or []

        raise TefasError(
            "TEFAS '{}' failed after {} attempts: {}".format(method, MAX_RETRIES, last_error)
        )

    # -- endpoints -----------------------------------------------------------

    def returns_universe(self, fund_type: str) -> List[dict]:
        """Whole universe in one call: period returns, category, risk score.

        Returns rows shaped like::

            {"fonKodu", "fonUnvan", "fonTurAciklama", "tefasDurum",
             "getiri1a", "getiri3a", "getiri6a", "getiri1y", "getiriyb",
             "getiri3y", "getiri5y", "getiriOrani", "riskDegeri"}
        """
        # No "islem" key on purpose. The field selects the trading status:
        # 1 returns only the funds traded on TEFAS (1,056 YAT), 0 only those that
        # are not (1,076), and omitting it returns both (2,132) with the
        # `tefasDurum` flag telling them apart.
        #
        # Both are wanted. Plenty of funds outside TEFAS are large and widely
        # held -- TMV alone has 36.5 billion TRY and 12,423 investors -- and
        # leaving them out silently understated the market.
        payload = {
            "dil": "TR",
            "fonTipi": fund_type,
            "donemGetiri1a": "1",
            "donemGetiri3a": "1",
            "donemGetiri6a": "1",
            "donemGetiri1y": "1",
            "donemGetiriyb": "1",
            "donemGetiri3y": "1",
            "donemGetiri5y": "1",
            "calismaTipi": 2,
            "getiriOrani": "1",
        }
        rows = self._post("fonGetiriBazliBilgiGetir", payload)
        for row in rows:
            row["fonTipi"] = fund_type
        return rows

    def fund_snapshot(self, code: str) -> Optional[dict]:
        """Per-fund snapshot: price, daily return, share count, AUM, investors.

        Returns rows shaped like::

            {"fonKodu", "fonUnvan", "sonFiyat", "gunlukGetiri", "payAdet",
             "portBuyukluk", "fonKategori", "kategoriDerece", "kategoriFonSay",
             "yatirimciSayi", "pazarPayi"}
        """
        rows = self._post("fonBilgiGetir", {"dil": "TR", "fonKodu": code})
        return rows[0] if rows else None

    def fund_types(self) -> List[dict]:
        return self._post("fonTurGetir", {"dil": "TR"})

    def probe(self, codes: Iterable[str]) -> Dict[str, float]:
        """Prices for a handful of funds, to test whether a session is out yet.

        A full sweep costs ten minutes; this costs a couple of seconds, so a run
        that fires before TEFAS has published can bail out immediately instead of
        scanning the whole universe for nothing.
        """
        prices: Dict[str, float] = {}
        for code in codes:
            try:
                row = self.fund_snapshot(code)
            except TefasError as exc:
                log.warning("Probe failed for %s: %s", code, exc)
                continue
            if row and row.get("sonFiyat") is not None:
                prices[code] = float(row["sonFiyat"])
        return prices

    # -- composite -----------------------------------------------------------

    def snapshot_many(
        self, codes: Iterable[str], progress_every: int = 100
    ) -> Dict[str, dict]:
        """Fetch snapshots for many funds, skipping the ones that fail.

        A handful of codes always come back empty (funds delisted from the
        platform but still present in the returns table). Those are skipped
        rather than aborting the run.
        """
        codes = list(codes)
        out: Dict[str, dict] = {}
        missing: List[str] = []

        for index, code in enumerate(codes, start=1):
            try:
                row = self.fund_snapshot(code)
            except TefasError as exc:
                log.warning("Snapshot failed for %s: %s", code, exc)
                missing.append(code)
                continue
            if row:
                out[code] = row
            else:
                missing.append(code)

            if progress_every and index % progress_every == 0:
                log.info("Snapshots: %d/%d", index, len(codes))

        if missing:
            log.info("No snapshot for %d fund(s): %s", len(missing), ", ".join(missing[:20]))
        return out
