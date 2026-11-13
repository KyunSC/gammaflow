"""Parity of prop_policy/sim.py with flybrain.prop (constant risk) plus a hand-checked variable-risk case.

Run from functions/ml: python3 -m unittest prop_policy.tests.test_sim -v
"""
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML))
sys.path.insert(0, str(ML / "data" / "prop_structure" / "apex"))
import lucid_structure as L  # noqa: E402
from flybrain import prop as F  # noqa: E402
from prop_policy import sim  # noqa: E402

FIX = ML / "flybrain" / "fixtures" / "prop_parity.json"
PLANS = json.loads((ML / "data" / "prop_policy" / "plans.json").read_text())


def equal(tc, a, b, path=""):
    if b is None:
        tc.assertTrue(a is None or isinstance(a, (float, int)) and not math.isfinite(a), path)
    elif isinstance(b, dict):
        tc.assertEqual(set(a), set(b), path)
        for k in b:
            equal(tc, a[k], b[k], path + "/" + k)
    elif isinstance(b, list):
        tc.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            equal(tc, x, y, f"{path}/{i}")
    elif isinstance(b, (float, int)) and not isinstance(b, bool):
        tc.assertAlmostEqual(a, b, delta=1e-9, msg=path)
    else:
        tc.assertEqual(a, b, path)


def replay(days, plan, sim_fn, paths, block, horizon, seed):
    """run_prop's historical replay and mulberry32 block bootstrap, with the account simulator swapped in."""
    hist = [sim_fn(days, (lambda s: lambda k: s + k if s + k < days["n"] else -1)(s), plan) for s in range(days["n"])]
    rng = F.mulberry32(seed)
    bl = max(1, min(block, days["n"]))
    boot = []
    for _ in range(paths):
        seq = []

        def next_day(k):
            while len(seq) <= k:
                if len(seq) >= horizon:
                    return -1
                b = math.floor(rng() * max(1, days["n"] - bl + 1))
                for j in range(bl):
                    if len(seq) < horizon:
                        seq.append((b + j) % days["n"])
            return seq[k]
        boot.append(sim_fn(days, next_day, plan))
    return hist, boot


class FixtureParity(unittest.TestCase):
    """All 60 prop_parity.json cases: every attempt equals flybrain's, and the summaries equal the JS outputs."""

    def test_all_cases(self):
        f = json.loads(FIX.read_text())
        days = F.build_day_table(f["result"], f["time"], f["initialCapital"])
        self.assertEqual(len(f["cases"]), 60)
        for c in f["cases"]:
            plan = c["plan"]
            with self.subTest(firm=plan["firm"], plan=plan["plan"], size=plan["size"], dll=plan["dll"]):
                h1, b1 = replay(days, plan, sim.simulate_account, f["paths"], f["blockSize"], f["horizon"], f["seed"])
                h0, b0 = replay(days, plan, F.simulate_account, f["paths"], f["blockSize"], f["horizon"], f["seed"])
                self.assertEqual(h1, h0)
                self.assertEqual(b1, b0)
                out = c["output"]["bootstrap"]
                got = F.summarize_attempts(b1, plan)
                for k in out:
                    if k in ("paths", "blockSize", "horizon"):
                        continue
                    equal(self, got[k], out[k], "bootstrap/" + k)
                hout = c["output"]["historical"]
                hgot = F.summarize_attempts(h1, plan)
                for k in hout:
                    if k in ("list", "meanCashPnl"):
                        continue
                    equal(self, hgot[k], hout[k], "historical/" + k)
                costs1 = [sim.attempt_cost(a, plan) for a in b1]
                self.assertEqual(costs1, [F.attempt_cost(a, plan) for a in b1])


class HarnessParity(unittest.TestCase):
    """sim.attempts / sim.summarize against lucid_structure.attempts / score and apex_study.run at constant risk."""

    def test_attempts_and_score(self):
        for name in ("Topstep Cons no-fee 150K", "LucidFlex 50K", "LucidDirect 150K", "Alpha Standard 50K",
                     "MFF Builder 50K (at the 40% promo)", "Apex 50K Intraday (provisional)"):
            e = PLANS[name]
            plan = e["plan"]
            risk = 0.6 * plan["maxLoss"]
            with self.subTest(plan=name):
                d = L.make_days(4000, risk, 300, 1.0, seed=3, comm=plan["commissionPerSide"])
                ref = L.attempts(d, plan, paths=600, seed=5)
                got = sim.attempts(L.day_table(d), plan, paths=600, seed=5, drop_open=True)
                self.assertEqual(got, ref)
                if not e.get("provisional"):
                    r = L.score(plan, e["fee"], risk, 300, 1.0, paths=600, n_days=4000, seed=3, rseed=5)
                    s = sim.summarize(got, plan, fee=e["fee"])
                    for k in ("ev", "pass_rate", "p_paid", "mean_take", "days_used"):
                        self.assertAlmostEqual(s[k], r[k], delta=1e-9, msg=k)
                    self.assertAlmostEqual(s["cost"], r["fee"], delta=1e-9)

    def test_apex_wrapper(self):
        import apex_study as A
        for name in ("Apex 50K EOD (provisional)", "Apex 50K Intraday (provisional)"):
            e = PLANS[name]
            p = e["plan"]
            risk, st = A.bracket(p, 0.5)
            ref = A.run(p, risk, st, 0, 1, 500)
            ev_ref = ref["take"] - e["fee"] - e["activation_on_pass"] * ref["pass_rate"]
            d = L.make_days(40000, risk, st, 1.0, seed=0, comm=p["commissionPerSide"])
            s = sim.summarize(sim.attempts(L.day_table(d), p, paths=500, seed=1, drop_open=True), p, eval_limit=e["eval_limit_days"])
            with self.subTest(plan=name):
                self.assertAlmostEqual(s["ev"], ev_ref, delta=1e-9)
                for k, rk in (("pass_rate", "pass_rate"), ("p_paid", "p_paid"), ("mean_take", "take"), ("days_used", "days")):
                    self.assertAlmostEqual(s[k], ref[rk], delta=1e-9, msg=k)


def table(rows):
    """One bar per day: rows of (lo, hi, open, close)."""
    n = len(rows)
    lo, hi, op, cl = (list(map(float, x)) for x in zip(*rows))
    return dict(n=n, start=list(range(n)), end=list(range(n)), active=[1] * n, time=[0.0] * n,
                lo=lo, hi=hi, open=op, close=cl, min_lo=lo)


HAND_PLAN = dict(startBalance=50000, maxLoss=2000, lockOffset=100, evalLockOffset=100, evalDrawdown="eod", fundedDrawdown="eod",
                 dailyLossLimit=0, dllFundedOnly=False, profitTarget=1700, evalMinDays=1, evalConsistency=0, hasEval=True,
                 fundedConsistency=0, fundedConsistencyStrict=False, fundedMinDays=1, minProfitDays=0, minDayProfit=0,
                 profitGoal=[0], payoutFraction=None, payoutCap=[1000], buffer=0, minPayout=100, maxPayouts=5, split=0.9,
                 payoutKeepsMll=False, price=100, rebillDays=None, activationFee=0, activationOnPass=False)
# Level 0 is small risk, level 1 big risk; same three draws (d = 0, 1, 2), so the coin flips are shared.
LOW = table([(0, 500, 0, 500), (-300, 0, 0, -300), (0, 500, 0, 500)])
HIGH = table([(0, 1500, 0, 1500), (-2100, 0, 0, -900), (0, 1500, 0, 1500)])


class Rule:
    """Big risk while at least $1,500 of the target is left, small risk after. Records what it saw."""

    def __init__(self):
        self.seen = []

    def level(self, s):
        self.seen.append((s.stage, s.day, s.bal, s.threshold, s.cushion, s.to_target))
        return 1 if s.to_target >= 1500 else 0


class HandChecked(unittest.TestCase):
    def run_case(self, plan, policy, draws):
        lv = []
        out = sim.simulate_account([LOW, HIGH], lambda k: draws[k] if k < len(draws) else -1, plan, policy, lv)
        return out, lv

    def test_switching_policy(self):
        # Day 0: $1,700 of the target left >= 1,500 -> HIGH, +1,500 -> 51,500, floor 49,500.
        # Day 1: $200 left -> LOW, -300 -> 51,200 (HIGH's -2,100 dip would have breached 49,500).
        # Day 2: $500 left -> LOW, +500 -> 51,700, profit 1,700 >= target: pass after 3 days.
        # Funded day 0 (draw 0 again): goal 0 left -> LOW, +500 -> 50,500; payout min(500, cap 1,000) = 500, lock at 50,100.
        pol = Rule()
        out, lv = self.run_case(HAND_PLAN, pol, [0, 1, 2, 0])
        self.assertEqual(lv, [1, 0, 0, 0])
        self.assertEqual(pol.seen, [("eval", 0, 50000, 48000, 2000, 1700), ("eval", 1, 51500, 49500, 2000, 200),
                                    ("eval", 2, 51200, 49500, 1700, 500), ("funded", 0, 50000, 48000, 2000, 100)])
        self.assertEqual((out["outcome"], out["evalDays"], out["fundedDays"], out["payouts"], out["take"], out["daysUsed"]),
                         ("funded-open", 3, 1, [500], 450.0, 4))

    def test_constant_high_breaches(self):
        # Day 0 HIGH +1,500 -> 51,500, floor 49,500. Day 1 HIGH dips to 49,400 <= 49,500: breached at the floor.
        out, lv = self.run_case(HAND_PLAN, sim.Constant(1), [0, 1, 2])
        self.assertEqual(lv, [1, 1])
        self.assertEqual((out["outcome"], out["evalDays"], out["daysUsed"]), ("failed", 2, 2))

    def test_constant_high_with_dll(self):
        # DLL $1,000: day 1's dip stops at 50,500 (> floor 49,500), pnl -1,000. Day 2 +1,500 -> 52,000: pass, 1 DLL hit.
        plan = dict(HAND_PLAN, dailyLossLimit=1000)
        out, lv = self.run_case(plan, sim.Constant(1), [0, 1, 2])
        self.assertEqual(lv, [1, 1, 1])
        self.assertEqual((out["outcome"], out["evalDays"], out["dllHits"]), ("funded-open", 3, 1))

    def test_matches_flybrain_on_each_level(self):
        for lvl, t in enumerate((LOW, HIGH)):
            for draws in ([0, 1, 2], [2, 2, 1, 0, 0], [1, 1, 1]):
                nd = lambda k, dr=draws: dr[k] if k < len(dr) else -1
                self.assertEqual(sim.simulate_account([LOW, HIGH], nd, HAND_PLAN, sim.Constant(lvl)),
                                 F.simulate_account(t, nd, HAND_PLAN))


class TieFuzz(unittest.TestCase):
    """Day tables on a $100 grid hit the rule boundaries (pnl == minDayProfit, dip == DLL level, profit == target,
    consistency equalities) that the fixture's continuous P&L almost never lands on. Compared with flybrain on every
    fixture plan plus the nine loop plans, two bars per day, intraday and EOD."""

    def test_grid_tables(self):
        plans = [c["plan"] for c in json.loads(FIX.read_text())["cases"]] + [e["plan"] for e in PLANS.values()]
        rng = np.random.default_rng(11)
        for t in range(40):
            n = 30
            first = rng.integers(-12, 13, n) * 100.0
            close = rng.integers(-12, 16, n) * 100.0
            lo1, hi1 = np.minimum(first, 0) - rng.integers(0, 3, n) * 100, np.maximum(first, 0) + rng.integers(0, 3, n) * 100
            lo2, hi2 = np.minimum(first, close) - rng.integers(0, 3, n) * 100, np.maximum(first, close)
            bars = lambda a, b: np.stack((a, b), 1).ravel().tolist()
            days = dict(n=n, start=list(range(0, 2 * n, 2)), end=list(range(1, 2 * n, 2)), active=rng.integers(0, 2, n).tolist(),
                        time=[0.0] * n, lo=bars(lo1, lo2), hi=bars(hi1, hi2), open=bars(np.zeros(n), first), close=bars(first, close),
                        min_lo=np.minimum(lo1, lo2).tolist())
            draws = rng.integers(0, n, 120).tolist()
            nd = lambda k: draws[k] if k < len(draws) else -1
            for p in plans:
                for scale in (1.0, 2.5):
                    sd = dict(days, **{k: [v * scale for v in days[k]] for k in ("lo", "hi", "open", "close", "min_lo")})
                    with self.subTest(t=t, plan=(p["firm"], p["plan"], p["size"], p["dll"]), scale=scale):
                        self.assertEqual(sim.simulate_account(sd, nd, p), F.simulate_account(sd, nd, p))


class SequencePolicy(unittest.TestCase):
    """Exact variable-risk check: a policy whose level is a pre-drawn sequence over the day index must equal flybrain on
    one table assembled from the chosen (level, draw) days. Covers level switches in the funded stage, intraday
    trailing, the DLL, payouts and graduation, on every loop plan."""

    def test_sequence_equals_assembled_table(self):
        rng = np.random.default_rng(17)
        for name, e in PLANS.items():
            plan = e["plan"]
            tabs = [L.day_table(L.make_days(500, f * plan["maxLoss"], 300, 1.0, seed=9, comm=plan["commissionPerSide"]))
                    for f in (0.25, 0.5, 0.8)]
            for t in range(60):
                H = 120
                draws, seq = rng.integers(0, 500, H).tolist(), rng.integers(0, 3, H).tolist()
                bars = [(tabs[seq[k]], draws[k]) for k in range(H)]
                cat = dict(n=H, start=[], end=[], active=[], time=[0.0] * H, lo=[], hi=[], open=[], close=[], min_lo=[])
                for tb, d in bars:
                    cat["start"].append(len(cat["lo"]))
                    for i in range(tb["start"][d], tb["end"][d] + 1):
                        for key in ("lo", "hi", "open", "close"):
                            cat[key].append(tb[key][i])
                    cat["end"].append(len(cat["lo"]) - 1)
                    cat["active"].append(tb["active"][d])
                    cat["min_lo"].append(tb["min_lo"][d])

                class Seq:
                    def level(self, s):
                        return seq[s.k]
                lv = []
                got = sim.simulate_account(tabs, lambda k: draws[k] if k < H else -1, plan, Seq(), lv)
                ref = F.simulate_account(cat, lambda k: k if k < H else -1, plan)
                with self.subTest(plan=name, t=t):
                    self.assertEqual(got, ref)
                    self.assertEqual(lv, seq[:len(lv)])


class Branches(unittest.TestCase):
    def test_gap_below_floor_while_dll_fires(self):
        # Floor 48,000, DLL level 49,000. Bar 2 gaps open at 47,500: the DLL fires but the frozen fill
        # min(49,000, 47,500) is below the floor, so the account is breached at 47,500 with one DLL hit.
        plan = dict(HAND_PLAN, dailyLossLimit=1000)
        t = dict(n=1, start=[0], end=[1], active=[1], time=[0.0], lo=[-500.0, -2600.0], hi=[0.0, -2500.0],
                 open=[0.0, -2500.0], close=[-500.0, -2550.0], min_lo=[-2600.0])
        nd = lambda k: 0 if k == 0 else -1
        got = sim.run_stage([t], nd, 0, plan, "eval", sim.Constant(0))
        self.assertEqual(got, F.run_stage(t, nd, 0, plan, "eval"))
        self.assertEqual((got["status"], got["balance"], got["dllHits"]), ("breached", 47500.0, 1))

    def test_funded_to_target_gates(self):
        s = sim.State()
        s.stage, s.start, s.cycle_start, s.goal = "funded", 50000, 50000, 0
        s.plan = dict(buffer=52100, payoutFraction=None, minPayout=500)  # Apex: balance >= 52,600
        s.bal = 51000
        self.assertAlmostEqual(s.to_target, 1600)
        s.plan = dict(buffer=0, payoutFraction=0.5, minPayout=500)  # Flex: 0.5 x profit >= 500
        self.assertAlmostEqual(s.to_target, 0)
        s.bal = 50400
        self.assertAlmostEqual(s.to_target, 600)
        s.plan, s.goal, s.cycle_start = dict(buffer=155100, payoutFraction=None, minPayout=500), 9000, 150000  # LucidDirect
        s.start, s.bal = 150000, 156000
        self.assertAlmostEqual(s.to_target, 3000)

    def test_censored_attempts_charged_as_failures(self):
        # A policy that never trades (all-zero table) leaves every evaluation open at the horizon.
        z = dict(n=5, start=list(range(5)), end=list(range(5)), active=[1] * 5, time=[0.0] * 5, lo=[0.0] * 5, hi=[0.0] * 5,
                 open=[0.0] * 5, close=[0.0] * 5, min_lo=[0.0] * 5)
        for name in ("Topstep Cons no-fee 50K noDLL", "Apex 50K EOD (provisional)", "LucidFlex 50K"):
            e = PLANS[name]
            self.assertEqual(sim.attempts([z], e["plan"], paths=20, drop_open=True), [])
            done = sim.attempts([z], e["plan"], paths=20)
            r = sim.summarize(done, e["plan"], fee=e["fee"], eval_limit=e.get("eval_limit_days"))
            self.assertEqual((r["n"], r["censored"], r["pass_rate"], r["mean_take"]), (20, 1.0, 0.0, 0.0))
            want = {"Topstep Cons no-fee 50K noDLL": 95 * math.ceil(250 / 21), "Apex 50K EOD (provisional)": 59,
                    "LucidFlex 50K": 90.2}[name]
            self.assertAlmostEqual(r["cost"], want, delta=1e-9, msg=name)


if __name__ == "__main__":
    unittest.main()
