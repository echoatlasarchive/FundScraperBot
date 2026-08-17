# FundScraperBot

Daily, weekly and monthly TEFAS + BEFAS fund reports delivered to Telegram,
driven entirely by GitHub Actions. No server, no database, no paid API.

Code and comments are English. The bot's output is Turkish.

## What it reports

* **Watchlist** — daily return, AUM, investor count, net flow, category rank and
  market share for `PHE`, `TLY`, `KHA`, `THF`, plus a separate money-market
  section for `TP2`, `PRY`, `PNU`.
* **Rankings** — top 10 best and worst daily returns, top 10 net inflows and
  outflows, and the same tables again restricted to money-market funds.
* **Weekly / monthly** — the same shape over a longer window, plus the funds
  whose AUM grew the most.

Rankings only consider funds with at least 100 million TRY under management
(`config.MIN_AUM_TRY`). Small funds otherwise dominate every leaderboard with
percentage moves that are noise.

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
