"""Turkish-language message rendering for Telegram.

This is the only module that speaks Turkish; everything upstream stays in
English. Output uses Telegram's HTML parse mode.

Reports are built as a list of *blocks*. A block is one heading together with
the table beneath it, and the splitter never cuts one in half -- otherwise a
heading can end up stranded at the bottom of one message with its table at the
top of the next.

Two table shapes are used:

* Numeric comparisons go in ``<pre>`` blocks so columns line up in the phone's
  monospace font. Lines stay under ~40 characters to avoid horizontal scrolling.

  Nothing inside these tables is emphasised. Telegram silently discards nested
  formatting inside ``<pre>`` -- sending ``<pre>...<b>+0,30</b>...</pre>`` comes
  back from the API with a single ``pre`` entity and no ``bold`` entity at all --
  and an ASCII marker standing in for bold was more clutter than signal.
* Rankings that carry a fund's full name use two lines per entry instead, since
  those names run to seventy characters and would wreck any fixed-width layout.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Callable, List, Optional

from . import config, metrics

TELEGRAM_LIMIT = 4096

MONTHS_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
DAYS_TR = [
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
]

# -- primitives --------------------------------------------------------------


def tr_date(day: date, with_weekday: bool = False) -> str:
    text = "{} {} {}".format(day.day, MONTHS_TR[day.month - 1], day.year)
    if with_weekday:
        text += " " + DAYS_TR[day.weekday()]
    return text


def tr_number(value: float, decimals: int = 2) -> str:
    """Turkish convention: dot for thousands, comma for the decimal mark."""
    text = "{:,.{}f}".format(value, decimals)
    # en-US separators -> tr-TR separators
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def money(value: Optional[float], signed: bool = False) -> str:
    """Compact lira amount: 40,9 Mr₺ / 118,4 Mn₺ / 1.234 ₺."""
    if value is None:
        return "—"
    sign = ""
    if signed:
        sign = "+" if value > 0 else ("−" if value < 0 else "±")
    magnitude = abs(value)

    if magnitude >= 1_000_000_000:
        return "{}{} Mr₺".format(sign, tr_number(magnitude / 1_000_000_000, 1))
    if magnitude >= 1_000_000:
        return "{}{} Mn₺".format(sign, tr_number(magnitude / 1_000_000, 1))
    if magnitude >= 1_000:
        return "{}{} B₺".format(sign, tr_number(magnitude / 1_000, 1))
    return "{}{} ₺".format(sign, tr_number(magnitude, 0))


def percent(value: Optional[float], decimals: int = 2, signed: bool = True) -> str:
    if value is None:
        return "—"
    sign = ""
    if signed:
        sign = "+" if value > 0 else ("−" if value < 0 else "")
    return "{}%{}".format(sign, tr_number(abs(value), decimals))


def pct_bare(value: Optional[float], decimals: int = 2) -> str:
    """Percentage without the sign glyph, for use inside aligned tables."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("-" if value < 0 else " ")
    return "{}{}".format(sign, tr_number(abs(value), decimals))


def money_compact(value: Optional[float]) -> str:
    """Lira amount squeezed for a table cell: -1,5Mr / +354Mn / +98,0B."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("-" if value < 0 else " ")
    magnitude = abs(value)

    if magnitude >= 1_000_000_000:
        return "{}{}Mr".format(sign, tr_number(magnitude / 1_000_000_000, 1))
    if magnitude >= 1_000_000:
        return "{}{}Mn".format(sign, tr_number(magnitude / 1_000_000, 0))
    if magnitude >= 1_000:
        return "{}{}B".format(sign, tr_number(magnitude / 1_000, 0))
    return "{}{}".format(sign, tr_number(magnitude, 0))


def signed_int(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("-" if value < 0 else " ")
    return "{}{}".format(sign, tr_number(abs(value), 0))


def count(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return tr_number(abs(value), 0)


def arrow(value: Optional[float]) -> str:
    if value is None:
        return "·"
    if value > 0:
        return "▲"
    if value < 0:
        return "▼"
    return "─"


def signed_count(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return "{}{}".format(arrow(value), count(value))


def short_category(record: dict, width: int = 11) -> str:
    text = (record.get("category") or record.get("umbrella") or "").strip()
    for suffix in (" Şemsiye Fonu", " Fonu", " Fon"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    if len(text) > width:
        text = text[: width - 1] + "."
    return text


def fund_name(record: dict) -> str:
    return (record.get("name") or "").strip()


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- returns table (code + daily / 1m / YTD, best marked) ---------------------

# (field, heading, cell width, formatter)
# Widths are tuned so the widest row stays inside ~40 characters even with the
# flow columns attached, which is what fits a phone without sideways scrolling.
# Each is one wider than its values need, to space the columns apart.
RETURN_COLUMNS = (
    ("daily_return", "Günlük", 7, lambda v: pct_bare(v, 2)),
    ("ret_1m", "1 Ay", 7, lambda v: pct_bare(v, 2)),
    ("ret_ytd", "Yılbaşı", 8, lambda v: pct_bare(v, 1)),
)

FLOW_COLUMNS = (
    ("flow", "Akış", 8, money_compact),
    ("investor_change", "Kişi", 7, signed_int),
)


def _returns_table(
    records: List[dict], numbered: bool = False, columns=RETURN_COLUMNS
) -> str:
    """Monospace table of daily / 1-month / year-to-date returns."""
    label_width = 6 if numbered else 4

    header = "{:<{}}".format("Kod", label_width)
    for _, title, width, _ in columns:
        header += "{:>{}}".format(title, width)
    rows = [header]

    for index, record in enumerate(records):
        label = (
            "{}.{}".format(index + 1, record.get("code") or "")
            if numbered
            else (record.get("code") or "")
        )
        row = "{:<{}}".format(label[:label_width], label_width)
        for key, _, width, fmt in columns:
            row += "{:>{}}".format(fmt(_num(record.get(key))), width)
        rows.append(row)

    return "<pre>" + esc("\n".join(rows)) + "</pre>"


# -- named ranking lists -----------------------------------------------------


def _named_ranking(records: List[dict], value_fmt: Callable[[dict], str]) -> str:
    """Two lines per fund: rank, code and value, then the full fund name."""
    lines = []
    for index, record in enumerate(records, start=1):
        lines.append(
            "<b>{}. {}</b> · {}".format(
                index, esc(record.get("code") or ""), value_fmt(record)
            )
        )
        lines.append("<i>{}</i>".format(esc(fund_name(record))))
    return "\n".join(lines)


def _block(heading: str, body: str, empty_note: str = "Yeterli veri yok.") -> str:
    if not body:
        return "<b>{}</b>\n<i>{}</i>".format(heading, esc(empty_note))
    return "<b>{}</b>\n{}".format(heading, body)


# -- watchlist ---------------------------------------------------------------


def _watchlist_block(
    by_code: dict, codes: List[str], title: str, with_flow: bool
) -> List[str]:
    records = [by_code[c] for c in codes if c in by_code]
    missing = [c for c in codes if c not in by_code]

    if not records:
        return [_block(title, "", "Takip listesi için veri yok.")]

    columns = RETURN_COLUMNS + FLOW_COLUMNS if with_flow else RETURN_COLUMNS
    body = _returns_table(records, columns=columns)

    if missing:
        body += "\n<i>Veri yok: {}</i>".format(esc(", ".join(missing)))

    return [_block(title, body)]


# -- platform sections -------------------------------------------------------


def _returns_ranking_block(
    heading: str,
    records: List[dict],
    limit: int,
    guard: Optional[str],
    sort_key: str = "daily_return",
) -> List[str]:
    """Best performers with the full multi-period returns table."""
    top = metrics.top_by(records, sort_key, reverse=True, limit=limit, guard=guard)
    if not top:
        return [_block(heading, "")]

    body = _returns_table(top, numbered=True)
    body += "\n" + "\n".join(
        "<i>{}. {} — {}</i>".format(i, esc(r.get("code") or ""), esc(fund_name(r)))
        for i, r in enumerate(top, start=1)
    )
    return [_block(heading, body)]


def _platform_section(
    heading: str,
    records: List[dict],
    guard: Optional[str],
    flow_note: str,
    include_money_market: bool,
    sort_key: str = "daily_return",
) -> List[str]:
    segments = metrics.split_segments(records)
    blocks = ["━━━━━━━━━━━━━━━━━━━━\n<b>{}</b>".format(heading)]

    if not any(segments.values()):
        blocks.append("<i>Eşikleri geçen fon yok.</i>")
        return blocks

    general = segments["general"]

    blocks += _returns_ranking_block(
        "🚀 EN İYİ GETİRİ", general, config.TOP_N, guard, sort_key
    )

    blocks.append(
        _block(
            "💰 EN ÇOK PARA GİRİŞİ",
            _named_ranking(
                metrics.top_by(general, "flow", reverse=True, limit=config.TOP_N),
                lambda r: money(r.get("flow"), signed=True),
            ),
            flow_note,
        )
    )
    blocks.append(
        _block(
            "👥 YATIRIMCI SAYISI EN ÇOK ARTAN",
            _named_ranking(
                metrics.top_by(
                    general, "investor_change", reverse=True, limit=config.TOP_N
                ),
                lambda r: "+{} kişi".format(count(r.get("investor_change"))),
            ),
            flow_note,
        )
    )

    if include_money_market:
        blocks.append(
            _block(
                "💸 EN ÇOK PARA ÇIKIŞI",
                _named_ranking(
                    metrics.top_by(general, "flow", reverse=False, limit=config.TOP_N),
                    lambda r: money(r.get("flow"), signed=True),
                ),
                flow_note,
            )
        )
        blocks.append(
            _block(
                "👥 YATIRIMCI SAYISI EN ÇOK AZALAN",
                _named_ranking(
                    metrics.top_by(
                        general, "investor_change", reverse=False, limit=config.TOP_N
                    ),
                    lambda r: "{} kişi".format(signed_int(r.get("investor_change"))),
                ),
                flow_note,
            )
        )
        if segments["money_market"]:
            blocks += _returns_ranking_block(
                "🏦 PARA PİYASASI — EN İYİ GETİRİ",
                segments["money_market"],
                config.SUB_TOP_N,
                guard,
                sort_key,
            )

    if segments["metals"]:
        blocks += _returns_ranking_block(
            "🥇 KIYMETLİ MADENLER — EN İYİ GETİRİ",
            segments["metals"],
            config.SUB_TOP_N,
            guard,
            sort_key,
        )

    return blocks


def _kap_block(items: List[dict], note: Optional[str] = None) -> List[str]:
    if not items:
        return [
            _block(
                "📄 KAP BİLDİRİMLERİ",
                "",
                note or "Takip listende dün ve bugün yeni bildirim yok.",
            )
        ]

    lines = []
    for item in items:
        when = tr_date(item["date"]) if item.get("date") else ""
        if item.get("time"):
            when = "{} {}".format(when, item["time"]).strip()

        head = "<b>{}</b> · {}".format(esc(item.get("code") or ""), esc(when))
        if item.get("url"):
            head = '<b>{}</b> · <a href="{}">{}</a>'.format(
                esc(item.get("code") or ""), esc(item["url"]), esc(when)
            )
        lines.append(head)
        lines.append(esc(item.get("subject") or "Bildirim"))

        summary = (item.get("summary") or "").strip()
        if summary and summary != "-":
            if len(summary) > 200:
                summary = summary[:199].rstrip() + "…"
            lines.append("<i>{}</i>".format(esc(summary)))

        for number, url in enumerate(item.get("attachments") or [], start=1):
            label = "📎 Ek {}".format(number) if number > 1 else "📎 Ek (PDF)"
            lines.append('<a href="{}">{}</a>'.format(esc(url), label))

        lines.append("")

    return [_block("📄 KAP BİLDİRİMLERİ", "\n".join(lines).strip())]


def _footnote(total: int) -> str:
    return "<i>* {} fon tarandı · {} ve {} yatırımcı alt sınırı</i>".format(
        count(total), money(config.MIN_AUM_TRY), count(config.MIN_INVESTORS)
    )


# -- reports -----------------------------------------------------------------


def daily_report(
    records: List[dict],
    data_day: date,
    run_day: date,
    baseline_day: Optional[date],
    kap_items: Optional[List[dict]] = None,
    kap_note: Optional[str] = None,
) -> List[str]:
    by_code = metrics.index_by_code(records)
    eligible = metrics.eligible_universe(records)
    tefas, befas = metrics.split_by_platform(eligible)

    blocks = [
        "📊 <b>TEFAS + BEFAS Günlük</b>\n{} <i>({} kapanış verileri)</i>".format(
            tr_date(run_day, with_weekday=True), tr_date(data_day, with_weekday=True)
        )
    ]

    if baseline_day is None:
        blocks.append(
            "⚠️ <i>Bu ilk kayıt. Para akışı ve yatırımcı değişimi için en az "
            "iki günlük veri gerekiyor — akış sıralamaları yarınki mesajdan "
            "itibaren gelecek.</i>"
        )

    blocks += _watchlist_block(by_code, config.WATCHLIST, "⭐ TAKİP LİSTEM", True)
    blocks += _watchlist_block(
        by_code, config.MONEY_MARKET_WATCHLIST, "🏦 TAKİP — PARA PİYASASI", False
    )
    blocks += _watchlist_block(
        by_code, config.BEFAS_WATCHLIST, "⭐ TAKİP — BEFAS (Emeklilik)", True
    )

    flow_note = (
        "Akış hesabı için önceki güne ait kayıt gerekiyor."
        if baseline_day is None
        else "Yeterli veri yok."
    )

    blocks += _platform_section(
        "🇹🇷 TEFAS · YATIRIM FONLARI",
        tefas,
        "daily",
        flow_note,
        include_money_market=True,
    )
    blocks += _platform_section(
        "🏛 BEFAS · EMEKLİLİK FONLARI",
        befas,
        "daily",
        flow_note,
        include_money_market=False,
    )

    blocks += _kap_block(kap_items or [], kap_note)
    blocks.append(_footnote(len(records)))
    return blocks


def _period_report(
    records: List[dict],
    label: str,
    emoji: str,
    data_day: date,
    baseline_day: Optional[date],
) -> List[str]:
    eligible = metrics.eligible_universe(records)
    tefas, befas = metrics.split_by_platform(eligible)

    blocks = [
        "{} <b>TEFAS + BEFAS {}</b>\n<i>{} tarihine kadar</i>".format(
            emoji, label, tr_date(data_day, with_weekday=True)
        )
    ]

    if baseline_day is None:
        blocks.append(
            "⚠️ <i>{} raporu için henüz yeterli geçmiş veri yok. "
            "Bot veri biriktirmeye devam ediyor.</i>".format(label)
        )
        return blocks

    blocks += _platform_section(
        "🇹🇷 TEFAS · YATIRIM FONLARI",
        tefas,
        "period",
        "Yeterli veri yok.",
        include_money_market=True,
        sort_key="period_return",
    )
    blocks += _platform_section(
        "🏛 BEFAS · EMEKLİLİK FONLARI",
        befas,
        "period",
        "Yeterli veri yok.",
        include_money_market=False,
        sort_key="period_return",
    )
    blocks.append(_footnote(len(records)))
    return blocks


def weekly_report(records, data_day, baseline_day) -> List[str]:
    return _period_report(records, "Haftalık", "🗓", data_day, baseline_day)


def monthly_report(records, data_day, baseline_day) -> List[str]:
    return _period_report(records, "Aylık", "📅", data_day, baseline_day)


# -- delivery helpers --------------------------------------------------------


def render(blocks: List[str]) -> str:
    """Whole report as one string, for previews and tests."""
    return "\n\n".join(blocks)


def split_for_telegram(blocks, limit: int = TELEGRAM_LIMIT) -> List[str]:
    """Pack blocks into messages without ever splitting a block.

    A block is a heading plus its table, so this is what keeps a heading from
    being stranded at the end of one message with its table at the top of the
    next. A single block larger than the limit is emitted on its own and left
    for Telegram to reject loudly rather than being silently mangled.
    """
    if isinstance(blocks, str):
        blocks = [blocks]

    messages: List[str] = []
    current: List[str] = []
    size = 0

    for block in blocks:
        block_size = len(block) + 2  # the "\n\n" joiner
        if current and size + block_size > limit:
            messages.append("\n\n".join(current))
            current, size = [], 0
        current.append(block)
        size += block_size

    if current:
        messages.append("\n\n".join(current))
    return [m for m in messages if m.strip()]
