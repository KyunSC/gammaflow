"""Offline checks for amt_lucid_study on hand-built profiles and bars."""
import unittest

import numpy as np

import amt_lucid_study as amt


def bars(rows, start=amt.OPEN):
    """rows of (o, h, l, c) on consecutive minutes from `start`."""
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.arange(start, start + len(a))


class ValueArea(unittest.TestCase):
    def test_poc_and_70pct(self):
        vols = np.array([1, 2, 10, 40, 20, 5, 1, 1], dtype=float)  # total 80, 70% = 56
        lv = amt.value_area(vols, 10000, 1.0)                     # $100.00 base, ratio 1
        self.assertEqual(lv["poc"], 100.0)                       # bin 3 = $100.03 -> 100.0 on the 0.25 tick
        # 40 -> +20 (up) = 60 >= 56: VA is bins 3..4
        self.assertEqual((lv["val"], lv["vah"]), (round(100.03 / .25) * .25, round(100.04 / .25) * .25))

    def test_tie_goes_to_mid(self):
        vols = np.array([5, 1, 1, 1, 5, 1, 1, 1, 1], dtype=float)
        lv = amt.value_area(vols, 0, 100.0)                       # $0.01 bin = 1 point
        self.assertEqual(lv["poc"], 4.0)


class Signals(unittest.TestCase):
    lv = dict(vah=110.0, val=100.0, poc=104.0, high=112.0, low=98.0)

    def test_va_reentry_short_to_far_edge(self):
        # opens above VAH at 112, trades back in: the 09:30-09:59 period closes at 108 (inside)
        rows = [(112, 113, 111, 111)] + [(109, 110, 108, 108)] * 29 + [(108, 108.5, 107, 108)] * 60
        O, H, L, C, m = bars(rows)
        sig = amt.signal_va_reentry(self.lv, O, H, L, C, m, k=1, target="far_edge")
        d, j, sd, td = sig
        self.assertEqual((d, j), (-1, 30))
        self.assertEqual(sd, 113 + amt.TICK - (108 - amt.TICK))  # stop above the session high
        self.assertEqual(td, (108 - amt.TICK) - 100.0)

    def test_va_reentry_needs_k_periods(self):
        rows = [(112, 113, 111, 111)] + [(109, 110, 108, 108)] * 29 + [(111, 112, 110.5, 111)] * 60
        O, H, L, C, m = bars(rows)
        self.assertIsNone(amt.signal_va_reentry(self.lv, O, H, L, C, m, k=2, target="far_edge"))

    def test_ov_accept_long(self):
        rows = [(111, 112, 110.5, 111.5)] * 30 + [(112, 113, 111.5, 112.5)] * 60
        O, H, L, C, m = bars(rows)
        d, j, sd, td = amt.signal_ov_accept(self.lv, O, H, L, C, m, ref="va", rr=2.0)
        self.assertEqual((d, j), (1, 30))
        self.assertEqual(sd, 112 + amt.TICK - (110.5 - amt.TICK))
        self.assertEqual(td, round(2 * sd / amt.TICK) * amt.TICK)

    def test_ov_accept_rejects_return_to_value(self):
        rows = [(111, 112, 109.5, 111.5)] * 30 + [(112, 113, 111.5, 112.5)] * 60
        O, H, L, C, m = bars(rows)
        self.assertIsNone(amt.signal_ov_accept(self.lv, O, H, L, C, m, ref="va", rr=1.0))

    def test_va_fail_fades_probe(self):
        # opens inside, probes above VAH in the first 5m, closes back inside at 109
        rows = [(108, 111, 107.5, 110.5)] * 4 + [(110.5, 110.6, 108.9, 109)] + [(109, 109.5, 108, 108.5)] * 80
        O, H, L, C, m = bars(rows)
        d, j, sd, td = amt.signal_va_fail(self.lv, O, H, L, C, m, p=5, target="poc")
        self.assertEqual((d, j), (-1, 5))
        self.assertEqual(sd, 111 + amt.TICK - (109 - amt.TICK))

    def test_va_fail_accepted_probe_is_no_trade(self):
        rows = [(108, 111, 107.5, 110.8)] * 5 + [(110.8, 111, 108, 108.5)] * 80
        O, H, L, C, m = bars(rows)
        self.assertIsNone(amt.signal_va_fail(self.lv, O, H, L, C, m, p=5, target="poc"))


class Bracket(unittest.TestCase):
    def test_target_needs_tick_through(self):
        # entry 100.25, target 101.25, stop 99.25: three bars only touch the target, then the stop trades
        rows = [(100, 100.5, 99.9, 100.2)] + [(100.2, 101.25, 100, 101)] * 3 + [(101, 101, 99, 99.2)] * 400
        O, H, L, C, m = bars(rows)
        self.assertEqual(amt.bracket(O, H, L, C, m, 1, 0, 1.0, 1.0, 2.0)["reason"], "stop")
        rows[2] = (100.2, 101.5, 100, 101)                         # one tick through -> filled at the target
        O, H, L, C, m = bars(rows)
        t = amt.bracket(O, H, L, C, m, 1, 0, 1.0, 1.0, 2.0)
        self.assertEqual(t["reason"], "target")
        self.assertEqual(t["pnl"], 1.0 * 2.0 * 40 - 2 * amt.COMMISSION_SIDE * 40)

    def test_both_touched_is_stop(self):
        rows = [(100, 100.5, 99.9, 100.2), (100.2, 102, 98, 100)] + [(100, 100.1, 99.9, 100)] * 400
        O, H, L, C, m = bars(rows)
        t = amt.bracket(O, H, L, C, m, 1, 1, 1.0, 1.0, 2.0)
        self.assertEqual(t["reason"], "stop")
        self.assertLess(t["r"], -1)


if __name__ == "__main__":
    unittest.main()
