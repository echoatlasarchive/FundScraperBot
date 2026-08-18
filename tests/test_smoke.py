"""Smoke tests for the pure-logic layers. No network access.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, formatter, metrics, storage  # noqa: E402


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
        "investors": 10_000,  # comfortably above config.MIN_INVESTORS
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

    def test_late_evening_run_stays_on_the_same_trading_day(self):
        # 02:15 Istanbul on Tuesday is still 23:15 UTC on Monday. Deriving the
        # date from a UTC clock would report Friday instead of Monday and
        # silently corrupt the flow baseline.
        istanbul = datetime(2026, 8, 18, 2, 15, tzinfo=storage.ISTANBUL)
        utc_equivalent = datetime(2026, 8, 17, 23, 15)

        self.assertEqual(storage.data_date_for(istanbul), date(2026, 8, 17))
        self.assertNotEqual(
            storage.data_date_for(istanbul), storage.data_date_for(utc_equivalent)
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
        text = formatter.daily_report(
            records=self._records(),
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
            kap_note="KAP kapalı.",
        )
        self.assertIn("TAKİP LİSTEM", text)
        self.assertIn("Para Piyasası", text)
        self.assertIn("Kıymetli Madenler", text)
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
        text = formatter.daily_report(
            records=records,
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=date(2026, 8, 14),
        )
        # A tighter limit forces several splits regardless of how long the
        # synthetic fund names happen to make the report.
        limit = 1500
        chunks = formatter.split_for_telegram(text, limit=limit)

        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), limit)
            self.assertEqual(chunk.count("<pre>"), chunk.count("</pre>"))
        # Nothing is silently dropped on the way out.
        self.assertEqual(
            sum(c.count("<pre>") for c in chunks), text.count("<pre>")
        )

    def test_split_keeps_a_table_intact(self):
        table = "<pre>" + "\n".join("row {}".format(i) for i in range(10)) + "</pre>"
        text = "\n".join(["header", table, "x" * 4000, "footer"])
        for chunk in formatter.split_for_telegram(text):
            self.assertLessEqual(len(chunk), formatter.TELEGRAM_LIMIT)
            if "<pre>" in chunk:
                self.assertIn("row 9", chunk)
                self.assertIn("</pre>", chunk)

    def test_watchlist_codes_all_appear(self):
        text = formatter.daily_report(
            records=self._records(),
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
        )
        for code in config.ALL_WATCHED:
            self.assertIn(code, text)

    def test_metals_do_not_leak_into_the_headline_table(self):
        text = formatter.daily_report(
            records=self._records(),
            data_day=date(2026, 8, 17),
            run_day=date(2026, 8, 18),
            baseline_day=None,
        )
        headline = text.split("🥇")[0].split("🏦 Para Piyasası")[0]
        self.assertNotIn("G011", headline)  # best-performing gold fund


if __name__ == "__main__":
    unittest.main()
