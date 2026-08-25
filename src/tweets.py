"""Draft posts for X, written from the day's numbers plus a little context.

These go to the owner only, never to the channel: they are drafts to be read,
edited and posted by hand.

Three rules shape everything here.

**Only post what is worth reading.** An early version announced that a metals
fund had gained 0.11% on the day, which tells a reader nothing and teaches them
to skip the account. Every figure now has to clear a threshold in
``config.MIN_TWEETWORTHY_*`` before it earns a sentence.

**Stay descriptive.** The account carries a "yatırım tavsiyesi değildir"
notice, so the text has to be consistent with it: what moved and by how much,
never what anyone should do about it. Context is allowed -- "bitcoin rose 7%
today and these funds hold blockchain companies" is an observation. A
recommendation is not.

**Say only what the data shows.** Fund holdings and their weights are not
available anywhere in the TEFAS API (the portfolio-breakdown endpoint is one of
the retired ones), so no draft claims to know what a fund holds. It says what
the fund is called and what it returned.

Two drafts were removed on 2026-08-26 at the owner's request and must not come
back: the "popüler fonlar" thread, which grouped named funds under editorial
headings, and the "kripto ve blokzinciri fonları" thread. The crypto weights
they used still feed the standalone card in ``infographic.build_crypto_card``,
and ``config.CRYPTO_HOLDINGS`` and ``market.bitcoin_24h`` are kept for the
hand-written crypto post the owner is preparing.

Every draft ends in ``ytd``. Posts longer than a single tweet come back as a
list, to be sent as a thread.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

from . import config, formatter, market, metrics

LIMIT = 280


# --- helpers ----------------------------------------------------------------


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tr_title(text: str) -> str:
    """Title-case that survives Turkish.

    ``str.title()`` renders "HİSSE" as "Hi̇sse" -- an i followed by a combining
    dot -- because Python lowercases İ to i + U+0307. Mapping the two I forms by
    hand before folding avoids that.
    """

    def word(match) -> str:
        raw = match.group()
        head = raw[0].replace("i", "İ").replace("ı", "I").upper()
        tail = raw[1:].replace("I", "ı").replace("İ", "i").lower()
        return head + tail

    return re.sub(r"[^\W\d_]+", word, text, flags=re.UNICODE)


def _name(record: dict) -> str:
    name = (record.get("name") or "").strip()
    for noise in (" (HİSSE SENEDİ YOĞUN FON)", " EMEKLİLİK YATIRIM FONU", " A.Ş."):
        name = name.replace(noise, "")
    return _tr_title(" ".join(name.split()))


def tag(code: str) -> str:
    return "#{}".format((code or "").upper())


def _pct(value) -> str:
    return formatter.percent(value)


def _day_label(day: date, today: date) -> str:
    return "Dün" if (today - day).days == 1 else formatter.tr_date(day)


def _finish(lines: Sequence[str]) -> Optional[str]:
    """Join lines and append the notice, or drop the draft if it will not fit."""
    body = "\n".join(line for line in lines if line)
    text = "{}\n\n{}".format(body, config.TWEET_SUFFIX)
    return text if len(text) <= LIMIT else None


def _significant_return(record: dict, key: str = "daily_return") -> bool:
    value = _num(record.get(key))
    return value is not None and abs(value) >= config.MIN_TWEETWORTHY_RETURN_PCT


def _significant_flow(record: dict) -> bool:
    value = _num(record.get("flow"))
    return value is not None and abs(value) >= config.MIN_TWEETWORTHY_FLOW_TRY


def _significant_investors(record: dict) -> bool:
    value = _num(record.get("investor_change"))
    return value is not None and abs(value) >= config.MIN_TWEETWORTHY_INVESTORS


def _top(records, key, reverse=True, limit=1, guard=None) -> List[dict]:
    return metrics.top_by(records, key, reverse=reverse, limit=limit, guard=guard)


def _index(records: List[dict]) -> Dict[str, dict]:
    return metrics.index_by_code(records)


def _segments(records: List[dict]):
    eligible = metrics.eligible_universe(records)
    tefas, befas = metrics.split_by_platform(eligible)
    return tefas, befas


# --- one draft per infographic card -----------------------------------------


def card_tefas_flows(tefas_general: List[dict], when: str) -> Optional[str]:
    """Matches TEFAS card 1: returns and money flow."""
    best = _top(tefas_general, "daily_return", guard="daily")
    inflow = _top(tefas_general, "flow")
    outflow = _top(tefas_general, "flow", reverse=False)

    lines = ["📊 {} TEFAS'ta öne çıkanlar".format(when), ""]
    if best and _significant_return(best[0]):
        lines.append(
            "🚀 En çok kazandıran {} {}".format(
                tag(best[0]["code"]), _pct(best[0].get("daily_return"))
            )
        )
    if inflow and _significant_flow(inflow[0]):
        lines.append(
            "💰 En çok para giren {} {}".format(
                tag(inflow[0]["code"]), formatter.money(inflow[0].get("flow"))
            )
        )
    if outflow and _significant_flow(outflow[0]):
        lines.append(
            "💸 En çok çıkış olan {} {}".format(
                tag(outflow[0]["code"]), formatter.money(outflow[0].get("flow"))
            )
        )

    if len(lines) <= 2:
        return None
    return _finish(lines)


def card_tefas_segments(tefas: List[dict], when: str) -> Optional[str]:
    """Matches TEFAS card 2: investor counts and the two sub-segments."""
    segments = metrics.split_segments(tefas)
    general = segments["general"]

    gained = _top(general, "investor_change")
    lost = _top(general, "investor_change", reverse=False)
    money = _top(segments["money_market"], "daily_return", guard="daily")
    metals = _top(segments["metals"], "daily_return", guard="daily")

    lines = ["👥 {} yatırımcılar ne yaptı?".format(when), ""]
    if gained and _significant_investors(gained[0]):
        lines.append(
            "📈 {} fonuna {} kişi katıldı".format(
                tag(gained[0]["code"]),
                formatter.count(gained[0].get("investor_change")),
            )
        )
    if lost and _significant_investors(lost[0]):
        lines.append(
            "📉 {} fonundan {} kişi ayrıldı".format(
                tag(lost[0]["code"]),
                formatter.count(lost[0].get("investor_change")),
            )
        )
    if metals and _significant_return(metals[0]):
        lines.append(
            "🥇 Kıymetli madenlerde {} {}".format(
                tag(metals[0]["code"]), _pct(metals[0].get("daily_return"))
            )
        )

    # Money-market funds are reported by flow, never by daily return. Their
    # return is ~0.1% by construction, so quoting it is the kind of empty number
    # this module exists to avoid; where the money goes is the actual news.
    money_flow = _top(segments["money_market"], "flow")
    if money_flow and _significant_flow(money_flow[0]):
        lines.append(
            "🏦 Para piyasasında {} {} giriş".format(
                tag(money_flow[0]["code"]),
                formatter.money(money_flow[0].get("flow")),
            )
        )

    if len(lines) <= 2:
        return None
    return _finish(lines)


def card_bes(befas: List[dict], when: str) -> Optional[str]:
    """Matches the BES card."""
    segments = metrics.split_segments(befas)
    general = segments["general"]

    best = _top(general, "daily_return", guard="daily")
    inflow = _top(general, "flow")
    gained = _top(general, "investor_change")

    lines = ["🏛 {} BES tarafı".format(when), ""]
    if best and _significant_return(best[0]):
        lines.append(
            "🚀 En çok kazandıran {} {}".format(
                tag(best[0]["code"]), _pct(best[0].get("daily_return"))
            )
        )
    if inflow and _significant_flow(inflow[0]):
        lines.append(
            "💰 En çok para giren {} {}".format(
                tag(inflow[0]["code"]), formatter.money(inflow[0].get("flow"))
            )
        )
    if gained and _significant_investors(gained[0]):
        lines.append(
            "👥 {} fonuna {} kişi katıldı".format(
                tag(gained[0]["code"]),
                formatter.count(gained[0].get("investor_change")),
            )
        )

    if len(lines) <= 2:
        return None
    lines.append("")
    lines.append("Emeklilik fonunuz hangisi?")
    return _finish(lines)


# --- commentary -------------------------------------------------------------


def tera_group(records: List[dict], when: str) -> Optional[str]:
    """The Tera Portföy funds and what they did on the day.

    Four funds, one line each, daily return only. `TMV` is the one TEFAS does
    not trade, which is exactly why it is in ``config.EXTRA_FUND_CODES`` and
    reachable at all; every other code has to be TEFAS-traded, and that is
    checked here rather than assumed of the list, so a fund that is delisted
    later drops out on its own instead of quietly becoming an untraded
    recommendation.
    """
    by_code = _index(records)
    lines = []
    for code in config.TERA_GROUP:
        record = by_code.get(code)
        if not record:
            continue
        if code not in config.EXTRA_FUND_CODES and not metrics.is_tefas_traded(record):
            continue
        if record.get("daily_return") is None:
            continue
        lines.append("{} {}".format(tag(code), _pct(record.get("daily_return"))))

    if not lines:
        return None
    heading = (
        "🔷 Tera grubu dün ne yaptı?"
        if when == "Dün"
        else "🔷 Tera grubu {} günü ne yaptı?".format(when)
    )
    return _finish([heading, ""] + lines)


def bes_five_year(records: List[dict]) -> Optional[List[str]]:
    """What backing a five-year champion would have meant since.

    The point is the gap between the long record and the recent one, which is
    why the draft is dropped unless both numbers exist.
    """
    _, befas = _segments(records)
    pool = [
        record
        for record in metrics.split_segments(befas)["general"]
        if _num(record.get("ret_5y")) is not None
        and _num(record.get("ret_1m")) is not None
        and abs(_num(record.get("ret_5y"))) <= config.MAX_ABS_PERIOD_RETURN_PCT
    ]
    if not pool:
        return None

    pool.sort(key=lambda r: -(_num(r.get("ret_5y")) or 0))
    champions = pool[:3]

    opening = _finish(
        [
            "🏆 BES'te 5 yılın şampiyonuna paranızın tamamını koysaydınız?",
            "",
            "Son 5 yılın en çok kazandıran emeklilik fonları 👇",
        ]
    )
    if not opening:
        return None

    lines = []
    for record in champions:
        lines.append(
            "{} 5 yıl {} · 1 yıl {} · 1 ay {}".format(
                tag(record["code"]),
                _pct(record.get("ret_5y")),
                _pct(record.get("ret_1y")),
                _pct(record.get("ret_1m")),
            )
        )
    body = _finish(lines)

    closing = _finish(
        [
            "Çok yükselmiş bir fon hep yükselecek demek değil.",
            "Fon yönetimi değişir, karar hataları olur, konjonktür döner.",
            "",
            "Portföyünüzü çeşitlendirin ve aktif takip edin.",
            "Görseldeki fonlar örnek amaçlıdır.",
        ]
    )

    return [t for t in (opening, body, closing) if t]


def why_funds() -> List[str]:
    """Evergreen: why a fund at all. Rotated in, not posted every day."""
    return [
        text
        for text in (
            _finish(
                [
                    "💭 Para zor kazanılıyor ve kaybetmek istemiyorsunuz.",
                    "",
                    "Birikiminiz var ama tek tek hisse seçmek istemiyorsanız,",
                    "işi profesyonellere bırakmanın bir yolu var: fonlar.",
                ]
            ),
            _finish(
                [
                    "Parayı para piyasası fonunda ya da mevduatta tutup",
                    "enflasyonla ucu ucuna denk getirmek bir strateji değil.",
                    "",
                    "\"Dolar alın\" diyen sözde ekonomistleri de dinlemeyin.",
                ]
            ),
            _finish(
                [
                    "Yatırım yapmayı öğrenin. Fonları öğrenin.",
                    "",
                    "Her gün TEFAS ve BEFAS verisini sade dille paylaşıyoruz.",
                    "Takipte kalın 👇",
                    "t.me/NeredeParaVar",
                ]
            ),
        )
        if text
    ]


def benchmark_thread(records: List[dict]) -> Optional[List[str]]:
    """Evergreen: what the year has actually paid, fund by fund.

    Gold and deposits are represented by the best TEFAS fund of that kind rather
    than by a spot price, because a fund is what a reader could have bought --
    and because no free, reliable feed for Turkish inflation or the lira was
    found worth trusting unattended.
    """
    eligible = metrics.eligible_universe(records)
    by_code = _index(eligible)

    def best_where(predicate) -> Optional[dict]:
        pool = [
            r
            for r in eligible
            if predicate(r) and _num(r.get("ret_ytd")) is not None
        ]
        return max(pool, key=lambda r: r["ret_ytd"]) if pool else None

    gold = best_where(metrics.is_precious_metal)
    money = best_where(metrics.is_money_market)
    named = [by_code[c] for c in ("PHE", "PBR", "TLY", "DFI") if c in by_code]

    if not named or not money:
        return None

    opening = _finish(
        [
            "💰 \"10 milyon liram var, ne yapmalıyım?\"",
            "",
            "Cevap her zaman aynı: portföy yapın.",
            "İşi bilmiyorsanız profesyonele emanet edin — yani fona.",
            "",
            "Yılbaşından beri neler oldu 👇",
        ]
    )
    if not opening:
        return None

    lines = [
        "{} {}".format(tag(r["code"]), _pct(r.get("ret_ytd"))) for r in named
    ]
    if gold:
        lines.append("🥇 Altın fonu {} {}".format(tag(gold["code"]), _pct(gold.get("ret_ytd"))))
    lines.append(
        "🏦 Para piyasası {} {}".format(tag(money["code"]), _pct(money.get("ret_ytd")))
    )
    body = _finish(lines)

    closing = _finish(
        [
            "Aradaki fark tesadüf değil, tercih.",
            "",
            "Fonlar hakkında daha fazlası için takipte kalın.",
            "t.me/NeredeParaVar",
        ]
    )
    return [t for t in (opening, body, closing) if t]


# --- assembly ---------------------------------------------------------------


def build_drafts(
    records: List[dict], data_day: date, today: date
) -> List[Dict[str, object]]:
    """Every draft for the day, each tagged with a title and its tweets.

    Returns a list of ``{"title": str, "tweets": [str, ...]}``. A draft with
    more than one tweet is meant to be posted as a thread.
    """
    when = _day_label(data_day, today)
    tefas, befas = _segments(records)
    tefas_general = metrics.split_segments(tefas)["general"]

    # The evergreen posts rotate so the account does not repeat itself daily.
    rotation = today.toordinal() % 2

    plans: List = [
        ("Kart 1 — TEFAS getiri ve akış", lambda: card_tefas_flows(tefas_general, when)),
        ("Kart 2 — TEFAS yatırımcı ve segmentler", lambda: card_tefas_segments(tefas, when)),
        ("Kart 3 — BES", lambda: card_bes(befas, when)),
        ("Tera grubu", lambda: tera_group(records, when)),
    ]
    if rotation == 0:
        plans.append(("BES 5 yıl retrospektifi", lambda: bes_five_year(records)))
        plans.append(("Neden fon?", why_funds))
    else:
        plans.append(("Yılbaşından beri karşılaştırma", lambda: benchmark_thread(records)))

    drafts: List[Dict[str, object]] = []
    for title, build in plans:
        try:
            result = build()
        except Exception:  # noqa: BLE001 - one bad draft must not stop the rest
            continue
        if not result:
            continue
        tweets = [result] if isinstance(result, str) else [t for t in result if t]
        if tweets:
            drafts.append({"title": title, "tweets": tweets})
    return drafts


def as_message(drafts: List[Dict[str, object]]) -> List[str]:
    """Telegram blocks, one per draft, each ready to copy out."""
    if not drafts:
        return [
            "<b>🐦 TWEET TASLAKLARI</b>\n"
            "<i>Bugün eşiği geçen bir hareket yok.</i>"
        ]

    blocks = [
        "<b>🐦 TWEET TASLAKLARI</b>\n"
        "<i>Kopyala-yapıştır için. Birden fazla tweet'i olanlar flood.</i>"
    ]
    for index, draft in enumerate(drafts, start=1):
        tweets = draft["tweets"]
        header = "<b>{}. {}</b>".format(index, formatter.esc(str(draft["title"])))
        if len(tweets) > 1:
            header += " <i>({} tweet'lik flood)</i>".format(len(tweets))
        parts = [header]
        for order, tweet in enumerate(tweets, start=1):
            label = "{}/{}".format(order, len(tweets)) if len(tweets) > 1 else ""
            parts.append(
                "{}<code>{}</code>\n<i>{} karakter</i>".format(
                    "<b>{}</b>\n".format(label) if label else "",
                    formatter.esc(str(tweet)),
                    len(str(tweet)),
                )
            )
        blocks.append("\n\n".join(parts))
    return blocks
