"""The structure model's day table, which the engine reads in a different order from a real bar."""
import unittest

import numpy as np

import lucid_structure as L
from flybrain.prop import resolve_plan, simulate_account


def one_day(pnl, lo, hi, won):
    return dict(pnl=np.array([pnl]), lo=np.array([lo]), hi=np.array([hi]), won=np.array([won]))


def run(d, plan):
    days = L.day_table(d)
    return simulate_account(days, lambda k: 0 if k == 0 else -1, plan)


class DayTable(unittest.TestCase):
    def test_a_winner_is_not_breached_by_its_own_earlier_dip(self):
        # +$2,600 with a -$500 dip on the way: the dip is above the opening floor, so nothing breaches.
        plan = {**resolve_plan("rapid", "50k", True, firm="mff"), "hasEval": False}
        self.assertEqual(run(one_day(2590.0, -500.0, 2600.0, True), plan)["outcome"], "funded-open")

    def test_one_bar_order_would_have_breached_that_day(self):
        plan = {**resolve_plan("rapid", "50k", True, firm="mff"), "hasEval": False}
        d = one_day(2590.0, -500.0, 2600.0, True)
        d["won"] = None
        self.assertEqual(run(d, plan)["outcome"], "funded-breached")

    def test_a_loser_that_ran_past_the_trail_still_breaches(self):
        # Up $2,100 lifts an intraday floor to +$100, so falling to -$1,550 goes through it.
        plan = {**resolve_plan("rapid", "50k", True, firm="mff"), "hasEval": False}
        self.assertEqual(run(one_day(-1560.0, -1560.0, 2100.0, False), plan)["outcome"], "funded-breached")

    def test_two_bars_change_nothing_on_an_eod_plan(self):
        plan = resolve_plan("flex", "50k", True)
        d = L.make_days(3000, 1050, 250, 1.0, seed=5)
        flat = {**d, "won": None}
        self.assertEqual(L.attempts(d, plan, 800), L.attempts(flat, plan, 800))

    def test_multi_trade_days_stay_one_bar(self):
        d = L.make_days(50, 750, 375, 1.0, k=2, seed=5)
        self.assertIsNone(d["won"])
        self.assertEqual(L.day_table(d)["start"], list(range(50)))


if __name__ == "__main__":
    unittest.main()
