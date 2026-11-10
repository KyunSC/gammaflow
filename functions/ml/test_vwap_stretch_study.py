"""Offline checks for vwap_stretch_study on hand-built bars and a path-consistent random walk."""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

import vwap_stretch_study as vs

SPEC_SHA = "5a932782c41623b7"   # vs.script_sha(); any edit to the spec (or amt_lucid_study.py) must update this visibly


def sess(rows, v=100.0):
    """rows of (o, h, l, c[, volume]) from 09:30, padded with flat bars at the last close to 16:00."""
    rows = [r if len(r) == 5 else (*r, v) for r in rows]
    c = rows[-1][3]
    rows = rows + [(c, c, c, c, v)] * (390 - len(rows))
    a = np.array(rows, float)
    return dict(O=a[:, 0], H=a[:, 1], L=a[:, 2], C=a[:, 3], V=a[:, 4], m=np.arange(vs.OPEN, vs.OPEN + 390), inst=None)


def tape(days, pv=50.0):
    out, d = {}, date(2024, 1, 1)
    for s in days:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out[d] = s
        d += timedelta(days=1)
    return vs.build_tape(out, pv)


def random_walk(n, seed=3, vol=1.2, sub=12, drift=0.0):
    """RTH sessions of a fat-tailed random walk; bars are the OHLC of a finer path, so wicks are real excursions."""
    rng = np.random.default_rng(seed)
    out, d, px = {}, date(2023, 1, 2), 5000.0
    m = np.arange(vs.OPEN, vs.CLOSE)
    while len(out) < n:
        if d.weekday() < 5:
            px += rng.normal(0, vol * 8)
            steps = rng.standard_t(4, len(m) * sub) * vol / np.sqrt(sub) + drift / sub
            path = px + np.cumsum(steps).reshape(len(m), sub)
            o = np.r_[px, path[:-1, -1]]
            r = lambda x: np.round(x / vs.TICK) * vs.TICK
            out[d] = dict(O=r(o), H=r(np.maximum(path.max(1), o)), L=r(np.minimum(path.min(1), o)), C=r(path[:, -1]),
                          V=rng.gamma(2, 500, len(m)), m=m, inst=None)
            px = path[-1, -1]
        d += timedelta(days=1)
    return out


class Vwap(unittest.TestCase):
    def test_typical_price_weighted(self):
        H, L, C, V = (np.array(x, float) for x in ([3, 6], [1, 4], [2, 5], [1, 3]))
        np.testing.assert_allclose(vs.session_vwap(H, L, C, V), [2.0, (2 * 1 + 5 * 3) / 4])

    def test_zero_volume_falls_back_to_typical(self):
        out = vs.session_vwap(np.array([3.0]), np.array([1.0]), np.array([2.0]), np.array([0.0]))
        self.assertEqual(out[0], 2.0)


class TfBars(unittest.TestCase):
    def test_buckets_and_atr(self):
        rows = [(100, 101, 99, 100)] * 390                      # every 1m range is 2
        T = tape([sess(rows), sess(rows)])
        B = vs.tf_bars(T, 5)
        self.assertEqual(len(B.C), 2 * 78)
        self.assertEqual(B.close_min[0], vs.OPEN + 5)
        self.assertEqual((B.first[1], B.last[1]), (5, 9))
        self.assertTrue(np.isnan(B.atr[vs.ATR_N - 2]))
        self.assertAlmostEqual(B.atr[vs.ATR_N - 1], 2.0)

    def test_first_bar_of_a_session_ignores_the_gap(self):
        a = sess([(100, 101, 99, 100)] * 390)
        b = sess([(200, 201, 199, 200)] * 390)
        B = vs.tf_bars(tape([a, b]), 1)
        self.assertAlmostEqual(B.atr[390 + vs.ATR_N - 1], 2.0)  # a session's ATR has no 100-point gap in it
        self.assertAlmostEqual(B.atr[390], 2.0)

    def test_missing_minutes_do_not_shift_buckets(self):
        s = sess([(100, 101, 99, 100)] * 390)
        keep = np.r_[0:3, 5:390]                                 # 09:33 and 09:34 missing
        s = {k: (v[keep] if isinstance(v, np.ndarray) else v) for k, v in s.items()}
        B = vs.tf_bars(tape([s]), 5)
        self.assertEqual((B.first[0], B.last[0], B.first[1]), (0, 2, 3))
        self.assertEqual(B.close_min[1], vs.OPEN + 10)


def selloff(depth=12.0, bounce=None):
    """Quiet until 10:30 (1m range 1, so 5m ATR ~1), then a drop of `depth` over 10 minutes, then `bounce`."""
    rows = [(100, 100.5, 99.5, 100)] * 60
    px = 100.0
    for _ in range(10):
        rows.append((px, px + 0.25, px - depth / 10 - 0.25, px - depth / 10))
        px -= depth / 10
    for step in bounce or []:
        rows.append((px, max(px, px + step) + 0.25, min(px, px + step) - 0.25, px + step))
        px += step
    return sess(rows)


class Signal(unittest.TestCase):
    def test_buys_the_stretch_and_targets_vwap(self):
        T = tape([selloff(bounce=[0.5] * 30)] * 3)
        B = vs.tf_bars(T, 5)
        tr = vs.run_cell(T, B, dict(tf=5, target="vwap", stop="none"))
        self.assertGreaterEqual(len(tr), 1)
        t = tr[0]
        k = int(np.flatnonzero(B.last == t["j"] - 1)[0])
        self.assertLessEqual(B.C[k], T.vwap[B.last[k]] - vs.K_ATR * B.atr[k])
        self.assertEqual(t["reason"], "target")
        self.assertGreater(t["tgt_atr"], vs.K_ATR - 0.5)
        self.assertGreater(t["r"], 0)

    def test_no_signal_before_10(self):
        drop = [(100 - i, 100 - i + .25, 99 - i, 99 - i) for i in range(10)]          # 09:45-09:54 down 10
        rows = [(100, 100.25, 99.75, 100)] * 15 + drop + [(90 + 2 * i, 92 + 2 * i, 90 + 2 * i, 92 + 2 * i)
                                                           for i in range(5)] + [(100, 100.25, 99.75, 100)] * 5
        T = tape([sess(rows)])
        for tf in (1, 5):
            self.assertEqual(vs.run_cell(T, vs.tf_bars(T, tf), dict(tf=tf, target="vwap", stop="none")), [])

    def test_stop_one_atr(self):
        T = tape([selloff(bounce=[-0.5] * 20)] * 3)
        tr = vs.run_cell(T, vs.tf_bars(T, 5), dict(tf=5, target="vwap", stop="1atr"))
        self.assertEqual(tr[0]["reason"], "stop")
        self.assertGreater(tr[0]["r"], -1.6)                      # about -1 ATR plus a tick and costs

    def test_one_trade_per_stretch(self):
        T = tape([selloff(bounce=[-0.5] * 40)] * 3)              # stays stretched: a stop, then no re-entry
        tr = vs.run_cell(T, vs.tf_bars(T, 5), dict(tf=5, target="half", stop="1atr"))
        self.assertEqual(len(tr), 3)
        self.assertEqual(len({t["day"] for t in tr}), 3)

    def test_needs_other_sessions_for_the_random_twin(self):
        T = tape([selloff(bounce=[0.5] * 30)])
        self.assertEqual(vs.run_cell(T, vs.tf_bars(T, 5), dict(tf=5, target="vwap", stop="none")), [])

    def test_costs(self):
        T = tape([selloff(bounce=[0.5] * 30)] * 3)
        t = vs.run_cell(T, vs.tf_bars(T, 5), dict(tf=5, target="vwap", stop="none"))[0]
        self.assertLess(t["r"], t["r_gross"])
        self.assertLess(t["r2x"], t["r"])
        self.assertEqual(len(t["r_rand"]), vs.K_RAND)


class Fills(unittest.TestCase):
    def T(self, rows):
        return tape([sess(rows)])

    def test_stop_wins_a_bar_touching_both(self):
        T = self.T([(100, 100, 100, 100), (100, 103, 98, 101)])
        f = vs.fill(T, 1, 1, 100.25, 99.0, 102.0, 389, vs.SLIP, 0.0)
        self.assertEqual((f["reason"], f["amb"]), ("stop", True))
        self.assertAlmostEqual(f["pts"], 98.75 - 100.25)

    def test_gap_through_stop_fills_at_the_open(self):
        T = self.T([(100, 100.5, 99.5, 100), (97, 98, 96, 97.5)])
        f = vs.fill(T, 1, 0, 100.25, 99.0, 104.0, 389, vs.SLIP, 0.0)
        self.assertEqual((f["reason"], f["exit"]), ("stop", 1))
        self.assertAlmostEqual(f["pts"], 96.75 - 100.25)

    def test_target_needs_a_tick_through(self):
        T = self.T([(100, 100, 100, 100), (100, 102, 99.5, 101.5), (101.5, 102.25, 101, 102)])
        f = vs.fill(T, 1, 1, 100.0, 99.0, 102.0, 389, 0.0, 0.0)
        self.assertEqual((f["reason"], f["exit"]), ("target", 2))

    def test_time_exit_at_last_close(self):
        T = self.T([(100, 100.5, 99.5, 100)] * 5)
        f = vs.fill(T, 1, 0, 100.25, 90.0, 110.0, 4, vs.SLIP, 0.0)
        self.assertEqual(f["reason"], "time")
        self.assertAlmostEqual(f["pts"], 99.75 - 100.25)


class RandomWalk(unittest.TestCase):
    """No edge in, no edge out: on a driftless random walk neither twin is beaten and no cell earns gross R."""

    @classmethod
    def setUpClass(cls):
        cls.n = 300
        cls.cells = vs.run_cells(vs.build_tape(random_walk(cls.n), 50.0))

    def test_edges_and_gross_are_noise(self):
        tested = 0
        for name, tr in self.cells.items():
            if len(tr) < 40:
                continue
            tested += 1
            e = np.array([(t["r"] - t["r_flip"]) / 2 for t in tr])
            er = np.array([t["r"] - np.mean(t["r_rand"]) for t in tr])
            g = np.array([t["r_gross"] for t in tr])
            for x in (e, er):
                self.assertLess(abs(x.mean()), 4 * x.std() / np.sqrt(len(x)) + 0.02, name)
            self.assertLess(g.mean(), 4 * g.std() / np.sqrt(len(g)) + 0.02, name)
        self.assertGreaterEqual(tested, 6)

    def test_costs_only_subtract(self):
        for name, tr in self.cells.items():
            for t in tr:
                self.assertLessEqual(t["r"], t["r_gross"] + 1e-9, name)

    def test_score_fields(self):
        name = vs.cell_name(dict(tf=5, target="vwap", stop="1atr"))
        c = vs.score(self.cells[name], self.n)
        self.assertGreater(c["trades"], 60)
        self.assertLess(c["mean_2x"], c["mean"])
        self.assertTrue(0 < c["p_rand"] <= 1 and 0 < c["p_flip"] <= 1)
        self.assertEqual(sum(v["n"] for v in c["by_year"].values()), c["trades"])


class Drift(unittest.TestCase):
    """An up-drift lifts the coin-flip edge of any long, but not the random-time edge: that twin holds drift fixed."""

    def test_random_time_twin_absorbs_drift(self):
        cells = vs.run_cells(vs.build_tape(random_walk(300, seed=5, drift=0.08), 50.0),
                             [dict(tf=5, target="vwap", stop="none")])
        tr = next(iter(cells.values()))
        e = np.array([(t["r"] - t["r_flip"]) / 2 for t in tr])
        er = np.array([t["r"] - np.mean(t["r_rand"]) for t in tr])
        self.assertGreater(e.mean(), 2 * e.std() / np.sqrt(len(e)))
        self.assertLess(abs(er.mean()), 4 * er.std() / np.sqrt(len(er)) + 0.02)


class Selection(unittest.TestCase):
    def cell(self, n=80, mean=0.1, m2=0.05, ef=0.02, er=0.02, pr=0.05):
        return dict(trades=n, mean=mean, mean_2x=m2, edge_flip=ef, edge_rand=er, p_rand=pr)

    def res(self, spy, qqq):
        names = [vs.cell_name(p) for p in vs.GRID]
        return dict(SPY=dict(cells={n: dict(trades=0) for n in names} | spy),
                    QQQ=dict(cells={n: dict(trades=0) for n in names} | qqq))

    def test_needs_both_and_every_condition(self):
        a, b = vs.cell_name(vs.GRID[0]), vs.cell_name(vs.GRID[5])
        chosen = vs.select(self.res({a: self.cell(), b: self.cell(mean=0.3)}, {a: self.cell(), b: self.cell(m2=-0.01)}))
        self.assertEqual(chosen["cell"], a)
        self.assertIsNone(vs.select(self.res({a: self.cell(n=59)}, {a: self.cell()})))
        self.assertIsNone(vs.select(self.res({a: self.cell(er=-0.01)}, {a: self.cell()})))
        self.assertIsNone(vs.select(self.res({a: self.cell()}, {a: self.cell(ef=0.0)})))
        self.assertIsNone(vs.select(self.res({a: self.cell(pr=0.2)}, {a: self.cell()})))


class OneLook(unittest.TestCase):
    def test_spec_hash_pinned(self):
        self.assertEqual(vs.script_sha(), SPEC_SHA)

    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["x", *args]):
            return vs.main()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(vs, "OUT", self.dir), mock.patch.object(vs, "PREREG", self.dir / "prereg.json"),
                        mock.patch.object(vs, "LOOKS", self.dir / "looks.log")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_refuses_a_second_look(self):
        vs.LOOKS.write_text("script=x sessions=1 at now\n")
        self.assertEqual(self.run_main("--confirm"), 1)

    def test_refuses_without_freeze(self):
        self.assertEqual(self.run_main("--confirm"), 1)

    def test_refuses_a_changed_spec(self):
        vs.PREREG.write_text(json.dumps(dict(script_sha="stale", selected=None)))
        self.assertEqual(self.run_main("--confirm"), 1)
        self.assertFalse(vs.LOOKS.exists())

    def test_nothing_selected_leaves_futures_unread(self):
        vs.PREREG.write_text(json.dumps(dict(script_sha=vs.script_sha(), selected=None)))
        with mock.patch.object(vs, "load_fut", side_effect=AssertionError("futures read")):
            self.assertEqual(self.run_main("--confirm"), 0)
        self.assertFalse(vs.LOOKS.exists())

    def test_partial_download_does_not_spend_the_look(self):
        p = vs.GRID[0]
        vs.PREREG.write_text(json.dumps(dict(script_sha=vs.script_sha(), selected=dict(cell=vs.cell_name(p), params=p))))
        few = {date(2012, 1, 3) + timedelta(days=i): None for i in range(300)}
        with mock.patch.object(vs, "load_fut", return_value=few):
            self.assertEqual(self.run_main("--confirm"), 1)
        self.assertFalse(vs.LOOKS.exists())

    def test_coverage(self):
        self.assertEqual(len(vs.coverage_problems({})), 10)


if __name__ == "__main__":
    unittest.main()
