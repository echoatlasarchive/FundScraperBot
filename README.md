# FundScraperBot

Daily, weekly and monthly TEFAS + BEFAS fund reports delivered to Telegram,
driven entirely by GitHub Actions. No server, no database, no paid API.

Code and comments are English. The bot's output is Turkish.

## What it reports

**Watchlists** — daily return, AUM, investor count, net flow, category rank and
market share for each of:

| Group | Funds |
|---|---|
| TEFAS | `PHE`, `TLY`, `KHA`, `THF` |
| Money market | `TP2`, `PRY`, `PNU` |
| BEFAS (pension) | `GGJ`, `TVH`, `GCN`, `FFC`, `NHN`, `BZY` |

**Rankings** — TEFAS and BEFAS are reported under separate headings, each
showing the best returns, the largest inflows and outflows, and the biggest
gains in investor count. Every table lists five funds. Each platform then
repeats a best-returns table for its sub-segments:

* *Money market* — TEFAS only. Pension funds have no money-market category, so
  BEFAS gets no such section.
* *Precious metals* — gold and silver funds pooled together, on both platforms.

**Weekly / monthly** — the same shape over a longer window, plus the funds whose
AUM grew the most.

### Who makes it into a ranking

Two thresholds, both in `src/config.py`:

* `MIN_AUM_TRY` — 100 million TRY. Tiny funds otherwise dominate every
  leaderboard with percentage moves that are noise.
* `MIN_INVESTORS` — 5,000. Size alone does not separate a retail fund from a
  private vehicle: plenty of "Serbest" funds hold hundreds of millions on behalf
  of a handful of investors. Before this filter the top daily gainers included
  funds with 17, 19 and 23 investors. At 1,000 the eligible universe was 761
  funds; at 5,000 it is around 460, weighted towards widely held retail funds.

Money-market and precious-metal funds are held out of the headline tables, since
they have their own. Otherwise a rally in gold fills every slot of the general
leaderboard with the same trade.

### Segment classification

Category alone is not enough, so the fund's name is matched too.

* **Money market** — TEFAS files only 49 funds under "Para Piyasası Fonu", but
  105 are money-market funds in substance; the rest are logged as "Serbest" or
  "Katılım" (e.g. *Ak Portföy Para Piyasası Katılım Serbest Fon*).
* **Precious metals** — spread across "Altın Fonu", "Altın Katılım Fonu",
  "Kıymetli Madenler" and plain "Fon Sepeti Fonu" for the silver basket funds.

Matching uses word boundaries on case- and diacritic-folded text. Both details
matter: Turkish `ALTIN`/`Altın` fold differently under `str.lower()`, and a
naive substring search for "altın" also matches **altıncı** ("sixth"), which
would misfile ordinary hedge funds such as *Ak Portföy Altıncı Serbest* as gold
funds.

## Data sources

Everything comes from `https://www.tefas.gov.tr/api/funds/*`. It needs no
registration and no API key.

| Endpoint | Cost | Fields |
|---|---|---|
| `fonGetiriBazliBilgiGetir` | 1 call for the whole universe | period returns (1m/3m/6m/YTD/1y/3y/5y), umbrella type, risk score |
| `fonBilgiGetir` | 1 call per fund | price, daily return, share count, AUM, investor count, category rank, market share |
| `fonTurGetir` | 1 call | umbrella fund type list |

`fonTipi: "YAT"` covers the ~1,050 securities mutual funds; `fonTipi: "EMK"`
covers the ~310 pension funds. BEFAS needs no separate scraper.

A full run touches ~1,360 funds and takes 6–8 minutes.

### Things worth knowing about the upstream service

* The legacy `/api/DB/Bind*` endpoints are retired and answer
  `ERR-006 Method not found or disabled`. Every third-party TEFAS library built
  on them is dead.
* The HTML pages sit behind an F5/Shape bot wall, so the bearer token cannot be
  scraped from them. A long-lived static token is used instead, overridable via
  the `TEFAS_TOKEN` secret if it is ever rotated. A rotated token surfaces as a
  Telegram alert, not a silent failure.
* **There is no historical endpoint.** `fonBilgiGetir` returns a current
  snapshot only.

### Why history is built rather than fetched

Period *returns* are available from day one. AUM, investor counts and flows are
not — nothing upstream serves them for past dates. So each run stores a snapshot
in `data/snapshots/YYYY-MM-DD.csv.gz` and commits it back to the repository, and
metrics are computed by diffing snapshots.

That means flow rankings need two days of data, the weekly report needs about a
week, and the monthly report about a month. Each report says so explicitly
rather than printing an empty table.

### How net flow is computed

Comparing AUM day over day conflates money moving with the portfolio changing
value: a fund that gains 5% shows a larger AUM without a single lira being
invested. Share count separates the two:

```
net_flow = (shares_today − shares_yesterday) × price_today
```

`payAdet` is units outstanding, so this is money that actually entered or left,
with performance stripped out.

## Setup

### 1. Telegram

Create a bot with [@BotFather](https://t.me/botfather) and get your numeric chat
ID (message [@userinfobot](https://t.me/userinfobot)).

> If a token has ever been pasted into a file or a chat, run `/revoke` in
> BotFather and use the fresh one. Tokens belong in GitHub Secrets, nowhere else.

### 2. GitHub

Push this repository, then add under **Settings → Secrets and variables →
Actions**:

| Secret | Required | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN` | yes | BotFather token |
| `TELEGRAM_CHAT_ID` | yes | where reports are sent |
| `TEFAS_TOKEN` | no | only if TEFAS rotates its static token |

The daily workflow needs write access to commit snapshots: **Settings → Actions
→ General → Workflow permissions → Read and write permissions**.

### 3. Schedule

`daily.yml` runs at 09:00 UTC (12:00 Istanbul) on weekdays. `periodic.yml` runs
weekly on Monday and monthly on the 1st, 15 minutes later, and reads the
snapshots the daily job committed rather than fetching anything itself.

GitHub's scheduler queues jobs under load, so a run can start several minutes
late. That is normal and harmless here.

## Running locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

export TELEGRAM_TOKEN=...
export TELEGRAM_CHAT_ID=...

./venv/bin/python -m src.cli daily --dry-run          # print, send nothing
./venv/bin/python -m src.cli fetch --watchlist-only   # fast smoke test
./venv/bin/python -m src.cli daily                    # fetch, store and send
./venv/bin/python -m src.cli weekly
./venv/bin/python -m src.cli monthly
```

`--dry-run` needs no Telegram credentials.

## Configuration

`src/config.py` holds the watchlist, the size threshold, the ranking length and
the sanity bounds that keep data artifacts out of the tables — some funds report
period returns in the hundreds of thousands of percent after a share
restructuring.

## Layout

```
src/config.py      watchlist, thresholds, secret plumbing
src/tefas.py       API client, retries, token resolution
src/storage.py     snapshot read/write, staleness detection
src/metrics.py     flows, deltas, rankings, filters
src/formatter.py   Turkish Telegram rendering
src/telegram.py    delivery and failure alerts
src/kap.py         KAP disclosures (not yet wired — see the module docstring)
src/cli.py         entry point
```

## Known gaps

* **KAP disclosures are not implemented.** KAP moved to a Next.js application;
  its old public API either 404s or hangs, and the disclosure list now arrives
  through a server action keyed by a build hash. `src/kap.py` documents the two
  workable approaches. The daily report prints an explanatory line in the
  meantime.
* **No flow history before the first run.** See above.
* Public holidays are not modelled. When TEFAS publishes nothing, the fetched
  data is byte-identical to the previous snapshot; that is detected, no new file
  is written, and the report is labelled with the older date.
