# FundScraperBot

Daily, weekly and monthly TEFAS + BEFAS fund reports delivered to Telegram,
driven entirely by GitHub Actions. No server, no database, no paid API.

Two audiences: the owner's private chat gets everything, and the public channel
[@NeredeParaVar](https://t.me/NeredeParaVar) gets the same rankings without the
owner's watchlists, plus a disclaimer.

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

**KAP disclosures** — covering yesterday and today. The two audiences watch
different funds: the owner's copy reports on the watchlists above, while the
channel gets `TLY`, `TMV`, `DOH`, `DFI`, `THF`, `KHA`, `PHE` and `PBR` — the
funds the commentary already names, rather than a personal portfolio.
On a Monday the window reaches back to the previous Friday, so anything filed
after Friday's report is not missed. Each entry carries the subject, a short
summary and a link to any attached PDF.

**Infographic cards** — one for TEFAS and one for BEFAS, rendered in the
channel's palette and sent as images to both the owner and the channel.
See `src/infographic.py`.

**Crypto exposure card** — a separate, portrait, undated card listing the eight
blockchain/fintech funds and how much of each is invested in crypto-linked
assets, read from the funds' monthly KAP portfolio reports. Rendered on demand
with `python -m src.cli crypto-card`, not on the daily run, because the figures
only change when new monthly reports land.

**Tweet drafts** — commentary built from the day's numbers, sent to the owner
only, to edit and post by hand. One draft per infographic card, plus popular-fund
commentary, the blockchain/fintech funds hung on bitcoin's move, and rotating
evergreen posts. Everything clears a significance threshold first, carries `#`
tags and ends with `ytd`. See `src/tweets.py`.

**Weekly / monthly** — the same shape over a longer window, plus the funds whose
AUM grew the most.

### Who makes it into a ranking

Three gates, all in `src/config.py`:

* Only funds **TEFAS actually trades**. A fund sold solely through its own
  distributor cannot be bought on TEFAS, so it has no business heading a table
  aimed at TEFAS investors. Enforced twice: the returns query asks for
  `islem=1`, and `metrics.eligible_universe()` re-checks the flag, because
  stored snapshots are read back long after they were written.
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

A full run touches ~1,360 funds and takes 6–8 minutes, plus roughly two minutes
for the KAP pass over the seventeen funds in `config.KAP_CODES`.

### KAP

KAP serves its two relevant pages very differently, so `src/kap.py` uses two
techniques. The disclosure list at `/tr/fon-bildirimleri/<slug>` is
client-rendered by a Next.js server action whose id changes on every request,
and stays empty until a category is picked — so it is driven with headless
Chromium. Individual disclosures at `/tr/Bildirim/<id>` are server-rendered and
fetched over plain HTTP. The row checkbox's `id` attribute is the disclosure id
that bridges the two.

Two things that will look like bugs but are not: the browser locale must be
Turkish, or KAP bounces its own server actions to `/en/` and the table never
fills; and each fund needs a fresh browser context, because driving every
navigation through one page wedges after the first.

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
| `TELEGRAM_CHANNEL_ID` | no | public channel; omit to report to the owner only |
| `TEFAS_TOKEN` | no | only if TEFAS rotates its static token |

The daily workflow needs write access to commit snapshots: **Settings → Actions
→ General → Workflow permissions → Read and write permissions**.

### 3. Schedule

`daily.yml` fires twice on weekdays, at **08:20 and 09:20 UTC — 11:20 and 12:20
Istanbul** — and each attempt exits within seconds unless TEFAS has published a
session that is not already stored.

The hour is set by when TEFAS finishes, not by when the report would ideally
land. An earlier schedule fired hourly from 05:20 UTC to absorb GitHub's queue
delay, but firing early only helps if the data is there: a run that fetched at
10:29 Istanbul found eighteen funds still unpriced and reported one of them at
−100%. TEFAS does not omit a fund it has not valued — it returns the row with
price, assets and units all zero — so an early attempt is not a free retry, it
is another chance to publish a wrong report.

The count is set by GitHub, which skips scheduled runs outright: of five crons
on 2026-08-20 one fired, 2026-08-21 fired 100 minutes late, and 2026-08-24 did
not fire at all. A single attempt means no report at all on a skipped day, and
silently — the bot cannot warn about a run that never starts. So there are two,
both after the platform is done, and the second is free when the first worked.

`periodic.yml` runs weekly on Monday and monthly on the 1st — twice each, for
the same reason — and reads the snapshots the daily job committed rather than
fetching anything itself.

Separately from the schedule, a report is only ever **delivered** between 07:00
and 20:00 Istanbul. The schedule decides when the bot runs; the window decides
whether it may send. Without it, anything that fires the workflow off-schedule —
a manual dispatch made while testing, a re-run — posts to the public channel at
whatever hour that happens to be, which is how a report once went out at 02:17
in the morning. Outside the window a run still fetches, stores and prints, and
sends nothing, and says so with a Telegram alert; `--force` (or the workflow's
`force` input) overrides. The bound is deliberately loose: it exists to stop an
off-schedule run posting at 2am, not to enforce the 13:30 order cutoff, and a
tighter 14:00 edge once swallowed a weekly report that GitHub had fired 91
minutes late.

## Running locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

export TELEGRAM_TOKEN=...
export TELEGRAM_CHAT_ID=...

./venv/bin/python -m src.cli daily --dry-run          # print, send nothing
./venv/bin/python -m src.cli fetch --watchlist-only   # fast smoke test
./venv/bin/python -m src.cli crypto-card              # render the crypto card
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
src/kap.py         KAP disclosures for watchlist funds
src/infographic.py daily TEFAS/BEFAS cards as PNGs
src/tweets.py      draft posts for X, owner only
src/market.py      outside context (bitcoin), fails soft
src/cli.py         entry point
brand/             logos and covers, and the script that regenerates them
```

## Known gaps

* **No flow history before the first run.** See above.
* **A fund TEFAS has not priced yet is not a missing row.** It comes back with
  price, assets and units at zero and a daily return of −100%. The run refuses
  to report or store a session while any fund is in that state, and blanks the
  day's figures for such a fund on the paths that skip that check.
* Public holidays are not modelled. When TEFAS publishes nothing, the fetched
  data is byte-identical to the previous snapshot; that is detected, no new file
  is written, and the report is labelled with the older date.
