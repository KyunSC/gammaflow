"""outcomes.py rebuilds lucid_structure.make_days / day_table exactly. Run from functions/ml:
python3 -m unittest prop_policy.tests.test_outcomes -v"""
import sys
import unittest
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML))
import lucid_structure as L  # noqa: E402
from prop_policy import outcomes as O  # noqa: E402
from prop_policy import sim  # noqa: E402


class Rebuild(unittest.TestCase):
    def test_levels_match_make_days(self):
        rng = np.random.default_rng(3)
        for name, e in O.plans().items():
            p = e["plan"]
            lv = O.plan_levels(p)
            for i in rng.choice(len(lv), 4, replace=False):
                x = lv[i]
                for seed in (0, 7, 100, 115):
                    with self.subTest(plan=name, level=repr(x), seed=seed):
                        d = L.make_days(O.N_DAYS, x.risk, x.S, 1.0, seed=seed, comm=p["commissionPerSide"])
                        self.assertEqual(d["contracts"], x.n)
                        self.assertEqual(d["p"], x.p)
                        pnl, lo, hi, won = O.day_arrays(x, seed)
                        for a, b in ((pnl, d["pnl"]), (lo, d["lo"]), (hi, d["hi"]), (won, d["won"])):
                            np.testing.assert_array_equal(a, b)
                        self.assertEqual(O.day_table(x, seed), L.day_table(d))

    def test_win_loss_nets(self):
        x = O.Level(10, 310, 0.61)
        d = L.make_days(2000, x.risk, x.S, 1.0, seed=1, comm=0.61)
        np.testing.assert_allclose(np.unique(d["pnl"][d["won"]]), [x.win_net])
        self.assertTrue(set(np.round(d["pnl"][~d["won"]], 9)) <= set(np.round(x.loss_net, 9)))

    def test_grid_and_bracket(self):
        e = O.plans()["Topstep Cons no-fee 50K noDLL"]["plan"]
        g = O.grid(e)
        self.assertEqual((g[0], g[-1], len(g)), (400.0, 2000.0, 65))
        self.assertEqual(O.bracket(e, 1550), (10, 310, 1550.0))
        self.assertEqual(O.bracket(O.plans()["LucidDirect 150K"]["plan"], 1625), (11, 295, 1622.5))

    def test_common_random_numbers_and_sim_parity(self):
        """Two levels from one seed share win/loss outcomes; sim at constant level equals L.attempts on make_days."""
        e = O.plans()["LucidFlex 50K"]["plan"]
        a, b = O.Level(5, 300, 0.5), O.Level(10, 300, 0.5)
        np.testing.assert_array_equal(O.day_arrays(a, 3)[3], O.day_arrays(b, 3)[3])
        tabs = [O.day_table(a, 3, 4000), O.day_table(b, 3, 4000)]
        ref = L.attempts(L.make_days(4000, b.risk, b.S, 1.0, seed=3, comm=0.5), e, paths=300, seed=4)
        self.assertEqual(sim.attempts(tabs, e, sim.Constant(1), paths=300, seed=4, drop_open=True), ref)


if __name__ == "__main__":
    unittest.main()
