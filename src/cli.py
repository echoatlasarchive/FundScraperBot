"""Command line entry point.

    python -m src.cli daily            fetch, store, send the daily report
    python -m src.cli weekly           weekly report (baseline ~7 days back)
    python -m src.cli monthly          monthly report (baseline ~30 days back)
    python -m src.cli fetch            fetch and store only, send nothing
    python -m src.cli daily --dry-run  print the report instead of sending it
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from . import config, formatter, kap, metrics, storage, telegram
from .tefas import TefasClient, TefasError

log = logging.getLogger("fundbot")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# -- data acquisition --------------------------------------------------------


def collect(watchlist_only: bool = False) -> List[dict]:
    """Fetch the whole universe and merge in the per-fund snapshots."""
    client = TefasClient()

    returns_rows: List[dict] = []
    for fund_type in ("YAT", "EMK"):
        rows = client.returns_universe(fund_type)
        log.info("%s universe: %d funds.", fund_type, len(rows))
        returns_rows.extend(rows)

    if not returns_rows:
        raise TefasError("TEFAS returned an empty universe.")

    codes = [r["fonKodu"] for r in returns_rows if r.get("fonKodu")]
    if watchlist_only:
        codes = [c for c in codes if c in config.ALL_WATCHED]

    log.info("Fetching per-fund snapshots for %d funds...", len(codes))
    snapshots = client.snapshot_many(codes)
    log.info("Got %d snapshots.", len(snapshots))

    return storage.build_records(returns_rows, snapshots)


def store(records: List[dict], data_day: date) -> Tuple[date, bool]:
    """Persist a snapshot. Returns ``(effective_day, is_new_data)``.

    If the content matches the most recent stored snapshot, TEFAS has not
    published anything new -- a public holiday, or a run that fired early. The
    file is not rewritten and the caller is told to report against the old day.
    """
    previous_day = storage.latest_snapshot_date()
    if previous_day is not None:
        previous = storage.load_snapshot(previous_day)
        if previous and storage.fingerprint(list(previous.values())) == storage.fingerprint(records):
            log.warning(
                "Fetched data is identical to %s -- TEFAS has not published new "
                "figures. Not writing a new snapshot.",
                previous_day,
            )
            return previous_day, False

        # Cross-check the inferred label against the price series. A mismatch
        # means the clock-based guess is wrong -- typically a run made outside
        # the publication window, which would silently corrupt the flow
        # baseline by comparing a session against itself.
        consecutive = storage.follows_consecutively(records, previous)
        if consecutive is False:
            log.warning(
                "Fetched data does not look like the session right after %s, "
                "but it is being labelled %s. Flow figures may be unreliable; "
                "check the publication window.",
                previous_day,
                data_day,
            )
        elif consecutive:
            log.info("Verified: fetched data is the session after %s.", previous_day)

    storage.save_snapshot(data_day, records)
    return data_day, True


# -- baselines ---------------------------------------------------------------


def _baseline(current_day: date, days_back: Optional[int]) -> Tuple[Optional[date], Dict[str, dict]]:
    """Pick the stored snapshot to compare against.

    ``days_back=None`` means "the previous stored snapshot", used by the daily
    report. Weekly and monthly ask for the newest snapshot at or before the
    target date, so a missing day degrades to the closest earlier one instead of
    dropping the section.
    """
    if days_back is None:
        day = storage.latest_snapshot_date(before=current_day)
    else:
        day = storage.snapshot_on_or_before(current_day - timedelta(days=days_back))
        if day == current_day:
            day = None

    if day is None:
        return None, {}
    return day, storage.load_snapshot(day)


# -- commands ----------------------------------------------------------------


def run_daily(args) -> List[str]:
    # Pin the clock before fetching: collect() runs for several minutes, and a
    # run started late in the Istanbul evening would otherwise cross midnight
    # and file the data under the wrong trading day.
    run_dt = storage.now_istanbul()
    data_day = storage.data_date_for(run_dt)
    log.info("Run at %s (Istanbul) -> trading day %s", run_dt.isoformat(timespec="seconds"), data_day)

    records = collect()
    effective_day, is_new = store(records, data_day)

    if not is_new:
        records = list(storage.load_snapshot(effective_day).values())

    baseline_day, baseline = _baseline(effective_day, None)
    records = metrics.attach_deltas(records, baseline)

    log.info("Coverage: %s", metrics.coverage(records))

    kap_items = kap.fetch_disclosures(config.ALL_WATCHED, effective_day)
    kap_note = None if kap.ENABLED else kap.DISABLED_NOTE

    return formatter.daily_report(
        records=records,
        data_day=effective_day,
        run_day=run_dt.date(),
        baseline_day=baseline_day,
        kap_items=kap_items,
        kap_note=kap_note,
    )


def _run_period(days_back: int, builder) -> List[str]:
    current_day = storage.latest_snapshot_date()
    if current_day is None:
        raise RuntimeError("No snapshots stored yet. Run 'daily' or 'fetch' first.")

    records = list(storage.load_snapshot(current_day).values())
    baseline_day, baseline = _baseline(current_day, days_back)

    if baseline_day is None:
        return builder(records, current_day, None)

    # The baseline is a week or a month back, so the price-discontinuity check
    # does not apply -- it compares against a single day's reported return.
    records = metrics.attach_deltas(records, baseline, consecutive=False)
    records = metrics.attach_period_returns(records, baseline)
    return builder(records, current_day, baseline_day)


def run_weekly(args) -> List[str]:
    return _run_period(7, formatter.weekly_report)


def run_monthly(args) -> List[str]:
    return _run_period(30, formatter.monthly_report)


def run_fetch(args) -> Optional[List[str]]:
    data_day = storage.data_date_for(storage.now_istanbul())
    records = collect(watchlist_only=args.watchlist_only)
    effective_day, is_new = store(records, data_day)
    log.info("Stored %s (new data: %s).", effective_day, is_new)
    return None


COMMANDS = {
    "daily": run_daily,
    "weekly": run_weekly,
    "monthly": run_monthly,
    "fetch": run_fetch,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fundbot", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument(
        "--dry-run", action="store_true", help="print the report instead of sending it"
    )
    parser.add_argument(
        "--watchlist-only",
        action="store_true",
        help="fetch only the watched funds (fast, for testing)",
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="do not send a Telegram alert when the run fails",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    try:
        message = COMMANDS[args.command](args)
    except Exception as exc:  # noqa: BLE001 - top level guard
        log.exception("Run failed.")
        if not args.no_alert and not args.dry_run:
            telegram.send_alert("{}: {}".format(type(exc).__name__, exc))
        return 1

    if message is None:
        return 0

    if args.dry_run:
        telegram.preview(message)
    else:
        telegram.send(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
