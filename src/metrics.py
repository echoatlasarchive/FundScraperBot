"""Derived metrics: fund flows, deltas and rankings.

The important one is *net flow*. Comparing assets under management day over day
conflates two different things: money moving in or out, and the portfolio simply
going up or down in value. A fund that gained 5% shows a bigger AUM without a
single lira being invested.

Share count separates them. ``payAdet`` is the number of units outstanding, so::

    net_flow = (shares_today - shares_yesterday) * price_today

is money that actually entered or left the fund, with performance stripped out.
(TEFAS is internally consistent here: shares * price reproduces the reported AUM
to within rounding.)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import config


# -- classification ----------------------------------------------------------


def fold(text: str) -> str:
    """Case- and diacritic-fold Turkish text so matching is predictable.

    Turkish has a dotted/dotless i split that ``str.lower()`` gets wrong for our
    purposes: "ALTIN" (written with Latin I) lowercases to "altin", while
    "Altın" lowercases to "altın". Folding both dotted and dotless forms to a
    plain "i" makes the two comparable.
    """
    return (
        (text or "")
        .replace("İ", "i")
        .replace("I", "i")
        .lower()
        .replace("ı", "i")
    )


def _haystack(record: dict) -> str:
    return fold(
        "{} {} {}".format(
            record.get("category") or "",
            record.get("umbrella") or "",
            record.get("name") or "",
        )
    )


def is_money_market(record: dict) -> bool:
    haystack = _haystack(record)
    return any(keyword in haystack for keyword in config.MONEY_MARKET_KEYWORDS)


def is_precious_metal(record: dict) -> bool:
    haystack = _haystack(record)
    return any(
        re.search(pattern, haystack) for pattern in config.PRECIOUS_METAL_PATTERNS
    )


def is_pension(record: dict) -> bool:
    return (record.get("fund_type") or "") == "EMK"


def is_tefas(record: dict) -> bool:
    return (record.get("fund_type") or "") == "YAT"


# -- eligibility -------------------------------------------------------------


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def passes_size_filter(record: dict) -> bool:
    aum = _num(record.get("aum"))
    return aum is not None and aum >= config.MIN_AUM_TRY


def passes_investor_filter(record: dict) -> bool:
    investors = _num(record.get("investors"))
    return investors is not None and investors >= config.MIN_INVESTORS


def plausible_daily_return(record: dict) -> bool:
    ret = _num(record.get("daily_return"))
    return ret is not None and abs(ret) <= config.MAX_ABS_DAILY_RETURN_PCT


def plausible_period_return(value) -> bool:
    ret = _num(value)
    return ret is not None and abs(ret) <= config.MAX_ABS_PERIOD_RETURN_PCT


def eligible_universe(records: List[dict]) -> List[dict]:
    """Funds large and widely held enough to appear in a ranking."""
    return [
        r for r in records if passes_size_filter(r) and passes_investor_filter(r)
    ]


# -- deltas ------------------------------------------------------------------


def _is_discontinuous(record: dict, base: dict) -> bool:
    """Detect a share split, merger or redenomination between two snapshots.

    A split multiplies units outstanding and divides the price by the same
    factor, so it reads as an enormous inflow. It cannot be caught by comparing
    flow against the AUM change, because

        aum_now - aum_before == flow + shares_before * (price_now - price_before)

    is an algebraic identity that holds for splits and genuine flows alike.

    What does separate them is the price series. TEFAS reports ``gunlukGetiri``
    independently of the price level, so on a normal day the price ratio matches
    the reported return. Across a split it does not: the price collapses while
    the reported return stays ordinary.

    Only meaningful when the baseline is the immediately preceding trading day;
    across a longer gap the implied return covers several days and the check is
    skipped by the caller.
    """
    price_now = _num(record.get("price"))
    price_before = _num(base.get("price"))
    reported = _num(record.get("daily_return"))

    if not price_now or not price_before or reported is None:
        return False

    implied = (price_now / price_before - 1.0) * 100.0
    tolerance = max(2.0, abs(reported) * 0.5)
    return abs(implied - reported) > tolerance


def attach_deltas(
    current: List[dict],
    previous: Dict[str, dict],
    consecutive: bool = True,
) -> List[dict]:
    """Annotate each record with flow / AUM / investor changes against a baseline.

    Records with no baseline (new funds, or the very first run) get ``None`` for
    every delta rather than a misleading zero.

    ``consecutive`` says whether ``previous`` is the immediately preceding
    trading day. When it is, each record is additionally checked for a price
    discontinuity and flagged via ``flow_artifact`` so that splits stay out of
    the flow rankings.
    """
    out = []
    for record in current:
        enriched = dict(record)
        base = previous.get(record.get("code"))

        flow = aum_change = investor_change = flow_pct = aum_change_pct = None
        artifact = False

        if base:
            artifact = consecutive and _is_discontinuous(record, base)
            shares_now = _num(record.get("shares"))
            shares_before = _num(base.get("shares"))
            price_now = _num(record.get("price"))
            aum_now = _num(record.get("aum"))
            aum_before = _num(base.get("aum"))
            inv_now = _num(record.get("investors"))
            inv_before = _num(base.get("investors"))

            if None not in (shares_now, shares_before, price_now):
                flow = (shares_now - shares_before) * price_now
                if aum_before:
                    flow_pct = flow / aum_before * 100.0

            if None not in (aum_now, aum_before):
                aum_change = aum_now - aum_before
                if aum_before:
                    aum_change_pct = aum_change / aum_before * 100.0

            if None not in (inv_now, inv_before):
                investor_change = int(inv_now - inv_before)

        enriched["flow"] = flow
        enriched["flow_pct"] = flow_pct
        enriched["aum_change"] = aum_change
        enriched["aum_change_pct"] = aum_change_pct
        enriched["investor_change"] = investor_change
        enriched["flow_artifact"] = artifact
        out.append(enriched)
    return out


def period_return(current: dict, base: dict) -> Optional[float]:
    """Percent price return between two of our own snapshots."""
    price_now = _num(current.get("price"))
    price_before = _num(base.get("price"))
    if not price_now or not price_before:
        return None
    return (price_now / price_before - 1.0) * 100.0


def attach_period_returns(
    current: List[dict], baseline: Dict[str, dict], key: str = "period_return"
) -> List[dict]:
    out = []
    for record in current:
        enriched = dict(record)
        base = baseline.get(record.get("code"))
        enriched[key] = period_return(record, base) if base else None
        out.append(enriched)
    return out


# -- rankings ----------------------------------------------------------------


def top_by(
    records: List[dict],
    key: str,
    reverse: bool = True,
    limit: int = config.TOP_N,
    guard: Optional[str] = None,
) -> List[dict]:
    """Sort by ``key``, dropping records where it is missing.

    ``guard`` names a plausibility check: ``"daily"``, ``"period"`` or
    ``"flow"``. Tiny or restructured funds otherwise dominate every leaderboard
    with values that are data artifacts rather than performance. Flows default
    to the flow guard, since a share split fakes a huge inflow.
    """
    if guard is None and key == "flow":
        guard = "flow"

    pool = []
    for record in records:
        value = _num(record.get(key))
        if value is None:
            continue
        if guard == "daily" and abs(value) > config.MAX_ABS_DAILY_RETURN_PCT:
            continue
        if guard == "period" and abs(value) > config.MAX_ABS_PERIOD_RETURN_PCT:
            continue
        if guard == "flow":
            if record.get("flow_artifact"):
                continue
            share = _num(record.get("flow_pct"))
            if share is None or abs(share) > config.MAX_ABS_FLOW_PCT:
                continue
        pool.append((value, record))

    pool.sort(key=lambda pair: pair[0], reverse=reverse)
    return [record for _, record in pool[:limit]]


def split_money_market(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Return ``(non_money_market, money_market)``."""
    mm, rest = [], []
    for record in records:
        (mm if is_money_market(record) else rest).append(record)
    return rest, mm


def split_segments(records: List[dict]) -> Dict[str, List[dict]]:
    """Partition funds into the sections the report prints.

    Money-market and precious-metal funds get their own tables, so they are
    kept out of ``general``. Otherwise a rally in gold fills every slot of the
    headline leaderboard with the same trade, which says nothing the dedicated
    metals table would not already show.
    """
    segments: Dict[str, List[dict]] = {
        "general": [],
        "money_market": [],
        "metals": [],
    }
    for record in records:
        if is_money_market(record):
            segments["money_market"].append(record)
        elif is_precious_metal(record):
            segments["metals"].append(record)
        else:
            segments["general"].append(record)
    return segments


def split_by_platform(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Return ``(tefas, befas)`` -- securities funds and pension funds."""
    tefas = [r for r in records if not is_pension(r)]
    befas = [r for r in records if is_pension(r)]
    return tefas, befas


def index_by_code(records: List[dict]) -> Dict[str, dict]:
    return {r["code"]: r for r in records if r.get("code")}


# -- coverage ----------------------------------------------------------------


def coverage(records: List[dict]) -> dict:
    """Summary used to decide whether a section has enough data to be printed."""
    return {
        "total": len(records),
        "with_aum": sum(1 for r in records if _num(r.get("aum")) is not None),
        "with_flow": sum(1 for r in records if _num(r.get("flow")) is not None),
        "big_enough": sum(1 for r in records if passes_size_filter(r)),
        # The number that actually reaches the rankings -- both filters applied.
        "eligible": len(eligible_universe(records)),
    }
