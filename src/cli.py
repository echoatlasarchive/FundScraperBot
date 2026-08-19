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

from . import (
    config,
    formatter,
    infographic,
    kap,
    metrics,
    storage,
    telegram,
    tweets,
)
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

        # Cross-check the inferred label against the price series.
        consecutive = storage.follows_consecutively(records, previous)
        if consecutive:
            log.info("Verified: fetched data is the session after %s.", previous_day)
        elif consecutive is False and data_day == previous_day:
            # Same session fetched again, only with TEFAS's small intraday
            # revisions. Normal for a manual re-run; the stored file is simply
            # refreshed and the baseline stays the session before, so the flow
            # figures are unaffected.
            log.info("Re-fetched session %s; refreshing the snapshot.", previous_day)
        elif consecutive is False:
            log.warning(
                "Fetched data is neither the session after %s nor %s itself, "
                "yet it is being labelled %s. Flow figures may be unreliable.",
                previous_day,
                previous_day,
                data_day,
            )

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


PROBE_CODES = ["PHE", "TP2", "KHA", "TLY", "GCN"]


def session_is_published() -> bool:
    """Has TEFAS put out a session we have not already stored?

    Scheduled runs fire early and often so that the report lands before the
    fund-order cutoff, which means most of them find nothing new. Comparing a
    five-fund probe against the newest snapshot settles that in seconds, instead
    of ten minutes of scanning followed by a duplicate report.
    """
    latest = storage.latest_snapshot_date()
    if latest is None:
        return True  # nothing stored yet, so anything is new

    stored = storage.load_snapshot(latest)
    prices = TefasClient().probe(PROBE_CODES)
    if not prices:
        log.warning("Probe returned nothing; continuing with the full run.")
        return True

    changed = [
        code
        for code, price in prices.items()
        if code in stored and abs(price - float(stored[code]["price"])) > 1e-9
    ]
    log.info(
        "Probe against %s: %d/%d prices moved.", latest, len(changed), len(prices)
    )
    return bool(changed)


def resolve_data_day(records: List[dict], run_dt) -> date:
    """Which session the fetched data belongs to.

    Preferred answer comes from the snapshot chain: if the price identity
    confirms this data is the session right after the newest stored one, then
    that is what it is, whatever the clock says. The clock rule is only a
    fallback for the first run, or after a gap the chain cannot bridge.
    """
    latest = storage.latest_snapshot_date()
    if latest is not None:
        previous = storage.load_snapshot(latest)
        if previous and storage.follows_consecutively(records, previous):
            day = storage.next_business_day(latest)
            log.info("Session chain: %s -> %s.", latest, day)
            return day

    day = storage.data_date_for(run_dt)
    log.info("Falling back to the clock: trading day %s.", day)
    return day


def run_daily(args) -> Optional[List[str]]:
    # Pin the clock before fetching: collect() runs for several minutes, and a
    # run started late in the Istanbul evening would otherwise cross midnight
    # and file the data under the wrong trading day.
    run_dt = storage.now_istanbul()
    log.info("Run at %s (Istanbul).", run_dt.isoformat(timespec="seconds"))

    if args.only_if_new and not session_is_published():
        log.info("No new session yet; a later run will pick it up.")
        return None

    records = collect()
    data_day = resolve_data_day(records, run_dt)
    effective_day, is_new = store(records, data_day)

    if args.only_if_new and not is_new:
        log.info("Session %s was already reported; nothing to send.", effective_day)
        return None

    if not is_new:
        records = list(storage.load_snapshot(effective_day).values())

    baseline_day, baseline = _baseline(effective_day, None)
    records = metrics.attach_deltas(records, baseline)

    log.info("Coverage: %s", metrics.coverage(records))

    # KAP is keyed by fund name, not code, so pass both. The window is anchored
    # on the calendar day the report is sent, not the trading session it covers:
    # disclosures published this morning are news even though the prices are not.
    by_code = metrics.index_by_code(records)
    watched = [
        (code, by_code[code].get("name") or "")
        for code in config.ALL_WATCHED
        if code in by_code
    ]
    kap_items = kap.fetch_disclosures(watched, today=run_dt.date())
    kap_note = None if kap.ENABLED else kap.DISABLED_NOTE

    common = dict(
        records=records,
        data_day=effective_day,
        run_day=run_dt.date(),
        baseline_day=baseline_day,
        kap_items=kap_items,
        kap_note=kap_note,
    )

    cards = _build_cards(records, effective_day)
    channel = config.telegram_channel_id()

    if not args.dry_run:
        if channel:
            # Posted separately from the owner's copy, and without the
            # watchlists. A channel failure must not cost the owner their
            # report, so it is attempted first and its errors are swallowed.
            try:
                telegram.send(
                    formatter.daily_report(public=True, **common), chat_id=channel
                )
                _send_cards(cards, effective_day, channel)
            except Exception as exc:  # noqa: BLE001 - the private report matters more
                log.warning("Could not post to the public channel: %s", exc)

        _send_cards(cards, effective_day, None)

        # Drafts are for the owner to edit and post by hand; they never go to
        # the channel.
        try:
            drafts = tweets.build_drafts(records, effective_day, run_dt.date())
            telegram.send(tweets.as_message(drafts))
            log.info("Sent %d tweet draft(s).", len(drafts))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not send tweet drafts: %s", exc)

    return formatter.daily_report(**common)


def _build_cards(records: List[dict], day: date) -> List:
    try:
        return infographic.build_cards(records, day, config.CARD_DIR)
    except Exception as exc:  # noqa: BLE001 - the text report is what matters
        log.warning("Could not render infographics: %s", exc)
        return []


def _send_cards(cards: List, day: date, chat_id: Optional[str]) -> None:
    for path in cards:
        kind = "tefas" if "tefas" in path.name else "befas"
        telegram.send_photo(path, infographic.caption(kind, day), chat_id=chat_id)


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
        "--only-if-new",
        action="store_true",
        help="exit quietly unless TEFAS has published a session we have not stored",
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
