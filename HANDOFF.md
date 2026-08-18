# Handoff — FundScraperBot

Context for picking this project up cold, in a fresh session or by another
person. Written 2026-08-18.

Read `README.md` first for what the bot does and how to run it. This file
covers the things that are **not** obvious from the code: what was tried and
rejected, which assumptions are load-bearing, and where the sharp edges are.

---

## 1. What this is

A personal fund tracker. Every weekday at 12:00 Istanbul, GitHub Actions
fetches the whole TEFAS + BEFAS universe (~1,363 funds), computes rankings and
money-flow metrics, and sends a Turkish-language report to one Telegram chat.
Weekly reports go out Monday, monthly on the 1st.

Owner: `echoatlasarchive`. Repo is **public** — chosen so Actions minutes are
unlimited and free. Nothing secret lives in the code.

**Conventions that must not drift:**

* All code, comments, commit messages and documentation in **English**.
* Only the bot's Telegram output is in **Turkish**.
* Secrets only ever in GitHub Secrets, never in files, never pasted into chat.

---

## 2. Current state

| | |
|---|---|
| Repo | https://github.com/echoatlasarchive/FundScraperBot |
| Workflows | `daily.yml` (weekdays 09:00 UTC), `periodic.yml` (Mon + 1st) |
| Secrets set | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` |
| Tests | 32, `python -m unittest discover -s tests` |
| History | Building from scratch; see §4 |

**Watchlists** (`src/config.py`): TEFAS `PHE TLY KHA THF` · money market
`TP2 PRY PNU` · BEFAS `GGJ TVH GCN FFC NHN BZY`.

**Ranking filters**: AUM ≥ 100M TRY **and** ≥ 1,000 investors. The investor
threshold is the important one — see §5.

---

## 3. The TEFAS API — what actually works

Base: `https://www.tefas.gov.tr/api/funds/`. No registration, no API key.
Auth is a long-lived static bearer token (`src/tefas.py:FALLBACK_TOKEN`),
overridable via the `TEFAS_TOKEN` secret if it is ever rotated.

| Endpoint | Payload | Returns |
|---|---|---|
| `fonGetiriBazliBilgiGetir` | `fonTipi: YAT` or `EMK` | Whole universe in **one call**: period returns, umbrella type, risk score |
| `fonBilgiGetir` | `fonKodu: XXX` | **One fund per call**: price, daily return, share count, AUM, investor count, category rank, market share |
| `fonTurGetir` | `dil: TR` | Umbrella type list |

`YAT` = securities funds (~1,052). `EMK` = pension funds (~311). **BEFAS needs
no separate scraper** — it is `EMK` on the same API.

### Dead ends — do not spend time here again

* **All legacy `/api/DB/Bind*` endpoints are retired.** `BindHistoryInfo`,
  `BindComparisonFundReturns`, `BindHistoryAllocation` all answer
  `404 ERR-006 "Method not found or disabled!"`. Every third-party TEFAS
  library on GitHub is built on these and is therefore dead, including
  `Tefas-API` and the `tefas` PyPI package.
* **The HTML pages are behind an F5/Shape bot wall.** `tefas.gov.tr/tr/...`
  returns a JS challenge to plain requests, and a browser gets "Request
  Rejected". So the token cannot be scraped from the page. The **API layer
  itself is not protected** — that is why this works at all.
* **There is no historical endpoint.** Probed extensively.
  `fonFiyatBilgiGetir` exists but answers `"Sistem Hatası!!"` to every payload
  shape tried; `fonBuyuklukBazliBilgiGetir` and `fonDetayGetir` resolve but
  return empty for every payload tried. If someone cracks
  `fonBuyuklukBazliBilgiGetir`, it would replace ~1,360 calls with one — worth
  a look, but do not assume it is possible.

### Rate limiting

The service drops connections under concurrency — 6 parallel workers got
connection resets after ~11 requests. **Sequential with a 0.25s delay** is the
tested-stable setting: ~1,360 funds in 7–11 minutes, no failures. Do not
"optimise" this into a thread pool.

---

## 4. History is built, not fetched — the load-bearing constraint

Because nothing upstream serves past dates:

* **Period returns** (1m/3m/6m/YTD/1y/3y/5y) are available from day one.
* **AUM, investor counts and flows have no history.** Each run stores a
  snapshot in `data/snapshots/YYYY-MM-DD.csv.gz` and commits it back to the
  repo. Metrics come from diffing snapshots.

So flow rankings need two sessions, the weekly report about a week, the monthly
about a month. Each report says so explicitly rather than printing an empty
table. **Do not "fix" a missing flow table that is simply waiting for data.**

The snapshot files are the only copy of this history. Losing them loses the
history permanently — it cannot be re-fetched.

### Dating snapshots: two bugs already fixed here, do not reintroduce

TEFAS returns a snapshot with **no date attached**, so the session has to be
inferred from the clock. Two things went wrong:

1. **Timezone.** Runners are UTC, the market is Istanbul. Use
   `storage.now_istanbul()` (fixed UTC+3 — Turkey has had no DST since 2016).
2. **Publication window.** TEFAS publishes the previous session during the
   **business morning**, not at midnight. Measured directly: at 03:09 on
   Tuesday 2026-08-18 the API still served **Friday's** close; at 12:03 the
   same day it served **Monday's**. So `data_date_for()` steps back *two*
   sessions before 10:00 Istanbul and one after.

Both bugs produced the same silent corruption: a snapshot labelled with a
session it did not belong to, then used as its own flow baseline, yielding
meaningless flow figures that still looked plausible.

**Guard in place:** `storage.follows_consecutively()` cross-checks each fetch
against the stored baseline using the price identity below, and warns when the
inferred label disagrees. If you see that warning, trust it.

Also pin the clock **once at the start of the run**, before `collect()` — the
fetch takes ~10 minutes and can cross midnight.

---

## 5. Methodology decisions worth preserving

### Net flow uses share count, not AUM

```
net_flow = (shares_today − shares_yesterday) × price_today
```

Comparing AUM day over day conflates money moving with the portfolio changing
value: a fund up 5% shows a bigger AUM without a lira being invested.
`payAdet` is units outstanding, so this isolates actual money. TEFAS is
internally consistent: `shares × price` reproduces reported AUM to rounding.

### Share splits cannot be caught by an AUM cross-check

A split multiplies units and divides price, reading as a huge inflow. Note
that

```
aum_now − aum_before ≡ flow + shares_before × (price_now − price_before)
```

is an **algebraic identity** — it holds for splits and real flows alike, so it
cannot discriminate. What does: TEFAS reports `gunlukGetiri` independently of
the price level, so on a normal session the price ratio matches the reported
return, and across a split it does not. That is `metrics._is_discontinuous()`,
and the same identity powers `follows_consecutively()`. Only valid when the
baseline is the immediately preceding session — hence the `consecutive` flag.

### The investor threshold matters more than the size threshold

Assets alone do not separate a retail fund from a private vehicle. Before this
filter the top-10 daily gainers included funds with **17, 19 and 23**
investors. Real example: `PPF` (Azimut Akçe Serbest) holds 550M TRY for **22**
investors.

1,000 is placed deliberately — just below the 10th percentile of the mainstream
categories (equity 1,057, mixed 816, fund-of-funds 829) so it barely touches
them, while the median Serbest fund has 537 investors. Serbest drops from 27.7%
of the eligible universe to 13.5%. **Do not raise it casually**; re-derive from
the data if you change it.

### Segment classification needs the fund name, not just the category

* **Money market**: TEFAS files only 49 funds under "Para Piyasası Fonu", but
  **105** are money-market funds in substance — the rest are logged as
  "Serbest" or "Katılım" (e.g. *Ak Portföy Para Piyasası Katılım Serbest Fon*).
  All 56 name-matched additions were manually verified as genuine.
* **Precious metals**: spread across "Altın Fonu", "Altın Katılım Fonu",
  "Kıymetli Madenler", and plain "Fon Sepeti Fonu" for the silver baskets.

**Two Turkish text traps**, both handled in `metrics.fold()` and the
word-boundary patterns:

1. `"ALTIN".lower()` → `"altin"` but `"Altın".lower()` → `"altın"` — the
   dotted/dotless i split means naive lowercasing does not compare equal.
2. A substring search for "altın" also matches **"altıncı"** ("sixth"),
   misfiling ordinary hedge funds such as *Ak Portföy Altıncı Serbest* and
   *İstanbul Portföy Onaltıncı Serbest* as gold funds. Nine funds hit this.

### Sanity bounds

Some funds report period returns in the hundreds of thousands of percent after
a restructuring — `TLY` shows a 5-year return of ~589,891%. `MAX_ABS_*` in
`config.py` keeps these out of rankings. They are data artifacts, not
performance.

---

## 6. Open items

### KAP integration — not implemented

`src/kap.py` is a stub; the daily report prints an explanatory line. KAP moved
to a Next.js application and its old public API is gone:

* `POST /tr/api/memberDisclosureQuery` — the endpoint every existing KAP
  scraper uses. Still routes (does not 404) but **never responds**; hangs past
  120s.
* `/tr/api/disclosure/*`, `/tr/api/todayDisclosure`, RSS feeds — all 404.
  `/tr/api/member/filter/CompanyTypeFund` answers 200 with `[]`.
* Scraping `/tr/bildirim-sorgu` — the HTML carries only filter metadata
  (sectors, markets), not the disclosure list. That arrives via a Next.js
  **server action**, whose identifier is a build hash changing on every deploy.

Two viable routes, both cheap enough for Actions:

1. Call the server action, resolving its hash at run time from the page's JS
   chunks. No new dependencies, breaks whenever KAP redeploys.
2. Drive headless Playwright in the workflow. ~40s and ~200MB extra per run,
   robust against redesigns.

Scope when built: disclosures for watchlist funds only.

### Backfilling flow history

Decided to accept "start collecting from today" rather than delay launch. If a
source for historical AUM / investor counts turns up (SPK or Takasbank
bulletins, an archive site, a third-party dataset), it could be injected into
`data/snapshots/` retroactively using the same CSV schema.

### Other

* **GitHub's scheduler is unreliable.** `schedule` runs are queued and often
  delayed; 09:00 UTC is one of the most congested slots. Delays of 10–60
  minutes are normal and runs are occasionally skipped entirely. A missing
  12:00 message is not automatically a bug — check `gh run list` for whether a
  `schedule` event fired at all before debugging anything else.
* Public holidays are not modelled. When TEFAS publishes nothing the fetch is
  byte-identical to the previous snapshot; that is detected, no file is
  written, and the report is labelled with the older date.
* A static site over `data/snapshots/` via GitHub Pages was discussed as a
  later addition. Nothing built yet.

---

## 7. Operating it

```bash
# See today's report without sending it (no credentials needed)
./venv/bin/python -m src.cli daily --dry-run

# Fast smoke test against the live API
./venv/bin/python -m src.cli fetch --watchlist-only

# Trigger the real thing
gh workflow run daily.yml --repo echoatlasarchive/FundScraperBot

# Watch it
gh run list --repo echoatlasarchive/FundScraperBot --limit 5
gh run view <id> --repo echoatlasarchive/FundScraperBot --log
```

The bot commits snapshots itself, so a local clone goes stale. **`git pull`
before editing**, or a push will be rejected.

Failures send a Telegram alert rather than failing silently. A `401` from TEFAS
means the static token was rotated upstream — set `TEFAS_TOKEN`.
