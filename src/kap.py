"""KAP (Public Disclosure Platform) notifications for watched funds.

Status: not yet wired up. Kept behind a feature flag so the rest of the report
is never blocked by it.

What was tried and why it does not work today:

* ``POST /tr/api/memberDisclosureQuery`` -- the endpoint every existing KAP
  scraper uses. The route still resolves (it does not 404) but never responds;
  requests hang past 120 seconds.
* ``/tr/api/disclosure/*``, ``/tr/api/todayDisclosure``, RSS feeds -- all 404.
  ``/tr/api/member/filter/CompanyTypeFund`` answers 200 but returns ``[]``.
* Scraping ``/tr/bildirim-sorgu`` -- the page is a Next.js app and its HTML
  carries only filter metadata (sectors, markets), not the disclosure list.
  The list arrives through a Next.js *server action*, whose identifier is a
  build hash that changes on every deploy.

Two viable routes remain, both cheap enough for GitHub Actions:

1. Call the server action, resolving its hash at run time from the page's JS
   chunks. No extra dependencies, but breaks whenever KAP changes its internals.
2. Drive a headless browser (Playwright) in the workflow. Roughly 40 extra
   seconds and ~200 MB of tooling per run, but robust against redesigns.

Until one is chosen, :func:`fetch_disclosures` returns an empty list and the
report prints an explanatory line instead of silently omitting the section.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List, Sequence

log = logging.getLogger(__name__)

ENABLED = False

DISABLED_NOTE = (
    "KAP entegrasyonu henüz aktif değil — KAP yeni altyapısına geçtiği için "
    "ayrıca bağlanması gerekiyor."
)


def fetch_disclosures(codes: Sequence[str], since: date) -> List[dict]:
    """Return recent disclosures for ``codes``.

    Each item is shaped ``{"code", "title", "published", "url"}``. Returns an
    empty list while the integration is disabled, and never raises -- a KAP
    outage must not take the daily report down with it.
    """
    if not ENABLED:
        log.info("KAP integration disabled; skipping disclosures.")
        return []

    raise NotImplementedError(
        "Pick an approach from the module docstring before enabling KAP."
    )
