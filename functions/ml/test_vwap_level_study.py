"""Offline checks for vwap_level_study on hand-built bars, a random walk (no level effect) and a planted VWAP barrier."""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

import vwap_level_study as vl

SPEC_SHA = "ce0d36f6b0613926"   # vl.script_sha(); any edit to the spec (or amt_lucid_study.py) must update this visibly


def sess(rows):
    """rows of (h, l, c, volume) from 09:30, padded with flat bars at the last close to 16:00."""
    c = rows[-1][2]
    rows = rows + [(c, c, c, 1.0)] * (390 - len(rows))
    a = np.array(rows, float)
    return dict(H=a[:, 0], L=a[:, 1], C=a[:, 2], V=a[:, 3], m=np.arange(vl.OPEN, vl.OPEN + 390))


def quiet_morning():
    """09:30-10:39 inside 99.5-100.5 with heavy volume: A = 1 (5m range), VWAP pinned near 100 afterwards."""
    return [(100.5, 99.5, 100.0, 1000.0)] * 70


def after(path):
    """1m bars from 10:40 that walk through `path` (close prices), each bar spanning prev close -> close, light volume."""
    rows, px = [], 100.0
    for c in path:
        rows.append((max(px, c), min(px, c), c, 1.0))
        px = c
    return rows


def walk(n, seed=3, vol=0.08, sub=12, drift=0.0, drift_sd=0.0, barrier=0.0, hold=15):
    """RTH sessions of a fat-tailed random walk, with a per-minute drift of `drift` plus, per session, N(0, drift_sd)
    (trend days both ways). With `barrier` > 0, a planted VWAP effect: when price, after closing a
    minute at least ARM x A from the VWAP of the completed minutes, first reaches that VWAP, then with probability
    `barrier` the VWAP holds (every crossing is reflected) for the next `hold` minutes. The shifted copies get nothing.
    (A wall that always reflects is a different thing: price clings to VWAP, leaks through and then clings on the other
    side, so it breaks more often than a free walk. That is pinning, and the statistic reads it as negative.)"""
    rng = np.random.default_rng(seed)
    out, d, px = {}, date(2023, 1, 2), 100.0
    m = np.arange(vl.OPEN, vl.CLOSE)
    while len(out) < n:
        if d.weekday() < 5:
            px += rng.normal(0, vol * 4)
            H, L, C, V = (np.empty(len(m)) for _ in range(4))
            V[:] = rng.gamma(2, 500, len(m))
            pv = vsum = 0.0
            x, A, armed, until = px, None, 0, -1
            mu = drift + (rng.normal(0, drift_sd) if drift_sd else 0.0)
            for i in range(len(m)):
                lvl = pv / vsum if vsum else None
                if barrier and i == vl.A_READY - vl.OPEN:
                    A = vl.session_atr(dict(H=H[:i], L=L[:i], C=C[:i], m=m[:i]))
                steps = rng.standard_t(4, sub) * vol / np.sqrt(sub) + mu / sub
                hi = lo = x
                for st in steps:
                    y = x + st
                    if lvl is not None and (x - lvl) * (y - lvl) <= 0:
                        if armed:
                            armed = 0
                            if rng.random() < barrier:
                                until = i + hold
                        if i < until:
                            y = 2 * lvl - y
                    x = y
                    hi, lo = max(hi, x), min(lo, x)
                if A and lvl is not None and abs(x - lvl) >= vl.ARM * A:
                    armed = 1
                H[i], L[i], C[i] = hi, lo, x
                pv += (hi + lo + x) / 3 * V[i]
                vsum += V[i]
            out[d] = dict(H=H, L=L, C=C, V=V, m=m)
            px = x
        d += timedelta(days=1)
    return out


class Levels(unittest.TestCase):
    def test_vwap_and_twap(self):
        H, L, C, V = (np.array(x, float) for x in ([3, 6], [1, 4], [2, 5], [1, 3]))
        np.testing.assert_allclose(vl.session_vwap(H, L, C, V), [2.0, (2 * 1 + 5 * 3) / 4])
        np.testing.assert_allclose(vl.session_twap(H, L, C), [2.0, 3.5])

    def test_atr_is_14_five_minute_bars_through_1040(self):
        s = sess(quiet_morning() + after([100.0] * 10))
        self.assertAlmostEqual(vl.session_atr(s), 1.0)
        s["H"][70:] += 50                                          # bars from 10:40 do not enter A
        self.assertAlmostEqual(vl.session_atr(s), 1.0)

    def test_atr_needs_14_bars(self):
        s = sess(quiet_morning())
        keep = np.flatnonzero(s["m"] >= vl.OPEN + 10)               # 09:30-09:39 missing: 12 buckets by 10:40
        s = {k: v[keep] for k, v in s.items()}
        self.assertTrue(np.isnan(vl.session_atr(s)))

    def test_shifts_are_vwap_plus_constant(self):
        s = walk(1)[date(2023, 1, 2)]
        lv = vl.levels(s, 2.0)
        for k, name in zip(vl.SHIFTS, vl.PLACEBOS):
            np.testing.assert_allclose(lv[name] - lv["vwap"], 2.0 * k)


def vwap_touches(path):
    s = sess(quiet_morning() + after(path))
    A = vl.session_atr(s)
    return vl.touches(s, vl.levels(s, A)["vwap"], A)


class Touches(unittest.TestCase):
    up = [100.2, 100.6, 100.8, 100.8, 100.8, 100.6, 100.3]       # armed from above at 10:41, back near VWAP by 10:46

    def test_reject(self):
        t = vwap_touches(self.up + [100.0, 100.4, 100.8, 101.1])
        self.assertEqual(len(t), 1)
        i, side, _, res = t[0]
        self.assertEqual((side, res), (1, vl.REJECT))
        self.assertEqual(i, 70 + len(self.up))

    def test_break(self):
        self.assertEqual(vwap_touches(self.up + [100.0, 99.6, 99.2, 98.9])[0][3], vl.BREAK)

    def test_break_on_the_touch_bar(self):
        t = vwap_touches(self.up + [98.8, 101.2])
        self.assertEqual(t[0][3], vl.BREAK)

    def test_ambiguous_and_unresolved(self):
        s = sess(quiet_morning() + after(self.up + [100.0]) + [(101.5, 98.5, 100.0, 1.0)])
        A = vl.session_atr(s)
        self.assertEqual(vl.touches(s, vl.levels(s, A)["vwap"], A)[0][3], vl.AMBIG)
        self.assertEqual(vwap_touches(self.up + [100.0])[0][3], vl.OPEN_)

    def test_not_armed_no_touch(self):
        self.assertEqual(vwap_touches([100.2, 100.3, 100.1, 100.0, 100.4, 101.2]), [])

    def test_no_touch_before_1045(self):
        t = vwap_touches([100.6, 100.0, 101.2] + [101.2] * 5 + [100.0, 101.2])
        self.assertTrue(all(vl.OPEN + 70 + 5 <= i + vl.OPEN for i, *_ in t))
        self.assertEqual(len(t), 1)

    def test_level_is_previous_bar_close(self):
        s = sess(quiet_morning() + after(self.up + [100.0, 101.2]))
        A = vl.session_atr(s)
        lv = vl.levels(s, A)["vwap"].copy()
        i = vl.touches(s, lv, A)[0][0]
        lv[i] = 150.0                                              # the touch bar's own level is never used
        self.assertEqual(vl.touches(s, lv, A)[0][0], i)

    def test_strata(self):
        self.assertNotEqual(vl.stratum(1, 650, True), vl.stratum(-1, 650, True))
        self.assertNotEqual(vl.stratum(1, 650, True), vl.stratum(1, 650, False))
        self.assertNotEqual(vl.stratum(1, 650, True), vl.stratum(1, 800, True))
        self.assertEqual(len({vl.stratum(s, m, f) for s in (1, -1) for m in (650, 800, 900) for f in (0, 1)}),
                         vl.N_STRATA)


class Scoring(unittest.TestCase):
    def test_delta_weights_by_vwap_strata(self):
        cnt = np.zeros((len(vl.LEVELS), vl.N_STRATA, 4))
        cnt[0, 0, :2] = (60, 40)                                   # VWAP 0.60 in stratum 0
        cnt[0, 1, :2] = (10, 10)                                   # VWAP 0.50 in stratum 1
        cnt[1:5, 0, :2] = (50, 50)                                 # shifts 0.50 everywhere
        cnt[1:5, 1, :2] = (50, 50)
        self.assertAlmostEqual(vl.delta(cnt), (100 * 0.10 + 20 * 0.0) / 120)

    def test_empty_strata_drop_out(self):
        cnt = np.zeros((len(vl.LEVELS), vl.N_STRATA, 4))
        cnt[0, 0, :2] = (6, 4)
        cnt[0, 2, :2] = (9, 1)                                     # no shift touches in stratum 2
        cnt[1:5, 0, :2] = (5, 5)
        self.assertAlmostEqual(vl.delta(cnt), 0.1)


class Synthetic(unittest.TestCase):
    """The gate must stay shut on a walk with no level effect (with or without drift) and open on a planted barrier."""

    @classmethod
    def setUpClass(cls):
        cls.flat = vl.run(walk(500, seed=1))
        cls.drift = vl.run(walk(400, seed=2, drift=0.0008))          # ~4x an index's daily drift / sd, every day
        cls.trends = vl.run(walk(400, seed=5, drift_sd=0.004))       # strong trend days, up and down
        cls.planted = vl.run(walk(250, seed=1, barrier=0.3))

    def test_no_effect_on_a_random_walk(self):
        for r in (self.flat, self.drift, self.trends):
            self.assertLess(abs(r["delta"]), vl.MIN_EFFECT, r["delta"])
            self.assertFalse(r["passed"])
            self.assertGreater(r["per_level"]["vwap"]["resolved"], 1000)

    def test_planted_barrier_passes(self):
        r = self.planted
        self.assertGreater(r["delta"], 2 * vl.MIN_EFFECT, r["delta"])
        self.assertTrue(r["passed"])
        self.assertGreater(r["by_side"]["from_above"], 0)
        self.assertGreater(r["by_side"]["from_below"], 0)


class OneLook(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(vl, "PREREG", tmp / "prereg.json"),
                        mock.patch.object(vl, "LOOKS", tmp / "looks.log"),
                        mock.patch.object(vl, "OUT", tmp / "out")]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def confirm(self):
        with mock.patch.object(sys, "argv", ["x", "--confirm"]):
            return vl.main()

    def pin(self, **kw):
        vl.PREREG.write_text(json.dumps(dict(script_sha=vl.script_sha(), explore_passed=True, **kw)))

    def test_needs_prereg(self):
        with mock.patch.object(vl, "load_fut") as lf:
            self.assertEqual(self.confirm(), 1)
            lf.assert_not_called()

    def test_hash_change_refused(self):
        vl.PREREG.write_text(json.dumps(dict(script_sha="deadbeef", explore_passed=True)))
        with mock.patch.object(vl, "load_fut") as lf:
            self.assertEqual(self.confirm(), 1)
            lf.assert_not_called()

    def test_failed_exploration_never_reads_futures(self):
        vl.PREREG.write_text(json.dumps(dict(script_sha=vl.script_sha(), explore_passed=False)))
        with mock.patch.object(vl, "load_fut") as lf:
            self.assertEqual(self.confirm(), 0)
            lf.assert_not_called()
        self.assertFalse(vl.LOOKS.exists())

    def test_incomplete_download_does_not_spend_the_look(self):
        self.pin()
        few = {date(2012, 1, 3) + timedelta(days=i): None for i in range(10)}
        with mock.patch.object(vl, "load_fut", return_value=few):
            self.assertEqual(self.confirm(), 1)
        self.assertEqual(vl.looks(), [])

    def test_second_look_refused(self):
        self.pin()
        vl.LOOKS.write_text("script=x sessions=ES:1,NQ:1 at then\n")
        with mock.patch.object(vl, "load_fut") as lf:
            self.assertEqual(self.confirm(), 1)
            lf.assert_not_called()

    def test_look_is_logged_before_scoring(self):
        self.pin()
        full = {}
        d = vl.CONFIRM_START
        while d <= vl.CONFIRM_END:
            if d.weekday() < 5:
                full[d] = None
            d += timedelta(days=1)

        def boom(_):
            self.assertEqual(len(vl.looks()), 1)
            raise RuntimeError("stop")

        with mock.patch.object(vl, "load_fut", return_value=full), mock.patch.object(vl, "run", side_effect=boom):
            with self.assertRaises(RuntimeError):
                self.confirm()


class Spec(unittest.TestCase):
    def test_spec_hash_pinned(self):
        self.assertEqual(vl.script_sha(), SPEC_SHA)


if __name__ == "__main__":
    unittest.main()
