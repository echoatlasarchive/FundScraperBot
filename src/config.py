"""Static configuration and environment wiring.

Secrets are never stored here -- they come from the environment (GitHub Secrets
in CI, a local .env-style export when running by hand).
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
STATE_DIR = DATA_DIR / "state"

# --- Watchlist -------------------------------------------------------------
# Funds the daily message always reports on, whatever their ranking.

WATCHLIST = ["PHE", "TLY", "KHA", "THF"]
MONEY_MARKET_WATCHLIST = ["TP2", "PRY", "PNU"]

ALL_WATCHED = WATCHLIST + MONEY_MARKET_WATCHLIST

# --- Universe filters ------------------------------------------------------

# Funds smaller than this are excluded from every ranking. Tiny funds routinely
# post absurd percentage moves that would otherwise dominate the leaderboards.
MIN_AUM_TRY = 100_000_000.0

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

# How many funds appear in each ranking table.
TOP_N = 10

# --- TEFAS categories ------------------------------------------------------

# Substring match against `fonKategori` / `fonTurAciklama` to split the money
# market funds into their own section.
MONEY_MARKET_KEYWORDS = ("para piyasası",)

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
