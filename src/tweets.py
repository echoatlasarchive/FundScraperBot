"""Draft opening sentences for X, written from the day's actual numbers.

These go to the owner only, never to the channel: they are drafts to be read,
edited and posted by hand.

Two rules shape every line here. They stay descriptive -- what moved, by how
much -- and never suggest what anyone should do about it, because the account
carries a "yatırım tavsiyesi değildir" notice and the text has to be consistent
with it. And they only claim what the data actually shows: "kaç yatırımcı
katıldı" is a real count, whereas "ilgi patladı" is a story about a count.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable, List, Optional

from . import formatter, metrics

LIMIT = 280


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(records: List[dict], key: str, reverse: bool, guard=None) -> Optional[dict]:
    top = metrics.top_by(records, key, reverse=reverse, limit=1, guard=guard)
    return top[0] if top else None


def _tr_title(text: str) -> str:
    """Title-case that survives Turkish.

    ``str.title()`` mangles the dotted capital: "HİSSE" comes back as "Hi̇sse",
    an i with a separate combining dot, because Python lowercases İ to i plus
    U+0307. Mapping the two I forms by hand before folding avoids that.
    """

    def word(match: "re.Match") -> str:
        raw = match.group()
        head = raw[0].replace("i", "İ").replace("ı", "I").upper()
        tail = raw[1:].replace("I", "ı").replace("İ", "i").lower()
        return head + tail

    return re.sub(r"[^\W\d_]+", word, text, flags=re.UNICODE)


def _name(record: dict) -> str:
    """Fund company plus the distinguishing part, trimmed for a tweet."""
    name = (record.get("name") or "").strip()
    for noise in (" (HİSSE SENEDİ YOĞUN FON)", " EMEKLİLİK YATIRIM FONU", " A.Ş."):
        name = name.replace(noise, "")
    return _tr_title(" ".join(name.split()))


def _day_label(day: date, today: date) -> str:
    """Readers see "dün" on the day after; otherwise name the date."""
    if (today - day).days == 1:
        return "Dün"
    return formatter.tr_date(day)


# --- individual drafts ------------------------------------------------------


def _inflow(records, when) -> Optional[str]:
    record = _first(records, "flow", True)
    if not record:
        return None
    flow = formatter.money(record.get("flow"))
    line = "{}, en çok para giren fon oldu: {} ({}).".format(
        record["code"], flow, _name(record)
    )
    investors = _num(record.get("investor_change"))
    if investors and investors > 0:
        line += " Aynı gün {} yeni yatırımcı katıldı.".format(
            formatter.count(investors)
        )
    return "{} {}".format(when, line)


def _outflow(records, when) -> Optional[str]:
    record = _first(records, "flow", False)
    if not record or (_num(record.get("flow")) or 0) >= 0:
        return None
    return "{} {} fonundan {} çıktı — günün en büyük çıkışı. ({})".format(
        when,
        record["code"],
        formatter.money(record.get("flow")),
        _name(record),
    )


def _investors(records, when) -> Optional[str]:
    record = _first(records, "investor_change", True)
    if not record:
        return None
    count = _num(record.get("investor_change"))
    if not count or count <= 0:
        return None
    line = "{} yatırımcı sayısı en çok artan fon {} oldu: {} kişi.".format(
        when, record["code"], formatter.count(count)
    )
    flow = _num(record.get("flow"))
    if flow and flow > 0:
        line += " Fona giren para {}.".format(formatter.money(flow))
    return line


def _best_return(records, when) -> Optional[str]:
    record = _first(records, "daily_return", True, guard="daily")
    if not record:
        return None
    line = "{} en çok kazandıran fon {} oldu: {}. ({})".format(
        when,
        record["code"],
        formatter.percent(record.get("daily_return")),
        _name(record),
    )
    ytd = _num(record.get("ret_ytd"))
    if ytd is not None:
        line += " Yılbaşından beri {}.".format(formatter.percent(ytd))
    return line


def _metals(records, when) -> Optional[str]:
    metals = [r for r in records if metrics.is_precious_metal(r)]
    record = _first(metals, "daily_return", True, guard="daily")
    if not record:
        return None
    return "{} kıymetli madenlerde başı {} çekti: {}. Yılbaşından beri {}.".format(
        when,
        record["code"],
        formatter.percent(record.get("daily_return")),
        formatter.percent(record.get("ret_ytd")),
    )


def _befas(records, when) -> Optional[str]:
    """BES funds are the part most people never look at, so call it out."""
    record = _first(records, "flow", True)
    if not record:
        return None
    return (
        "{} BES tarafında en çok para giren fon {} oldu: {}. "
        "Emeklilik fonunuzun nerede durduğuna bakmak için iyi bir gün. ({})"
    ).format(when, record["code"], formatter.money(record.get("flow")), _name(record))


# --- assembly ---------------------------------------------------------------


def build_drafts(records: List[dict], data_day: date, today: date) -> List[str]:
    """A handful of drafts, each about a different fact, short enough to post."""
    when = _day_label(data_day, today)

    eligible = metrics.eligible_universe(records)
    tefas, befas = metrics.split_by_platform(eligible)
    tefas_general = metrics.split_segments(tefas)["general"]

    builders: List[Callable[[], Optional[str]]] = [
        lambda: _inflow(tefas_general, when),
        lambda: _investors(tefas_general, when),
        lambda: _best_return(tefas_general, when),
        lambda: _outflow(tefas_general, when),
        lambda: _metals(tefas, when),
        lambda: _befas(metrics.split_segments(befas)["general"], when),
    ]

    drafts = []
    for build in builders:
        try:
            text = build()
        except Exception:  # noqa: BLE001 - a bad draft must not stop the report
            continue
        if text and len(text) <= LIMIT and text not in drafts:
            drafts.append(text)
    return drafts


def as_message(drafts: List[str]) -> List[str]:
    """Telegram blocks: each draft on its own, ready to copy out."""
    if not drafts:
        return ["<b>🐦 TWEET TASLAKLARI</b>\n<i>Bugün öne çıkan bir hareket yok.</i>"]

    blocks = [
        "<b>🐦 TWEET TASLAKLARI</b>\n"
        "<i>Kopyala-yapıştır için. Her biri ayrı bir gönderi.</i>"
    ]
    for index, draft in enumerate(drafts, start=1):
        blocks.append(
            "<b>{}.</b> <code>{}</code>\n<i>{} karakter</i>".format(
                index, formatter.esc(draft), len(draft)
            )
        )
    return blocks
