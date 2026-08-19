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

# Funds the commentary tweets talk about by name, grouped so each line of the
# "popular funds" post has a point to make. Codes are verified against the
# snapshot at run time and silently dropped if a fund disappears.
POPULAR_GROUPS = [
    ("Popüler serbest fonlar", ["TLY", "DOH", "DFI"]),
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
# (the PDFs in blockchain/). Weight is the share of the whole portfolio.
#
# This is a hand-refreshed snapshot, not live data. Fund portfolios are disclosed
# monthly and TEFAS serves no breakdown at all -- its portfolio endpoint is one
# of the retired ones -- so there is nothing to poll. Re-run the extraction when
# new monthly reports land and update the month below with it.
#
# IJP is absent on purpose: its report lists quantities and prices but no
# per-holding weight, so any figure here would have been invented.
CRYPTO_HOLDINGS_MONTH = "Temmuz 2026"
CRYPTO_HOLDINGS = {
    "RBL": (24.8, ["BLCN %12,9", "BLOK %11,9"]),
    "IVY": (20.3, ["HOOD %3,7", "MARA %3,4", "MSTR %3,1", "GLXY %2,3"]),
    "BCK": (17.0, ["BLCN %4,7", "BLOK %3,7", "HOOD %3,1", "CLSK %1,2"]),
    "ZFB": (12.3, ["HOOD %2,4", "XYZ %2,3", "RIOT %2,1", "HUT %2,1"]),
    "GBV": (7.0, ["CORZ %2,8", "CIFR %2,4", "MARA %0,9"]),
    "YZC": (4.5, ["XYZ %2,6", "MSTR %2,0"]),
    "FJB": (2.3, ["APLD %2,3"]),
}

# A move smaller than this is not worth a post. A metals fund up 0.11% on the
# day says nothing to anyone, and publishing it trains readers to ignore the
# account.
MIN_TWEETWORTHY_RETURN_PCT = 1.0
MIN_TWEETWORTHY_FLOW_TRY = 100_000_000.0
MIN_TWEETWORTHY_INVESTORS = 500

# Every post carries this, per the account's own notice.
TWEET_SUFFIX = "ytd"

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
