"""Offline checks for prop_survey_study on hand-built bars and on random-walk sessions."""
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

import amt_lucid_study as amt
import prop_survey_study as ps

T = amt.TICK


def bars(rows, start=amt.OPEN):
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.arange(start, start + len(a))


class GapFill(unittest.TestCase):
    def test_gap_up_shorts_to_prior_close(self):
        # prior close 1000, opens 1001.5 (+0.15%), first 5 minutes stay above 1000
        rows = [(1001.5, 1002, 1001, 1001.5)] * 5 + [(1001.5, 1001.75, 1001, 1001.25)] * 400
        O, H, L, C, m = bars(rows)
        d, j, sd, td = ps.signal_gap_fill(1000.0, O, H, L, C, m)
        self.assertEqual((d, j), (-1, 5))
        self.assertEqual(td, 1001.5 - T - 1000.0)
        self.assertEqual(sd, td)                                   # 1:1 under the 0.20% cap

    def test_filled_in_first_five_minutes_is_skipped(self):
        rows = [(1001.5, 1002, 999.75, 1001)] * 5 + [(1001, 1001.5, 1000.5, 1001)] * 400
        O, H, L, C, m = bars(rows)
        self.assertIsNone(ps.signal_gap_fill(1000.0, O, H, L, C, m))

    def test_gap_too_large_or_small(self):
        rows = [(1003, 1004, 1002.5, 1003)] * 405                    # +0.30%
        self.assertIsNone(ps.signal_gap_fill(1000.0, *bars(rows)))
        rows = [(1000.25, 1000.75, 1000.25, 1000.5)] * 405           # +0.025%
        self.assertIsNone(ps.signal_gap_fill(1000.0, *bars(rows)))


class Sweep(unittest.TestCase):
    def test_sweep_of_high_fades_short(self):
        # prior range 990-1010; bar 10 trades to 1011, bar 12 closes back at 1009
        rows = [(1000, 1001, 999, 1000)] * 10 + [(1009, 1011, 1008, 1010.5), (1010.5, 1010.75, 1009.5, 1010.25),
                                                 (1010.25, 1010.5, 1008.75, 1009)] + [(1009, 1009.5, 1008, 1008.5)] * 400
        O, H, L, C, m = bars(rows)
        d, j, sd, td = ps.signal_sweep(1010.0, 990.0, O, H, L, C, m)
        self.assertEqual((d, j), (-1, 13))
        self.assertEqual(sd, 1011 + T - (1009 - T))
        self.assertEqual(td, round(2 * sd / T) * T)

    def test_accepted_break_is_no_sweep(self):
        # trades above 1010 and stays above for SWEEP_BARS bars, then comes back: spent, no trade
        rows = [(1000, 1001, 999, 1000)] * 10 + [(1010.5, 1012, 1010.25, 1011)] * ps.SWEEP_BARS + \
               [(1011, 1011, 1008, 1008.5)] * 400
        self.assertIsNone(ps.signal_sweep(1010.0, 990.0, *bars(rows)))

    def test_open_outside_range_is_skipped(self):
        rows = [(1012, 1013, 1009, 1009.5)] * 400
        self.assertIsNone(ps.signal_sweep(1010.0, 990.0, *bars(rows)))


class VwapFade(unittest.TestCase):
    def test_stretch_below_vwap_buys_toward_vwap(self):
        # 15 flat 5m bars (range 1) around 1000, then a drop to 997 -> dev = -3 ATR
        rows = [(1000, 1000.5, 999.5, 1000)] * 75 + [(1000, 1000, 997, 997)] * 5 + [(997, 997.5, 996.5, 997)] * 300
        O, H, L, C, m = bars(rows)
        V = np.ones(len(m))
        d, j, sd, td = ps.signal_vwap_fade(O, H, L, C, V, m)
        self.assertEqual((d, j), (1, 80))
        entry = 997 + T
        self.assertEqual(sd, 1.0)                                  # 1 ATR stop
        self.assertGreater(td, 2.0)                                # target near VWAP (~1000) - 0.2 ATR

    def test_no_signal_before_atr_history(self):
        rows = [(1000, 1000, 990, 990)] * 30 + [(990, 990.5, 989.5, 990)] * 300
        O, H, L, C, m = bars(rows)
        sig = ps.signal_vwap_fade(O, H, L, C, np.ones(len(m)), m)
        self.assertTrue(sig is None or m[sig[1]] >= amt.OPEN + 5 * (ps.ATR_N + 1))


def random_walk_sessions(n: int, seed: int) -> dict:
    """RTH 1m sessions of a driftless random walk (SPY-like prices), each opening near the prior close."""
    rng = np.random.default_rng(seed)
    out, px, d = {}, 450.0, date(2022, 1, 3)
    idx_min = np.arange(amt.OPEN, amt.CLOSE)
    while len(out) < n:
        if d.weekday() < 5:
            px *= np.exp(rng.normal(0, 0.003))                     # overnight gap
            steps = rng.normal(0, 0.0006, len(idx_min))
            c = px * np.exp(np.cumsum(steps))
            o = np.r_[px, c[:-1]]
            wig = np.abs(rng.normal(0, 0.0003, (2, len(c)))) * c
            h, lo = np.maximum(o, c) + wig[0], np.minimum(o, c) - wig[1]
            ts = pd.DatetimeIndex([pd.Timestamp(d, tz=amt.ET) + pd.Timedelta(minutes=int(x)) for x in idx_min])
            out[d] = pd.DataFrame(dict(open=o, high=h, low=lo, close=c, volume=rng.integers(1000, 5000, len(c)).astype(float),
                                       day=d, minute=idx_min), index=ts)
            px = c[-1]
        d += timedelta(days=1)
    return out


class NullCheck(unittest.TestCase):
    """On a random walk no rule has an edge, so none may beat the coin flip; the coin flip itself must be near 0R."""

    def test_random_walk_has_no_winner(self):
        sessions = random_walk_sessions(260, seed=7)
        rows = ps.build_rows(sessions, "SPY")
        plans = ps.resolved_plans()
        traded = 0
        for name, r in rows.items():
            s = ps.score(r, plans, n_random=60, boot_paths=400, control_paths=200)
            if "plans" not in s:
                continue
            traded += 1
            for plan in plans:
                self.assertNotEqual(ps.verdict(s, plan), "BEATS-COIN-FLIP", name)
            self.assertLess(s["trades"]["mean_r"], 0.25, name)     # costs and slippage make it negative on average
        self.assertGreaterEqual(traded, 5)

    def test_coin_rows_have_a_trade_every_session(self):
        sessions = random_walk_sessions(20, seed=1)
        rows = ps.build_rows(sessions, "QQQ")
        self.assertTrue(all(v is not None for v in rows["coin_1to1"].values()))
        scalp = [v for v in rows["coin_scalp"].values()]
        self.assertTrue(all(v["long"]["rr"] < 0.5 for v in scalp))


if __name__ == "__main__":
    unittest.main()
