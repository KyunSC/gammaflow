"""Offline checks for month_end_flows_study on synthetic daily closes."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import month_end_flows_study as me

SPEC_SHA = "c12c93d7f22f88bd"   # month_end_flows_study.script_sha(); update only in a commit that says why


def weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def prices(days, re=None, rb=None, seed=0, sd_e=0.01, sd_b=0.004) -> pd.DataFrame:
    """Closes built from daily returns; re/rb override the random draws where given."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sd_e, len(days)) if re is None else np.asarray(re, float)
    b = rng.normal(0, sd_b, len(days)) if rb is None else np.asarray(rb, float)
    e[0] = b[0] = 0.0
    return pd.DataFrame({me.EQ: 100 * np.cumprod(1 + e), me.BD: 100 * np.cumprod(1 + b)},
                        index=pd.Index(days, name="date"))


def with_effect(days, kind: str, bp: float, seed=0) -> pd.DataFrame:
    """Random closes plus `bp` per day on the H2 (stock) or H3 (bond) flagged days."""
    base = me.month_table(prices(days, seed=seed))
    rng = np.random.default_rng(seed)
    e, b = rng.normal(0, 0.01, len(days)), rng.normal(0, 0.004, len(days))
    pos = {d: i for i, d in enumerate(days)}
    for blk in me.flag_blocks(base, kind):
        for i in blk:
            (e if kind == "H2" else b)[pos[base.index[i]]] += bp / me.BP
    return prices(days, e, b)


class Calendar(unittest.TestCase):
    def test_month_table_drops_cut_months_and_counts_both_ends(self):
        days = weekdays(date(2020, 1, 15), date(2020, 4, 10))
        t = me.month_table(prices(days))
        self.assertEqual(sorted({d.month for d in t.index}), [2, 3])
        feb = t[[d.month == 2 for d in t.index]]
        self.assertEqual(feb["k"].iloc[0], 1)
        self.assertEqual(feb["j"].iloc[-1], 1)
        self.assertEqual(feb["j"].iloc[0], len(feb))

    def test_flag_blocks(self):
        t = me.month_table(prices(weekdays(date(2020, 1, 1), date(2020, 6, 30))))
        h2 = me.flag_blocks(t, "H2")
        self.assertTrue(all(len(b) == 4 for b in h2))
        first = t.iloc[h2[0]]
        self.assertEqual(list(first["j"].iloc[:1]), [1])
        self.assertEqual(list(first["k"].iloc[1:]), [1, 2, 3])
        h3 = me.flag_blocks(t, "H3")
        self.assertTrue(all(list(t.iloc[b]["j"]) == [3, 2, 1] for b in h3))


class Rebalance(unittest.TestCase):
    def setUp(self):
        self.days = weekdays(date(2021, 1, 1), date(2021, 5, 31))

    def test_drift_weight_math_and_reset(self):
        t = me.month_table(prices(self.days, re=[0.01] * len(self.days), rb=[0.0] * len(self.days)))
        w = me.drift_weight(t)
        self.assertAlmostEqual(w[0], 0.6 * 1.01 / (0.6 * 1.01 + 0.4))
        first_of_month = np.flatnonzero(t["k"].to_numpy() == 1)[1]
        self.assertAlmostEqual(w[first_of_month], w[0])   # reset after the previous month-end close

    def test_positions_fade_the_overweight_only_in_the_last_week(self):
        n = len(self.days)
        t = me.month_table(prices(self.days, re=[0.004] * n, rb=[0.0] * n))   # stocks always outrun
        pos = me.h1_positions(t)
        j = t["j"].to_numpy()
        self.assertTrue(np.all(pos[j <= 5] == -1))
        self.assertTrue(np.all(pos[j > 5] == 0))
        t2 = me.month_table(prices(self.days, re=[0.0] * n, rb=[0.004] * n))   # bonds outrun
        self.assertTrue(np.all(me.h1_positions(t2)[t2["j"].to_numpy() <= 5] == 1))

    def test_no_look_ahead(self):
        t = me.month_table(prices(self.days, seed=3))
        pos = me.h1_positions(t)
        i = int(np.flatnonzero(t["j"].to_numpy() == 3)[0])
        t2 = t.copy()
        t2.iloc[i, t2.columns.get_loc("re")] += 0.5    # a huge move on day i cannot change day i's position
        self.assertEqual(me.h1_positions(t2)[i], pos[i])

    def test_costs_charge_entries_exits_and_flips(self):
        n = len(self.days)
        t = me.month_table(prices(self.days, re=[0.004] * n, rb=[0.0] * n))
        b = me.h1_blocks(t)
        rt = me.EQ_RT_BP + me.BD_RT_BP
        self.assertTrue(np.allclose(b["cost"], rt))          # enter + exit = one round trip per leg
        self.assertTrue(np.allclose(b["net"], b["gross"] - rt))
        self.assertTrue(np.all(b["days"] == 5))
        with mock.patch.object(me, "h1_positions", return_value=np.where(t["j"] == 3, 1.0,
                               np.where(t["j"] <= 5, -1.0, 0.0))):
            self.assertTrue(np.allclose(me.h1_blocks(t)["cost"], 3 * rt))   # one flip out, one back

    def test_injected_rebalancing_pressure_is_found(self):
        """Stocks lose `c` (and bonds gain nothing) on each last-5 day after stocks led the month,
        and gain `c` after bonds led: the study must recover about 5 x c per month."""
        days = weekdays(date(2004, 1, 1), date(2019, 12, 31))
        j = me.month_table(prices(days))["j"].reindex(days).to_numpy()
        rng = np.random.default_rng(5)
        e, b = rng.normal(0, 0.01, len(days)), rng.normal(0, 0.004, len(days))
        c, w = 0.002, 0.6
        for i in range(1, len(days)):
            if not np.isnan(j[i]) and j[i] <= 5:
                e[i] -= c * np.sign(w - 0.6)
            s, bb = w * (1 + e[i]), (1 - w) * (1 + b[i])
            w = 0.6 if j[i] == 1 else s / (s + bb)
        t = me.month_table(prices(days, e, b))
        r = me.evaluate(t, "H1_rebalance", date(2006, 1, 1), date(2019, 12, 31))
        self.assertGreater(r["gross"]["mean"], 5 * c * me.BP * 0.7)
        self.assertLess(r["p_rand"], 0.01)

    def test_random_sign_null(self):
        b = pd.DataFrame({"gross": [50.0] * 40, "cost": [3.0] * 40})
        self.assertLess(me.random_p_h1(b), 0.01)
        b = pd.DataFrame({"gross": np.random.default_rng(1).normal(0, 50, 40), "cost": [3.0] * 40})
        self.assertGreater(me.random_p_h1(b), 0.05)


class Contrasts(unittest.TestCase):
    days = weekdays(date(2004, 1, 1), date(2019, 12, 31))

    def test_turn_of_month_effect_is_found(self):
        t = me.month_table(with_effect(self.days, "H2", 25.0))
        r = me.evaluate(t, "H2_turn_of_month", date(2006, 1, 1), date(2019, 12, 31))
        self.assertGreater(r["main"]["mean"], 60)             # ~4 x 25 bp minus 1 bp cost
        self.assertGreater(r["main"]["ci95"][0], 0)
        self.assertLess(r["p_rand"], 0.01)
        self.assertEqual(me.verdict(r, r["p_rand"]), "PASS")

    def test_no_effect_is_not_found(self):
        t = me.month_table(prices(self.days, seed=7))
        r = me.evaluate(t, "H2_turn_of_month", date(2006, 1, 1), date(2019, 12, 31))
        self.assertGreater(r["p_rand"], 0.05)
        self.assertTrue(me.verdict(r, r["p_rand"]).startswith("FAIL"))

    def test_treasury_month_end_uses_bonds(self):
        t = me.month_table(with_effect(self.days, "H3", 10.0, seed=2))
        r = me.evaluate(t, "H3_treasury_month_end", date(2006, 1, 1), date(2019, 12, 31))
        self.assertGreater(r["main"]["mean"], 20)
        self.assertLess(r["p_rand"], 0.01)
        r2 = me.evaluate(t, "H2_turn_of_month", date(2006, 1, 1), date(2019, 12, 31))
        self.assertLess(abs(r2["main"]["mean"]), 30)          # stocks untouched

    def test_window_keeps_only_whole_blocks(self):
        t = me.month_table(prices(self.days))
        r = me.evaluate(t, "H2_turn_of_month", date(2006, 1, 1), date(2006, 12, 31))
        self.assertEqual(r["main"]["n"], 11)   # Dec 2005 and Dec 2006 blocks straddle the edges


class Discipline(unittest.TestCase):
    def test_holm(self):
        adj = me.holm({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(adj["a"], 0.03)
        self.assertAlmostEqual(adj["c"], 0.06)
        self.assertAlmostEqual(adj["b"], 0.06)

    def test_rows_after_research_cap_are_refused(self):
        px = prices(weekdays(date(2026, 7, 1), me.RESEARCH_CAP + timedelta(days=3)))
        with self.assertRaises(SystemExit):
            me.check_cap(px)
        me.check_cap(px[px.index <= me.RESEARCH_CAP])
        self.assertLess(me.RESEARCH_CAP, me.VERIFY_START.date())

    def test_second_look_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "looks.log"
            log.write_text("script=x hyps=H2 at now\n")
            with mock.patch.object(me, "LOOKS", log), mock.patch.object(me, "OUT", Path(d)):
                self.assertEqual(me.score(me.month_table(prices(self.days()))), 1)

    def test_incomplete_history_does_not_spend_the_look(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "looks.log"
            with mock.patch.object(me, "LOOKS", log), mock.patch.object(me, "OUT", Path(d)):
                self.assertEqual(me.score(me.month_table(prices(self.days()))), 1)
            self.assertFalse(log.exists())

    def test_one_look_end_to_end(self):
        days = weekdays(me.DATA_START, me.RESEARCH_CAP)
        t = me.month_table(prices(days, seed=11))
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "looks.log"
            with mock.patch.object(me, "LOOKS", log), mock.patch.object(me, "OUT", Path(d)), \
                    mock.patch.object(me, "N_RANDOM", 300), mock.patch.object(me, "N_BOOT", 300):
                self.assertEqual(me.score(t), 0)
                self.assertEqual(len(me.looks()), 1)
                res = json.loads((Path(d) / "results.json").read_text())
                self.assertIn("H2_turn_of_month", res["test"])     # its short overlap never gates it
                self.assertFalse(res["replication"]["H2_turn_of_month"]["gated"])
                self.assertTrue(res["replication"]["H1_rebalance"]["gated"])
                self.assertEqual(me.score(t), 1)
            self.assertEqual(len(log.read_text().splitlines()), 1)

    def test_windows_follow_the_papers(self):
        for h, s in me.HYPS.items():
            self.assertLess(s["rep_end"], s["test_start"], h)
        self.assertEqual(me.HYPS["H1_rebalance"]["rep_end"], date(2023, 3, 17))

    def test_spec_is_pinned(self):
        self.assertEqual(me.script_sha(), SPEC_SHA)

    @staticmethod
    def days():
        return weekdays(date(2010, 1, 1), date(2012, 12, 31))   # far too short for the test windows


if __name__ == "__main__":
    unittest.main()
