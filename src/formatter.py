"""Turkish-language message rendering for Telegram.

This is the only module that speaks Turkish; everything upstream stays in
English. Output uses Telegram's HTML parse mode. Ranking tables go inside
``<pre>`` blocks so columns line up in the phone's monospace font -- lines are
kept under ~42 characters to avoid horizontal scrolling.
"""

from __future__ import annotations

import html
from datetime import date
from typing import List, Optional

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
        text += ", " + DAYS_TR[day.weekday()]
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

    for threshold, suffix in (
        (1_000_000_000, "Mr₺"),
        (1_000_000, "Mn₺"),
        (1_000, "B₺"),
    ):
        if magnitude >= threshold:
            scaled = magnitude / threshold
            # Drop a pointless ",0" so a round threshold reads "100 Mn₺".
            decimals = 0 if abs(scaled - round(scaled)) < 0.05 else 1
            return "{}{} {}".format(sign, tr_number(scaled, decimals), suffix)
    return "{}{} ₺".format(sign, tr_number(magnitude, 0))


def percent(value: Optional[float], decimals: int = 2, signed: bool = True) -> str:
    if value is None:
        return "—"
    sign = ""
    if signed:
        sign = "+" if value > 0 else ("−" if value < 0 else "")
    return "{}%{}".format(sign, tr_number(abs(value), decimals))


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


def short_category(record: dict, width: int = 13) -> str:
    text = (record.get("category") or record.get("umbrella") or "").strip()
    for suffix in (" Şemsiye Fonu", " Fonu", " Fon"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    if len(text) > width:
        text = text[: width - 1] + "."
    return text


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


# -- sections ----------------------------------------------------------------


def _watchlist_block(records_by_code: dict, codes: List[str], title: str) -> List[str]:
    lines = ["", "<b>{}</b>".format(title)]
    for code in codes:
        record = records_by_code.get(code)
        if not record:
            lines.append("<code>{}</code> — veri yok".format(code))
            continue

        lines.append(
            "<b>{}</b> · {}".format(esc(code), esc(short_category(record, 24)))
        )
        lines.append(
            "  {} │ {} │ {} kişi".format(
                percent(record.get("daily_return")),
                money(record.get("aum")),
                count(record.get("investors")),
            )
        )

        flow = record.get("flow")
        if flow is not None:
            lines.append(
                "  Akış {} ({}) · Yatırımcı {}".format(
                    money(flow, signed=True),
                    percent(record.get("flow_pct")),
                    signed_count(record.get("investor_change")),
                )
            )

        rank, total = record.get("cat_rank"), record.get("cat_count")
        extras = []
        if rank and total:
            extras.append("Kategoride {}/{}".format(int(rank), int(total)))
        if record.get("market_share"):
            extras.append("Pazar payı {}".format(percent(record["market_share"], 2, signed=False)))
        if extras:
            lines.append("  " + " · ".join(extras))
    return lines


def _ranking_block(
    title: str,
    records: List[dict],
    value_key: str,
    formatter,
    empty_note: str = "Yeterli veri yok.",
) -> List[str]:
    lines = ["", "<b>{}</b>".format(title)]
    if not records:
        lines.append("<i>{}</i>".format(empty_note))
        return lines

    rows = []
    for index, record in enumerate(records, start=1):
        rows.append(
            "{:>2} {:<4}{:>9}{:>10}  {}".format(
                index,
                (record.get("code") or "")[:4],
                formatter(record.get(value_key)),
                money(record.get("aum")),
                short_category(record),
            )
        )
    lines.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    return lines


def _flow_ranking_block(title: str, records: List[dict], empty_note: str) -> List[str]:
    lines = ["", "<b>{}</b>".format(title)]
    if not records:
        lines.append("<i>{}</i>".format(empty_note))
        return lines

    rows = []
    for index, record in enumerate(records, start=1):
        rows.append(
            "{:>2} {:<4}{:>11}{:>8}  {}".format(
                index,
                (record.get("code") or "")[:4],
                money(record.get("flow"), signed=True),
                percent(record.get("flow_pct"), 1),
                money(record.get("aum")),
            )
        )
    lines.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    lines.append("<i>Sütunlar: net akış · AUM'a oranı · fon büyüklüğü</i>")
    return lines


def _kap_block(items: List[dict], note: Optional[str] = None) -> List[str]:
    lines = ["", "<b>📄 KAP BİLDİRİMLERİ</b>"]
    if not items:
        lines.append("<i>{}</i>".format(esc(note or "Takip listende yeni bildirim yok.")))
        return lines
    for item in items:
        stamp = item.get("published") or ""
        title = esc(item.get("title") or "Bildirim")
        code = esc(item.get("code") or "")
        url = item.get("url")
        text = "• <b>{}</b> — {}".format(code, title)
        if stamp:
            text += " <i>({})</i>".format(esc(stamp))
        if url:
            text += ' <a href="{}">→</a>'.format(esc(url))
        lines.append(text)
    return lines


# -- reports -----------------------------------------------------------------


def daily_report(
    records: List[dict],
    data_day: date,
    run_day: date,
    baseline_day: Optional[date],
    kap_items: Optional[List[dict]] = None,
    kap_note: Optional[str] = None,
) -> str:
    by_code = metrics.index_by_code(records)
    eligible = metrics.eligible_universe(records)
    non_mm, mm = metrics.split_money_market(eligible)

    lines = [
        "📊 <b>TEFAS + BEFAS Günlük</b>",
        "<i>{} · {} kapanış verileri</i>".format(
            tr_date(run_day, with_weekday=True), tr_date(data_day)
        ),
        "<i>{} fon tarandı · sıralamalar {} üzeri fonlar arasında</i>".format(
            count(len(records)), money(config.MIN_AUM_TRY)
        ),
    ]

    if baseline_day is None:
        lines += [
            "",
            "⚠️ <i>Bu ilk kayıt. Para akışı ve yatırımcı değişimi için en az "
            "iki günlük veri gerekiyor — akış sıralamaları yarınki mesajdan "
            "itibaren gelecek.</i>",
        ]
    elif baseline_day != data_day:
        lines.append(
            "<i>Değişimler {} ile karşılaştırmalı.</i>".format(tr_date(baseline_day))
        )

    lines += _watchlist_block(by_code, config.WATCHLIST, "⭐ TAKİP LİSTEM")
    lines += _watchlist_block(
        by_code, config.MONEY_MARKET_WATCHLIST, "🏦 TAKİP — PARA PİYASASI"
    )

    lines += _ranking_block(
        "🚀 GÜNÜN EN İYİ GETİRİLERİ",
        metrics.top_by(non_mm, "daily_return", reverse=True, guard="daily"),
        "daily_return",
        lambda v: percent(v),
    )
    lines += _ranking_block(
        "📉 GÜNÜN EN KÖTÜ GETİRİLERİ",
        metrics.top_by(non_mm, "daily_return", reverse=False, guard="daily"),
        "daily_return",
        lambda v: percent(v),
    )

    flow_note = (
        "Akış hesabı için önceki güne ait kayıt gerekiyor."
        if baseline_day is None
        else "Yeterli veri yok."
    )
    lines += _flow_ranking_block(
        "💰 EN ÇOK PARA GİRİŞİ",
        metrics.top_by(eligible, "flow", reverse=True),
        flow_note,
    )
    lines += _flow_ranking_block(
        "💸 EN ÇOK PARA ÇIKIŞI",
        metrics.top_by(eligible, "flow", reverse=False),
        flow_note,
    )

    lines += ["", "━━━━━━━━━━━━━━━━━━━━", "<b>🏦 PARA PİYASASI FONLARI</b>"]
    lines += _ranking_block(
        "En iyi günlük getiri",
        metrics.top_by(mm, "daily_return", reverse=True, guard="daily"),
        "daily_return",
        lambda v: percent(v, 3),
    )
    lines += _flow_ranking_block(
        "En çok para girişi", metrics.top_by(mm, "flow", reverse=True), flow_note
    )
    lines += _flow_ranking_block(
        "En çok para çıkışı", metrics.top_by(mm, "flow", reverse=False), flow_note
    )

    lines += _kap_block(kap_items or [], kap_note)

    return "\n".join(lines)


def _period_report(
    records: List[dict],
    label: str,
    emoji: str,
    data_day: date,
    baseline_day: Optional[date],
    window_name: str,
) -> str:
    eligible = metrics.eligible_universe(records)
    non_mm, mm = metrics.split_money_market(eligible)

    lines = [
        "{} <b>TEFAS + BEFAS {}</b>".format(emoji, label),
        "<i>{} tarihine kadar</i>".format(tr_date(data_day)),
    ]

    if baseline_day is None:
        lines += [
            "",
            "⚠️ <i>{} raporu için henüz yeterli geçmiş veri yok. "
            "Bot veri biriktirmeye devam ediyor.</i>".format(label),
        ]
        return "\n".join(lines)

    lines.append(
        "<i>{} ile karşılaştırmalı · {} fon</i>".format(
            tr_date(baseline_day), count(len(eligible))
        )
    )

    lines += _ranking_block(
        "🚀 {} EN İYİ GETİRİ".format(window_name),
        metrics.top_by(non_mm, "period_return", reverse=True, guard="period"),
        "period_return",
        lambda v: percent(v),
    )
    lines += _ranking_block(
        "📉 {} EN KÖTÜ GETİRİ".format(window_name),
        metrics.top_by(non_mm, "period_return", reverse=False, guard="period"),
        "period_return",
        lambda v: percent(v),
    )
    lines += _flow_ranking_block(
        "💰 {} EN ÇOK PARA GİRİŞİ".format(window_name),
        metrics.top_by(eligible, "flow", reverse=True),
        "Yeterli veri yok.",
    )
    lines += _flow_ranking_block(
        "💸 {} EN ÇOK PARA ÇIKIŞI".format(window_name),
        metrics.top_by(eligible, "flow", reverse=False),
        "Yeterli veri yok.",
    )
    lines += _ranking_block(
        "📈 AUM'U EN ÇOK BÜYÜYEN",
        metrics.top_by(eligible, "aum_change_pct", reverse=True),
        "aum_change_pct",
        lambda v: percent(v, 1),
    )

    lines += ["", "━━━━━━━━━━━━━━━━━━━━", "<b>🏦 PARA PİYASASI FONLARI</b>"]
    lines += _ranking_block(
        "En iyi getiri",
        metrics.top_by(mm, "period_return", reverse=True, guard="period"),
        "period_return",
        lambda v: percent(v, 3),
    )
    lines += _flow_ranking_block(
        "En çok para girişi", metrics.top_by(mm, "flow", reverse=True), "Yeterli veri yok."
    )

    return "\n".join(lines)


def weekly_report(records, data_day, baseline_day) -> str:
    return _period_report(records, "Haftalık", "🗓", data_day, baseline_day, "HAFTANIN")


def monthly_report(records, data_day, baseline_day) -> str:
    return _period_report(records, "Aylık", "📅", data_day, baseline_day, "AYIN")


# -- delivery helpers --------------------------------------------------------


def _atomic_blocks(text: str) -> List[str]:
    """Break the report into units that must not be split.

    A ``<pre>`` table spans several physical lines; cutting it in half would
    leave an unbalanced tag and Telegram would reject the message. Everything
    else is a single line.
    """
    blocks: List[str] = []
    pending: List[str] = []

    for line in text.split("\n"):
        if pending:
            pending.append(line)
            if "</pre>" in line:
                blocks.append("\n".join(pending))
                pending = []
            continue

        if "<pre>" in line and "</pre>" not in line:
            pending = [line]
            continue

        blocks.append(line)

    if pending:  # unterminated block; keep it rather than dropping content
        blocks.append("\n".join(pending))

    return blocks


def split_for_telegram(text: str, limit: int = TELEGRAM_LIMIT) -> List[str]:
    """Pack the report into messages that each fit Telegram's size limit."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current: List[str] = []
    size = 0

    for block in _atomic_blocks(text):
        block_size = len(block) + 1

        if current and size + block_size > limit:
            chunks.append("\n".join(current).strip())
            current, size = [], 0

        current.append(block)
        size += block_size

    if current:
        chunks.append("\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]
