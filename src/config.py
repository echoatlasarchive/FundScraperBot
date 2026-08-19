"""Static configuration and environment wiring.

Secrets are never stored here -- they come from the environment (GitHub Secrets
in CI, a local .env-style export when running by hand).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# --- Paths -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
STATE_DIR = DATA_DIR / "state"
# Rendered infographic cards. Committed alongside the snapshots so the
# channel history stays reproducible.
CARD_DIR = DATA_DIR / "cards"

# --- Watchlist -------------------------------------------------------------
# Funds the daily message always reports on, whatever their ranking.

WATCHLIST = ["PHE", "TLY", "KHA", "THF"]
MONEY_MARKET_WATCHLIST = ["TP2", "PRY", "PNU"]

# BEFAS (pension) side, reported under its own heading.
BEFAS_WATCHLIST = ["GGJ", "TVH", "GCN", "FFC", "NHN", "BZY"]

ALL_WATCHED = WATCHLIST + MONEY_MARKET_WATCHLIST + BEFAS_WATCHLIST

# --- Universe filters ------------------------------------------------------

# Funds smaller than this are excluded from every ranking. Tiny funds routinely
# post absurd percentage moves that would otherwise dominate the leaderboards.
MIN_AUM_TRY = 100_000_000.0

# Assets alone do not separate a retail fund from a private vehicle. Plenty of
# "Serbest" funds hold hundreds of millions of lira on behalf of a handful of
# investors, and their returns are speculative rather than representative --
# before this filter the top-10 daily gainers included funds with 17, 19 and 23
# investors.
#
# Set to 5,000 by preference. For reference, at 1,000 the eligible universe was
# 761 funds with Serbest at 13.5%; at 5,000 it is roughly 460 with Serbest near
# 7%, so the leaderboards lean further towards widely held retail funds.
MIN_INVESTORS = 5_000

# Sanity bounds for a single day's return, in percent. Anything outside this is
# treated as a data artifact (share splits/merges, redenominations) and dropped
# from rankings. TLY, for example, reports a 5-year return of ~589,891%.
MAX_ABS_DAILY_RETURN_PCT = 25.0

# Same idea for period returns used in weekly/monthly rankings.
MAX_ABS_PERIOD_RETURN_PCT = 5_000.0

# Net flow is derived from the change in units outstanding, so a share split or
# merger looks like an enormous inflow or outflow even though no money moved.
# A single-day flow worth more than this share of the fund's assets is treated
# as a restructuring artifact and kept out of the rankings.
MAX_ABS_FLOW_PCT = 200.0

# Every ranking table shows five funds. Longer tables pushed the daily message
# past what is comfortable to read on a phone.
TOP_N = 5
SUB_TOP_N = 5

# --- TEFAS categories ------------------------------------------------------

# Matched against a case- and diacritic-folded blend of the fund's category,
# umbrella type and name, to split it out into its own report section.
MONEY_MARKET_KEYWORDS = ("para piyasasi",)

# Gold, silver and mixed precious-metal funds. These live under several
# different categories -- "Altın Fonu", "Altın Katılım Fonu", "Kıymetli
# Madenler", and silver basket funds filed as plain "Fon Sepeti Fonu" -- so the
# fund name has to be consulted too.
#
# Matching is done on word boundaries, which matters: "ALTINCI" means "sixth",
# not "gold". A naive substring search pulls in AK Portföy Altıncı Serbest and
# Kuveyt Türk Altıncı Katılım, which are ordinary hedge funds.
PRECIOUS_METAL_PATTERNS = (
    r"\baltin\b",
    r"\bgümüş\b",
    r"\bplatin\b",
    r"\bpaladyum\b",
    r"kiymetli maden",
)

# --- Commentary tweets -----------------------------------------------------

# Funds TEFAS does not trade that are still wanted by name, because the
# commentary talks about them.
#
# NOTHING ELSE from the untraded universe is ever fetched. Those funds cannot be
# bought on TEFAS, so they must never appear in a ranking, a comparison or any
# research -- only the codes listed here, and only where they are named.
EXTRA_FUND_CODES = ["TMV"]

# Funds the commentary tweets talk about by name, grouped so each line of the
# "popular funds" post has a point to make. Codes are verified against the
# snapshot at run time and silently dropped if a fund disappears.
POPULAR_GROUPS = [
    ("Popüler serbest fonlar", ["TLY", "TMV", "DOH", "DFI"]),
    ("Para ve yatırımcı çeken fonlar", ["THF", "KHA"]),
    ("Yılbaşından beri güçlü, son ayda zorlanan", ["PHE", "PBR"]),
]

# Crypto exposure is not a TEFAS category, so it has to be matched by name.
# "teknoloji" is useless here -- it pulls in 77 funds, nearly all semiconductor,
# defence or health. These five terms return exactly the blockchain and fintech
# funds and nothing else.
CRYPTO_NAME_PATTERNS = (
    "blockchain",
    "blokchain",
    "blokzinciri",
    "blok zinciri",
    "fintek",
    "fintech",
)

# Crypto exposure read out of the funds' own KAP portfolio reports for July 2026
# (the PDFs in blockchain/). The figure is the share of the fund's *total* value
# -- the "TOPLAM (FTD GÖRE)" column -- so it answers "how much of this fund is
# crypto", which is the question the card and the tweet ask.
#
# This is a hand-refreshed snapshot, not live data. Fund portfolios are disclosed
# monthly and TEFAS serves no breakdown at all -- its portfolio endpoint is one
# of the retired ones -- so there is nothing to poll. Re-run the extraction when
# new monthly reports land and update the month below with it.
#
# **What counts as crypto**, applied identically to all eight funds:
#
#   * companies whose business *is* crypto -- miners (MARA, RIOT, CLSK, CIFR,
#     WULF, HUT, IREN, BTDR, CORZ, HIVE, APLD), crypto-native financials (GLXY,
#     CRCL, HOOD), bitcoin treasuries (MSTR) and Block (XYZ);
#   * blockchain-thematic ETFs at face value (BLCN, BLOK, BCHN, IBLC), since
#     that is what they are built to hold.
#
# Excluded: diversified tech and semis (NVDA, AMD, MSFT, AAPL, MU, TSM, ...),
# general finance and payments (V, MA, PYPL, JPM, GS, BLK, NDAQ, CME, IBKR),
# broad-innovation ETFs (ARKW, QQQ, FINX, ROBT, AIQ, THNQ, WTAI), and firms with
# only a crypto subsidiary (SBI Holdings, GMO Internet, Customers Bancorp).
# KEEL Infrastructure -- held by IVY (2.4), BCK (0.7) and GBV (1.5) -- is counted
# in, by the owner's decision. It is the one position on this list whose business
# could not be verified from the reports themselves, so it is called out here
# rather than buried: if it ever turns out not to be crypto-linked, those three
# funds are the ones to correct, and by those amounts.
#
# Two of these funds hold *other funds on this list* -- YZC holds IJP, and FJB
# holds GBV, IJP, YZC and ZFB. Those are looked through at the held fund's own
# measured weight rather than counted at face value, because the alternative
# reports FJB at 16.8% when only about 4.5% of it is crypto. FJB's own direct
# crypto holding is a single position (APLD); everything else it has comes
# through the four Turkish funds.
#
# Reading the reports is the awkward part, and every issuer lays them out
# differently: RBL, IVY, BCK, ZFB and FJB print a plain FTD column; GBV's PDF is
# OCR-damaged (digits come out as letters, "5" as "S") and splits each position
# over many purchase lots that have to be summed; IJP puts the numbers and the
# security names in separate text blocks that have to be paired by position --
# there, the currency column confirms the pairing, and every weight was
# cross-checked against value / fund total.
CRYPTO_HOLDINGS_MONTH = "Temmuz 2026"
CRYPTO_HOLDINGS = {
    "RBL": (38.3, ["BLCN %12,9", "BLOK %11,7", "BCHN %7,2", "IBLC %6,6"]),
    "IVY": (28.9, ["HOOD %3,7", "IBLC %3,5", "MARA %3,4", "MSTR %3,0"]),
    "GBV": (22.3, ["CORZ %3,3", "BCHN %3,1", "XYZ %2,7", "MARA %2,3"]),
    "BCK": (18.6, ["BLCN %4,7", "BLOK %3,7", "HOOD %3,0", "CLSK %1,2"]),
    "ZFB": (12.3, ["HOOD %2,4", "XYZ %2,3", "RIOT %2,1", "HUT %2,1"]),
    "IJP": (11.0, ["BLCN %2,1", "CIFR %2,1", "HOOD %1,6", "MARA %1,1"]),
    "YZC": (4.7, ["XYZ %2,5", "MSTR %2,0", "IJP fonu %1,8"]),
    "FJB": (4.6, ["APLD %2,3", "GBV fonu %7,4", "IJP fonu %2,7"]),
}

# A move smaller than this is not worth a post. A metals fund up 0.11% on the
# day says nothing to anyone, and publishing it trains readers to ignore the
# account.
MIN_TWEETWORTHY_RETURN_PCT = 1.0
MIN_TWEETWORTHY_FLOW_TRY = 100_000_000.0
MIN_TWEETWORTHY_INVESTORS = 500

# Every post carries this, per the account's own notice.
TWEET_SUFFIX = "ytd"

# --- Delivery window -------------------------------------------------------

# Istanbul hours, [start, end), during which a report may actually be delivered.
#
# Nothing else in the pipeline knows what time it is. The schedule decides when
# the bot runs, so anything that fires the workflow outside the schedule -- a
# manual dispatch made while testing, a re-run of an old job, a cron someone
# edits -- delivers a full report to the public channel at that hour. That has
# happened once already: a dispatch at 01:46 Istanbul put the report, the cards
# and the tweet drafts out at 02:17 in the morning.
#
# The bounds come from what the report is for. TEFAS publishes the previous
# session during the business morning (see storage.PUBLICATION_HOUR_ISTANBUL),
# and the message is only useful before the 13:30 fund-order cutoff, so a
# delivery outside 07:00-14:00 is by definition not the delivery the schedule
# intended. Out of the window the run still fetches, stores and prints; it just
# sends nothing, unless --force says otherwise.
DELIVERY_WINDOW_ISTANBUL = (7, 14)


def within_delivery_window(moment) -> bool:
    start, end = DELIVERY_WINDOW_ISTANBUL
    return start <= moment.hour < end


# --- Public channel --------------------------------------------------------

# The public report deliberately omits the watchlists. Those are the owner's own
# holdings: publishing them would expose a personal portfolio, and framing a
# named set of funds as "mine" reads uncomfortably close to a recommendation.
# The channel gets the rankings and the KAP disclosures, which is what it
# promises its readers anyway.
PUBLIC_DISCLAIMER = (
    "Burada yer alan veriler kamuya açık TEFAS, BEFAS ve KAP kaynaklarından "
    "derlenmiştir. Yatırım tavsiyesi değildir."
)


# --- Runtime secrets -------------------------------------------------------


def telegram_token() -> str:
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_TOKEN is not set. Export it locally or add it as a GitHub "
            "Actions secret; never commit it."
        )
    return token


def telegram_chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set.")
    return chat_id


def telegram_channel_id() -> Optional[str]:
    """Public channel, if one is configured.

    Optional: without it the bot simply reports to its owner as before.
    """
    channel = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    return channel or None
