"""Offline checks for trader_playbooks_study on hand-built bars and a path-consistent random walk."""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

import trader_playbooks_study as tp

SPEC_SHA = "7e3668e82a6f0cbc"   # tp.script_sha(); any edit to the spec (or amt_lucid_study.py) must update this visibly


def sess(rows, v=100.0):
    """rows of (o, h, l, c[, volume]) from 09:30, padded with flat bars at the last close to 16:00."""
    rows = [r if len(r) == 5 else (*r, v) for r in rows]
    c = rows[-1][3]
    rows = rows + [(c, c, c, c, v)] * (390 - len(rows))
    a = np.array(rows, float)
    return dict(O=a[:, 0], H=a[:, 1], L=a[:, 2], C=a[:, 3], V=a[:, 4], m=np.arange(tp.OPEN, tp.OPEN + 390), inst=None)


def tape(days, pad=None, pv=50.0):
    """A tape of `pad` sessions (default: 14 sessions with a 40-point range, so ATR = 40) followed by `days`."""
    pad = [sess([(110, 130, 90, 110)])] * tp.ATR_SESSIONS if pad is None else pad
    out, d = {}, date(2024, 1, 1)
    for s in pad + days:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out[d] = s
        d += timedelta(days=1)
    return tp.build_tape(out, pv)


def expand15(o, h, l, c):
    """Fifteen 1m bars walking o -> l -> h -> c."""
    pts = np.r_[np.linspace(o, l, 6)[:-1], np.linspace(l, h, 6)[:-1], np.linspace(h, c, 6)]
    return [(a, max(a, b), min(a, b), b) for a, b in zip(pts[:-1], pts[1:])]


def random_walk(n, seed=3, vol=1.2, sub=12):
    """RTH sessions of a fat-tailed random walk; bars are the OHLC of a finer path, so wicks are real excursions."""
    rng = np.random.default_rng(seed)
    out, d, px = {}, date(2023, 1, 2), 5000.0
    m = np.arange(tp.OPEN, tp.CLOSE)
    while len(out) < n:
        if d.weekday() < 5:
            px += rng.normal(0, vol * 8)
            path = px + np.cumsum(rng.standard_t(4, len(m) * sub) * vol / np.sqrt(sub)).reshape(len(m), sub)
            o = np.r_[px, path[:-1, -1]]
            r = lambda x: np.round(x / tp.TICK) * tp.TICK
            out[d] = dict(O=r(o), H=r(np.maximum(path.max(1), o)), L=r(np.minimum(path.min(1), o)), C=r(path[:, -1]),
                          V=rng.gamma(2, 500, len(m)), m=m, inst=None)
            px = path[-1, -1]
        d += timedelta(days=1)
    return out


class Fills(unittest.TestCase):
    def T(self, rows):
        return tape([sess(rows)], pad=[])

    def test_stop_wins_a_bar_touching_both(self):
        T = self.T([(100, 100, 100, 100), (100, 103, 98, 101)])
        f = tp.fill(T, 1, 1, 100.25, 99.0, 102.0, 389, None, tp.SLIP, 0.0)
        self.assertEqual((f["reason"], f["amb"]), ("stop", True))
        self.assertAlmostEqual(f["r"], (98.75 - 100.25) / 1.25)

    def test_gap_through_stop_fills_at_the_open(self):
        T = self.T([(100, 100.5, 99.5, 100), (97, 98, 96, 97.5)])
        f = tp.fill(T, 1, 0, 100.25, 99.0, 104.0, 389, None, tp.SLIP, 0.0)
        self.assertEqual((f["reason"], f["exit"]), ("stop", 1))
        self.assertAlmostEqual(f["r"], (96.75 - 100.25) / 1.25)

    def test_target_needs_a_tick_through(self):
        T = self.T([(100, 100, 100, 100), (100, 102, 99.5, 101.5), (101.5, 102.25, 101, 102)])
        f = tp.fill(T, 1, 1, 100.0, 99.0, 102.0, 389, None, 0.0, 0.0)
        self.assertEqual((f["reason"], f["exit"]), ("target", 2))

    def test_time_exit_at_last_close(self):
        T = self.T([(100, 100.5, 99.75, 100.25)])
        f = tp.fill(T, -1, 0, 100.0, 101.0, 98.0, 5, None, tp.SLIP, 0.1)
        self.assertEqual(f["reason"], "time")
        self.assertAlmostEqual(f["r"], (100.0 - 100.5) - 0.1)

    def test_limit_fill_bar_down_bar_ignores_the_earlier_high(self):
        # buy limit 100 on a down bar (O-H-L-C): the 103 high came before the fill, the 99.5 low after it
        T = self.T([(101, 103, 99.5, 99.75)])
        long_ = tp.fill(T, 1, 0, 100.0, 99.0, 102.0, 389, 1, 0.0, 0.0)
        self.assertEqual(long_["reason"], "time")
        short = tp.fill(T, -1, 0, 100.0, 101.0, 99.75, 389, 1, 0.0, 0.0)    # its stop at 101 is not hit by the 103
        self.assertEqual(short["reason"], "target")

    def test_limit_fill_bar_up_bar_counts_the_later_high(self):
        T = self.T([(100.5, 103, 99.5, 102.5)])                               # O-L-H-C: the 103 comes after the fill
        f = tp.fill(T, 1, 0, 100.0, 99.0, 102.0, 389, 1, 0.0, 0.0)
        self.assertEqual((f["reason"], f["exit"]), ("target", 0))

    def test_limit_pair_enters_at_the_next_open(self):
        T = self.T([(101, 101, 99.5, 99.75), (99.75, 100, 99.5, 99.75), (99.75, 104, 99.75, 103.75)])
        rec = tp.execute(T, tp.Plan(1, 0, 100.0, 99.0, 102.0, 389, True))
        # bought at the next open 99.75 + 1 tick, stop 1 below and target 2 above that open
        self.assertAlmostEqual(rec["r_dir"], (101.75 - 100.0 - tp.COMMISSION_RT / 50) / 1.25)
        self.assertEqual(rec["d"], 1)


class LegProfile(unittest.TestCase):
    def test_thin_bin_between_two_clusters(self):
        rows = [(100, 110, 100, 108, 1000)] * 4 + [(110, 112, 110, 112, 50)] + [(112, 120, 112, 119, 1000)] * 4
        T = tape([sess(rows)], pad=[])
        z = tp.leg_lvn(T, 0, 8)
        self.assertIsNotNone(z)
        self.assertTrue(110 <= z[0] < z[1] <= 112.4, z)

    def test_uniform_leg_has_no_lvn(self):
        T = tape([sess([(100, 110, 100, 110, 1000)] * 5)], pad=[])
        self.assertIsNone(tp.leg_lvn(T, 0, 4))

    def test_leg_too_short(self):
        T = tape([sess([(100, 104, 100, 104, 1000)] * 5)], pad=[])            # 16 ticks < 20 bins
        self.assertIsNone(tp.leg_lvn(T, 0, 4))


LEG_ROWS = [(100, 110, 100, 108, 1000)] * 4 + [
    (108, 112, 108, 112, 50), (112, 114, 112, 114, 1000), (113.5, 116, 113, 116, 1000), (115.5, 118, 115, 118, 1000),
    (117.5, 120, 117, 119.5, 1000), (119.5, 119.5, 118, 118.5), (118.5, 118.5, 115, 115.5),
    (115.5, 115.5, 110.25, 111), (111, 116, 110.75, 115.5), (115.5, 121, 115, 120.5)]


class LvnLeg(unittest.TestCase):
    T = tape([sess(LEG_ROWS)])
    s = tp.ATR_SESSIONS

    def test_touch_buys_the_lvn_and_targets_the_leg_high(self):
        (t,) = tp.lvn_leg_session(self.T, self.s, 0.3, "touch", "extreme")
        # zone (110, 111): limit 110.5 filled by the 110.25 low; stop 110 - max(2 ticks, 0.05 x 20) = 109; target 120
        self.assertEqual((t["d"], t["reason"], t["stop_ticks"]), (1, "target", 6.0))
        self.assertAlmostEqual(t["r"], (120 - 110.5 - tp.COMMISSION_RT / 50) / 1.5)

    def test_reject_skips_a_leg_extreme_under_2r(self):
        # the rejection bar closes at 115.5: entry 115.75, stop 109, target 120 < 2R
        self.assertEqual(tp.lvn_leg_session(self.T, self.s, 0.3, "reject", "extreme"), [])
        (t,) = tp.lvn_leg_session(self.T, self.s, 0.3, "reject", "3R")
        self.assertEqual((t["d"], t["reason"], t["stop_ticks"]), (1, "time", 27.0))

    def test_leg_too_small_for_q(self):
        self.assertEqual(tp.lvn_leg_session(self.T, self.s, 0.6, "touch", "extreme"), [])   # 20 pts < 0.6 x 40

    def test_no_atr_no_trade(self):
        self.assertEqual(tp.lvn_leg_session(tape([sess(LEG_ROWS)], pad=[]), 0, 0.3, "touch", "3R"), [])


class Reclaim(unittest.TestCase):
    prior = sess([(110, 115, 105, 110)] * 390)          # VA 108 - 115, POC 110
    rows = [(111, 113, 110.5, 112.5, 1000), (112.5, 116, 112.5, 115.5, 50), (115.5, 120, 115.5, 119, 1000),
            (119, 120, 117, 117.5, 1000), (117.5, 117.5, 113.5, 113.75, 40), (113.75, 114, 111, 111.5, 1000),
            (111.5, 112, 110.5, 111, 1000), (110.5, 114.5, 110.25, 114, 300), (114, 116.25, 113.5, 115.75, 300),
            (115.75, 116, 112, 112.5, 300), (112.5, 112.5, 108, 108.5, 300), (108.5, 109, 107, 107.5, 300)]

    def T(self, rows):
        return tape([self.prior, sess(rows)])

    def test_levels(self):
        lv = tp.prior_levels(self.T(self.rows), tp.ATR_SESSIONS)
        self.assertEqual((lv["val"], lv["poc"], lv["vah"]), (108.0, 110.0, 115.0))

    def test_short_the_pullback_into_the_reclaim_leg_lvn(self):
        (t,) = tp.lvn_reclaim_session(self.T(self.rows), tp.ATR_SESSIONS + 1, "touch", "lvn")
        # sell limit 115.25 in the (114.775, 115.25) zone; stop widened to 4 ticks (116.25); the up fill bar's later
        # high reaches it
        self.assertEqual((t["d"], t["reason"], t["stop_ticks"]), (-1, "stop", 4.0))
        self.assertAlmostEqual(t["r"], -1.0 - tp.SLIP - tp.COMMISSION_RT / 50)

    def test_extreme_stop_fails_the_2r_minimum(self):
        self.assertEqual(tp.lvn_reclaim_session(self.T(self.rows), tp.ATR_SESSIONS + 1, "touch", "extreme"), [])

    def test_open_outside_value_no_trade(self):
        rows = [(117, 118, 116.5, 117.5)] + self.rows[1:]
        self.assertEqual(tp.lvn_reclaim_session(self.T(rows), tp.ATR_SESSIONS + 1, "touch", "lvn"), [])

    def test_reaching_the_poc_first_voids(self):
        rows = self.rows[:5] + [(113.75, 114, 110, 111, 1000)] + self.rows[6:]
        self.assertEqual(tp.lvn_reclaim_session(self.T(rows), tp.ATR_SESSIONS + 1, "touch", "lvn"), [])


class Pbd(unittest.TestCase):
    bars = [(110, 114, 109.9, 113.75), (113.75, 114.25, 112.75, 113.5), (113.5, 114.25, 112.75, 114),
            (114, 114.25, 113, 113.25), (113.25, 115, 113, 114.75), (114.75, 115, 114, 114.5), (114.5, 118.5, 114.25, 118)]
    flat = [sess([(110, 110.25, 109.75, 110)] * 390)] * 3

    def T(self, bars):
        return tape([sess([r for b in bars for r in expand15(*b)])], pad=self.flat)

    def test_retest_of_the_box_top_is_bought(self):
        T = self.T(self.bars)
        (t,) = tp.pbd(T, 2, "mid", 2)
        # box 112.75 - 114.25, limit 114.25, stop mid 113.5 - 1 tick, target 2R = 116.25
        self.assertEqual((t["d"], t["reason"], t["stop_ticks"]), (1, "target", 4.0))
        self.assertAlmostEqual(t["r"], 2 - tp.COMMISSION_RT / 50)
        (t,) = tp.pbd(T, 2, "far", 4)
        self.assertEqual((t["reason"], t["stop_ticks"]), ("time", 7.0))

    def test_no_retest_no_trade(self):
        bars = self.bars[:5] + [(114.75, 118.5, 114.5, 118)]
        self.assertEqual(tp.pbd(self.T(bars), 2, "mid", 2), [])

    def test_box_too_tall_no_trade(self):
        bars = self.bars[:2] + [(113.5, 114.25, 111, 114)] + self.bars[3:]      # 3.25 > 0.5 x 3.75
        self.assertEqual(tp.pbd(self.T(bars), 2, "mid", 2), [])

    def test_impulse_too_small_for_k(self):
        self.assertEqual(tp.pbd(self.T(self.bars), 8, "mid", 2), [])


class RandomWalk(unittest.TestCase):
    """No edge in, no edge out: on a random walk the coin-flip edge is ~0 and no cell earns gross R."""

    @classmethod
    def setUpClass(cls):
        cls.cells = tp.run_cells(tp.build_tape(random_walk(400), 50.0))

    def test_edge_and_gross_are_noise(self):
        for name, tr in self.cells.items():
            if len(tr) < 40:
                continue
            e = np.array([(t["r_dir"] - t["r_flip"]) / 2 for t in tr])
            g = np.array([t["r_gross"] for t in tr])
            se_e, se_g = e.std() / np.sqrt(len(e)), g.std() / np.sqrt(len(g))
            self.assertLess(abs(e.mean()), 4 * se_e + 0.02, name)
            self.assertLess(g.mean(), 4 * se_g, name)

    def test_costs_only_subtract(self):
        for name, tr in self.cells.items():
            for t in tr:
                self.assertLessEqual(t["r"], t["r_gross"] + 1e-9, name)

    def test_score_fields(self):
        name = "lvn_leg/q=0.3/entry=reject/target=3R"
        c = tp.score(self.cells[name])
        self.assertGreater(c["trades"], 100)
        self.assertLess(c["mean_2x"], c["mean"])
        self.assertTrue(0 < c["coin"]["p"] <= 1)


class Selection(unittest.TestCase):
    def cell(self, n=80, mean=0.1, m2=0.05, edge=0.02):
        return dict(trades=n, mean=mean, mean_2x=m2, edge=edge)

    def res(self, spy, qqq):
        names = [tp.cell_name(s, p) for s, ps in tp.GRID.items() for p in ps]
        return dict(SPY=dict(cells={n: dict(trades=0) for n in names} | spy),
                    QQQ=dict(cells={n: dict(trades=0) for n in names} | qqq))

    def test_needs_both_and_every_condition(self):
        a, b = "pbd/k=2/stop=mid/rr=2", "pbd/k=3/stop=far/rr=4"
        chosen = tp.select(self.res({a: self.cell(), b: self.cell(mean=0.3)}, {a: self.cell(), b: self.cell(m2=-0.01)}))
        self.assertEqual(chosen["pbd"]["cell"], a)
        self.assertIsNone(chosen["lvn_leg"])
        chosen = tp.select(self.res({a: self.cell(n=59)}, {a: self.cell()}))
        self.assertIsNone(chosen["pbd"])


class OneLook(unittest.TestCase):
    def test_spec_hash_pinned(self):
        self.assertEqual(tp.script_sha(), SPEC_SHA)

    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["x", *args]):
            return tp.main()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(tp, "OUT", self.dir), mock.patch.object(tp, "PREREG", self.dir / "prereg.json"),
                        mock.patch.object(tp, "LOOKS", self.dir / "looks.log")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_refuses_a_second_look(self):
        tp.LOOKS.write_text("script=x sessions=1 at now\n")
        self.assertEqual(self.run_main("--confirm"), 1)

    def test_refuses_without_freeze(self):
        self.assertEqual(self.run_main("--confirm"), 1)

    def test_refuses_a_changed_spec(self):
        tp.PREREG.write_text(json.dumps(dict(script_sha="stale", selected={})))
        self.assertEqual(self.run_main("--confirm"), 1)
        self.assertFalse(tp.LOOKS.exists())

    def test_nothing_selected_leaves_nq_unread(self):
        tp.PREREG.write_text(json.dumps(dict(script_sha=tp.script_sha(), selected={s: None for s in tp.GRID})))
        with mock.patch.object(tp, "load_nq", side_effect=AssertionError("NQ read")):
            self.assertEqual(self.run_main("--confirm"), 0)
        self.assertFalse(tp.LOOKS.exists())

    def test_partial_download_does_not_spend_the_look(self):
        tp.PREREG.write_text(json.dumps(dict(script_sha=tp.script_sha(), selected={
            "pbd": dict(cell="pbd/k=2/stop=mid/rr=2", params=dict(k=2, stop="mid", rr=2))})))
        few = {date(2012, 1, 3) + timedelta(days=i): None for i in range(300)}
        with mock.patch.object(tp, "load_nq", return_value=few):
            self.assertEqual(self.run_main("--confirm"), 1)
        self.assertFalse(tp.LOOKS.exists())

    def test_coverage(self):
        self.assertEqual(len(tp.coverage_problems({})), 10)


if __name__ == "__main__":
    unittest.main()
