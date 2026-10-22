"""Offline checks for vp_claims_study on hand-built bars and profiles."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import vp_claims_study as vp

T = vp.TICK


def sess(rows, start=vp.OPEN, inst=None):
    """rows of (o, h, l, c[, v]) on consecutive minutes from `start`."""
    a = np.array([r if len(r) == 5 else (*r, 100.0) for r in rows], dtype=float)
    return dict(O=a[:, 0], H=a[:, 1], L=a[:, 2], C=a[:, 3], V=a[:, 4], m=np.arange(start, start + len(a)), inst=inst)


def flat_day(px=100.0, n=390):
    return sess([(px, px + T, px - T, px)] * n)


class Profile(unittest.TestCase):
    def test_tick_hist_spreads_bar_volume(self):
        vols, base = vp.tick_hist(np.array([100.5]), np.array([100.0]), np.array([30.0]))
        self.assertEqual(base, 400)
        np.testing.assert_allclose(vols, [10, 10, 10])

    def test_value_area_matches_amt_rule(self):
        vols = np.array([1, 2, 10, 40, 20, 5, 1, 1], dtype=float)   # 70% of 80 = 56: 40 + 20
        self.assertEqual(vp.value_area(vols), (3, 3, 4))

    def test_nodes_find_peaks_and_trough(self):
        # two humps with a trough between, in bins of 1 tick (close 100 -> 0.05% = 0.05 pt -> w = 1)
        vols = np.array([1] * 3 + [5, 9, 20, 9, 5] + [1, 0.2, 1] + [5, 9, 30, 9, 5] + [1] * 3, dtype=float)
        poc = int(np.argmax(vols))
        nd = vp.nodes(vols, 0, poc, 100.0)
        self.assertEqual(nd["width"], 1)
        self.assertEqual(nd["hvn"], [5 * T])                         # the other hump; the POC hump is dropped
        self.assertEqual(nd["lvn"], [9 * T])

    def test_nodes_near_extremes_dropped(self):
        vols = np.array([30, 9, 5, 1, 1, 1, 1, 1, 5, 9, 20], dtype=float)
        nd = vp.nodes(vols, 0, 0, 100.0)
        self.assertEqual(nd["hvn"], [])

    def test_pairs_skip_rolls(self):
        s = {date(2020, 3, 12): dict(inst=1), date(2020, 3, 13): dict(inst=2), date(2020, 3, 16): dict(inst=2)}
        self.assertEqual(vp.pairs(s), [(date(2020, 3, 13), date(2020, 3, 16))])


class T1(unittest.TestCase):
    lv = dict(poc=104.0, vwap=104.0, range=10.0)

    def test_touch_and_mirror(self):
        s = sess([(100, 100.5, 99.5, 100)] * 5 + [(100, 104.25, 99, 103)] + [(103, 103.5, 102.5, 103)] * 384)
        self.assertEqual(vp.t1_touches(self.lv, s), (1, 0))          # mirror = 96, never traded

    def test_first_five_minutes_ignored(self):
        s = sess([(100, 104.5, 99.5, 100)] + [(100, 100.5, 99.5, 100)] * 389)
        self.assertEqual(vp.t1_touches(self.lv, s), (0, 0))

    def test_too_close_skipped(self):
        self.assertIsNone(vp.t1_touches(dict(poc=100.5, range=10.0), flat_day()))


class T2(unittest.TestCase):
    def path(self, after):
        """flat below 100 until 09:50, a bar into 100, then `after`."""
        pre = [(99, 99.25, 98.75, 99)] * 20
        return sess(pre + [(99, 100.25, 99, 100)] + after + [(100, 100.25, 99.75, 100)] * (369 - len(after)))

    def test_through(self):
        self.assertEqual(vp.first_passage(100.0, 2.0, self.path([(100, 102.25, 99.5, 102)])), "through")

    def test_back(self):
        self.assertEqual(vp.first_passage(100.0, 2.0, self.path([(100, 100.5, 97.75, 98)])), "back")

    def test_ambiguous(self):
        self.assertEqual(vp.first_passage(100.0, 2.0, self.path([(100, 102.5, 97.5, 100)])), "ambiguous")

    def test_open_when_unresolved(self):
        self.assertEqual(vp.first_passage(100.0, 2.0, self.path([])), "open")

    def test_from_above_mirrors(self):
        pre = [(101, 101.25, 100.75, 101)] * 20
        s = sess(pre + [(101, 101, 99.75, 100)] + [(100, 100.25, 97.75, 98)] + [(98, 98.25, 97.75, 98)] * 368)
        self.assertEqual(vp.first_passage(100.0, 2.0, s), "through")

    def test_no_approach_before_0945(self):
        s = sess([(99, 100.25, 99, 100)] * 390)                     # sits on the level from the open
        self.assertIsNone(vp.first_passage(100.0, 2.0, s))

    def test_placebos_avoid_nodes(self):
        lv = dict(width=1, nbins=40, base=0, poc_bin=20, hvn=[10 * T], lvn=[30 * T])
        ps = vp.placebos(lv, date(2015, 6, 1))
        bins = [round(p / T) for p in ps]
        self.assertEqual(len(ps), vp.N_PLACEBO)
        self.assertTrue(all(min(abs(b - 10), abs(b - 20), abs(b - 30)) > vp.NODE_GAP for b in bins))
        self.assertEqual(ps, vp.placebos(lv, date(2015, 6, 1)))     # seeded by the date


class T3(unittest.TestCase):
    def balanced_day(self, probe_bar=None):
        """Every bar spans 99.75-100.25, 5m closes alternate either side of a flat VWAP; optional probe 5m bar."""
        rows = [(100, 100.25, 99.75, 100.25 if (i // 5) % 2 else 99.75) for i in range(390)]
        if probe_bar is not None:
            for i in range(probe_bar * 5, probe_bar * 5 + 5):
                rows[i] = (100.25, 101.5, 100.0, 100.25)
        return sess(rows)

    def test_gate_flat_vs_trend(self):
        dps = vp.decisions(self.balanced_day())
        self.assertTrue(dps and all(vp.balanced(dp, 0.05) for dp in dps))
        trend = sess([(100 + i * .05, 100 + i * .05 + T, 100 + i * .05 - T, 100 + i * .05) for i in range(390)])
        self.assertFalse(any(vp.balanced(dp, 0.15) for dp in vp.decisions(trend)))

    def test_decision_window(self):
        ends = [vp.OPEN + 5 * (s["e"] // 5 + 1) for s in vp.decisions(self.balanced_day())]
        self.assertEqual((min(ends), max(ends)), (vp.T3_FIRST, vp.T3_LAST))

    def test_probe_above_vah_closing_inside_is_short(self):
        dps = vp.decisions(self.balanced_day(probe_bar=30))          # 12:00-12:05 bar, decision at 12:05
        sig = [dp for dp in dps if dp["side"]]
        self.assertEqual(len(sig), 1)
        self.assertEqual(sig[0]["side"], -1)
        self.assertGreaterEqual(sig[0]["h5"], sig[0]["vah"] + T)

    def test_bracket2_halves(self):
        # short at 100 - tick; POC 99 (1 pt), far edge 98; both fill
        s = sess([(100, 100, 99.5, 99.75), (99.75, 99.75, 98.75, 99), (99, 99, 97.5, 97.75)] + [(97.75, 98, 97.5, 97.75)] * 10)
        r = vp.bracket2(s, -1, 0, 2.0, 100 - T - 99, 100 - T - 98, False, 0.0)
        self.assertAlmostEqual(r, ((100 - T - 99) + (100 - T - 98)) / 2 / 2.0)

    def test_bracket2_stop_first_and_breakeven(self):
        both = sess([(100, 102.5, 98.5, 100)] + [(100, 100.25, 99.75, 100)] * 5)
        self.assertAlmostEqual(vp.bracket2(both, -1, 0, 2.0, 1.0, 2.0, False, 0.0), (-2.0 - T) / 2.0)
        # first half at the POC, then back to entry: the second half exits at entry - slippage with be
        s = sess([(100, 100, 98.5, 98.75), (98.75, 100.0, 98.75, 99.75)] + [(99.75, 101.0, 99.5, 100.5)] * 5)
        entry = 100 - T
        r = vp.bracket2(s, -1, 0, 2.0, entry - 99.0, entry - 97.0, True, 0.0)
        self.assertAlmostEqual(r, ((entry - 99.0) + (entry - (entry + T))) / 2 / 2.0)

    def test_bracket2_costs_and_time_exit(self):
        s = sess([(100, 100.25, 99.75, 100)] * 390)
        r = vp.bracket2(s, 1, 0, 2.0, 1.0, 2.0, False, 0.09)
        self.assertAlmostEqual(r, (100 - T - (100 + T) - 0.09) / 2.0)

    def test_plan_skips_entry_through_stop(self):
        dp = dict(side=-1, e=0, h5=100.0, l5=99.0, val=95.0, poc=97.0, vah=100.0)
        s = sess([(100, 100, 99, 99.5), (101, 101, 100, 100.5)])
        self.assertIsNone(vp.t3_plan(dp, s, 1))

    def test_edge_nets_out_the_coin(self):
        mk = lambda r, f: dict(day=date(2015, 1, 5), dir=1, r=r, r_flip=f)
        sc = vp.t3_score(dict(bal=[mk(-0.2, -0.6)] * 3, twin=[mk(0.1, 0.1)] * 3), False)
        self.assertAlmostEqual(sc["edge"], 0.2)                     # worse R than the twin, better than its coin
        self.assertAlmostEqual(sc["twin_edge"], 0.0)

    def test_selection_rule(self):
        def cell(n, mean, twin):
            return dict(trades=n, mean=mean, edge=mean, twin_edge=twin)
        names = [vp.cell_name(p) for p in vp.T3_GRID]
        ex = {sym: dict(t3={n: cell(10, 1.0, 0.0) for n in names}) for sym in ("SPY", "QQQ")}
        self.assertIsNone(vp.select_t3(ex))                          # too few trades everywhere
        ex["SPY"]["t3"][names[3]] = cell(80, 0.2, 0.1)
        ex["QQQ"]["t3"][names[3]] = cell(70, 0.1, -0.1)
        ex["SPY"]["t3"][names[5]] = cell(80, 0.5, 0.6)              # loses to its twin: ineligible
        ex["QQQ"]["t3"][names[5]] = cell(70, 0.5, 0.0)
        self.assertEqual(vp.select_t3(ex)["cell"], names[3])


class Inference(unittest.TestCase):
    def test_boot_mean(self):
        self.assertGreater(vp.boot_mean(np.full(50, 0.2) + np.random.default_rng(1).normal(0, .01, 50))["lower_alpha"], 0)
        self.assertLess(vp.boot_mean(np.random.default_rng(1).normal(0, 1, 400))["lower_alpha"], 0)

    def test_verdicts(self):
        good = dict(mean=.1, lower_alpha=.01)
        res = dict(t1=dict(poc=good), t2=dict(lvn_minus_hvn=good, placebo_minus_hvn=dict(mean=-.01)), t3=None)
        v = vp.verdicts(res)
        self.assertEqual((v["T1"], v["T2"]), ("PASS", "FAIL"))
        self.assertTrue(v["T3"].startswith("DROPPED"))


class Guards(unittest.TestCase):
    def run_main(self, out, *argv):
        with mock.patch.object(vp, "OUT", out), mock.patch("sys.argv", ["vp", *argv]), \
             mock.patch.object(vp, "load_es", side_effect=AssertionError("ES must not be read")):
            return vp.main()

    def test_confirm_needs_freeze_and_same_script(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            self.assertEqual(self.run_main(out, "--confirm"), 1)
            (out / "preregistered.json").write_text(json.dumps(dict(script_sha="0" * 16, t3=None)))
            self.assertEqual(self.run_main(out, "--confirm"), 1)
            self.assertFalse((out / "confirm.lock").exists())

    def test_confirm_refuses_second_look(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "preregistered.json").write_text(json.dumps(dict(script_sha=vp.script_sha(), t3=None)))
            (out / "confirm.lock").write_text("script=x at then\n")
            self.assertEqual(self.run_main(out, "--confirm"), 1)

    def test_freeze_once(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "explore.json").write_text(json.dumps(dict(selected_t3=None)))
            self.assertEqual(self.run_main(out, "--freeze"), 0)
            self.assertEqual(self.run_main(out, "--freeze"), 1)

    def test_load_es_window_and_single_contract(self):
        idx = pd.date_range("2021-12-30 14:30", periods=390, freq="1min", tz="UTC")
        idx2 = pd.date_range("2022-01-03 14:30", periods=390, freq="1min", tz="UTC")
        rows = lambda n, inst: dict(open=[4000.0] * n, high=[4000.25] * n, low=[3999.75] * n, close=[4000.0] * n,
                                    volume=[10] * n, instrument_id=inst)
        df = pd.concat([pd.DataFrame(rows(390, [1] * 390), index=idx), pd.DataFrame(rows(390, [1] * 390), index=idx2)])
        df.index.name = "ts_event"
        with tempfile.TemporaryDirectory() as d:
            df.to_parquet(Path(d) / "2021-12-01_2022-02-01.parquet")
            s = vp.load_es(Path(d))
            self.assertEqual(list(s), [date(2021, 12, 30)])          # 2022 is outside the window
            mixed = df.iloc[:390].copy()
            mixed.loc[mixed.index[200:], "instrument_id"] = 2
            mixed.to_parquet(Path(d) / "2021-12-01_2022-02-01.parquet")
            self.assertEqual(vp.load_es(Path(d)), {})


if __name__ == "__main__":
    unittest.main()
