"""legacy/test_mfp_crypto_study.py ported unchanged against eval.engine (review finding 5). Dropped: the C5 test and
the spec-grid/hash tests, which need the MFP spec table; the cost-fixture test is kept without them."""
import unittest

import numpy as np
import pandas as pd

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval import engine as st  # noqa: E402
from strategies.c4 import signals_c4  # noqa: E402

st.signals_c4 = signals_c4

T0 = int(pd.Timestamp("2021-03-01", tz="UTC").timestamp())  # a Monday


def market(close, high=None, low=None, open_=None, t0=T0, drop=(), symbol="BTCUSDT", volume=None):
    c = np.asarray(close, float)
    o = c if open_ is None else np.asarray(open_, float)
    h = np.maximum(o, c) if high is None else np.asarray(high, float)
    lo = np.minimum(o, c) if low is None else np.asarray(low, float)
    t = t0 + 60 * np.arange(len(c))
    keep = np.setdiff1d(np.arange(len(c)), list(drop))
    df = pd.DataFrame(dict(time=t, open=o, high=h, low=lo, close=c, volume=np.ones(len(c)) if volume is None else volume))
    return st.Market(symbol, df.iloc[keep].reset_index(drop=True))


def flat_walk(n, p=50000.0):
    return np.full(n, p)


class Execution(unittest.TestCase):
    def test_stop_cost_arithmetic(self):
        # Price falls 1% over 10 bars: a long with a 0.5% stop exits at the stop, a short at its target.
        px = np.r_[np.full(5, 50000.0), np.linspace(50000, 49500, 10), np.full(200, 49500.0)]
        m = market(px, open_=np.r_[px[0], px[:-1]])
        sg = st.Signal(0, 1, 250.0, 250.0, m.n - 1)
        lg, sh = st.simulate(m, 1, sg, 1), st.simulate(m, 1, sg, -1)
        self.assertEqual((lg.reason, sh.reason), ("stop", "target"))
        qty = st.RISK_USD / 250.0
        fee = 3e-4 * qty * (50000 + 49750)
        slip = 0.8e-4 * qty * (50000 + 49750)
        self.assertAlmostEqual(lg.pnl, -qty * 250 - fee - slip, places=6)
        self.assertAlmostEqual(sh.pnl, qty * 250 - fee - slip, places=6)
        self.assertAlmostEqual(lg.r, lg.pnl / st.RISK_USD)

    def test_swap_charged_per_hour_crossed(self):
        m = market(flat_walk(24 * 60 * 2 + 10))
        sg = st.Signal(0, 1, 500.0, None, 24 * 60 + 1)  # held exactly one day of bars from 00:01
        lg = st.simulate(m, 1, sg, 1)
        qty = st.RISK_USD / 500.0
        swap = 24 * 3e-4 / 24 * qty * 50000
        self.assertEqual(lg.reason, "time")
        self.assertAlmostEqual(lg.pnl, -swap - 2 * 3e-4 * qty * 50000 - 2 * 0.8e-4 * qty * 50000, places=6)

    def test_gap_through_stop_fills_at_open_and_stop_wins_ties(self):
        o = np.r_[np.full(3, 100.0), 90.0, np.full(5, 90.0)]
        m = market(o, open_=o)
        lg = st.simulate(m, 1, st.Signal(0, 1, 5.0, 5.0, m.n - 1), 1)
        self.assertEqual(lg.reason, "stop")
        self.assertLess(lg.pnl, -st.RISK_USD * 1.9)  # 10 points against a 5 point stop, plus costs
        # One bar that spans both levels: the stop fills.
        h = np.r_[100, 100, 110, 100, 100.0]
        lo = np.r_[100, 100, 90, 100, 100.0]
        m2 = market(np.full(5, 100.0), high=h, low=lo)
        self.assertEqual(st.simulate(m2, 1, st.Signal(0, 1, 5.0, 5.0, 4), 1).reason, "stop")

    def test_mirror_is_the_reflected_path(self):
        rng = np.random.default_rng(3)
        px = 1000 + np.cumsum(rng.normal(0, 1, 3000))
        up, down = market(px), market(2000 - px)
        sg = st.Signal(0, 1, 15.0, 30.0, 2999)
        a, b = st.simulate(up, 1, sg, 1), st.simulate(down, 1, sg, -1)
        self.assertEqual((a.exit, a.reason), (b.exit, b.reason))

    def test_leverage_cap_trims_size(self):
        m = market(flat_walk(100))
        lg = st.simulate(m, 1, st.Signal(0, 1, 1.0, None, 50), 1)  # $500 on a $1 stop would be $25M notional
        self.assertAlmostEqual(lg.qty * 50000, m.market["leverage"] * st.PLAN["startBalance"])

    def test_trailing_stop_ratchets_at_day_close(self):
        n = 3 * 1440
        px = np.r_[np.linspace(100, 120, 1440), np.full(1440, 120.0), np.linspace(120, 110, 1440)]
        m = market(px)
        lg = st.simulate(m, 1, st.Signal(0, 1, 5.0, None, n - 1, trail=5.0), 1)
        self.assertEqual(lg.reason, "stop")
        self.assertGreater(m.c[lg.exit], 114.5)  # trailed to 120 - 5, not left at the 95 initial stop


class Book(unittest.TestCase):
    def test_next_entry_waits_for_both_mirrors(self):
        px = np.r_[np.full(5, 100.0), np.linspace(100, 104, 20), np.full(100, 104.0)]
        m = market(px)
        sigs = [st.Signal(0, 1, 2.0, 10.0, 60), st.Signal(10, 1, 2.0, 2.0, 80), st.Signal(70, -1, 2.0, 2.0, 120)]
        trades = st.run_book(m, sigs)
        # The short mirror stops out early; the long holds to its time exit at 60, so the bar-10 signal is skipped.
        self.assertEqual([t.entry for t in trades], [1, 71])
        self.assertEqual(trades[0].exit, 60)

    def test_holes_are_flagged(self):
        m = market(flat_walk(400), drop=range(100, 130))
        trades = st.run_book(m, [st.Signal(50, 1, 100.0, None, 200), st.Signal(250, 1, 100.0, None, 300)])
        self.assertEqual([t.holed for t in trades], [True, False])
        self.assertEqual(m.holes()[0]["missing_bars"], 30)

    def test_zero_volume_runs_count_as_holes(self):
        v = np.ones(400)
        v[150:160] = 0
        v[300:302] = 0  # two quiet minutes are not an outage
        m = market(flat_walk(400), volume=v)
        self.assertEqual(m.stale_report()["stale_bars"], 10)
        trades = st.run_book(m, [st.Signal(50, 1, 100.0, None, 200), st.Signal(250, 1, 100.0, None, 350)])
        self.assertEqual([t.holed for t in trades], [True, False])

    def test_book_replays_every_calendar_day_and_matches_cash(self):
        rng = np.random.default_rng(5)
        n = 1440 * 20
        px = 30000 * np.exp(np.cumsum(rng.normal(0, 4e-4, n)))
        m = market(px)
        sigs = [st.Signal(k, 1 if k % 3 else -1, 150.0, 300.0, min(n - 1, k + 1440 * 2)) for k in range(100, n - 3000, 1440 * 3)]
        trades = st.run_book(m, sigs)
        b = st.build_book(m, trades)
        for dirs in (np.ones(len(trades), int), -np.ones(len(trades), int), st.coin_dirs(len(trades), 1)):
            res, time = st.book_result(b, dirs)
            pnl = sum(t.legs[int(d)].pnl for t, d in zip(trades, dirs))
            self.assertAlmostEqual(res["equity"][-1], st.PLAN["startBalance"] + pnl, places=6)
            self.assertTrue(np.all(np.diff(time) >= 0))
            days = set(st.run_prop.__globals__["ny_day"](time).tolist())
            self.assertEqual(len(days), int(m.ny_date[-1] - m.ny_date[0] + 1))
        ev = st.account_ev(b, np.ones(len(trades), int), paths=20)
        self.assertTrue(np.isfinite(ev["ev"]))


    def test_daily_series_has_one_value_per_block_day(self):
        m = market(flat_walk(3 * 1440))
        trades = st.run_book(m, [st.Signal(10, 1, 100.0, None, 100), st.Signal(1500, -1, 100.0, None, 1600)])
        d = st.daily(m, trades, np.array([1.0, 2.0]))
        self.assertEqual(d.tolist(), [1.0, 2.0, 0.0])
        self.assertEqual(st.daily(m, [], np.array([])).tolist(), [0.0, 0.0, 0.0])


class Signals(unittest.TestCase):
    def test_c4_breaks_the_et_open_range(self):
        # 2021-03-01 is EST: 09:30 ET = 14:30 UTC. Build one weekday with a range then an upside break at 10:05 ET.
        n = 1440
        px = np.full(n, 100.0)
        start = 14 * 60 + 30
        px[start:start + 30] = np.tile([99.0, 101.0], 15)
        px[start + 35:] = 102.0
        m = market(px)
        sigs = st.signals_c4(m, stop="opposite", m=2.0)
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual((s.sig, s.side, s.stop, s.target), (start + 35, 1, 3.0, 6.0))
        self.assertEqual(m.ny_min[s.end], 15 * 60 + 59)

    def test_c4_skips_a_range_with_a_hole(self):
        start = 14 * 60 + 30
        px = np.full(1440, 100.0)
        px[start + 35:] = 102.0
        self.assertEqual(st.signals_c4(market(px, drop=[start + 3]), "opposite", 2.0), [])


class TwinTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(11)
        self.rl = rng.normal(0, 1, 600)
        self.rs = -self.rl - 0.15  # costs make both mirrors lose a little

    def test_planted_lookahead_passes_and_coin_fails(self):
        look = np.where(self.rl > self.rs, 1, -1)
        self.assertTrue(st.passes(st.r_test(self.rl, self.rs, look, n_twins=500)))
        rate = np.mean([st.passes(st.r_test(self.rl, self.rs, st.coin_dirs(600, k), n_twins=300, seed=k)) for k in range(60)])
        self.assertLess(rate, 0.15)

    def test_long_share_twins_absorb_drift(self):
        # Every long wins by drift alone: a long-only rule beats the fair coin but not its own-share twins.
        rl, rs = np.full(300, 0.2), np.full(300, -0.3)
        dirs = np.ones(300, int)
        self.assertLess(st.r_test(rl, rs, dirs, p_long=0.5, n_twins=300)["p"], 0.01)
        t = st.r_test(rl, rs, dirs, n_twins=300)
        self.assertAlmostEqual(t["excess"], 0.0)
        self.assertFalse(st.passes(t))


class Costs(unittest.TestCase):
    def test_costs_come_from_the_js_fixture(self):
        self.assertEqual(st.MARKETS["BTC"]["commissionBps"], 3)
        self.assertEqual(st.MARKETS["BTC"]["swapDailyBps"], 3)
        self.assertEqual(st.slip_bps(st.MARKETS["BTC"], 50e3), 0.8)
        self.assertEqual(st.slip_bps(st.MARKETS["BTC"], 2e6), 2)
        self.assertEqual(st.PLAN["dailyLossLimit"], 1500)


if __name__ == "__main__":
    unittest.main()
