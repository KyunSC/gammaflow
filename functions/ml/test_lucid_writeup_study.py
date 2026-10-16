"""Offline checks for lucid_writeup_study on hand-built bars."""
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

import lucid_writeup_study as lw

TICK = lw.TICK


def session(closes, vol=100.0, spread=0.25):
    """390 RTH 1m bars from 09:30; each bar opens at the previous close."""
    c = np.asarray(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame(dict(open=o, high=np.maximum(o, c) + spread, low=np.minimum(o, c) - spread, close=c,
                             volume=np.full(len(c), vol), minute=np.arange(lw.OPEN, lw.OPEN + len(c))))


def arr(g):
    return lw.arrays(g, 1.0)


class Orb(unittest.TestCase):
    def test_breakout_long_with_midpoint_stop(self):
        c = [100.0] * 15 + [100.5] + [101.5] * 374                     # range 99.75-100.25 (+ spread)
        O, H, L, C, m, v, vwap = arr(session(c))
        d, j, stop_d = lw.orb_signal(O, H, L, C, m, vwap)
        self.assertEqual((d, j), (1, 16))                              # 09:45 bar closes above -> enter 09:46
        mid = (H[:15].max() + L[:15].min()) / 2
        self.assertAlmostEqual(stop_d, round((O[16] + TICK - mid) / TICK) * TICK)

    def test_needs_vwap_side(self):
        # breaks above the range but closes below a VWAP dragged up by a heavy early spike bar
        c = [100.0] * 15 + [100.5] * 375
        g = session(c)
        g.loc[3, ["high", "close"]] = [110.0, 100.0]
        g.loc[3, "volume"] = 1e6
        O, H, L, C, m, v, vwap = arr(g)
        self.assertIsNone(lw.orb_signal(O, H, L, C, m, vwap))

    def test_vwap_exit_next_open(self):
        c = [100.0] * 15 + [101.0] * 20 + [99.0] * 355                  # collapses below VWAP at 10:05
        O, H, L, C, m, v, vwap = arr(session(c, spread=0.0))
        t = lw.manage(O, H, L, C, m, 1, 16, 5.0, 2.0, lw.FLAT, vwap)
        self.assertEqual(t["reason"], "vwap")
        self.assertAlmostEqual(t["gross"], ((99.0 - TICK) - (101.0 + TICK)) * 2.0 * t["contracts"])

    def test_stop_gap_fills_at_open(self):
        g = session([100.0] * 20 + [90.0] * 370, spread=0.0)
        g.loc[20, ["open", "high"]] = 90.0                             # gaps through the 98 stop
        O, H, L, C, m, v, vwap = arr(g)
        t = lw.manage(O, H, L, C, m, 1, 5, 2.0, 2.0, lw.FLAT)
        self.assertEqual(t["reason"], "stop")
        self.assertAlmostEqual(t["gross"], (90.0 - TICK - (100.0 + TICK)) * 2.0 * t["contracts"])


class Itsm(unittest.TestCase):
    def test_features_and_time_exit(self):
        c = np.linspace(100, 103, 390)
        O, H, L, C, m, v, vwap = arr(session(c, spread=0.0))
        f = lw.itsm_features(O, H, L, C, m, prev_close=99.0)
        self.assertGreater(f["r1"], 0)
        self.assertGreater(f["r12"], 0)
        self.assertEqual(m[f["entry"]], lw.B_ENTRY)
        t = lw.manage(O, H, L, C, m, 1, f["entry"], 1.0, 5.0, lw.B_EXIT)
        exit_bar = lw.bar_at(m, lw.B_EXIT)
        self.assertEqual(t["reason"], "time")
        self.assertAlmostEqual(t["gross"], ((O[exit_bar] - TICK) - (O[f["entry"]] + TICK)) * 5.0 * t["contracts"])

    def test_skip_when_risk_too_wide(self):
        O, H, L, C, m, v, vwap = arr(session([100.0] * 390))
        self.assertIsNone(lw.manage(O, H, L, C, m, 1, 300, 2 * lw.RISK_USD / 5.0 + 1, 5.0, lw.B_EXIT))


class Build(unittest.TestCase):
    def sessions(self, n, seed=0):
        rng = np.random.default_rng(seed)
        out, d, px = {}, date(2023, 1, 2), 400.0
        for _ in range(n):
            c = px + np.cumsum(rng.normal(0, 0.05, 390))
            out[d] = session(c, vol=float(rng.integers(50, 150)))
            px = c[-1]
            d += timedelta(days=1)
        return out

    def test_warmup_and_no_lookahead(self):
        s = self.sessions(40)
        rows = lw.build(s, "SPY")
        # r1 needs a prior close, so the move filter is the last to warm up: MOVE_N + 1 sessions
        self.assertEqual(len(rows["itsm"]), 40 - max(lw.RVOL_N, lw.ATR_N, lw.MOVE_N + 1))
        days = sorted(s)
        changed = dict(s)
        changed[days[-1]] = session(np.full(390, 1.0))                 # rewrite the last day
        rows2 = lw.build(changed, "SPY")
        for rule in rows:
            for d in days[:-1]:
                self.assertEqual(rows[rule].get(d) is None, rows2[rule].get(d) is None)
                if rows[rule].get(d):
                    self.assertEqual(rows[rule][d]["long"]["pnl"], rows2[rule][d]["long"]["pnl"])

    def test_filtered_orb_is_subset(self):
        rows = lw.build(self.sessions(60, seed=3), "QQQ")
        f = {d for d, r in rows["orb15"].items() if r}
        u = {d for d, r in rows["orb15_unfiltered"].items() if r}
        self.assertTrue(f <= u)


class Verdict(unittest.TestCase):
    def s(self, ev, lo, p=0.001):
        return dict(trades=100, lucid=dict(pro=dict(ev=ev)), mean_r_ci=[lo, lo + 0.2], random=dict(p=p))

    def test_rules(self):
        self.assertEqual(lw.verdict(self.s(-5, 0.1), True), "FAIL")
        self.assertEqual(lw.verdict(self.s(50, 0.01), True), "PASS")
        self.assertEqual(lw.verdict(self.s(50, 0.01, p=0.03), True), "STRUCTURE-ONLY")   # p above 0.05 / 4
        self.assertEqual(lw.verdict(self.s(50, 0.01, p=0.03), False), "PASS")
        self.assertEqual(lw.verdict(self.s(50, -0.01), False), "STRUCTURE-ONLY")


if __name__ == "__main__":
    unittest.main()
