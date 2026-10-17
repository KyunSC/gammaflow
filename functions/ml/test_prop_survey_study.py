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


def random_walk_sessions(n: int, seed: int, start: int = ps.PRE_OPEN) -> dict:
    """1m sessions (08:00-15:59 ET by default) of a driftless random walk (SPY-like prices), each opening near the
    prior close."""
    rng = np.random.default_rng(seed)
    out, px, d = {}, 450.0, date(2022, 1, 3)
    idx_min = np.arange(start, amt.CLOSE)
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


class RangeReclaim(unittest.TestCase):
    def setUp(self):
        # 08:00 hour: low 1000, high 1016 (16 points), closes at 1013 (loc 0.81)
        hour = [(1000, 1016, 1000, 1013)] + [(1013, 1014, 1005, 1013)] * 59
        self.hour = hour

    def run_rows(self, after, day=date(2023, 6, 1)):
        O, H, L, C, m = bars(self.hour + after, start=ps.PRE_OPEN)
        return ps.signal_range_reclaim(day, O, H, L, C, m)

    def test_break_reclaim_retest_shorts(self):
        after = [(1013, 1015, 1012, 1014)] * 3 + [(1014, 1017, 1014, 1016.5)] + [(1016.5, 1016.75, 1015, 1015.5)] + \
                [(1015.5, 1015.75, 1014, 1014.5)] * 3 + [(1014.5, 1016.25, 1014, 1015)] + [(1015, 1015.5, 1012, 1013)] * 400
        d, j, sd, td, kw = self.run_rows(after)
        self.assertEqual((d, j - 60), (-1, 9))                    # break bar 3, reclaim bar 4 (1 min), retest bar 8
        self.assertEqual((sd, td, kw["risk"]), (12.0, 12.0, 625.0))
        self.assertEqual(kw["until"], ps.PRE_OPEN + 60 + 9 + 360)

    def test_reclaim_in_blackout_cancels(self):
        after = [(1014, 1017, 1014, 1016.5)] + [(1016.5, 1017, 1016.25, 1016.5)] * 2 + [(1016.5, 1016.75, 1015, 1015.5)] + \
                [(1015.5, 1016.25, 1014, 1015)] * 400                # first close inside 3 minutes after the break
        self.assertIsNone(self.run_rows(after))

    def test_macro_day_and_mid_close_skipped(self):
        after = [(1013, 1017, 1012, 1015.5)] + [(1015.5, 1016.25, 1014, 1015)] * 400
        self.assertIsNone(self.run_rows(after, day=date(2023, 6, 2)))   # NFP
        self.assertIn(date(2023, 5, 31), ps.MACRO)                       # ADP: Wednesday of that week
        self.hour[-1] = (1013, 1014, 1005, 1008)                         # closes at loc 0.5
        self.assertIsNone(self.run_rows(after))


class OrbMid(unittest.TestCase):
    def test_long_with_buffered_midpoint_stop(self):
        rows = [(100, 110, 90, 105)] * 15 + [(105, 109, 104, 108)] * 5 + [(108, 112, 107, 111)] * 5 + [(111, 112, 110, 111)] * 400
        O, H, L, C, m = bars(rows)
        d, j, sd, td, kw = ps.signal_orb15_mid(O, H, L, C, m)
        self.assertEqual((d, j), (1, 25))
        self.assertEqual(sd, 111 + T - 95)                         # midpoint 100 - 5
        self.assertEqual(td, 2 * sd)
        self.assertEqual(kw["risk"], 500.0)


class OrbFvg(unittest.TestCase):
    def test_breakout_with_gap_long_and_wide_stop_target(self):
        rows = [(100, 110, 90, 105)] * 15 + [(105, 106, 104, 105), (105, 109, 105, 108.5), (109, 114, 108, 113)] + \
               [(113, 114, 112, 113)] * 400
        O, H, L, C, m = bars(rows)
        d, j, sd, td = ps.signal_orb_fvg(O, H, L, C, m, wide=30.0)
        self.assertEqual((d, j), (1, 18))
        self.assertEqual(sd, 113 + T - 106)                        # stop at bar[-2].high
        self.assertEqual(td, round(2 * sd / T) * T)
        self.assertEqual(ps.signal_orb_fvg(O, H, L, C, m, wide=5.0)[3], sd)   # wide stop -> 1R

    def test_no_gap_no_trade(self):
        rows = [(100, 110, 90, 105)] * 15 + [(105, 112, 104, 111)] * 3 + [(111, 112, 110, 111)] * 400
        self.assertIsNone(ps.signal_orb_fvg(*bars(rows), wide=30.0))


class ContFvg(unittest.TestCase):
    def test_pullback_into_gap_then_prior_high_break(self):
        # prior range 900-1100, opens 1050 -> magnet is the high, longs only
        rows = [(1050, 1051, 1049, 1050), (1050, 1052, 1049.5, 1051.5), (1053, 1056, 1052, 1055),   # FVG 1051..1052
                (1055, 1055.5, 1051.75, 1052), (1052, 1056, 1051.5, 1055.75)] + [(1055.75, 1056, 1055, 1055.5)] * 400
        O, H, L, C, m = bars(rows)
        self.assertEqual(ps.signal_cont_fvg(1100.0, 900.0, O, H, L, C, m), (1, 5, 20.0, 20.0))

    def test_close_through_far_edge_voids(self):
        rows = [(1050, 1051, 1049, 1050), (1050, 1052, 1049.5, 1051.5), (1053, 1056, 1052, 1055),
                (1055, 1055.5, 1050, 1050.5), (1050.5, 1054, 1050, 1053.5)] + [(1053.5, 1053.75, 1053, 1053.5)] * 400
        self.assertIsNone(ps.signal_cont_fvg(1100.0, 900.0, *bars(rows)))


class ErlIrl(unittest.TestCase):
    def test_high_sweep_then_bearish_gap_limit(self):
        # prior high 1010: the 09:30 hour trades 1012 and closes 1008; 30m bars 3-5 leave a bearish FVG 1000..1003
        rows = [(1005, 1012, 1004, 1008)] * 60 + [(1008, 1008, 1003, 1004)] * 30 + [(1004, 1004, 995, 996)] * 30 + \
               [(996, 1000, 990, 995)] * 30 + [(995, 1000.5, 994, 999)] + [(999, 999, 980, 981)] * 200
        O, H, L, C, m = bars(rows)
        d, j, sd, td, kw = ps.signal_erl_irl(1010.0, 900.0, O, H, L, C, m)
        self.assertEqual((d, j, kw["entry"]), (-1, 150, 1000.0))
        self.assertEqual(sd, 1003 + T - 1000)
        self.assertEqual(td, round(2 * sd / T) * T)

    def test_bracket_uses_limit_price(self):
        rows = [(999, 1003.5, 998, 999)] + [(999, 1000.5, 990, 991)] * 10   # the fill bar's own high is ignored
        O, H, L, C, m = bars(rows)
        t = ps.bracket(O, H, L, C, m, -1, 0, 3.25, 6.5, 2.0, entry=1000.0)
        self.assertEqual(t["reason"], "target")
        self.assertAlmostEqual(t["r"] * 3.25 * 2.0 * t["contracts"],
                               (6.5 * 2.0 - 2 * ps.COMMISSION_SIDE) * t["contracts"])


class PastedWinners(unittest.TestCase):
    def test_impulse_long_with_min_stop_and_10r(self):
        rows = [(1000, 1003, 999, 1002)] * 10 + [(1002, 1004, 1001, 1003)] * 400
        O, H, L, C, m = bars(rows)
        d, j, sd, td, kw = ps.signal_impulse(O, H, L, C, m)
        self.assertEqual((d, j, sd, td, kw["risk"]), (1, 10, 15.0, 150.0, 200.0))   # 1002.25 - 999 < 15 -> 15

    def test_impulse_flat_open_skipped(self):
        rows = [(1000, 1003, 999, 1001.5)] * 10 + [(1001.5, 1002, 1001, 1001.5)] * 400
        self.assertIsNone(ps.signal_impulse(*bars(rows)))

    def test_orb_two_closes(self):
        # range 990-1010 (mid 1000); 09:45 bar closes 1011, 09:50 bar 1012 -> long at 09:55, stop at the midpoint
        rows = [(1000, 1010, 990, 1005)] * 15 + [(1005, 1012, 1004, 1011)] * 5 + [(1011, 1013, 1010, 1012)] * 5 + \
               [(1012, 1013, 1011, 1012)] * 400
        O, H, L, C, m = bars(rows)
        d, j, sd, td, kw = ps.signal_orb_2close(O, H, L, C, m, 2.0)
        self.assertEqual((d, j, sd, td), (1, 25, 1012 + T - 1000, 2 * (1012 + T - 1000)))
        self.assertEqual(ps.signal_orb_2close(O, H, L, C, m, None)[3], ps.NO_TARGET)

    def test_orb_two_closes_needs_both(self):
        rows = [(1000, 1010, 990, 1005)] * 15 + [(1005, 1012, 1004, 1011)] * 5 + [(1011, 1011, 1004, 1006)] * 400
        self.assertIsNone(ps.signal_orb_2close(*bars(rows), 2.0))

    def test_vwap_ema_cross_and_exits(self):
        # below VWAP until 10:00, the 10:00-10:04 bar closes above it, then price rolls over at 10:30
        rows = [(1000, 1000.5, 999, 999.5)] * 30 + [(999.5, 1004, 999.5, 1003.5)] * 5 + \
               [(1003.5, 1006, 1003, 1005.5)] * 25 + [(1005.5, 1005.5, 990, 990.5)] * 400
        O, H, L, C, m = bars(rows)
        V = np.ones(len(m))
        d, j, sd, td, kw = ps.signal_vwap_ema(np.full(78, 1000.0), O, H, L, C, V, m)
        self.assertEqual((d, j), (1, 35))
        self.assertEqual(sd, 15.0)                                 # swing low 999 - 5 is 9.75 away -> the 15 minimum
        self.assertEqual(td, ps.NO_TARGET)
        self.assertEqual(kw["exit_at"][1], 65)                     # first 5m close under EMA9 is the 10:30 bar
        self.assertEqual(kw["exit_at"][-1], 40)                    # the short's twin exits after the next bar

    def test_rule_exit_at_open(self):
        rows = [(1000, 1001, 999, 1000.5)] * 5 + [(1003, 1004, 1002, 1003.5)] * 5
        O, H, L, C, m = bars(rows)
        t = ps.bracket(O, H, L, C, m, 1, 0, 15.0, ps.NO_TARGET, 2.0, risk=200.0, exit_at=5)
        self.assertEqual(t["reason"], "rule")
        self.assertAlmostEqual(t["pnl"], (1003 - T - (1000 + T)) * 2.0 * t["contracts"] - 2 * ps.COMMISSION_SIDE * t["contracts"])


class NullCheck(unittest.TestCase):
    """On a random walk no rule has an edge, so none may beat the coin flip; the coin flip itself must be near 0R."""

    def test_random_walk_has_no_winner(self):
        sessions = random_walk_sessions(260, seed=7)
        plans = ps.resolved_plans()
        traded = 0
        rows = {f"{sym}/{n}": r for sym in ("SPY", "QQQ") for n, r in ps.build_rows(sessions, sym).items()}
        self.assertEqual(len(rows), 2 * len(ps.COINS) + sum(len(v) for v in ps.TESTS.values()))
        for name, r in rows.items():
            s = ps.score(r, plans, n_random=60, boot_paths=400, control_paths=200)
            if "plans" not in s:
                continue
            traded += 1
            for plan in plans:
                self.assertNotEqual(ps.verdict(s, plan), "BEATS-COIN-FLIP", name)
            self.assertLess(s["trades"]["mean_r"], 0.25, name)     # costs and slippage make it negative on average
        self.assertGreaterEqual(traded, len(rows) - 1)                # every rule trades on a random walk

    def test_coin_rows_have_a_trade_every_session(self):
        sessions = random_walk_sessions(20, seed=1)
        rows = ps.build_rows(sessions, "QQQ")
        self.assertTrue(all(v is not None for v in rows["coin_1to1"].values()))
        scalp = [v for v in rows["coin_scalp"].values()]
        self.assertTrue(all(v["long"]["rr"] < 0.5 for v in scalp))


if __name__ == "__main__":
    unittest.main()
