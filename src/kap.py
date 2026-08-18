"""KAP (Public Disclosure Platform) notifications for watched funds.

KAP runs on Next.js and serves its fund pages in two very different ways, so
this module uses two very different techniques:

* **The disclosure list is client-rendered.** ``/tr/fon-bildirimleri/<slug>``
  arrives as a shell; the table is filled in by a Next.js *server action* whose
  identifier changes on every request, and replaying that POST from plain HTTP
  answers ``Server action not found``. Worse, the table stays empty until a
  category is chosen -- the page opens on a disabled "Seçim Yapınız" option. So
  the list is read with a headless browser that picks "Tüm Bildirimler" and
  presses the filter button, exactly as a person would.
* **Each disclosure page is server-rendered.** ``/tr/Bildirim/<id>`` comes back
  complete over plain HTTP, carrying the summary, the attachment count and the
  ``/tr/api/file/download/<id>`` links. No browser needed, so the per-disclosure
  fetches stay fast.

The bridge between the two is the row checkbox: its ``id`` attribute is the
disclosure id.

Everything here fails soft. A KAP outage, a redesign or a missing browser must
never take the daily fund report down with it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from . import storage

log = logging.getLogger(__name__)

try:  # Playwright is only needed for the list page.
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the environment
    sync_playwright = None


class _EmptyTable(Exception):
    """The filter repainted no rows -- worth one retry before believing it."""

ENABLED = sync_playwright is not None

DISABLED_NOTE = (
    "KAP taraması çalıştırılamadı — tarayıcı bileşeni bu ortamda kurulu değil."
)

BASE = "https://www.kap.org.tr"
FUND_PAGE = BASE + "/tr/fon-bildirimleri/{slug}"
DISCLOSURE_PAGE = BASE + "/tr/Bildirim/{id}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9"}

SLUG_CACHE = "kap_slugs"

# Turkish letters have no business in a URL slug. Note the two I forms: KAP
# writes "ZURİCH" where TEFAS writes "ZURICH", which is why fund *names* are
# useless for verifying we landed on the right page -- the fund code is used
# instead.
TURKISH_TO_ASCII = str.maketrans("ÇĞİIÖŞÜçğıiöşü", "cgiiosucgiiosu")


# -- slug resolution ---------------------------------------------------------


def _slugify(text: str) -> str:
    ascii_text = (text or "").translate(TURKISH_TO_ASCII).lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _candidate_slugs(code: str, name: str) -> List[str]:
    """KAP slugs are the code followed by the full fund name.

    The parenthetical suffix is usually part of the slug ("... fonu-hisse-
    senedi-yogun-fon"), but not always, so the stripped form is kept as a
    fallback.
    """
    full = _slugify(name)
    bare = _slugify(re.sub(r"\(.*?\)", " ", name))
    candidates = ["{}-{}".format(code.lower(), full)]
    if bare and bare != full:
        candidates.append("{}-{}".format(code.lower(), bare))
    return candidates


def _page_is_for(html: str, code: str) -> bool:
    """An unknown slug still answers 200, with a ~69 KB shell and no fund on it.

    A real page is substantially larger and mentions the fund code.
    """
    return len(html) > 75_000 and code.upper() in html


def resolve_slug(
    session: requests.Session, code: str, name: str, cache: Dict[str, str]
) -> Optional[str]:
    cached = cache.get(code)
    if cached:
        return cached

    for candidate in _candidate_slugs(code, name):
        try:
            resp = session.get(FUND_PAGE.format(slug=candidate), timeout=60)
        except requests.RequestException as exc:
            log.warning("KAP slug probe failed for %s: %s", code, exc)
            continue
        if resp.status_code == 200 and _page_is_for(resp.text, code):
            cache[code] = candidate
            return candidate

    log.warning("Could not resolve a KAP page for %s (%s).", code, name)
    return None


# -- date handling -----------------------------------------------------------


def window_start(today: date) -> date:
    """Earliest disclosure date to report on.

    The report covers yesterday and today. On a Monday that reaches back to the
    previous Friday instead, so disclosures published after Friday's report --
    on Friday evening or over the weekend -- are not skipped. Stepping back one
    *business* day gives exactly that: Friday on a Monday, yesterday otherwise.
    """
    return storage.previous_business_day(today)


def parse_row_date(text: str, today: date) -> Optional[date]:
    """KAP labels recent rows "Bugün" / "Dün" and older ones "14.08.2026"."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered.startswith("bugün"):
        return today
    if lowered.startswith("dün"):
        return today - timedelta(days=1)

    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", cleaned)
    if match:
        day, month, year = (int(g) for g in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _row_time(text: str) -> str:
    match = re.search(r"(\d{2}:\d{2})", text or "")
    return match.group(1) if match else ""


# -- list scraping (headless browser) ----------------------------------------

# Column order of the disclosure table.
COL_DATE, COL_CODE, COL_FUND, COL_TYPE, COL_SUBJECT, COL_SUMMARY = 2, 3, 4, 5, 6, 7


def _scrape_fund_rows(page, url: str, code: str, today: date, since: date) -> List[dict]:
    # Not "networkidle": the page keeps firing analytics and bot-detection
    # beacons, so the network never goes quiet and the wait always times out.
    # Waiting for the controls themselves is both faster and reliable.
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector("[role=combobox]", timeout=45_000)
    page.wait_for_timeout(1_000)

    # The table renders nothing until a category is chosen; the first option is
    # a disabled placeholder, so "Tüm Bildirimler" is the one to pick.
    page.locator("[role=combobox]").nth(1).click()
    page.wait_for_selector("[role=option]", timeout=20_000)
    page.locator("[role=option]").locator("text=Tüm Bildirimler").first.click()
    page.wait_for_timeout(500)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.locator("button.filter-btn").first.click()

    # The filter repaints the table; give the rows a moment to arrive.
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('table tbody tr').length > 1",
            timeout=30_000,
        )
    except Exception:  # noqa: BLE001 - either no disclosures, or a flaky repaint
        raise _EmptyTable(code)
    page.wait_for_timeout(1_500)

    rows = page.locator("table tbody tr")
    found: List[dict] = []

    for index in range(rows.count()):
        row = rows.nth(index)
        cells = row.locator("td")
        if cells.count() <= COL_SUMMARY:
            continue

        def cell(i: int) -> str:
            return " ".join(cells.nth(i).inner_text().split())

        raw_date = cell(COL_DATE)
        published = parse_row_date(raw_date, today)
        if published is None:
            continue
        if published < since:
            # Rows are newest first, so everything below is older still.
            break
        if cell(COL_CODE).upper() != code.upper():
            # The page also lists platform-wide announcements with no fund code.
            continue

        checkbox = row.locator("input[type=checkbox]").first
        disclosure_id = checkbox.get_attribute("id") if checkbox.count() else None
        if not disclosure_id:
            continue

        found.append(
            {
                "code": code,
                "id": disclosure_id,
                "date": published,
                "time": _row_time(raw_date),
                "type": cell(COL_TYPE),
                "subject": cell(COL_SUBJECT),
                "summary": cell(COL_SUMMARY),
            }
        )

    return found


# -- detail fetching (plain HTTP) --------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S)


def _visible_text(html: str) -> str:
    stripped = _SCRIPT_RE.sub(" ", html)
    return " ".join(_TAG_RE.sub(" ", stripped).split())


def enrich(session: requests.Session, item: dict) -> dict:
    """Add attachment links, and a summary if the list row did not carry one."""
    try:
        resp = session.get(DISCLOSURE_PAGE.format(id=item["id"]), timeout=60)
    except requests.RequestException as exc:
        log.warning("KAP detail fetch failed for %s: %s", item["id"], exc)
        return item

    if resp.status_code != 200:
        return item

    html = resp.text
    paths = []
    for path in re.findall(r"(?:/tr)?/api/file/download/[0-9a-zA-Z]+", html):
        url = BASE + (path if path.startswith("/tr") else "/tr" + path)
        if url not in paths:
            paths.append(url)
    item["attachments"] = paths

    if not item.get("summary") or item["summary"] == "-":
        text = _visible_text(html)
        match = re.search(r"Özet Bilgi\s+(.{5,220}?)\s+\[", text)
        if match:
            item["summary"] = match.group(1)

    return item


# -- entry point -------------------------------------------------------------


def fetch_disclosures(
    funds: Sequence[Tuple[str, str]],
    today: Optional[date] = None,
) -> List[dict]:
    """Disclosures for ``funds`` published within the reporting window.

    ``funds`` is a sequence of ``(code, name)`` pairs. Each item comes back as
    ``{"code", "id", "date", "time", "type", "subject", "summary",
    "attachments", "url"}``.

    Returns an empty list rather than raising: the fund report must survive a
    KAP outage.
    """
    if not ENABLED:
        log.info("KAP scraping unavailable (playwright not installed).")
        return []

    today = today or storage.now_istanbul().date()
    since = window_start(today)
    log.info("KAP window: %s .. %s", since, today)

    session = requests.Session()
    session.headers.update(HEADERS)

    cache = storage.read_state(SLUG_CACHE)
    results: List[dict] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()

            for code, name in funds:
                slug = resolve_slug(session, code, name, cache)
                if not slug:
                    continue

                # A fresh context per fund. Driving thirteen navigations through
                # one page wedges KAP: the first fund loads and every one after
                # it times out, presumably because its bot-detection scripts
                # accumulate state. Throwing the context away each time costs a
                # second or two and makes the run reliable.
                #
                # A non-Turkish locale makes KAP bounce its own server actions
                # to /en/ and lose them, leaving the table permanently empty.
                url = FUND_PAGE.format(slug=slug)
                for attempt in (1, 2):
                    context = browser.new_context(
                        locale="tr-TR",
                        extra_http_headers={"Accept-Language": "tr-TR,tr;q=0.9"},
                        viewport={"width": 1500, "height": 1100},
                    )
                    page = context.new_page()
                    try:
                        rows = _scrape_fund_rows(page, url, code, today, since)
                        log.info(
                            "KAP %s: %d disclosure(s) in window.", code, len(rows)
                        )
                        results.extend(rows)
                        break
                    except _EmptyTable:
                        # The filter occasionally repaints nothing. One retry
                        # sorts it out; a fund genuinely without disclosures
                        # simply reports zero twice.
                        if attempt == 2:
                            log.info("KAP %s: no rows after retry.", code)
                    except Exception as exc:  # noqa: BLE001 - one fund must not stop the rest
                        log.warning("KAP scrape failed for %s: %s", code, exc)
                        if attempt == 2:
                            break
                    finally:
                        context.close()

            browser.close()
    except Exception as exc:  # noqa: BLE001 - browser launch, etc.
        log.warning("KAP scraping aborted: %s", exc)
        return []

    storage.write_state(SLUG_CACHE, cache)

    for item in results:
        enrich(session, item)
        item["url"] = DISCLOSURE_PAGE.format(id=item["id"])

    results.sort(key=lambda i: (i["date"], i.get("time") or ""), reverse=True)
    return results
