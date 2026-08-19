"""Smoke tests for the pure-logic layers. No network access.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, formatter, infographic, kap, metrics, storage, tweets  # noqa: E402


def make_record(code, **overrides):
    record = {
        "code": code,
        "name": "{} FONU".format(code),
        "fund_type": "YAT",
        "umbrella": "Hisse Senedi Şemsiye Fonu",
        "category": "Hisse Senedi Fonu",
        "risk": "6",
        "price": 2.0,
        "daily_return": 1.0,
        "shares": 1_000_000_000,
        "aum": 2_000_000_000.0,
        "investors": 20_000,  # comfortably above config.MIN_INVESTORS
        "market_share": 1.5,
        "cat_rank": 3,
        "cat_count": 197,
        "ret_1m": 5.0,
        "ret_3m": 10.0,
        "ret_6m": 20.0,
        "ret_1y": 50.0,
        "ret_ytd": 30.0,
        "ret_3y": None,
        "ret_5y": None,
    }
    record.update(overrides)
    return record


class TestNumberFormatting(unittest.TestCase):
    def test_turkish_separators(self):
        self.assertEqual(formatter.tr_number(1234567.891, 2), "1.234.567,89")
        self.assertEqual(formatter.tr_number(0.5, 2), "0,50")

    def test_money_scales(self):
        self.assertEqual(formatter.money(40_860_361_191.65), "40,9 Mr₺")
        self.assertEqual(formatter.money(118_400_000), "118,4 Mn₺")
        self.assertEqual(formatter.money(1_500), "1,5 B₺")
        self.assertEqual(formatter.money(None), "—")

    def test_money_sign_uses_typographic_minus(self):
        self.assertTrue(formatter.money(-1_000_000, signed=True).startswith("−"))
        self.assertTrue(formatter.money(1_000_000, signed=True).startswith("+"))

    def test_percent(self):
        self.assertEqual(formatter.percent(0.0728), "+%0,07")
        self.assertEqual(formatter.percent(-2.5), "−%2,50")
        self.assertEqual(formatter.percent(None), "—")

    def test_short_category_strips_suffix(self):
        self.assertEqual(
            formatter.short_category({"category": "Para Piyasası Fonu"}, 40),
            "Para Piyasası",
        )


class TestFlowMetrics(unittest.TestCase):
    def test_flow_isolates_money_from_performance(self):
        # Price rose 10% and 100m new units were created. AUM grows by both, but
        # only the new units are actual money coming in.
        previous = {"AAA": make_record("AAA", price=2.0, shares=1_000_000_000, aum=2e9)}
        current = [make_record("AAA", price=2.2, shares=1_100_000_000, aum=2.42e9,
                               daily_return=10.0)]

        enriched = metrics.attach_deltas(current, previous)[0]

        self.assertAlmostEqual(enriched["flow"], 100_000_000 * 2.2)
        self.assertAlmostEqual(enriched["aum_change"], 0.42e9)
        # Flow is well below the AUM change, which also contains the 10% gain.
        self.assertLess(enriched["flow"], enriched["aum_change"])

    def test_pure_performance_move_produces_zero_flow(self):
        previous = {"AAA": make_record("AAA", price=2.0, shares=1_000_000_000, aum=2e9)}
        current = [make_record("AAA", price=3.0, shares=1_000_000_000, aum=3e9,
                               daily_return=50.0)]

        enriched = metrics.attach_deltas(current, previous)[0]

        self.assertEqual(enriched["flow"], 0)
        self.assertAlmostEqual(enriched["aum_change"], 1e9)

    def test_missing_baseline_gives_none_not_zero(self):
        enriched = metrics.attach_deltas([make_record("NEW")], {})[0]
        for key in ("flow", "aum_change", "investor_change", "flow_pct"):
            self.assertIsNone(enriched[key], key)

    def test_share_split_is_excluded_from_flow_rankings(self):
        # A 10:1 split multiplies units by ten and divides the price by ten.
        # No money moved, but a naive flow calculation reports a huge inflow.
        previous = {"SPL": make_record("SPL", price=20.0, shares=100_000_000, aum=2e9)}
        current = [make_record("SPL", price=2.0, shares=1_000_000_000, aum=2e9)]

        enriched = metrics.attach_deltas(current, previous)
        self.assertGreater(enriched[0]["flow"], 1e9)      # the artifact exists
        self.assertTrue(enriched[0]["flow_artifact"])     # ...and is detected

        # ...but the guard keeps it out of the leaderboard.
        self.assertEqual(metrics.top_by(enriched, "flow"), [])

    def test_genuine_flow_survives_the_guard(self):
        previous = {"AAA": make_record("AAA", price=2.0, shares=1_000_000_000, aum=2e9)}
        current = [make_record("AAA", price=2.0, shares=1_050_000_000, aum=2.1e9,
                               daily_return=0.0)]

        enriched = metrics.attach_deltas(current, previous)
        self.assertEqual([r["code"] for r in metrics.top_by(enriched, "flow")], ["AAA"])


class TestFilters(unittest.TestCase):
    def test_size_filter(self):
        small = make_record("SML", aum=50_000_000.0)
        big = make_record("BIG", aum=500_000_000.0)
        self.assertEqual(
            [r["code"] for r in metrics.eligible_universe([small, big])], ["BIG"]
        )

    def test_absurd_daily_return_is_dropped(self):
        sane = make_record("OK", daily_return=4.0)
        absurd = make_record("BAD", daily_return=6000.0)
        ranked = metrics.top_by([sane, absurd], "daily_return", guard="daily")
        self.assertEqual([r["code"] for r in ranked], ["OK"])

    def test_money_market_split(self):
        equity = make_record("EQT")
        mm = make_record("MMF", category="Para Piyasası Fonu", umbrella="Para Piyasası Şemsiye Fonu")
        rest, money_market = metrics.split_money_market([equity, mm])
        self.assertEqual([r["code"] for r in rest], ["EQT"])
        self.assertEqual([r["code"] for r in money_market], ["MMF"])

    def test_thinly_held_fund_is_excluded(self):
        # A private vehicle: half a billion lira, 22 investors. Real example.
        private = make_record("PPF", aum=549_797_497.0, investors=22)
        retail = make_record("RTL", aum=549_797_497.0, investors=12_000)
        self.assertEqual(
            [r["code"] for r in metrics.eligible_universe([private, retail])], ["RTL"]
        )


class TestSegmentation(unittest.TestCase):
    def test_turkish_case_folding(self):
        # "ALTIN" uses a dotless-I capital; "Altın" a dotless-i lowercase.
        self.assertEqual(metrics.fold("ALTIN"), metrics.fold("Altın"))
        self.assertEqual(metrics.fold("KIYMETLİ"), "kiymetli")

    def test_gold_and_silver_funds_are_metals(self):
        cases = [
            ("QNB PORTFÖY ALTIN FONU", "Altın Fonu"),
            ("AK PORTFÖY GÜMÜŞ FON SEPETI FONU", "Fon Sepeti Fonu"),
            ("GARANTİ EMEKLİLİK GÜMÜŞ FON SEPETİ EMEKLİLİK YATIRIM FONU", "Fon Sepeti Fonu"),
            ("TEB PORTFÖY KIYMETLİ MADENLER FON SEPETİ FONU", "Fon Sepeti Fonu"),
            ("OSMANLI PORTFÖY ALTIN FON SEPETİ FONU", "Fon Sepeti Fonu"),
        ]
        for name, category in cases:
            record = make_record("X", name=name, category=category, umbrella=category)
            self.assertTrue(metrics.is_precious_metal(record), name)

    def test_altinci_is_not_gold(self):
        # "Altıncı" means "sixth". A substring search would wrongly match it.
        for name in (
            "AK PORTFÖY ALTINCI SERBEST(DÖVİZ) FON",
            "İSTANBUL PORTFÖY ONALTINCI SERBEST FON",
            "ZİRAAT PORTFÖY ALTINCI SERBEST (TL) FON",
        ):
            record = make_record("X", name=name, category="Serbest Fon",
                                 umbrella="Serbest Şemsiye Fonu")
            self.assertFalse(metrics.is_precious_metal(record), name)

    def test_segments_are_disjoint_and_complete(self):
        records = [
            make_record("EQT"),
            make_record("MMF", category="Para Piyasası Fonu"),
            make_record("GLD", name="QNB PORTFÖY ALTIN FONU", category="Altın Fonu"),
        ]
        segments = metrics.split_segments(records)
        self.assertEqual([r["code"] for r in segments["general"]], ["EQT"])
        self.assertEqual([r["code"] for r in segments["money_market"]], ["MMF"])
        self.assertEqual([r["code"] for r in segments["metals"]], ["GLD"])
        self.assertEqual(sum(len(v) for v in segments.values()), len(records))

    def test_platform_split(self):
        tefas, befas = metrics.split_by_platform(
            [make_record("YAT1"), make_record("EMK1", fund_type="EMK")]
        )
        self.assertEqual([r["code"] for r in tefas], ["YAT1"])
        self.assertEqual([r["code"] for r in befas], ["EMK1"])


class TestDateLogic(unittest.TestCase):
    def test_monday_run_reports_friday(self):
        monday = datetime(2026, 8, 17, 12, 0, tzinfo=storage.ISTANBUL)
        self.assertEqual(storage.data_date_for(monday), date(2026, 8, 14))

    def test_midweek_run_reports_previous_day(self):
        wednesday = datetime(2026, 8, 19, 12, 0, tzinfo=storage.ISTANBUL)
        self.assertEqual(storage.data_date_for(wednesday), date(2026, 8, 18))

    def test_the_clock_is_read_in_istanbul_not_utc(self):
        # 12:03 Istanbul on Tuesday is 09:03 UTC the same day -- both after the
        # publication window, so both resolve to Monday. But 00:30 Istanbul on
        # Tuesday is 21:30 UTC on *Monday*, and reading that naive UTC stamp as
        # a local time lands on the wrong calendar day entirely.
        self.assertEqual(
            storage.data_date_for(datetime(2026, 8, 18, 12, 3, tzinfo=storage.ISTANBUL)),
            date(2026, 8, 17),
        )
        # Monday 00:30 in Istanbul is Sunday 21:30 UTC. Read as Istanbul time it
        # is a pre-publication Monday, so the newest session is Thursday; read
        # off a UTC clock it looks like a Sunday evening, giving Friday.
        istanbul_small_hours = datetime(2026, 8, 17, 0, 30, tzinfo=storage.ISTANBUL)
        utc_same_instant = datetime(2026, 8, 16, 21, 30)
        self.assertEqual(storage.data_date_for(istanbul_small_hours), date(2026, 8, 13))
        self.assertEqual(storage.data_date_for(utc_same_instant), date(2026, 8, 14))

    def test_run_before_publication_window_sees_an_older_session(self):
        # Measured against the live API: at 03:09 on Tuesday 2026-08-18 TEFAS
        # still served Friday's close, not Monday's.
        early = datetime(2026, 8, 18, 3, 9, tzinfo=storage.ISTANBUL)
        midday = datetime(2026, 8, 18, 12, 3, tzinfo=storage.ISTANBUL)

        self.assertEqual(storage.data_date_for(early), date(2026, 8, 14))
        self.assertEqual(storage.data_date_for(midday), date(2026, 8, 17))

    def test_consecutive_sessions_are_recognised(self):
        previous = {
            "F{:03d}".format(i): make_record("F{:03d}".format(i), price=2.0)
            for i in range(60)
        }
        # Every fund up 1.5%: prices and reported returns agree.
        current = [
            make_record(code, price=2.03, daily_return=1.5) for code in previous
        ]
        self.assertTrue(storage.follows_consecutively(current, previous))

    def test_a_skipped_session_is_detected(self):
        previous = {
            "F{:03d}".format(i): make_record("F{:03d}".format(i), price=2.0)
            for i in range(60)
        }
        # Prices moved 3% but each fund reports a 1.5% day: a session is missing.
        current = [
            make_record(code, price=2.06, daily_return=1.5) for code in previous
        ]
        self.assertFalse(storage.follows_consecutively(current, previous))

    def test_too_little_overlap_is_inconclusive(self):
        previous = {"AAA": make_record("AAA")}
        self.assertIsNone(
            storage.follows_consecutively([make_record("AAA")], previous)
        )

    def test_now_istanbul_is_three_hours_ahead_of_utc(self):
        now = storage.now_istanbul()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), timedelta(hours=3))


class TestReportRendering(unittest.TestCase):
    def _records(self):
        records = [
            make_record(code, daily_return=value, aum=1e9 + index * 1e8)
            for index, (code, value) in enumerate(
                [("PHE", 3.1), ("TLY", 2.2), ("KHA", -1.4), ("THF", 0.3)]
            )
        ]
        records += [
            make_record(
                code,
                category="Para Piyasası Fonu",
                umbrella="Para Piyasası Şemsiye Fonu",
                daily_return=0.38,
            )
            for code in ("TP2", "PRY", "PNU")
        ]
        records += [
            make_record("B{:03d}".format(i), fund_type="EMK", daily_return=i * 0.1)
            for i in range(20)
        ]
        records += [
            make_record(code, fund_type="EMK", daily_return=0.4)
            for code in config.BEFAS_WATCHLIST
        ]
        records += [
            make_record(
                "G{:03d}".format(i),
                name="PORTFÖY ALTIN FONU {}".format(i),
                category="Altın Fonu",
                daily_return=i * 0.2,
            )
            for i in range(12)
        ]
        records += [make_record("F{:03d}".format(i), daily_return=i * 0.1) for i in range(40)]
        return metrics.attach_deltas(records, {})

    def test_daily_report_renders_without_baseline(self):
        text = formatter.render(formatter.daily_report(
            records=self._records(),
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
            kap_note="KAP kapalı.",
        ))
        self.assertIn("TAKİP LİSTEM", text)
        self.assertIn("PARA PİYASASI", text)
        self.assertIn("KIYMETLİ MADENLER", text)
        self.assertIn("TEFAS · YATIRIM FONLARI", text)
        self.assertIn("BEFAS · EMEKLİLİK FONLARI", text)
        self.assertIn("ilk kayıt", text)      # day-one explanation
        self.assertIn("KAP kapalı.", text)
        self.assertEqual(text.count("<pre>"), text.count("</pre>"))

    def test_chunks_respect_the_telegram_limit_and_never_split_a_table(self):
        # A full report with every flow section populated runs past the limit,
        # so this exercises the packing rather than the short-circuit.
        # Back out yesterday's price from the reported return so the series is
        # continuous and the split guard does not fire on every fund.
        previous = {
            r["code"]: make_record(
                r["code"],
                shares=990_000_000,
                price=r["price"] / (1 + r["daily_return"] / 100.0),
            )
            for r in self._records()
        }
        records = metrics.attach_deltas(self._records(), previous)
        blocks = formatter.daily_report(
            records=records,
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=date(2026, 8, 14),
        )
        # A tighter limit forces several splits regardless of how long the
        # synthetic fund names happen to make the report.
        limit = 1500
        chunks = formatter.split_for_telegram(blocks, limit=limit)

        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), limit)
            self.assertEqual(chunk.count("<pre>"), chunk.count("</pre>"))
        # Nothing is silently dropped on the way out.
        whole = formatter.render(blocks)
        self.assertEqual(
            sum(c.count("<pre>") for c in chunks), whole.count("<pre>")
        )

    def test_split_never_separates_a_heading_from_its_table(self):
        # A block is a heading plus its table. The splitter must keep them
        # together, or a message ends on a bare heading.
        blocks = [
            "<b>BASLIK {}</b>\n<pre>satir {}</pre>".format(i, i) for i in range(12)
        ]
        chunks = formatter.split_for_telegram(blocks, limit=200)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.count("<b>"), chunk.count("<pre>"))
            self.assertEqual(chunk.count("<pre>"), chunk.count("</pre>"))
            self.assertFalse(chunk.rstrip().endswith("</b>"))

    def test_watchlist_codes_all_appear(self):
        text = formatter.render(formatter.daily_report(
            records=self._records(),
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
        ))
        for code in config.ALL_WATCHED:
            self.assertIn(code, text)

    def test_metals_do_not_leak_into_the_headline_table(self):
        text = formatter.render(formatter.daily_report(
            records=self._records(),
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
        ))
        headline = text.split("🥇")[0].split("🏦 PARA PİYASASI")[0]
        self.assertNotIn("G011", headline)  # best-performing gold fund


if __name__ == "__main__":
    unittest.main()


class TestKapWindow(unittest.TestCase):
    def test_window_runs_from_noon_on_the_previous_report_day(self):
        # The report goes out at noon, so the window starts where the last one
        # ended: no gap, no repeats.
        tuesday = date(2026, 8, 18)
        self.assertEqual(kap.window_start(tuesday), datetime(2026, 8, 17, 12, 0))

    def test_monday_reaches_back_to_friday_noon(self):
        # Nothing filed on Friday afternoon or over the weekend may be dropped.
        monday = date(2026, 8, 17)
        self.assertEqual(kap.window_start(monday), datetime(2026, 8, 14, 12, 0))

    def test_row_timestamps_decide_the_window(self):
        today = date(2026, 8, 18)
        start = kap.window_start(today)
        # 08:58 yesterday belongs to the previous report; 17:53 yesterday does not.
        self.assertLess(kap.parse_row_datetime("Dün 08:58", today), start)
        self.assertGreater(kap.parse_row_datetime("Dün 17:53", today), start)
        self.assertGreater(kap.parse_row_datetime("Bugün 08:55", today), start)

    def test_relative_dates(self):
        today = date(2026, 8, 18)
        self.assertEqual(kap.parse_row_date("Bugün 08:55", today), today)
        self.assertEqual(kap.parse_row_date("Dün 17:53", today), date(2026, 8, 17))
        self.assertEqual(
            kap.parse_row_date("14.08.2026 16:44", today), date(2026, 8, 14)
        )
        self.assertIsNone(kap.parse_row_date("", today))

    def test_slug_includes_the_parenthetical_form_first(self):
        slugs = kap._candidate_slugs(
            "PHE", "PUSULA PORTFÖY HİSSE SENEDİ FONU (HİSSE SENEDİ YOĞUN FON)"
        )
        self.assertEqual(
            slugs[0], "phe-pusula-portfoy-hisse-senedi-fonu-hisse-senedi-yogun-fon"
        )
        self.assertIn("phe-pusula-portfoy-hisse-senedi-fonu", slugs)

    def test_slug_folds_both_turkish_i_forms(self):
        # TEFAS writes ZURICH with a Latin I, KAP writes ZURİCH with a dotted one.
        self.assertEqual(kap._slugify("ZURICH"), kap._slugify("ZURİCH"))

    def test_platform_announcements_are_not_filtered_out_by_code(self):
        # The rows worth reporting are often platform-wide announcements that
        # carry the PDF but leave the Kod column blank, naming the funds in
        # "İlgili Şirketler" instead. Filtering on Kod dropped exactly those.
        item = {"code": "TLY", "row_code": "", "funds": ["TLY"],
                "published": datetime(2026, 8, 18, 8, 55),
                "date": date(2026, 8, 18), "time": "08:55",
                "subject": "Kamuyu Aydınlatma Platformu Duyurusu",
                "summary": "Özel Durumlar Tebliği'nin 12-(4). maddesi",
                "attachments": ["https://www.kap.org.tr/tr/api/file/download/abc"],
                "url": "https://www.kap.org.tr/tr/Bildirim/1"}
        block = formatter._kap_block([item])[0]
        self.assertIn("TLY", block)
        self.assertIn("file/download/abc", block)

    def test_one_announcement_shared_by_several_funds_is_labelled_once(self):
        item = {"funds": ["TLY", "PRY"], "code": "TLY",
                "published": datetime(2026, 8, 18, 8, 55),
                "date": date(2026, 8, 18), "time": "08:55",
                "subject": "Duyuru", "summary": "",
                "attachments": ["https://x/y"], "url": "https://z"}
        block = formatter._kap_block([item])[0]
        self.assertIn("TLY/PRY", block)

    def test_shell_page_is_not_mistaken_for_a_fund_page(self):
        # An unknown slug still answers 200 with a small shell.
        self.assertFalse(kap._page_is_for("x" * 69_000, "TLY"))
        self.assertTrue(kap._page_is_for("TLY" + "x" * 80_000, "TLY"))


class TestKapRendering(unittest.TestCase):
    def test_disclosure_with_attachment_renders_summary_and_link(self):
        items = [{
            "code": "TLY", "date": date(2026, 8, 17), "time": "17:53",
            "subject": "Borsa Dışı Repo - Ters Repo Sözleşmesi",
            "summary": "Borsa Dışı Ters Repo Sözleşmesi",
            "attachments": ["https://www.kap.org.tr/tr/api/file/download/abc123"],
            "url": "https://www.kap.org.tr/tr/Bildirim/1651233",
        }]
        block = formatter._kap_block(items)[0]
        self.assertIn("TLY", block)
        self.assertIn("17 Ağustos 2026 17:53", block)
        self.assertIn("Ters Repo", block)
        self.assertIn("file/download/abc123", block)
        self.assertIn("Bildirim/1651233", block)

    def test_no_disclosures_says_so(self):
        block = formatter._kap_block([])[0]
        self.assertIn("yeni bildirim yok", block)


class TestPublicReport(unittest.TestCase):
    def _records(self):
        records = [
            make_record(code, daily_return=v)
            for code, v in [("PHE", 3.1), ("TLY", 2.2), ("KHA", -1.4), ("THF", 0.3)]
        ]
        records += [
            make_record(c, category="Para Piyasası Fonu", daily_return=0.38)
            for c in ("TP2", "PRY", "PNU")
        ]
        records += [
            make_record(c, fund_type="EMK", daily_return=0.4)
            for c in config.BEFAS_WATCHLIST
        ]
        records += [make_record("F{:03d}".format(i), daily_return=i * 0.1) for i in range(30)]
        return metrics.attach_deltas(records, {})

    def test_public_report_omits_the_owners_watchlists(self):
        # The watchlists are a personal portfolio; a public channel must not
        # carry them.
        text = formatter.render(
            formatter.daily_report(
                records=self._records(),
                data_day=date(2026, 8, 17),
                run_day=date(2026, 8, 18),
                baseline_day=None,
                public=True,
            )
        )
        self.assertNotIn("TAKİP LİSTEM", text)
        self.assertNotIn("TAKİP — BEFAS", text)
        # ...but the rankings it exists for are still there.
        self.assertIn("EN İYİ GETİRİ", text)
        self.assertIn("EN ÇOK PARA GİRİŞİ", text)

    def test_public_report_carries_the_disclaimer(self):
        text = formatter.render(
            formatter.daily_report(
                records=self._records(),
                data_day=date(2026, 8, 17),
                run_day=date(2026, 8, 18),
                baseline_day=None,
                public=True,
            )
        )
        self.assertIn("Yatırım tavsiyesi değildir", text)

    def test_private_report_still_has_the_watchlists(self):
        text = formatter.render(
            formatter.daily_report(
                records=self._records(),
                data_day=date(2026, 8, 17),
                run_day=date(2026, 8, 18),
                baseline_day=None,
            )
        )
        self.assertIn("TAKİP LİSTEM", text)
        self.assertNotIn("Yatırım tavsiyesi değildir", text)


class TestTurkishTitleCase(unittest.TestCase):
    def test_dotted_capital_survives(self):
        # str.title() turns "HİSSE" into "Hi̇sse" -- an i followed by a
        # combining dot -- because Python lowercases İ to i + U+0307.
        self.assertEqual(
            tweets._tr_title("TERA PORTFÖY HİSSE SENEDİ FONU"),
            "Tera Portföy Hisse Senedi Fonu",
        )
        self.assertNotIn("\u0307", tweets._tr_title("HİSSE"))

    def test_dotless_i_becomes_capital_i(self):
        self.assertEqual(tweets._tr_title("ALTIN KATILIM"), "Altın Katılım")


class TestTweetDrafts(unittest.TestCase):
    def _records(self):
        rows = [
            make_record("AAA", daily_return=2.5, ret_ytd=88.0),
            make_record("BBB", daily_return=0.4),
            make_record("CCC", daily_return=-0.6),
        ]
        previous = {
            "AAA": make_record("AAA", shares=900_000_000, investors=15_000),
            "BBB": make_record("BBB", shares=1_100_000_000, investors=25_000),
            "CCC": make_record("CCC", shares=1_000_000_000, investors=20_000),
        }
        for r in rows:
            r["daily_return"] = 0.0  # keep the price identity consistent
        return metrics.attach_deltas(rows, previous)

    def test_drafts_fit_a_tweet(self):
        drafts = tweets.build_drafts(self._records(), date(2026, 8, 18), date(2026, 8, 19))
        self.assertTrue(drafts)
        for draft in drafts:
            self.assertLessEqual(len(draft), tweets.LIMIT)

    def test_yesterday_is_named_relatively(self):
        self.assertEqual(tweets._day_label(date(2026, 8, 18), date(2026, 8, 19)), "Dün")
        self.assertIn("Ağustos", tweets._day_label(date(2026, 8, 14), date(2026, 8, 19)))

    def test_no_drafts_still_produces_a_message(self):
        blocks = tweets.as_message([])
        self.assertTrue(blocks)
        self.assertIn("TWEET TASLAKLARI", blocks[0])


class TestInfographicNames(unittest.TestCase):
    def test_names_are_printed_in_full(self):
        # Truncating is not safe here: whole fund families differ only in their
        # last word, so "... BİRİNCİ" and "... İKİNCİ SERBEST FON" collapse to
        # the same string once shortened.
        full = "TERA PORTFÖY BİRİNCİ SERBEST FON"
        self.assertEqual(infographic.fund_name({"name": full}), full)

    def test_long_names_keep_every_word(self):
        long_name = "TÜRKİYE HAYAT VE EMEKLİLİK A.Ş. OKS KATILIM STANDART EMEKLİLİK YATIRIM FONU"
        out = infographic.fund_name({"name": long_name})
        self.assertEqual(out, long_name)
        self.assertNotIn("…", out)

    def test_whitespace_is_tidied(self):
        self.assertEqual(infographic.fund_name({"name": "  AK   PORTFÖY  "}), "AK PORTFÖY")


class TestInfographicTables(unittest.TestCase):
    def test_table_counts_match_the_brief(self):
        self.assertEqual(len(infographic.TEFAS_TABLES), 7)
        self.assertEqual(len(infographic.BES_TABLES), 4)

    def test_tables_are_split_into_readable_cards(self):
        # Four tables per landscape card, so TEFAS takes two and BES one.
        import math
        self.assertEqual(
            math.ceil(len(infographic.TEFAS_TABLES) / infographic.TABLES_PER_CARD), 2
        )
        self.assertEqual(
            math.ceil(len(infographic.BES_TABLES) / infographic.TABLES_PER_CARD), 1
        )

    def test_cards_are_landscape(self):
        self.assertGreater(infographic.WIDTH, infographic.MIN_HEIGHT)


class TestPublicationCompleteness(unittest.TestCase):
    """TEFAS releases funds across the morning, so "something moved" is not the
    same as "the session is out"."""

    def _pair(self, moved: int, total: int = 400):
        previous = {
            "F{:04d}".format(i): make_record("F{:04d}".format(i), price=2.0)
            for i in range(total)
        }
        current = [
            make_record(code, price=2.05 if i < moved else 2.0)
            for i, code in enumerate(previous)
        ]
        return current, previous

    def test_a_finished_session_passes(self):
        current, previous = self._pair(moved=399)
        self.assertGreaterEqual(
            storage.published_fraction(current, previous),
            storage.PUBLISHED_THRESHOLD,
        )

    def test_a_half_published_session_is_caught(self):
        # The failure this guards against: an early run finds the first funds
        # updated and reports them against yesterday's prices for the rest.
        current, previous = self._pair(moved=200)
        self.assertLess(
            storage.published_fraction(current, previous),
            storage.PUBLISHED_THRESHOLD,
        )

    def test_too_little_overlap_is_inconclusive(self):
        current, previous = self._pair(moved=5, total=20)
        self.assertIsNone(storage.published_fraction(current, previous))


class TestChannelReport(unittest.TestCase):
    def test_disclaimer_does_not_claim_automation(self):
        self.assertNotIn("otomatik", config.PUBLIC_DISCLAIMER)
        self.assertIn("Yatırım tavsiyesi değildir", config.PUBLIC_DISCLAIMER)

    def test_platform_heading_travels_with_its_first_table(self):
        records = metrics.attach_deltas(
            [make_record("F{:03d}".format(i), daily_return=i * 0.1) for i in range(20)],
            {},
        )
        blocks = formatter.daily_report(
            records=records,
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
            public=True,
        )
        banners = [b for b in blocks if "TEFAS · YATIRIM FONLARI" in b]
        self.assertEqual(len(banners), 1)
        # The banner must not be a block on its own, or it can be packed as the
        # last thing in a message with its table in the next one.
        self.assertIn("EN İYİ GETİRİ", banners[0])
