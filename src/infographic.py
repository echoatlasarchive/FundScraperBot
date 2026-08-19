"""Daily infographic cards, one for TEFAS and one for BEFAS.

Rendered as HTML and screenshotted through the Chromium that Playwright already
installs for the KAP scraper, so the cards cost no extra dependency.

Cards are 1080 wide and grow to fit their content: a fixed height silently cut
off the last section and, worse, the disclaimer. Type, palette and the
question-mark mark are the same ones in ``brand/build_brand.py``; if the brand
changes, change it in both.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import date
from typing import List, Optional, Sequence

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

WIDTH, MIN_HEIGHT = 1080, 1350


def _mark(px: int) -> str:
    """The logo mark inline, sized in pixels."""
    return (
        f'<svg viewBox="0 0 1024 1024" width="{px}" height="{px}">'
        f'<g transform="translate(0,34)">'
        f'<path d="{HOOK}" fill="none" stroke="{CHALK}" stroke-width="94" '
        f'stroke-linecap="round"/>'
        f'<text x="512" y="838" font-family="{SANS}" font-weight="700" '
        f'font-size="228" fill="{AMBER}" text-anchor="middle">₺</text>'
        f"</g></svg>"
    )


# --- text helpers -----------------------------------------------------------

# Every Turkish fund name carries the same scaffolding; stripping it leaves the
# part that actually distinguishes one fund from another.
NOISE = (
    " (HİSSE SENEDİ YOĞUN FON)",
    " EMEKLİLİK YATIRIM FONU",
    " YATIRIM FONU",
    " A.Ş.",
)


def short_name(record: dict, limit: int = 42) -> str:
    name = (record.get("name") or "").strip()
    for noise in NOISE:
        name = name.replace(noise, "")
    name = " ".join(name.split())
    if len(name) > limit:
        name = name[: limit - 1].rstrip(" ,·-") + "…"
    return name


def _esc(text: str) -> str:
    return formatter.esc(text)


# --- card sections ----------------------------------------------------------


def _rows(records: Sequence[dict], value_fmt, accent: str) -> str:
    out = []
    for index, record in enumerate(records, start=1):
        out.append(
            f'<div class="row">'
            f'<div class="rank">{index}</div>'
            f'<div class="code">{_esc(record.get("code") or "")}</div>'
            f'<div class="name">{_esc(short_name(record))}</div>'
            f'<div class="val" style="color:{accent}">{value_fmt(record)}</div>'
            f"</div>"
        )
    if not out:
        out.append('<div class="empty">Bugün için yeterli veri yok.</div>')
    return "".join(out)


def _section(title: str, body: str) -> str:
    return f'<div class="section"><h2>{title}</h2>{body}</div>'


def _card_html(
    heading: str,
    subheading: str,
    day: date,
    sections: str,
) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{WIDTH}px; min-height:{MIN_HEIGHT}px; background:{FOREST}; color:{CHALK};
        font-family:{SANS}; -webkit-font-smoothing:antialiased;
        display:flex; flex-direction:column; padding:60px 58px 46px; }}
header {{ display:flex; align-items:center; gap:22px;
          border-bottom:3px solid {RULE}; padding-bottom:26px; }}
.brand {{ font-size:38px; font-weight:700; letter-spacing:-1px; line-height:1; }}
.date {{ margin-left:auto; text-align:right; font-size:26px; color:{MUTED};
         line-height:1.35; }}
.date b {{ display:block; color:{CHALK}; font-size:30px; font-weight:600; }}
h1 {{ font-size:56px; font-weight:700; letter-spacing:-2px; margin:34px 0 4px; }}
.sub {{ font-size:25px; color:{AMBER}; letter-spacing:2px; font-weight:600;
        text-transform:uppercase; }}
.section {{ margin-top:34px; }}
h2 {{ font-size:27px; font-weight:700; letter-spacing:.5px; color:{CHALK};
      padding-bottom:12px; border-bottom:2px solid {RULE}; margin-bottom:6px; }}
.row {{ display:flex; align-items:baseline; gap:16px; padding:11px 0;
        border-bottom:1px solid rgba(255,255,255,.05); }}
.rank {{ width:26px; font-size:22px; color:{MUTED}; font-weight:600; }}
.code {{ width:74px; font-size:29px; font-weight:700; letter-spacing:-.5px; }}
.name {{ flex:1; font-size:22px; color:{MUTED}; line-height:1.25;
         overflow:hidden; }}
.val  {{ font-size:29px; font-weight:700; font-variant-numeric:tabular-nums;
         white-space:nowrap; }}
.empty {{ font-size:22px; color:{MUTED}; padding:16px 0; }}
footer {{ margin-top:auto; padding-top:24px; border-top:3px solid {RULE};
          font-size:20px; color:{MUTED}; line-height:1.5; }}
footer b {{ color:{AMBER}; font-weight:600; }}
</style></head><body>
<header>{_mark(62)}<div class="brand">NeredeParaVar</div>
  <div class="date"><b>{formatter.tr_date(day)}</b>kapanış verileri</div>
</header>
<h1>{heading}</h1><div class="sub">{subheading}</div>
{sections}
<footer>Kaynak: TEFAS · BEFAS · KAP — kamuya açık verilerden otomatik derlenmiştir.<br>
<b>Yatırım tavsiyesi değildir.</b> · t.me/NeredeParaVar</footer>
</body></html>"""


# --- public API -------------------------------------------------------------


def _pct(record: dict) -> str:
    return formatter.percent(record.get("daily_return"))


def _flow(record: dict) -> str:
    return formatter.money(record.get("flow"), signed=True)


def _investors(record: dict) -> str:
    return "{} kişi".format(formatter.signed_int(record.get("investor_change")))


def build_cards(
    records: List[dict], day: date, out_dir: pathlib.Path
) -> List[pathlib.Path]:
    """Render the TEFAS and BEFAS cards. Returns the files written.

    Returns an empty list rather than raising if rendering is unavailable: the
    text report is the thing that must go out.
    """
    if not ENABLED:
        log.info("Infographics skipped (playwright not installed).")
        return []

    eligible = metrics.eligible_universe(records)
    tefas, befas = metrics.split_by_platform(eligible)
    limit = config.TOP_N

    def general(rows):
        return metrics.split_segments(rows)["general"]

    plans = [
        (
            "tefas",
            "TEFAS",
            "Yatırım Fonları",
            general(tefas),
            [
                ("🚀 GÜNÜN EN İYİ GETİRİLERİ", "daily_return", True, _pct, AMBER, "daily"),
                ("💰 EN ÇOK PARA GİRİŞİ", "flow", True, _flow, AMBER, None),
                ("💸 EN ÇOK PARA ÇIKIŞI", "flow", False, _flow, RED, None),
            ],
        ),
        (
            "befas",
            "BEFAS",
            "Emeklilik Fonları",
            general(befas),
            [
                ("🚀 GÜNÜN EN İYİ GETİRİLERİ", "daily_return", True, _pct, AMBER, "daily"),
                ("💰 EN ÇOK PARA GİRİŞİ", "flow", True, _flow, AMBER, None),
                ("👥 YATIRIMCI SAYISI EN ÇOK ARTAN", "investor_change", True,
                 _investors, AMBER, None),
            ],
        ),
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[pathlib.Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": MIN_HEIGHT})
        for slug, heading, subheading, pool, specs in plans:
            sections = "".join(
                _section(
                    title,
                    _rows(
                        metrics.top_by(
                            pool, key, reverse=reverse, limit=limit, guard=guard
                        ),
                        fmt,
                        colour,
                    ),
                )
                for title, key, reverse, fmt, colour, guard in specs
            )
            page.set_content(_card_html(heading, subheading, day, sections))
            page.wait_for_timeout(400)
            path = out_dir / "{}_{}.png".format(day.isoformat(), slug)
            # full_page so a long card keeps its footer instead of being clipped
            page.screenshot(path=str(path), full_page=True)
            written.append(path)
            log.info("Rendered %s", path.name)
        browser.close()

    return written


def caption(kind: str, day: date) -> str:
    """Telegram caption for a card. Kept short; the card carries the detail."""
    label = "TEFAS · Yatırım Fonları" if kind == "tefas" else "BEFAS · Emeklilik Fonları"
    return "📊 <b>{}</b>\n<i>{} kapanış verileri</i>".format(
        label, formatter.tr_date(day)
    )
