"""Daily infographic cards for TEFAS and BES.

Rendered as HTML and screenshotted through the Chromium that Playwright already
installs for the KAP scraper, so the cards cost no extra dependency.

Landscape, 1920 wide, two columns, growing in height to fit their content -- a
fixed height silently cut off the last section and, worse, the disclaimer.

Fund names are printed in full and wrap onto a second line rather than being
truncated: an abbreviated Turkish fund name is frequently ambiguous, since whole
families differ only in their last word ("... BİRİNCİ / İKİNCİ SERBEST FON").

TEFAS needs seven tables and BES four; four tables is what a readable landscape
card holds, so TEFAS is split across two cards and BES takes one.

Palette, type and the question-mark mark mirror ``brand/build_brand.py``. If the
brand changes, change it in both.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import date
from typing import Callable, List, Optional, Sequence

from . import config, formatter, metrics

log = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the environment
    sync_playwright = None

ENABLED = sync_playwright is not None

# --- brand (mirrors brand/build_brand.py) -----------------------------------

FOREST = "#16342A"
CHALK = "#E8E4D9"
AMBER = "#E0A33C"
MUTED = "#8FA79B"
RULE = "#274539"
RED = "#D9705A"

SANS = "'Helvetica Neue',Helvetica,Arial,sans-serif"
HOOK = "M 322 352 C 322 168, 706 168, 706 358 C 706 496, 512 492, 512 606"

WIDTH, MIN_HEIGHT = 1920, 1080

# Four tables is what fits a landscape card two columns wide without shrinking
# the type past readable.
TABLES_PER_CARD = 4


def _mark(px: int) -> str:
    return (
        f'<svg viewBox="0 0 1024 1024" width="{px}" height="{px}">'
        f'<g transform="translate(0,34)">'
        f'<path d="{HOOK}" fill="none" stroke="{CHALK}" stroke-width="94" '
        f'stroke-linecap="round"/>'
        f'<text x="512" y="838" font-family="{SANS}" font-weight="700" '
        f'font-size="228" fill="{AMBER}" text-anchor="middle">₺</text>'
        f"</g></svg>"
    )


def fund_name(record: dict) -> str:
    """The full registered name, whitespace tidied. Never truncated."""
    return " ".join((record.get("name") or "").split())


def _esc(text: str) -> str:
    return formatter.esc(text)


# --- value formatters -------------------------------------------------------


def _pct(record: dict) -> str:
    return formatter.percent(record.get("daily_return"))


def _flow(record: dict) -> str:
    return formatter.money(record.get("flow"), signed=True)


def _investors(record: dict) -> str:
    # signed_int uses an ASCII hyphen so the Telegram <pre> tables stay aligned;
    # the cards are not fixed-width, so they take the typographic minus that the
    # money figures beside them already use.
    text = formatter.signed_int(record.get("investor_change")).replace("-", "\u2212")
    return "{} kişi".format(text)


# --- table specs ------------------------------------------------------------
# (title, field, best-first, formatter, accent, plausibility guard, segment)

TEFAS_TABLES = [
    ("🚀 EN İYİ GETİRİ", "daily_return", True, _pct, AMBER, "daily", "general"),
    ("💰 EN ÇOK PARA GİRİŞİ", "flow", True, _flow, AMBER, None, "general"),
    ("💸 EN ÇOK PARA ÇIKIŞI", "flow", False, _flow, RED, None, "general"),
    ("👥 YATIRIMCI SAYISI EN ÇOK ARTAN", "investor_change", True, _investors,
     AMBER, None, "general"),
    ("👥 YATIRIMCI SAYISI EN ÇOK AZALAN", "investor_change", False, _investors,
     RED, None, "general"),
    ("🏦 PARA PİYASASI — EN İYİ GETİRİ", "daily_return", True, _pct, AMBER,
     "daily", "money_market"),
    ("🥇 KIYMETLİ MADENLER — EN İYİ GETİRİ", "daily_return", True, _pct, AMBER,
     "daily", "metals"),
]

BES_TABLES = [
    ("🚀 EN İYİ GETİRİ", "daily_return", True, _pct, AMBER, "daily", "general"),
    ("💰 EN ÇOK PARA GİRİŞİ", "flow", True, _flow, AMBER, None, "general"),
    ("👥 YATIRIMCI SAYISI EN ÇOK ARTAN", "investor_change", True, _investors,
     AMBER, None, "general"),
    ("🥇 KIYMETLİ MADENLER — EN İYİ GETİRİ", "daily_return", True, _pct, AMBER,
     "daily", "metals"),
]


# --- rendering --------------------------------------------------------------


def _rows(records: Sequence[dict], value_fmt: Callable[[dict], str], accent: str) -> str:
    if not records:
        return '<div class="empty">Bugün için yeterli veri yok.</div>'
    return "".join(
        f'<div class="row">'
        f'<div class="rank">{index}</div>'
        f'<div class="code">{_esc(record.get("code") or "")}</div>'
        f'<div class="name">{_esc(fund_name(record))}</div>'
        f'<div class="val" style="color:{accent}">{value_fmt(record)}</div>'
        f"</div>"
        for index, record in enumerate(records, start=1)
    )


def _card_html(heading: str, subheading: str, day: date, tables: str, part: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{WIDTH}px; min-height:{MIN_HEIGHT}px; background:{FOREST}; color:{CHALK};
        font-family:{SANS}; -webkit-font-smoothing:antialiased;
        display:flex; flex-direction:column; padding:52px 60px 40px; }}
header {{ display:flex; align-items:center; gap:22px;
          border-bottom:3px solid {RULE}; padding-bottom:22px; }}
.brand {{ font-size:38px; font-weight:700; letter-spacing:-1px; }}
.title {{ margin-left:44px; display:flex; align-items:baseline; gap:18px; }}
.title h1 {{ font-size:52px; font-weight:700; letter-spacing:-2px; }}
.title .sub {{ font-size:24px; color:{AMBER}; letter-spacing:2px;
               font-weight:600; text-transform:uppercase; }}
.date {{ margin-left:auto; text-align:right; font-size:24px; color:{MUTED};
         line-height:1.3; }}
.date b {{ display:block; color:{CHALK}; font-size:30px; font-weight:600; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:24px 56px;
         margin-top:26px; }}
.section {{ break-inside:avoid; }}
h2 {{ font-size:24px; font-weight:700; color:{CHALK}; padding-bottom:9px;
      border-bottom:2px solid {RULE}; margin-bottom:2px; }}
.row {{ display:flex; align-items:baseline; gap:14px; padding:9px 0;
        border-bottom:1px solid rgba(255,255,255,.05); }}
.rank {{ width:22px; font-size:19px; color:{MUTED}; font-weight:600;
         flex:none; }}
.code {{ width:66px; font-size:26px; font-weight:700; letter-spacing:-.5px;
         flex:none; }}
.name {{ flex:1; font-size:18px; color:{MUTED}; line-height:1.25; }}
.val  {{ font-size:25px; font-weight:700; font-variant-numeric:tabular-nums;
         white-space:nowrap; flex:none; text-align:right; min-width:170px; }}
.empty {{ font-size:19px; color:{MUTED}; padding:14px 0; }}
footer {{ margin-top:auto; padding-top:22px; border-top:3px solid {RULE};
          display:flex; align-items:flex-end; gap:24px;
          font-size:19px; color:{MUTED}; line-height:1.5; }}
footer b {{ color:{AMBER}; font-weight:600; }}
footer .part {{ margin-left:auto; white-space:nowrap; }}
</style></head><body>
<header>{_mark(58)}<div class="brand">NeredeParaVar</div>
  <div class="title"><h1>{heading}</h1><div class="sub">{subheading}</div></div>
  <div class="date"><b>{formatter.tr_date(day)}</b>kapanış verileri</div>
</header>
<div class="grid">{tables}</div>
<footer><div>Kaynak: TEFAS · BEFAS · KAP — kamuya açık verilerden derlenmiştir.<br>
<b>Yatırım tavsiyesi değildir.</b> · t.me/NeredeParaVar</div>
<div class="part">{part}</div></footer>
</body></html>"""


def _build_sections(segments: dict, specs, limit: int) -> List[str]:
    out = []
    for title, key, reverse, fmt, accent, guard, segment in specs:
        rows = metrics.top_by(
            segments.get(segment, []), key, reverse=reverse, limit=limit, guard=guard
        )
        out.append(
            '<div class="section"><h2>{}</h2>{}</div>'.format(
                title, _rows(rows, fmt, accent)
            )
        )
    return out


def _chunk(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_cards(
    records: List[dict], day: date, out_dir: pathlib.Path
) -> List[pathlib.Path]:
    """Render every card. Returns the files written, in reading order.

    Returns an empty list rather than raising if rendering is unavailable: the
    text report is the thing that must go out.
    """
    if not ENABLED:
        log.info("Infographics skipped (playwright not installed).")
        return []

    eligible = metrics.eligible_universe(records)
    tefas, befas = metrics.split_by_platform(eligible)
    limit = config.TOP_N

    plans = [
        # "BES" is what people call the pension system; "BEFAS" is the platform
        # the funds trade on, so it belongs in the subheading, not the title.
        ("tefas", "TEFAS", "Yatırım Fonları", metrics.split_segments(tefas), TEFAS_TABLES),
        ("bes", "BES", "BEFAS · Emeklilik Fonları", metrics.split_segments(befas), BES_TABLES),
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[pathlib.Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": MIN_HEIGHT})

        for slug, heading, subheading, segments, specs in plans:
            groups = _chunk(_build_sections(segments, specs, limit), TABLES_PER_CARD)
            for index, group in enumerate(groups, start=1):
                part = (
                    "{}/{}".format(index, len(groups)) if len(groups) > 1 else ""
                )
                page.set_content(
                    _card_html(heading, subheading, day, "".join(group), part)
                )
                page.wait_for_timeout(400)
                name = "{}_{}{}.png".format(
                    day.isoformat(), slug, "" if len(groups) == 1 else "_{}".format(index)
                )
                path = out_dir / name
                # full_page so a long card keeps its footer instead of being clipped
                page.screenshot(path=str(path), full_page=True)
                written.append(path)
                log.info("Rendered %s", name)

        browser.close()

    return written


def caption(path: pathlib.Path, day: date) -> str:
    """Telegram caption for a card. Kept short; the card carries the detail."""
    label = "TEFAS · Yatırım Fonları" if "_tefas" in path.name else "BES · Emeklilik Fonları"
    return "📊 <b>{}</b>\n<i>{} kapanış verileri</i>".format(
        label, formatter.tr_date(day)
    )


# --- one-off crypto exposure card -------------------------------------------
#
# Deliberately a separate builder rather than an extra table on the daily cards.
# It answers a question that does not change day to day -- fund portfolios are
# disclosed monthly -- and it is shaped for a single post: portrait rather than
# landscape, no date, and no BEFAS in the source line, since every fund on it is
# a TEFAS securities fund and the figures come from KAP, not from either
# platform. The daily cards keep their own format; nothing here touches them.

CRYPTO_WIDTH, CRYPTO_MIN_HEIGHT = 1080, 1350


def crypto_rows(records: List[dict]) -> List[tuple]:
    """``(code, full name, weight)`` for the crypto funds, heaviest first.

    Names are taken from the snapshot so the card cannot drift from what TEFAS
    calls a fund; a fund missing from the snapshot still gets its row, under its
    code alone, rather than silently disappearing from the picture.
    """
    by_code = metrics.index_by_code(records or [])
    rows = [
        (code, fund_name(by_code.get(code, {})) or code, weight)
        for code, (weight, _) in config.CRYPTO_HOLDINGS.items()
    ]
    return sorted(rows, key=lambda row: -row[2])


def _crypto_html(rows: Sequence[tuple]) -> str:
    widest = max((weight for _, _, weight in rows), default=1.0) or 1.0
    body = "".join(
        f'<div class="row">'
        f'<div class="head"><span class="code">{_esc(code)}</span>'
        f'<span class="val">{formatter.percent(weight, 1, signed=False)}</span></div>'
        f'<div class="name">{_esc(name)}</div>'
        f'<div class="track"><div class="bar" '
        f'style="width:{max(weight / widest * 100.0, 1.5):.1f}%"></div></div>'
        f"</div>"
        for code, name, weight in rows
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{CRYPTO_WIDTH}px; min-height:{CRYPTO_MIN_HEIGHT}px; background:{FOREST};
        color:{CHALK}; font-family:{SANS}; -webkit-font-smoothing:antialiased;
        display:flex; flex-direction:column; padding:56px 62px 44px; }}
header {{ display:flex; align-items:center; gap:18px; }}
.brand {{ font-size:34px; font-weight:700; letter-spacing:-1px; }}
h1 {{ font-size:56px; font-weight:700; letter-spacing:-2px; line-height:1.08;
      margin-top:38px; }}
.sub {{ font-size:25px; color:{AMBER}; font-weight:600; margin-top:14px;
        line-height:1.4; }}
.list {{ margin-top:34px; display:flex; flex-direction:column; gap:19px; }}
.head {{ display:flex; align-items:baseline; gap:16px; }}
.code {{ font-size:38px; font-weight:700; letter-spacing:-1px; }}
.val  {{ margin-left:auto; font-size:38px; font-weight:700;
         font-variant-numeric:tabular-nums; color:{AMBER}; }}
.name {{ font-size:18px; color:{MUTED}; line-height:1.3; margin-top:3px; }}
.track {{ margin-top:9px; height:11px; border-radius:6px;
          background:rgba(255,255,255,.07); overflow:hidden; }}
.bar {{ height:100%; border-radius:6px; background:{AMBER}; }}
footer {{ margin-top:auto; padding-top:26px; border-top:3px solid {RULE};
          font-size:19px; color:{MUTED}; line-height:1.55; }}
footer b {{ color:{AMBER}; font-weight:600; }}
footer .src {{ margin-bottom:10px; }}
</style></head><body>
<header>{_mark(54)}<div class="brand">NeredeParaVar</div></header>
<h1>TEFAS'ta kripto<br>içeren fonlar</h1>
<div class="sub">Fonların portföyünde kripto ile ilişkili
  varlıkların ağırlığı</div>
<div class="list">{body}</div>
<footer>
  <div class="src">Kaynak: fonların {config.CRYPTO_HOLDINGS_MONTH} KAP portföy
    raporları. Kripto madencileri, kripto borsaları ve blokzinciri ETF'leri
    dahildir; genel teknoloji ve ödeme şirketleri hariçtir.</div>
  <b>Yatırım tavsiyesi değildir.</b> · t.me/NeredeParaVar
</footer>
</body></html>"""


def build_crypto_card(
    records: List[dict], out_dir: pathlib.Path
) -> Optional[pathlib.Path]:
    """Render the crypto-exposure card. Returns the file written, or None."""
    if not ENABLED:
        log.info("Crypto card skipped (playwright not installed).")
        return None

    rows = crypto_rows(records)
    if not rows:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "kripto_fonlari.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": CRYPTO_WIDTH, "height": CRYPTO_MIN_HEIGHT}
        )
        page.set_content(_crypto_html(rows))
        page.wait_for_timeout(400)
        page.screenshot(path=str(path), full_page=True)
        browser.close()

    log.info("Rendered %s", path.name)
    return path
