# Handoff — FundScraperBot

Context for picking this project up cold, in a fresh session or by another
person. Written 2026-08-18, last updated 2026-08-20 (delivery window, the
traded-only filter moved into `metrics`, and the rebuilt crypto weights).

Read `README.md` first for what the bot does and how to run it. This file
covers the things that are **not** obvious from the code: what was tried and
rejected, which assumptions are load-bearing, and where the sharp edges are.

---

## 1. What this is

A fund tracker with two audiences. Every weekday morning GitHub Actions fetches
the whole TEFAS + BEFAS universe (~1,365 funds), computes rankings and money-flow
metrics, and sends a Turkish-language report — the full version, watchlists
included, to the owner's private chat, and a public version without them to the
@NeredeParaVar channel. Weekly reports go out Monday, monthly on the 1st.

It also renders two infographic cards a day (TEFAS and BEFAS) and drafts a few
posts for X, which go to the owner only.

Owner: `echoatlasarchive`. Repo is **public** — chosen so Actions minutes are
unlimited and free, which the multi-attempt schedule now depends on. Nothing
secret lives in the code.

**Conventions that must not drift:**

* All code, comments, commit messages and documentation in **English**.
* Only the bot's Telegram output is in **Turkish**.
* Secrets only ever in GitHub Secrets, never in files, never pasted into chat.

---

## 2. Current state

| | |
|---|---|
| Repo | https://github.com/echoatlasarchive/FundScraperBot |
| Workflows | `daily.yml` (weekdays, 08:20 UTC), `periodic.yml` (Mon + 1st, 09:15 + 10:15 UTC) |
| Secrets set | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_CHANNEL_ID` |
| Tests | 97, `python -m unittest discover -s tests` |
| Public channel | [@NeredeParaVar](https://t.me/NeredeParaVar), id `-1004445596324` |
| Brand assets | `brand/`, regenerate with `python brand/build_brand.py` |
| History | Building from scratch; see §4 |

**Watchlists** (`src/config.py`): TEFAS `TLY THF DOH DMG PHE KHA TAU` · money
market `TP2 PRY PNU` · BEFAS `GGJ TVH GCN`. KAP scans these plus `TMV`.

**Ranking filters**: AUM ≥ 100M TRY **and** ≥ 5,000 investors. The investor
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

### 4a. An unpriced fund is a placeholder, not a missing row

The failure that ended the multi-cron schedule, and the more important half of
it. **TEFAS does not omit a fund it has not valued yet.** It returns the row
with `sonFiyat`, `portBuyukluk` and `payAdet` all zero, and `gunlukGetiri` at
**-100**, because the price nominally fell to nothing. `yatirimciSayi` stays
populated, so the record does not look empty.

On 2026-08-20 eighteen funds were in that state when the run fetched at 10:29,
and the report went out with `PHE` at **-100%**.

Every guard missed it, each for its own reason:

* `storage.published_fraction()` **skips any record without a usable price on
  either side**, so the placeholders left its denominator rather than counting
  against it. It read **99.5%** against a 95% threshold and passed. Raising the
  threshold would not have helped — eighteen funds out of 1,370 is 1.3%.
* `MAX_ABS_DAILY_RETURN_PCT` (25%) does keep -100 out of the *rankings*, via
  `top_by(guard="daily")`. But the **watchlist block prints unconditionally** —
  it is a fixed list of the owner's funds, not a ranking — and `PHE` is on it.
  `PBR` is in `POPULAR_GROUPS`, so the tweet drafts carried it too.
* The snapshot was then **stored** with those zeros, which makes it the next
  day's flow baseline: `PHE` going 0 → 9.3bn units reads as an enormous inflow.

Two fixes, at different depths:

* `storage.unvalued_funds()` finds them. **The tell is a zero, not an absence,
  and a transition, not a standing state.** A per-fund request that times out
  leaves the row with *no* price rather than a zero — one did the same day,
  `AIS`, out of 1,370 — and counting that as an unfinished session would hold
  the whole day's report hostage to a single flaky request, which with one
  scheduled attempt means no report at all. Only an explicit zero is TEFAS
  saying "not valued yet".

  **The transition matters too.** Some funds sit at zero permanently — dormant or wound up, `ETN` and
  `ZTV` among them, three on that day — so a plain "any zero price" test would
  block every run for ever. A fund that had a real price in the baseline and has
  none now is a fund still being valued. Even one is disqualifying: nothing is
  reported and nothing is stored.
* `metrics.is_reportable()` decides whether being late matters. Refusing to
  report while **any** fund is unpriced was too strict and cost a day: on
  2026-08-25 exactly one fund was late — `PSH`, 16.6M TRY and 354 investors,
  below both ranking thresholds and on no list — and the run reported nothing.
  `PSH` appears in no table, no card and no tweet; nobody would have seen it
  either way. The question is not "is the session complete" but **"is the data I
  am about to print complete"**, so only a fund that would have been printed
  blocks: one over both thresholds, or one named in `config.NAMED_FUNDS` (the
  watchlists, the KAP sets, the crypto funds, the commentary's funds, `TMV`).
  Judge it on the **baseline** row — a placeholder has zero assets and fails the
  size filter by construction, so judging it on its own row would make every
  late fund look harmless and the gate would never fire at all.

  Checked against both incidents: 2026-08-20 flags 14, of which 8 are
  reportable including `PHE` → blocks, correctly. 2026-08-25 flags `PSH` alone,
  0 reportable → proceeds, correctly.
* `metrics.is_valued()` is the backstop, applied in `attach_deltas()`, which
  every path runs through. An unvalued record's `daily_return`, `flow` and
  `aum_change` are blanked so they render as `—`. This matters because a
  **forced manual run skips the gate entirely** — `--force` drops
  `--only-if-new` — and that is exactly the run someone makes when they are
  impatient about a late session.

The 2026-08-19 snapshot was repaired by re-fetching the same session later the
same day, once TEFAS had finished: the platform serves the previous close until
the next one is published, so a re-fetch inside that window costs nothing but
time. `store()` already handles it — same `data_day` as the newest file means
the "re-fetched session, refreshing the snapshot" branch.

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

The threshold started at 1,000 — just below the 10th percentile of the
mainstream categories (equity 1,057, mixed 816, fund-of-funds 829) so it barely
touched them, while the median Serbest fund has 537 investors. It was later
raised to 5,000 by preference, taking the eligible universe from 761 funds to
about 460. **Do not change it casually**; re-derive from the data if you do.

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

## 6. Scheduling — why it looks over-engineered

A single 09:00 UTC cron delivered the report at **13:28 Istanbul**, past the
13:30 fund-order cutoff, which makes it useless for its main purpose. Measured
cause, two consecutive days:

| | |
|---|---|
| cron | 09:00 UTC |
| actually queued | 10:03 UTC (and 10:02 the day before) — **~63 minutes late** |
| run duration | ~25 minutes |

So GitHub's queue, not TEFAS, was the problem. On-the-hour crons sit in the most
congested slot. The fix has three parts, and removing any one of them brings the
lateness back:

1. **Fire early and repeatedly** — hourly from 05:20 UTC, so a queue delay still
   leaves room before the cutoff.
2. **Fire off the hour** (`:20`), which is measurably less congested.
3. **`--only-if-new`** — two gates, in order of cost:
   * `cli.session_is_published()` probes five funds (`cli.PROBE_CODES`) against
     the newest snapshot and exits in seconds unless something moved.
   * `cli.session_is_complete()` then checks the *whole* universe after the
     scan. This is the important one. TEFAS values and releases funds across
     the morning, so "something moved" does not mean "the session is out" — an
     early run can find the first funds updated and everything else still on
     yesterday's prices, and a report built on that silently mixes two
     sessions. A finished session moves **99.6%** of prices (measured: 1,360 of
     1,365 between 2026-08-17 and 2026-08-18, and four of the five that stood
     still were dormant funds with no assets and no investors), so
     `storage.PUBLISHED_THRESHOLD` is 0.95 and anything below it waits for a
     later attempt.

   Public repo, so unlimited Actions minutes — a discarded scan costs nothing.

That probe also retired the last of the clock guessing. `cli.resolve_data_day()`
now takes the trading day from the **snapshot chain** — if the price identity
confirms this data is the session after the newest stored one, that is what it
is — and falls back to `data_date_for()` only on a first run or after a gap the
chain cannot bridge.

### Where this ended up

**One cron, `20 8 * * 1-5`, and it reports whatever it finds.** Both are the
owner's decision, each stated twice, and the reasoning below is kept because it
explains what the trade-offs were rather than what they should be.

The hour is not negotiable and is the one thing every version has agreed on:
**nothing may fetch before TEFAS has finished, about 11:00 Istanbul.** That is
what caused the -100% report (§4a) and it is the constraint the whole schedule
exists around.

The count and the gates were tried both ways within a week, and both directions
failed in their own way:

* *Many early attempts* (05:20–09:20 UTC hourly) — every extra attempt fetched
  before the data existed, so it was not a free retry but another chance to
  publish a wrong report.
* *Two late attempts + hard gates* — GitHub still skipped the 11:20 slot, and
  the gates turned every delay into silence: 2026-08-24 no daily report and no
  weekly report, 2026-08-25 a whole report discarded over `PSH`.

So the gates now measure and report rather than withhold (`cli.report_gaps`),
and there is one attempt. **A skipped cron therefore means no report that day
and nothing will say so** — the run cannot warn about its own failure to start.
That is understood and accepted; dispatch `daily.yml` by hand when a morning
passes without a message.

### Historical: the hourly schedule, superseded 2026-08-20

Everything above is still true about GitHub's queue, and it was still the wrong
thing to optimise for. Firing early only helps if the data is there, and it is
not: the constraint is when **TEFAS** finishes, not when GitHub gets round to
us. Each extra early attempt was therefore not a free retry but another chance
to publish a wrong report, with the completeness gate as the only thing in the
way — and on 2026-08-20 that gate let one through (see §4a).

Two measurements settled it:

* A run that fetched at **10:29 Istanbul** found eighteen funds still unpriced,
  `PHE` among them. The owner, watching the platform from 09:00 that morning,
  puts the point at which most funds are settled at about **11:00**.
* Of the five crons that day, GitHub fired **one** (07:20 UTC, nine minutes
  late). The redundancy the schedule was built for did not materialise anyway.

So the fetch starts after TEFAS is done. Starting late enough that the data is
there is a simpler guarantee than starting early and testing whether it is.

**The hour and the count are set by different things.** The hour is TEFAS. The
count is GitHub, which does not merely delay scheduled runs — it skips them:

| | |
|---|---|
| 2026-08-20 | five crons scheduled, **one** fired (nine minutes late) |
| 2026-08-21 | fired **100 minutes** late |
| 2026-08-24 | **not fired at all** — and `periodic.yml` was skipped the same day, so it was the scheduler, not either file |

A single attempt was tried for exactly one working week and failed on the first
Monday. Worse, it failed **silently**: the "session incomplete" alert only fires
from a run that starts, and a run that never starts cannot say anything. The
owner noticed at 13:00 that no message had arrived.

So: `- cron: "20 8,9 * * 1-5"`, 11:20 and 12:20 Istanbul. Two attempts, **both
after TEFAS is done**, which is what keeps this from being the old hourly
schedule wearing a hat — no attempt ever fetches early. The second costs nothing
when the first succeeded: `session_is_published()` probes five funds against the
newest snapshot and exits in seconds. Both still land before the 13:30 cutoff.

`periodic.yml` gets the same treatment for the same reason: it had one chance in
its first week and was skipped, so no weekly report had ever gone out.

Do not add a third attempt at 10:20 UTC: 13:20 Istanbul plus a ~30 minute run
finishes after the order cutoff the report exists to beat.

`--only-if-new` stays. It is not a retry, it is the gate that stops a holiday or
an unfinished session being reported, and it is what raises that alert.

### The delivery window — what the schedule cannot protect

*(Widened to 07:00–20:00 on 2026-08-25; see the end of this section.)*

Everything above governs when the workflow *runs*. Nothing in it governs when
the bot *sends*, and those came apart on 2026-08-20: a `workflow_dispatch` fired
at 01:46 Istanbul to test a code change, ran the full send path because
`--only-if-new` was only passed on `schedule`, and delivered the report, the
three cards and the tweet drafts to the public channel at **02:17 in the
morning**. The cron was never involved. It also re-reported a session
(2026-08-18) that had already gone out.

Two fixes, and both are needed:

* `config.within_delivery_window()` — a report may only be delivered between
  **07:00 and 14:00 Istanbul**. Outside it, `cli.main()` flips `args.dry_run`
  before dispatching the command, which is the single point every send in the
  process sits behind: the owner's copy, the channel copy, the cards and the
  drafts. The run still fetches, still stores, still prints. `--force`
  overrides. The bounds are not arbitrary — TEFAS has not published before the
  business morning, and the message is useless after the 13:30 order cutoff, so
  a send outside them is by definition not the send the schedule intended.
* The workflow now passes `--only-if-new` on a manual dispatch too, so a
  dispatch cannot re-send a session that has already been reported. The
  `force` input lifts both gates together for a deliberate re-send.

A plain manual dispatch is therefore safe at any hour: it prints the report into
the Actions log and sends nothing. **Do not "restore" the old behaviour where a
dispatch always reports** — that convenience is exactly what published a report
at 2am.

**The bounds were wrong, though, and were widened to 07:00–20:00.** 14:00 came
from the 13:30 order cutoff, which is a statement about how *useful* a late
report is — not about whether it should exist. GitHub fires these runs 40 to 100
minutes late, and on 2026-08-24 it fired `periodic.yml` at 14:47 Istanbul: the
window turned a late weekly report into no weekly report, silently, and the
owner only found out by asking. Late beats nothing. The window's real job is
narrower than the cutoff — stop an off-schedule run posting to the channel in
the middle of the night — and 20:00 does that while surviving any plausible
delay on a 12:20 cron.

Suppression is also no longer silent: when the window blocks a send the run
raises a Telegram alert saying so. That is the whole reason the weekly failure
went unnoticed for a day.

## 7. Report format (`src/formatter.py`)

Rebuilt once already, from a first draft that packed every available figure in.
The current shape came from direct user feedback and is deliberately terse:
five rows per table, no AUM/category-rank clutter, full fund names on rankings
that need them.

### Blocks, not one long string

Report builders (`daily_report`, `weekly_report`, `monthly_report`) return
`List[str]`, not a single string. A **block** is one heading plus its table.
`split_for_telegram()` packs blocks into messages and never cuts one in half —
otherwise a heading can be stranded at the bottom of one message with its table
at the top of the next. `formatter.render(blocks)` joins them back into one
string, for tests and for `telegram.preview()`.

### No bold inside tables, and never will be

Every numeric table is a `<pre>` block, for column alignment. An early version
marked each column's best value with `<b>`. **Telegram silently discards
formatting nested inside `<pre>`**: a probe message sent through the real bot
API came back with a single `pre` entity and no `bold` entity at all — verified
against the API response, not the docs. An ASCII `*` marker was tried as a
substitute and then removed on user feedback for being clutter. There is no
way to have both alignment and per-cell emphasis in one Telegram message; do
not attempt it again without a fundamentally different table shape (e.g.
splitting emphasised values into their own line).

### Table shapes

Two shapes, chosen by whether the row needs a fund's full name:

* **Aligned `<pre>` tables** (watchlists, returns rankings within a segment):
  fixed-width columns, five rows, no fund name — used when the code alone is
  identifying enough (a watchlist the user already knows, or a numbered rank).
* **Two-line entries** (flow/investor-change rankings, KAP items): rank + code
  + value on one line, the full fund name in italics underneath. Fund names run
  to 70+ characters and cannot share a fixed-width row with anything else.

### Numbers

Turkish formatting lives in a handful of primitives at the top of the module:
`tr_number` (dot thousands, comma decimal), `money` (₺ with Mr/Mn/B suffixes),
`money_compact` (same idea without the space, for table cells), `percent` /
`pct_bare`, `signed_int`. Reuse these rather than formatting inline — the
compact and full forms exist because six-column watchlist rows need the
narrower one to fit in ~40 characters on a phone.

---

## 8. KAP

Implemented in `src/kap.py`, for the funds on `config.KAP_CODES`. Worth knowing before
touching it, because most of this was found the hard way:

* KAP's old public API is gone. `POST /tr/api/memberDisclosureQuery` still
  routes but **never responds** (hangs past 120s); `/tr/api/disclosure/*`,
  `/tr/api/todayDisclosure` and every RSS path 404.
* The disclosure list is rendered by a Next.js **server action** whose id
  changes on *every request* — replaying the POST answers `Server action not
  found`, and no 40-hex action ids appear in the JS chunks. Hence the browser.
* **The table starts empty.** The category dropdown opens on a disabled "Seçim
  Yapınız" placeholder; nothing renders until "Tüm Bildirimler" is selected and
  the filter button pressed.
* **The browser locale must be Turkish.** With an English locale KAP 307s its
  own server action to `/en/<hash>`, which 404s, and the table never fills. This
  is why the first attempts looked like a dead end.
* **One context per fund.** Reusing a single page across all seventeen funds
  wedges after the first: every later navigation times out.
* Do not wait for `networkidle` — analytics and bot-detection beacons keep the
  network busy forever. Wait for the controls instead.
* Individual disclosures at `/tr/Bildirim/<id>` *are* server-rendered and can be
  fetched with plain `requests`. The bridge from list to detail is the row
  checkbox's `id` attribute, which is the disclosure id.
* Slugs are `code-slugified-full-name`, parenthetical included. Validate a
  candidate by the **fund code**, never the name: TEFAS writes "ZURICH" with a
  Latin I where KAP writes "ZURİCH" with a dotted one. An unknown slug still
  answers 200, with a ~69 KB shell instead of the ~89 KB real page.
* Attachment links are `/tr/api/file/download/<id>`. KAP prefixes the response
  with 27 bytes of Java serialization header before `%PDF` — its own quirk, the
  same as on KAP's site, and harmless since the bot only links to the file.
* **Do not filter rows on the Kod column.** The most useful rows are often
  platform-wide announcements ("Kamuyu Aydınlatma Platformu Duyurusu", type
  DKB/PSP) that carry the PDF but leave Kod blank, naming the funds in "İlgili
  Şirketler" instead. An early version required `Kod == fund code` and silently
  dropped exactly those. The fund page only lists disclosures concerning that
  fund, so appearing on it is qualification enough — but dedupe by disclosure
  id, since one announcement shows up under several funds.
* Only disclosures **with an attachment** are reported, and the window runs from
  **noon on the previous report day to now** — the report goes out at noon, so
  this is precisely "everything since the last message".
* The filter repaint is flaky: a fund can render nothing for fifteen seconds and
  fifty rows on the next press. The button is pressed up to three times before
  an empty table is believed.

### The two audiences watch different funds

The owner's watchlists are a personal portfolio and stay private (§9), so
reporting their KAP disclosures to the channel would leak exactly what the
public report is careful not to print. The channel's KAP section therefore
covers `config.PUBLIC_KAP_CODES` — `TLY TMV DOH DFI THF KHA PHE PBR`, the funds
the "popular funds" post already names — while the owner's copy keeps reporting
on `ALL_WATCHED`.

Scraping is expensive (one browser context per fund, ~30s each), so there is
still **one pass**, over the union in `config.KAP_CODES` (17 funds; the KAP
stage grows from about 7 minutes to about 9), and `kap.limited_to()` splits the
result afterwards.

That split **narrows each item's `funds` list, it does not only filter on it**,
and the difference is a leak. A platform-wide announcement is collected from
every fund page it appears on, so one item can arrive tagged `["PHE", "GGJ"]`.
Filtering alone keeps it — `PHE` is a channel fund — and then prints the header
`PHE/GGJ`, putting a watchlist code into the public message. Narrowing prints
`PHE`. `limited_to` copies each item so the other audience's list is untouched.

`TMV` is on the channel list and is **not TEFAS-traded**, which is why it sits
in `EXTRA_FUND_CODES`: reporting a disclosure about a fund the commentary names
by hand is not ranking, comparing or researching it (§10). Nothing else untraded
belongs on that list.

## 9. Brand and the public channel

Assets live in `brand/` and are regenerated by `python brand/build_brand.py`;
edit that script rather than the PNGs. Palette: forest `#16342A`, chalk
`#E8E4D9`, amber `#E0A33C`. The mark is a question mark whose dot is the lira
sign — the channel's name is a question. The hook is a drawn path, not a set
glyph, because a typeface's "?" arrives with its own dot and the lira sign has
to occupy that slot rather than sit beneath it.

Sizes follow each platform: avatars at 1024/800/512/400 (all cropped to a
circle), X header 1500x500 with content clear of the lower-left avatar overlay,
YouTube banner 2560x1440 with everything inside the central 1546x423 that phones
do not crop.

`src/infographic.py` mirrors the same palette and mark for the daily cards.
If the brand changes, change it in both places.

Cards are landscape 1920-wide, two columns, growing in height to fit. Fund names
are printed **in full** and wrap rather than truncating — whole Turkish fund
families differ only in their last word ("... BİRİNCİ / İKİNCİ SERBEST FON"), so
an ellipsis makes them ambiguous. Four tables is what a readable landscape card
holds, so the seven TEFAS tables take two cards and the four BES tables take one.
The heading says **BES** (what people call the system) with BEFAS in the
subheading (the platform the funds trade on).

### The crypto card is a one-off, and deliberately different

`infographic.build_crypto_card()` renders a single portrait card of the eight
blockchain/fintech funds and their crypto weights, via `python -m src.cli
crypto-card`. It differs from the daily cards on purpose, and the differences
are the point: **portrait** not landscape, **no date**, **no BEFAS** in the
source line, and the disclaimer plus the Telegram link at the foot. It carries
no returns at all — only the weight — because the weights come from monthly KAP
reports, and putting a day's return beside them invites the reader to connect
two numbers that do not belong to the same period.

It is a **separate builder** and is not on the daily run: the figures only change
when new KAP reports land, so it is rendered, looked at and posted by hand.
`build_cards()` is untouched. **The daily cards keep their own format** —
landscape, dated, TEFAS · BEFAS · KAP in the source line — and this card's shape
must not spread to them.

**What the channel does not get:** the watchlists. Those are the owner's own
holdings — publishing them exposes a personal portfolio and, presented as "mine",
reads close enough to a recommendation to be worth avoiding. `daily_report`
takes `public=True` for the channel copy, which drops those blocks and appends
`config.PUBLIC_DISCLAIMER`. Tweet drafts likewise never leave the private chat.

## 10. Tweet drafts (`src/tweets.py`)

Owner-only, never posted to the channel: drafts to read, edit and post by hand.
Three rules, each of which came from a concrete failure:

* **Only what is worth reading.** An early version announced a metals fund up
  0.11% on the day. Everything now clears a threshold in
  `config.MIN_TWEETWORTHY_*` (1% return, 100M TRY flow, 500 investors).
  Money-market funds are reported by **flow, never by daily return** — their
  return is ~0.1% by construction, so quoting it is exactly the empty number the
  thresholds exist to stop.
* **Descriptive, not advisory.** The account carries a "yatırım tavsiyesi
  değildir" notice, so the copy has to match it. Context is fine ("bitcoin rose
  7% and these funds hold blockchain companies"); a recommendation is not. Every
  draft ends in `config.TWEET_SUFFIX` (`ytd`).
* **Only what the data shows.** Fund *holdings and weights* are not obtainable —
  the portfolio-breakdown endpoint is one of the retired ones (§3) — so no draft
  claims to know what a fund holds. Weights have to be read off KAP's monthly
  portfolio PDFs by hand.

Drafts come back as `{"title", "tweets": [...]}`; more than one tweet means a
thread. Threads exist because the account is not X Premium, so 280 characters is
the hard limit.

**Only funds TEFAS actually trades may be ranked or researched.** The returns
query takes `islem=1` for that. Omitting the field returns the untraded funds
too, and an earlier version did — which put funds nobody can buy on TEFAS into
leaderboards aimed at TEFAS investors. The untraded set is fetched for exactly
one purpose: pulling out the codes in `config.EXTRA_FUND_CODES` (currently just
`TMV`, 36.5bn TRY and 12,423 investors) because the commentary names them.
**Never widen this to research, comparisons or rankings.**

The fetch is not the only place this has to hold, and relying on it alone was a
mistake. Snapshots *are* the history, and they are read back long after they are
written — by the weekly and monthly reports, and as every daily flow baseline —
so a snapshot taken while the query was wide carries untraded funds into rankings
built months later. One already does: `data/snapshots/2026-08-18.csv.gz` holds
**2,532 rows, 1,165 of them untraded**, of which 105 clear both ranking
thresholds. The file was written by that 02:17 run, before `islem=1` was
restored. Among the 105 are `TI1` (218bn TRY, 238,924 investors) and `GTL`
(202bn, 347,032) — large enough to head a table, and unbuyable on TEFAS.

`metrics.eligible_universe()` therefore applies `is_tefas_traded()` as well.
That function existed already and was **never called by anything** — the rule was
only ever enforced at fetch time. With the filter in place the 2026-08-18
snapshot yields 462 eligible funds instead of 567. The polluted rows are left in
the file rather than deleted: they are extra data, not wrong data, the 1,367
traded rows beside them are intact, and §4's rule about never destroying
snapshots applies. A blank `tefas_traded` (files written before the column
existed) counts as traded, since that is all the old query returned.

**Crypto funds are matched by name, and "teknoloji" must not be one of the
patterns** — it returns 77 funds, nearly all semiconductor, defence or health.
`config.CRYPTO_NAME_PATTERNS` returns exactly the eight blockchain/fintech funds
(BCK, FJB, GBV, IJP, IVY, RBL, YZC, ZFB) and nothing else. There is no "BLO".

Crypto *weights* in `config.CRYPTO_HOLDINGS` are transcribed by hand from the
funds' monthly KAP portfolio PDFs in `blockchain/`, because every portfolio
company uses a different layout. The figure is the **share of the fund's total
value** — the `TOPLAM (FTD GÖRE)` column — so it answers "how much of this fund
is crypto".

The first pass at this was wrong, and wrong in a way worth remembering: it read
each PDF for the tickers it already expected and stopped there, so a fund's
figure was the sum of the two or three positions that happened to be found, not
its exposure. `RBL` was recorded at 24.8% (BLCN + BLOK) while it also holds two
more blockchain ETFs, BCHN and IBLC, for 38.3% in total; `GBV` was recorded at
7.0% against an actual 20.9%, because its OCR-damaged PDF splits each position
over a dozen purchase lots and only a few were picked up. Rebuilt figures:

| | RBL | IVY | GBV | BCK | ZFB | IJP | YZC | FJB |
|---|---|---|---|---|---|---|---|---|
| was | 24.8 | 20.3 | 7.0 | 17.0 | 12.3 | 5.9 | 4.5 | 2.3 |
| is | **38.3** | **28.9** | **22.3** | **18.6** | 12.3 | **11.0** | **4.7** | **4.6** |

**The inclusion rule has to be stated or the number means nothing**, so it is
written out in full in `config.CRYPTO_HOLDINGS`'s comment and summarised on the
card itself. In short: companies whose business *is* crypto (miners, crypto-native
financials, bitcoin treasuries, Block) plus blockchain-thematic ETFs at face
value; not diversified tech, not general payments or exchanges, not
broad-innovation ETFs, and not firms with merely a crypto subsidiary.

Two judgement calls inside that rule:

* **Fund-of-fund holdings are looked through, ETFs are not.** `YZC` holds `IJP`,
  and `FJB` holds `GBV`, `IJP`, `YZC` and `ZFB` — 14.5% of itself in the four.
  Counting those at face value puts `FJB` at 16.8% when only ~4.5% of it is
  crypto, because those funds are themselves mostly not crypto. Their measured
  weights are known, so they are applied. A blockchain ETF's underlying is not
  known and is thematic by construction, so it stays at face value.
* **`KEEL Infrastructure` is counted in**, by the owner's decision. It is the
  one holding on the list whose business could not be verified from the reports,
  so it is flagged in `config.CRYPTO_HOLDINGS` rather than left silent: it is
  worth 2.4 in `IVY`, 1.5 in `GBV` and 0.7 in `BCK`, and those are the three
  figures to correct if it ever turns out not to be crypto-linked.

Reading the reports is the awkward part. `RBL`, `IVY`, `BCK`, `ZFB` and `FJB`
print a plain FTD column. `GBV`'s PDF is OCR-damaged — digits come out as
letters, every `5` as `S` — and needs per-lot summing. `IJP` splits the numeric
columns and the security names into separate text blocks that have to be paired
by position; the currency column confirms the pairing, and every weight was
cross-checked against value ÷ fund total. Note that all these PDFs carry KAP's
27-byte Java serialization header before `%PDF` (§8), which `pypdf` recovers
from with a warning.

Refresh these when new monthly reports land; there is nothing to poll, since
TEFAS's portfolio endpoint is retired.

`src/market.py` supplies the only outside data: bitcoin's 24-hour move from
CoinGecko's free tier. Turkish inflation and the lira rate are deliberately
absent — no free source was found trustworthy enough to publish from unattended,
and a wrong benchmark in a posted tweet is worse than a missing one. Where a
benchmark is needed, TEFAS's own funds stand in (a gold fund for gold, a
money-market fund for deposits), which is honest because that is what a reader
could actually have bought.

## 11. Open items

### Backfilling flow history

Decided to accept "start collecting from today" rather than delay launch. If a
source for historical AUM / investor counts turns up (SPK or Takasbank
bulletins, an archive site, a third-party dataset), it could be injected into
`data/snapshots/` retroactively using the same CSV schema.

### KAP window boundary — a known judgment call

The window is exactly noon-to-noon (`kap.REPORT_HOUR = 12`), matching when the
report is sent. This means a disclosure published *before* noon on the previous
calendar day is never reported — it belonged to the previous day's window. The
user flagged one such case (PRY, 08:58 the day before) as something they
expected to see; it was excluded on purpose, following the noon rule they had
stated explicitly. If this comes up again, the fix is one line
(`REPORT_HOUR = 0`), but note the trade-off: a wider window means disclosures
published between midnight and noon appear in two consecutive reports.

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

## 12. Operating it

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
