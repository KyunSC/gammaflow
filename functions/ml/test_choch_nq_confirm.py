"""Synthetic checks for choch_nq_confirm (no real bars)."""
import unittest

import choch_futures_lucid as base
import choch_nq_confirm as nq


def lucid(ev):
    return {"NQ": {"1050": {"ev": ev}}, "ES": {"1050": {"ev": -999}}}


class T(unittest.TestCase):
    def test_window_months(self):
        m = nq.months()
        self.assertEqual((m[0], m[-1], len(m)), ("2022-01", "2026-08", 56))

    def test_window_stops_before_verify_block(self):
        from holdout import VERIFY_START
        self.assertLess(nq.WINDOW[1], VERIFY_START.date())
        self.assertGreaterEqual((VERIFY_START.date() - nq.WINDOW[1]).days, 7)

    def test_verdict_is_nq_only(self):
        ok = {"trades": 100, "p": 0.01, "excess_ci": [0.01, 0.1]}
        bad = {"trades": 100, "p": 0.4, "excess_ci": [-0.1, 0.1]}
        self.assertTrue(base.passes(ok))
        self.assertFalse(base.passes(bad))
        self.assertEqual(nq.nq_verdict({"NQ": {"twins": ok}, "ES": {"twins": bad}}, lucid(-5)), "PASS")
        self.assertEqual(nq.nq_verdict({"NQ": {"twins": bad}, "ES": {"twins": ok}}, lucid(10)), "STRUCTURE-ONLY")
        self.assertEqual(nq.nq_verdict({"NQ": {"twins": bad}, "ES": {"twins": ok}}, lucid(-1)), "FAIL")
        edge = {"trades": 1369, "p": 0.0255, "excess_ci": [0.0002, 0.08]}  # the 2011-2021 NQ result must not pass
        self.assertEqual(nq.nq_verdict({"NQ": {"twins": edge}, "ES": {"twins": bad}}, lucid(-1)), "FAIL")

    def test_spec_hash_covers_code(self):
        h = nq.spec_hash()
        self.assertEqual(set(h["sha256"]), {"choch_rule.py", "choch_futures_lucid.py", "choch_nq_confirm.py", "orb15_2r_study.py",
                                               "open_ema_trail_study.py", "holdout.py", "lucid_structure.py", "prop.py"})


if __name__ == "__main__":
    unittest.main()
