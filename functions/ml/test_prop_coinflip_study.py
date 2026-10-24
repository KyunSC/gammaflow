"""Offline checks for prop_coinflip_study on hand-built days."""
import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

import prop_coinflip_study as pc

A = pc.A_PTS
R = pc.TOPSTEP_50K


def days(long_x, long_mae=None, short_mae=None):
    """Days where the long earns long_x points and the short the mirror; both resolve when |x| = A."""
    x = np.asarray(long_x, float)
    lm = np.minimum(x, 0) if long_mae is None else np.asarray(long_mae, float)
    sm = np.minimum(-x, 0) if short_mae is None else np.asarray(short_mae, float)
    dates = pd.bdate_range("2020-01-01", periods=len(x)).values.astype("datetime64[D]")
    return pc.Days(dates, np.column_stack([x, -x]), np.column_stack([lm, sm]),
                   np.column_stack([x <= -A, -x <= -A]))


def run_fixed(d, side, rules=R):
    """One path that always takes `side` (0 long, 1 short)."""
    return pc.simulate(d, rules, sides=np.full((len(d.dates), 1), side))


class Bracket(unittest.TestCase):
    def test_target_stop_and_close(self):
        # long target on bar 2 after a 10-point dip; short is stopped on that bar
        bars = np.array([[-10, 5, 0], [-2, 8, 6], [5, 26, 20]], float)
        x, mae, stop = pc.bracket_from_path(bars)
        self.assertEqual((x[0], mae[0], stop[0]), (A, -10, False))
        self.assertEqual((x[1], mae[1], stop[1]), (-A, -A, True))
        # neither level: exit at the last close
        x, mae, stop = pc.bracket_from_path(np.array([[-3, 4, 1], [-1, 6, 2]], float))
        self.assertEqual(tuple(x), (2, -2))
        self.assertEqual(tuple(mae), (-3, -6))

    def test_bar_spanning_both_levels_stops_both_sides(self):
        x, _, stop = pc.bracket_from_path(np.array([[-30, 30, 0]], float))
        self.assertEqual(tuple(x), (-A, -A))
        self.assertTrue(stop.all())

    def test_brownian_days_mirror_and_bounds(self):
        dates = pd.bdate_range("2020-01-01", periods=400)
        d = pc.brownian_days(dates, np.full(400, 40.0), seed=3)
        np.testing.assert_allclose(d.x[:, 1], -d.x[:, 0])
        self.assertTrue((np.abs(d.x) <= A + 1e-9).all())
        self.assertTrue((d.mae <= 1e-12).all() and (d.mae >= -A).all())
        self.assertTrue((d.mae <= np.minimum(d.x, 0) + 1e-9).all())
        self.assertGreater(d.resolved_share, .5)


class Account(unittest.TestCase):
    def test_own_money_is_commission_only_when_every_day_resolves(self):
        dates = pc.session_dates("2020-01-01", "2021-01-01")
        d = pc.brownian_days(dates, np.full(len(dates), 2000.0), seed=1)
        self.assertEqual(d.resolved_share, 1.0)
        res = pc.simulate(d, R, n_paths=4000, seed=2)
        # mean of +-400 coin flips is ~0; the commission is exact
        self.assertAlmostEqual(res["own"].mean() / len(dates), -R.commission, delta=400 / np.sqrt(4000) * 3)

    def test_straight_wins_pass_then_pay(self):
        d = days([A] * 30)
        res = run_fixed(d, 0)
        win = A * pc.USD_PER_PT - R.commission           # 390.24
        # 8 wins reach $3,000 -> pass on day 8 (index 7); XFA from day 9: 5 wins -> balance 1,951.2
        self.assertEqual(int(res["passes"][0]), 1)
        self.assertEqual(res["fees"][0], R.monthly + R.activation)
        first = 0.5 * 5 * win
        self.assertGreaterEqual(int(res["payouts"][0]), 2)
        self.assertGreaterEqual(res["pay_gross"][0], first)
        self.assertAlmostEqual(res["pay_net"][0], R.split * res["pay_gross"][0])
        self.assertEqual(int(res["xfa_breaches"][0]), 0)

    def test_five_losses_breach_combine_and_reset_uses_credit(self):
        d = days([-A] * 10)
        res = run_fixed(d, 0)
        # 5 x 409.76 > 2,000: breach on day 5, again on day 10; one free credit, then a paid reset
        self.assertEqual(int(res["attempts"][0]), 3)
        self.assertEqual(res["fees"][0], R.monthly + R.reset)

    def test_intraday_dip_breaches_a_winning_day(self):
        # four losses leave a $360.96 cushion; a winner that first dips 25 points breaches anyway
        d = days([-A] * 4 + [A], long_mae=[-A] * 4 + [-24.9])
        res = run_fixed(d, 0)
        self.assertEqual(int(res["attempts"][0]), 2)
        d = days([-A] * 4 + [A], long_mae=[-A] * 4 + [-10.0])
        self.assertEqual(int(run_fixed(d, 0)["attempts"][0]), 1)

    def test_floor_after_payout(self):
        # pass (8 wins); XFA W W L W W W -> peak 1,541.44, payout 770.72; then 2 losses -> -48.80:
        # the $0 floor breaches, a floor still trailing the peak (-458.56) does not
        x = [A] * 8 + [A, A, -A, A, A, A] + [-A] * 2
        zero = run_fixed(days(x), 0)
        trail = run_fixed(days(x), 0, replace(R, mll_zero_after_payout=False))
        self.assertEqual(int(zero["payouts"][0]), 1)
        self.assertEqual(int(zero["xfa_breaches"][0]), 1)
        self.assertEqual(int(trail["xfa_breaches"][0]), 0)


if __name__ == "__main__":
    unittest.main()
