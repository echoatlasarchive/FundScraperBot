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


def data_date_for(run_dt: datetime) -> date:
    """TEFAS publishes day T's prices on the morning of T+1.

    A run on Monday reports Friday's data; any other weekday reports the day
    before. Public holidays are not modelled -- they surface as an unchanged
    snapshot, which :func:`fingerprint` detects.

    Pass a timezone-aware Istanbul timestamp taken once at the start of the run:
    the fetch takes several minutes, so recomputing this afterwards can cross
    midnight and attribute the data to a different day.
    """
    day = run_dt.date()
    step = 1
    while True:
        candidate = day - timedelta(days=step)
        if candidate.weekday() < 5:  # Mon-Fri
            return candidate
        step += 1


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
