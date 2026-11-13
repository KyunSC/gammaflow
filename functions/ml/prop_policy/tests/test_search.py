"""search.py harness equals sim.attempts at constant risk; policies stay inside the cap. From functions/ml:
python3 -m unittest prop_policy.tests.test_search -v"""
import sys
import unittest
from pathlib import Path

ML = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML))
from prop_policy import outcomes as O, policies as P, search as SR, sim  # noqa: E402


class Harness(unittest.TestCase):
    def test_full_run_equals_sim_attempts(self):
        for name in ("Topstep Cons no-fee 50K noDLL", "Apex 50K Intraday (provisional)", "LucidDirect 150K"):
            e, p, menu, head, h = SR.setup(name)
            pol = P.Fixed(head, head).bind(menu, range(len(menu)))
            got = SR.full_run(pol, p, SR.LazyTables(menu, 100), 400, 200)
            for a in got:
                self.assertEqual(set(a["levels"]), {head})
                del a["levels"]
            ref = sim.attempts([O.day_table(menu[head], 100)], p, paths=400, seed=200)
            self.assertEqual(got, ref)

    def test_policies_respect_allowed(self):
        e, p, menu, head, h = SR.setup("LucidFlex 50K")
        allowed = [i for i, l in enumerate(menu) if l.risk <= 1005]
        tabs = SR.LazyTables(menu, 3)
        pols = [P.Ladder(1, 1, allowed[0]), P.Ladder(4, 2, allowed[-1]),
                P.Grid({c: allowed[(j * 5) % len(allowed)] for j, c in enumerate(P.Grid.CELLS)})]
        for pol in pols:
            pol.bind(menu, allowed)
            for a in SR.full_run(pol, p, tabs, 300, 9):
                self.assertTrue(set(a["levels"]) <= set(allowed), pol.kind)


if __name__ == "__main__":
    unittest.main()
