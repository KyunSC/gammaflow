"""Offline checks for vp_claims_study on hand-built bars and profiles."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import vp_claims_study as vp

T = vp.TICK
SPEC_SHA = "1dcb2bad4a7db98b"   # vp.script_sha(): vp_claims_study.py + amt_lucid_study.py; any change shows up here


def trading_days(n, start=date(2023, 1, 3)):
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5 and d not in vp.NYSE_HOLIDAYS:
            days.append(d)
        d += timedelta(days=1)
    return days


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

    def test_pairs_need_the_previous_trading_day(self):
        days = [date(2023, 1, 3), date(2023, 1, 9),                  # a hole: Jan 4-6 missing
                date(2023, 1, 13), date(2023, 1, 17),                # MLK Monday between: still adjacent
                date(2023, 4, 6), date(2023, 4, 10),                 # Good Friday between
                date(2023, 11, 22), date(2023, 11, 27)]              # half-day Friday dropped: not adjacent
        s = {d: dict(inst=None) for d in days}
        self.assertEqual(vp.pairs(s), [(date(2023, 1, 13), date(2023, 1, 17)), (date(2023, 4, 6), date(2023, 4, 10))])
        self.assertEqual(vp.prev_session(date(2012, 10, 31)), date(2012, 10, 26))   # Sandy closure


class T1(unittest.TestCase):
    lv = dict(poc=104.0, vwap=103.0, mid=103.0, close=101.0, val=102.0, vah=106.0, low=98.0, high=108.0, range=10.0,
              width=0, hvn=[], lvn=[], base=392, nbins=41, poc_bin=24)

    def day(self, high, low=99.5):
        """Open 100; one 10:00 bar reaches `high` and `low`."""
        rows = [(100, 100.25, 99.75, 100)] * 30 + [(100, high, low, 100)] + [(100, 100.25, 99.75, 100)] * 359
        return sess(rows)

    def test_session_touch_mirror_and_control(self):
        hits, weight, lv = vp.t1_session(self.lv, self.day(104.25))
        cell, touch, mirror = lv["poc"]
        self.assertEqual((touch, mirror), (1, 0))                    # mirror = 96, never traded
        self.assertAlmostEqual(hits[cell] / weight[cell], 1.0)       # 104.25 shares the POC's cell and was reached
        far = vp.t1_session(self.lv, self.day(102.0))
        self.assertEqual(far[2]["poc"][1], 0)
        self.assertAlmostEqual(far[0][cell], 0.0)

    def test_first_five_minutes_ignored(self):
        s = sess([(100, 104.5, 99.5, 100)] + [(100, 100.5, 99.5, 100)] * 389)
        self.assertEqual(vp.t1_session(self.lv, s)[2]["poc"][1:], (0, 0))

    def test_too_close_skipped(self):
        lv = dict(self.lv, poc=100.5)
        self.assertNotIn("poc", vp.t1_session(lv, flat_day())[2])

    def run_t1(self, highs):
        days = trading_days(len(highs) + 1)
        sessions = {d: self.day(h) for d, h in zip(days, [100.25] + highs)}
        with mock.patch.object(vp, "prior_levels", return_value=self.lv):
            return vp.t1(sessions)["poc"]

    def test_reversion_alone_is_not_a_magnet(self):
        # half the days run far enough to pass the POC, half don't: the POC is reached exactly as often as any
        # prior-range price that far up, so no excess, though touch - mirror says +0.5
        r = self.run_t1([105.0, 102.0] * 20)
        self.assertAlmostEqual(r["mean"], 0.0)
        self.assertAlmostEqual(r["minus_mirror"]["mean"], 0.5)

    def test_stopping_at_the_poc_is_excess(self):
        r = self.run_t1([104.0] * 40)                                # reaches the POC, never the tick past it
        self.assertAlmostEqual(r["mean"], 1.0)
        self.assertGreater(r["lower_alpha"], 0)


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

    def test_approach_bar_run_up_is_not_a_reversal(self):
        # the approach bar comes up from 97.75; its low printed before the touch, so it is not "back"
        pre = [(98, 98.25, 97.75, 98)] * 20
        s = sess(pre + [(98, 100.5, 97.75, 100.25), (100.25, 102.5, 100, 102.25)] + [(102, 102.25, 101.75, 102)] * 368)
        self.assertEqual(vp.first_passage(100.0, 2.0, s), "through")
        s = sess(pre + [(98, 102.5, 97.75, 102.25)] + [(102, 102.25, 101.75, 102)] * 369)   # one-bar breakout
        self.assertEqual(vp.first_passage(100.0, 2.0, s), "through")

    def test_strata_and_stratified_difference(self):
        lv = dict(val=99.0, vah=101.0, range=10.0)
        self.assertEqual(vp.t2_stratum(100.0, lv, 100.5), 3)         # inside VA, near the open
        self.assertEqual(vp.t2_stratum(106.0, lv, 100.0), 2)         # outside the VA, 0.6x the range away
        # Simpson: LVNs sit where pass-through is high for every kind; within each stratum LVN = HVN
        thr = np.zeros((3, vp.T2_NSTRATA)); tot = np.zeros((3, vp.T2_NSTRATA))
        tot[0, 0], thr[0, 0], tot[0, 1], thr[0, 1] = 90, 18, 10, 8      # HVN: mostly in the 20% stratum
        tot[1, 0], thr[1, 0], tot[1, 1], thr[1, 1] = 10, 2, 90, 72      # LVN: mostly in the 80% stratum
        self.assertGreater(thr[1].sum() / tot[1].sum() - thr[0].sum() / tot[0].sum(), 0.4)
        self.assertAlmostEqual(vp.strat_diff(thr, tot, 1, 0), 0.0)

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
        r2 = vp.bracket2(s, 1, 0, 2.0, 1.0, 2.0, False, 0.18, slip=2)
        self.assertAlmostEqual(r2, (100 - 2 * T - (100 + 2 * T) - 0.18) / 2.0)

    def test_bracket2_slip_keeps_planned_levels(self):
        # long, planned entry 100.25, stop 98.25; a bar to 98.25 stops both the 1-tick and the 2-tick replays
        s = sess([(100, 100.25, 99.75, 100), (100, 100, 98.25, 98.5)] + [(98.5, 98.75, 98.25, 98.5)] * 5)
        self.assertAlmostEqual(vp.bracket2(s, 1, 0, 2.0, 1.0, 2.0, False, 0.0), (98.25 - T - (100 + T)) / 2.0)
        self.assertAlmostEqual(vp.bracket2(s, 1, 0, 2.0, 1.0, 2.0, False, 0.0, slip=2),
                               (98.25 - 2 * T - (100 + 2 * T)) / 2.0)

    def test_plan_skips_entry_through_stop(self):
        dp = dict(side=-1, e=0, h5=100.0, l5=99.0, val=95.0, poc=97.0, vah=100.0)
        s = sess([(100, 100, 99, 99.5), (101, 101, 100, 100.5)])
        self.assertIsNone(vp.t3_plan(dp, s, 1))

    def test_edge_nets_out_the_coin(self):
        mk = lambda r, f: dict(day=date(2015, 1, 5), dir=1, r=r, r_flip=f, r_2x=r - .1, friction_r=.1, stop_ticks=6)
        sc = vp.t3_score(dict(bal=[mk(-0.2, -0.6)] * 3, twin=[mk(0.1, 0.1)] * 3), False)
        self.assertAlmostEqual(sc["edge"], 0.2)                     # worse R than the twin, better than its coin
        self.assertAlmostEqual(sc["twin_edge"], 0.0)
        self.assertAlmostEqual(sc["mean_2x"], -0.3)
        self.assertEqual(sc["stop_ticks_median"], 6)

    def test_selection_rule(self):
        def cell(n, mean, twin, mean_2x=None):
            return dict(trades=n, mean=mean, edge=mean, twin_edge=twin, mean_2x=mean if mean_2x is None else mean_2x)
        names = [vp.cell_name(p) for p in vp.T3_GRID]
        ex = {sym: dict(t3={n: cell(10, 1.0, 0.0) for n in names}) for sym in ("SPY", "QQQ")}
        self.assertIsNone(vp.select_t3(ex))                          # too few trades everywhere
        ex["SPY"]["t3"][names[3]] = cell(80, 0.2, 0.1)
        ex["QQQ"]["t3"][names[3]] = cell(70, 0.1, -0.1)
        ex["SPY"]["t3"][names[5]] = cell(80, 0.5, 0.6)              # loses to its twin: ineligible
        ex["QQQ"]["t3"][names[5]] = cell(70, 0.5, 0.0)
        self.assertEqual(vp.select_t3(ex)["cell"], names[3])
        ex["QQQ"]["t3"][names[3]] = cell(70, 0.1, -0.1, mean_2x=-0.05)  # dies at doubled friction
        self.assertIsNone(vp.select_t3(ex))


class Inference(unittest.TestCase):
    def test_boot_mean(self):
        self.assertGreater(vp.boot_mean(np.full(50, 0.2) + np.random.default_rng(1).normal(0, .01, 50))["lower_alpha"], 0)
        self.assertLess(vp.boot_mean(np.random.default_rng(1).normal(0, 1, 400))["lower_alpha"], 0)

    def test_verdicts(self):
        good = dict(mean=.1, lower_alpha=.01)
        t1 = dict(poc=good, vwap=dict(mean=.05), mid=dict(mean=0.0), close=dict(mean=None))
        res = dict(t1=t1, t2=dict(lvn_minus_hvn=good, placebo_minus_hvn=dict(mean=-.01)), t3=None)
        v = vp.verdicts(res)
        self.assertEqual((v["T1"], v["T2"]), ("PASS", "FAIL"))
        self.assertTrue(v["T3"].startswith("DROPPED"))
        t1["vwap"] = dict(mean=.12)                                  # VWAP pulls harder: the profile adds nothing
        self.assertEqual(vp.verdicts(res)["T1"], "FAIL")


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.prereg, self.looks = self.out / "prereg.json", self.out / "looks.log"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *argv, es=None):
        load = mock.Mock(return_value=es) if es is not None else mock.Mock(side_effect=AssertionError("ES must not be read"))
        with mock.patch.object(vp, "OUT", self.out), mock.patch.object(vp, "PREREG", self.prereg), \
             mock.patch.object(vp, "LOOKS", self.looks), mock.patch("sys.argv", ["vp", *argv]), \
             mock.patch.object(vp, "load_es", load), mock.patch.object(vp, "run_all", return_value=dict()) as run:
            return vp.main(), run

    def freeze_ok(self):
        (self.out / "explore.json").write_text(json.dumps(dict(script_sha=vp.script_sha(), selected_t3=None)))
        with mock.patch.object(vp, "select_t3", return_value=None):
            return self.run_main("--freeze")[0]

    def test_spec_hash_pinned(self):
        self.assertEqual(vp.script_sha(), SPEC_SHA, "spec changed: update SPEC_SHA in the same commit, on purpose")
        self.assertIn(Path(vp.HERE / "amt_lucid_study.py"), vp.SPEC_FILES)

    def test_prereg_and_looks_are_committed_paths(self):
        self.assertEqual(vp.PREREG.parent, vp.HERE)
        self.assertEqual(vp.LOOKS.parent, vp.HERE)

    def test_confirm_needs_freeze_and_same_script(self):
        self.assertEqual(self.run_main("--confirm")[0], 1)
        self.prereg.write_text(json.dumps(dict(script_sha="0" * 16, t3=None)))
        self.assertEqual(self.run_main("--confirm")[0], 1)
        self.assertFalse(self.looks.exists())

    def test_confirm_refuses_second_look(self):
        self.prereg.write_text(json.dumps(dict(script_sha=vp.script_sha(), t3=None)))
        self.looks.write_text("script=x sessions=2500 at then\n")
        self.assertEqual(self.run_main("--confirm")[0], 1)

    def test_confirm_refuses_partial_download_without_spending_the_look(self):
        self.prereg.write_text(json.dumps(dict(script_sha=vp.script_sha(), t3=None)))
        partial = {d: {} for d in trading_days(1200, start=date(2012, 1, 3))}     # ~2012-2016 only
        rc, run = self.run_main("--confirm", es=partial)
        self.assertEqual(rc, 1)
        run.assert_not_called()
        self.assertFalse(self.looks.exists())

    def test_confirm_logs_the_look_before_scoring(self):
        self.prereg.write_text(json.dumps(dict(script_sha=vp.script_sha(), t3=None)))
        full = {d: {} for d in trading_days(2600, start=date(2012, 1, 3)) if d <= vp.CONFIRM_END}
        seen = []
        with mock.patch.object(vp, "verdicts", side_effect=lambda r: seen.append(self.looks.read_text()) or {}), \
             mock.patch.object(vp, "report"):
            rc, run = self.run_main("--confirm", es=full)
        self.assertEqual(rc, 0)
        self.assertIn(f"script={vp.script_sha()}", seen[0])
        self.assertEqual(self.run_main("--confirm", es=full)[0], 1)

    def test_freeze_once(self):
        self.assertEqual(self.freeze_ok(), 0)
        self.assertEqual(self.freeze_ok(), 1)

    def test_freeze_refuses_stale_explore(self):
        (self.out / "explore.json").write_text(json.dumps(dict(script_sha="0" * 16, selected_t3={"cell": "x"})))
        self.assertEqual(self.run_main("--freeze")[0], 1)
        self.assertFalse(self.prereg.exists())

    def test_freeze_recomputes_the_pick(self):
        (self.out / "explore.json").write_text(json.dumps(dict(script_sha=vp.script_sha(), selected_t3={"cell": "edited"})))
        with mock.patch.object(vp, "select_t3", return_value=None):
            self.assertEqual(self.run_main("--freeze")[0], 0)
        self.assertIsNone(json.loads(self.prereg.read_text())["t3"])

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
