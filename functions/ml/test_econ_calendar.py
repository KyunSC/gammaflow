"""Offline checks for econ_calendar: seed sanity, the claims rule, queries, and generated files."""
import unittest
from collections import Counter
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import econ_calendar as ec

CPI_SEP_2026 = datetime(2026, 9, 11, 8, 30, tzinfo=ec.ET)


class Seeds(unittest.TestCase):
    def setUp(self):
        self.evs = ec.build_events()

    def test_every_event_is_on_a_business_day(self):
        hol = ec._observed_set(range(2021, 2029))
        bad = [(e.day, e.event) for e in self.evs if e.day.weekday() > 4 or e.day in hol]
        self.assertEqual(bad, [])

    def test_no_event_is_listed_twice(self):
        dupes = [k for k, n in Counter((e.day, e.event) for e in self.evs).items() if n > 1]
        self.assertEqual(dupes, [])

    def test_monthly_releases_print_about_once_a_month(self):
        for ev in ("cpi", "nfp", "ppi", "retail_sales", "jolts", "ism_mfg"):
            days = [e.day for e in self.evs if e.event == ev and e.day <= date(2026, 8, 31)]
            months = (2026 - 2022) * 12 + 8
            # the 2025 shutdown cancelled some releases and doubled up others
            self.assertTrue(months - 3 <= len(days) <= months + 2, (ev, len(days)))

    def test_claims_off_thursday_dates_match_dol(self):
        # every non-Thursday date in ALFRED rid=180 from 2022 to 2026-10-08
        moved = [e.day for e in self.evs if e.event == "claims" and e.day.weekday() != 3]
        self.assertEqual([d.isoformat() for d in moved], [
            "2022-11-23", "2023-11-22", "2024-07-03", "2024-11-27", "2025-01-08", "2025-06-18",
            "2025-11-26", "2025-12-24", "2025-12-31"])
        oct25 = [e.day for e in self.evs if e.event == "claims" and date(2025, 10, 1) <= e.day <= date(2025, 11, 19)]
        self.assertEqual(oct25, [])

    def test_fomc_press_conference_follows_each_decision(self):
        dec = {e.day for e in self.evs if e.event == "fomc"}
        pc = {e.day for e in self.evs if e.event == "fomc_presser"}
        self.assertEqual(dec, pc)

    def test_shutdown_time_overrides(self):
        pce = {e.day.isoformat(): e.time_et for e in self.evs if e.event == "pce"}
        self.assertEqual(pce["2025-12-05"], "10:00")
        self.assertEqual(pce["2025-12-23"], "08:30")

    def test_nothing_past_coverage(self):
        for e in self.evs:
            self.assertLessEqual(e.day, date.fromisoformat(ec.THROUGH[e.event]), e)


class Queries(unittest.TestCase):
    def bars(self, start, n, minutes=5):
        return pd.date_range(start, periods=n, freq=f"{minutes}min")

    def test_window_marks_overlapping_bars(self):
        t = self.bars(CPI_SEP_2026 - timedelta(hours=1), 25)
        on = ec.news_window(t, 300, "high", before_min=5, after_min=15)
        mins = [(ts - CPI_SEP_2026).total_seconds() / 60 for ts, f in zip(t, on) if f]
        self.assertEqual(mins, [-5, 0, 5, 10])
        in_bar = ec.news_window(t, 300, "high", before_min=0, after_min=0)
        self.assertEqual([(ts - CPI_SEP_2026).total_seconds() / 60 for ts, f in zip(t, in_bar) if f], [0])

    def test_minutes_to_next_and_since(self):
        at = self.bars(CPI_SEP_2026 - timedelta(minutes=30), 2, minutes=60)
        self.assertEqual(ec.minutes_to_next(at, "high")[0], 30)
        self.assertEqual(ec.minutes_since(at, "high")[1], 30)

    def test_epoch_inputs_work(self):
        ts = int(CPI_SEP_2026.timestamp())
        self.assertTrue(ec.news_window(np.array([ts]), 60, "high", 0, 1)[0])

    def test_past_coverage_raises_unless_allowed(self):
        late = self.bars(datetime(2026, 12, 1, 10, tzinfo=ec.ET), 3)
        with self.assertRaises(ValueError):
            ec.news_window(late, 300, "high")
        self.assertFalse(ec.news_window(late, 300, "high", allow_uncovered=True).any())
        self.assertTrue(np.isnan(ec.minutes_to_next(late, "high", allow_uncovered=True)).all())

    def test_source_filter_drops_rule_events(self):
        checked = ec.events("high", sources=("official", "vintage"))
        self.assertFalse(any(e.event.startswith("ism") for e in checked))
        self.assertIn(date(2026, 9, 11), ec.news_days("high", sources=("official",)))

    def test_impact_ordering(self):
        self.assertLess(len(ec.events("high")), len(ec.events("medium")))
        self.assertLess(len(ec.events("medium")), len(ec.events("low")))


class Generated(unittest.TestCase):
    def test_csv_and_frontend_module_are_current(self):
        self.assertEqual(ec.main(["--check"]), 0, "run python econ_calendar.py --write")


if __name__ == "__main__":
    unittest.main()
