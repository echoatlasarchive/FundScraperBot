"""Snapshot persistence.

TEFAS exposes no historical endpoint, so the daily snapshot *is* our history.
Each run writes one gzipped CSV keyed by the date the data refers to, and the
files are committed back to the repository -- free, versioned, and directly
consumable by a static site later on.

One file is roughly 40 KB compressed, so a year of trading days costs ~10 MB.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config

log = logging.getLogger(__name__)

FIELDS = [
    "code",
    "name",
    "fund_type",
    "umbrella",
    "category",
    "risk",
    "price",
    "daily_return",
    "shares",
    "aum",
    "investors",
    "market_share",
    "cat_rank",
    "cat_count",
    "ret_1m",
    "ret_3m",
    "ret_6m",
    "ret_1y",
    "ret_ytd",
    "ret_3y",
    "ret_5y",
]

_NUMERIC = {
    "price",
    "daily_return",
    "shares",
    "aum",
    "investors",
    "market_share",
    "cat_rank",
    "cat_count",
    "ret_1m",
    "ret_3m",
    "ret_6m",
    "ret_1y",
    "ret_ytd",
    "ret_3y",
    "ret_5y",
}


# -- record building ---------------------------------------------------------


def build_records(
    returns_rows: List[dict], snapshots: Dict[str, dict]
) -> List[dict]:
    """Merge the universe-wide returns table with the per-fund snapshots."""
    records = []
    for row in returns_rows:
        code = row.get("fonKodu")
        if not code:
            continue
        snap = snapshots.get(code, {})
        records.append(
            {
                "code": code,
                "name": row.get("fonUnvan") or snap.get("fonUnvan") or "",
                "fund_type": row.get("fonTipi") or "",
                "umbrella": row.get("fonTurAciklama") or "",
                "category": snap.get("fonKategori") or "",
                "risk": row.get("riskDegeri") or "",
                "price": snap.get("sonFiyat"),
                "daily_return": snap.get("gunlukGetiri"),
                "shares": snap.get("payAdet"),
                "aum": snap.get("portBuyukluk"),
                "investors": snap.get("yatirimciSayi"),
                "market_share": snap.get("pazarPayi"),
                "cat_rank": snap.get("kategoriDerece"),
                "cat_count": snap.get("kategoriFonSay"),
                "ret_1m": row.get("getiri1a"),
                "ret_3m": row.get("getiri3a"),
                "ret_6m": row.get("getiri6a"),
                "ret_1y": row.get("getiri1y"),
                "ret_ytd": row.get("getiriyb"),
                "ret_3y": row.get("getiri3y"),
                "ret_5y": row.get("getiri5y"),
            }
        )
    return records


# -- dates -------------------------------------------------------------------


# Turkey has been on permanent UTC+3 since abolishing DST in 2016, so a fixed
# offset is exact and avoids depending on a tz database being present on the CI
# runner.
ISTANBUL = timezone(timedelta(hours=3))


def now_istanbul() -> datetime:
    """Current time in the market's own timezone.

    GitHub Actions runners are on UTC. Deriving the trading day from the runner
    clock puts a run made in the Istanbul small hours on the wrong side of
    midnight, which mislabels the snapshot and silently corrupts the flow
    baseline.
    """
    return datetime.now(ISTANBUL)


# TEFAS publishes the previous session's figures during the business morning,
# not at midnight. Measured directly: at 03:09 on Tuesday 2026-08-18 the API
# still served Friday's close, while at 12:03 the same day it served Monday's.
# Runs before this hour therefore see one session *older* than the calendar
# would suggest.
PUBLICATION_HOUR_ISTANBUL = 10


def previous_business_day(day: date, steps: int = 1) -> date:
    for _ in range(steps):
        day -= timedelta(days=1)
        while day.weekday() >= 5:  # skip Sat/Sun
            day -= timedelta(days=1)
    return day


def data_date_for(run_dt: datetime) -> date:
    """Which trading session the data fetched *now* belongs to.

    TEFAS serves a snapshot with no date attached, so the session has to be
    inferred from the clock. After the morning publication window a run sees the
    previous session; before it, the previous session is not out yet and the API
    still serves the one before that.

    Pass a timezone-aware Istanbul timestamp taken once at the start of the run:
    the fetch takes several minutes, so recomputing this afterwards can cross
    midnight and attribute the data to a different day.

    Public holidays are not modelled -- they surface as an unchanged snapshot,
    which :func:`fingerprint` detects.
    """
    steps = 1 if run_dt.hour >= PUBLICATION_HOUR_ISTANBUL else 2
    return previous_business_day(run_dt.date(), steps)


# -- paths -------------------------------------------------------------------


def snapshot_path(day: date) -> Path:
    return config.SNAPSHOT_DIR / "{}.csv.gz".format(day.isoformat())


def list_snapshot_dates() -> List[date]:
    if not config.SNAPSHOT_DIR.exists():
        return []
    dates = []
    for path in config.SNAPSHOT_DIR.glob("*.csv.gz"):
        try:
            dates.append(date.fromisoformat(path.name[: -len(".csv.gz")]))
        except ValueError:
            continue
    return sorted(dates)


# -- read / write ------------------------------------------------------------


def _coerce(value: str):
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return value
    return number


def save_snapshot(day: date, records: List[dict]) -> Path:
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(day)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({k: ("" if record.get(k) is None else record.get(k)) for k in FIELDS})
    log.info("Wrote %d records to %s", len(records), path.name)
    return path


def load_snapshot(day: date) -> Dict[str, dict]:
    path = snapshot_path(day)
    if not path.exists():
        return {}
    out: Dict[str, dict] = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = {k: (_coerce(v) if k in _NUMERIC else v) for k, v in row.items()}
            code = record.get("code")
            if code:
                out[code] = record
    return out


def latest_snapshot_date(before: Optional[date] = None) -> Optional[date]:
    dates = list_snapshot_dates()
    if before is not None:
        dates = [d for d in dates if d < before]
    return dates[-1] if dates else None


def snapshot_on_or_before(day: date) -> Optional[date]:
    dates = [d for d in list_snapshot_dates() if d <= day]
    return dates[-1] if dates else None


# -- staleness ---------------------------------------------------------------


def follows_consecutively(current: List[dict], previous: Dict[str, dict]) -> Optional[bool]:
    """Is ``current`` the session immediately after ``previous``?

    TEFAS attaches no date to its snapshot, so the label is inferred from the
    clock -- and a run made outside the publication window infers it wrongly.
    The price series settles the question independently: on consecutive sessions
    the reported daily return reproduces the price ratio between the two
    snapshots exactly.

    Returns ``None`` when there is too little overlap to judge.
    """
    agree = total = 0
    for code, record in ((r.get("code"), r) for r in current):
        base = previous.get(code)
        if not base:
            continue
        price_now = record.get("price")
        price_before = base.get("price")
        reported = record.get("daily_return")
        if not price_now or not price_before or reported is None:
            continue
        implied = (price_now / price_before - 1.0) * 100.0
        total += 1
        if abs(implied - reported) < 0.02:
            agree += 1

    if total < 50:
        return None
    return agree / total > 0.8


def fingerprint(records: List[dict]) -> str:
    """Content hash used to detect that TEFAS has not published new data yet."""
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda r: r.get("code") or ""):
        digest.update(
            "{}|{}|{}|{}\n".format(
                record.get("code"),
                record.get("price"),
                record.get("shares"),
                record.get("aum"),
            ).encode("utf-8")
        )
    return digest.hexdigest()


# -- small key/value state ---------------------------------------------------


def read_state(name: str) -> dict:
    path = config.STATE_DIR / "{}.json".format(name)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("Could not read state %s: %s", name, exc)
        return {}


def write_state(name: str, payload: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.STATE_DIR / "{}.json".format(name)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
