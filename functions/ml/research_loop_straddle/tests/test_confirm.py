"""Tests for research_loop_straddle/confirm.py. No market data is read: every day is hand-built.

Run: .venv/bin/python -m unittest discover -s research_loop_straddle/tests -v   (from functions/ml)
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import confirm as c  # noqa: E402
import delta_hedge as dh  # noqa: E402
import greeks as g  # noqa: E402

N_BARS = 78  # 09:35 -> 16:00 on 5-minute bars
DT = 5 / (60 * 24 * 365)


def synthetic_path(S: np.ndarray, K: float, sigma: float) -> dict:
    """A straddle_path-shaped dict for a 0DTE day: constant IV marks, intrinsic on the last bar."""
    T = DT * np.arange(N_BARS, -1, -1, dtype=float)
    Tg = np.maximum(T, dh.MIN_T_INTRADAY)
    V = (g.bs_price(S, K, Tg, sigma, np.ones_like(S, bool)) + g.bs_price(S, K, Tg, sigma, np.zeros_like(S, bool)))
    V[-1] = abs(S[-1] - K)
    iv = np.full(len(S), sigma)
    return dict(S=S, V=V, iv_call=iv, iv_put=iv.copy(), T=T, K=K, fills=None)


def gbm(S0: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    z = rng.standard_normal(N_BARS)
    r = (dh.RISK_FREE_RATE - 0.5 * sigma ** 2) * DT + sigma * np.sqrt(DT) * z
    return S0 * np.exp(np.r_[0.0, np.cumsum(r)])


def cell_frame(net: np.ndarray, start: str = "2017-01-02", symbol: str = "SPY", variant: str = "5m",
               cost: float = 2.0) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(net)).strftime("%Y-%m-%d")
    return pd.DataFrame({"symbol": symbol, "variant": variant, "date": dates, "net_base": net,
                         "net_stress": net - cost, "gross": net + cost, "cost_base": cost, "cost_stress": 2 * cost,
                         "shares_traded": 100.0, "spread_cost": 1.0, "premium": 200.0, "spot0": 250.0,
                         "margin": 5200.0})


class CostWrapper(unittest.TestCase):
    def test_shares_traded_counts_entry_rebalances_and_unwind(self):
        self.assertEqual(c.shares_traded([10, 12, 8]), 10 + 2 + 4 + 8)
        self.assertEqual(c.shares_traded([-5, -5]), 10)
        self.assertEqual(c.shares_traded([]), 0)

    def test_flat_spot_day_costs(self):
        """Spot never moves: hedge is set at entry, adjusted as delta decays, unwound at 16:00.
        Net = gross - 2 x commission - per-share cost on exactly the shares traded."""
        S = np.full(N_BARS + 1, 250.0)
        p = synthetic_path(S, 249.0, 0.15)
        res = dh.hedge_pnl(**p, rebalance_every=1, hedge_cost_bps=0.0)
        sh = c.shares_traded(res["bars"]["hedge"])
        out = c.price_day(p, 1.0, 0.5, every=1)
        self.assertAlmostEqual(out["gross"], res["pnl"])
        self.assertAlmostEqual(out["shares_traded"], sh)
        self.assertGreater(sh, 0)
        self.assertAlmostEqual(out["net_base"], out["gross"] - 2 * 0.65 - 0.005 * sh)
        self.assertAlmostEqual(out["net_stress"], out["gross"] - 2 * 1.00 - 0.01 * sh)
        # spot pinned near K: the short straddle keeps most of the premium
        self.assertGreater(out["gross"], 0)

    def test_hedge_cost_bps_not_double_charged(self):
        S = np.linspace(250, 252, N_BARS + 1)
        p = synthetic_path(S, 250.0, 0.2)
        out = c.price_day(p, 1.0, 1.0, every=6)
        res = dh.hedge_pnl(**p, rebalance_every=6, hedge_cost_bps=0.0)
        self.assertEqual(res["hedge_cost"], 0.0)
        self.assertAlmostEqual(out["gross"], res["pnl"])

    def test_30m_trades_fewer_shares_than_5m(self):
        S = gbm(250.0, 0.2, np.random.default_rng(1))
        p = synthetic_path(S, 250.0, 0.2)
        self.assertLess(c.price_day(p, 1, 1, every=6)["shares_traded"], c.price_day(p, 1, 1, every=1)["shares_traded"])

    def test_bid_fills_charge_the_spread(self):
        """Entry at the bid below mid costs 100 x (mid - bid) through delta_hedge's spread_cost."""
        S = np.full(N_BARS + 1, 250.0)
        p = synthetic_path(S, 250.0, 0.2)
        mid = dh.hedge_pnl(**p, rebalance_every=1)["pnl"]
        p_bid = {**p, "fills": (p["V"][0] - 0.05, p["V"][-1])}
        self.assertAlmostEqual(c.price_day(p_bid, 1, 1, every=1)["gross"], mid - 5.0)

    def test_margin_atm_and_otm(self):
        # ATM: 20% of S + both premiums
        self.assertAlmostEqual(c.margin_per_straddle(400, 400, 1.5, 1.5), 100 * (80 + 3.0))
        # spot 10 above K: put leg OTM by 10 -> 20% S - 10; call side larger (ITM call, OTM 0)
        m = c.margin_per_straddle(410, 400, 10.2, 0.3)
        self.assertAlmostEqual(m, 100 * max(10.2 + 82 + 0.3, 0.3 + 72 + 10.2))
        # deep OTM floor at 10%
        self.assertAlmostEqual(c.margin_per_straddle(100, 200, 0.0, 100.0), 100 * max(0 + 10 + 100, 100 + 20 + 0))

    def test_run_day_skips_pre2022_half_days_without_reading(self):
        with mock.patch.object(dh, "load_day", side_effect=AssertionError("read")):
            for d in c.EARLY_CLOSE_PRE2022:
                self.assertEqual(c.run_day("SPY", d), [])
        self.assertEqual(len(c.EARLY_CLOSE_PRE2022), 12)
        self.assertTrue(all("2016" <= d[:4] <= "2021" for d in c.EARLY_CLOSE_PRE2022))

    def test_run_day_skips_no_straddle_and_non_settling(self):
        with mock.patch.object(dh, "load_day", return_value=None):
            self.assertEqual(c.run_day("SPY", "2018-01-03"), [])
        with mock.patch.object(dh, "load_day", return_value={"settle": False}):
            self.assertEqual(c.run_day("SPY", "2018-01-03"), [])


class RealizedEqualsImplied(unittest.TestCase):
    def test_gross_is_zero_mean_so_net_is_minus_costs(self):
        """GBM at the marked IV, mid fills: the hedged short straddle earns ~0 before costs, so the
        net is ~ -costs. Checked against the cross-path standard error."""
        rng = np.random.default_rng(7)
        sigma = 0.20
        for every in (1, 6):
            gross, net, cost = [], [], []
            for _ in range(600):
                S = gbm(250.0, sigma, rng)
                out = c.price_day(synthetic_path(S, 250.0, sigma), 1.0, 1.0, every=every)
                gross.append(out["gross"]), net.append(out["net_base"]), cost.append(out["cost_base"])
            gross, net, cost = map(np.asarray, (gross, net, cost))
            se = gross.std(ddof=1) / np.sqrt(len(gross))
            prem = synthetic_path(np.full(N_BARS + 1, 250.0), 250.0, sigma)["V"][0] * 100
            self.assertLess(abs(gross.mean()), 3 * se + 0.02 * prem, f"every={every}")
            self.assertAlmostEqual((net + cost).mean(), gross.mean())
            self.assertLess(net.mean(), gross.mean())

    def test_pinned_spot_earns_and_big_move_loses(self):
        """Sanity: realized << implied wins, realized >> implied loses."""
        flat = c.price_day(synthetic_path(np.full(N_BARS + 1, 250.0), 250.0, 0.2), 1, 1, every=1)
        jump = np.r_[np.full(40, 250.0), np.full(N_BARS + 1 - 40, 245.0)]
        moved = c.price_day(synthetic_path(jump, 250.0, 0.2), 1, 1, every=1)
        self.assertGreater(flat["gross"], 0)
        self.assertLess(moved["gross"], 0)


class Stats(unittest.TestCase):
    def test_clean_positive_cell_passes(self):
        rng = np.random.default_rng(0)
        net = 10 + rng.normal(0, 20, 300)
        s = c.cell_stats(cell_frame(net))
        self.assertTrue(s["pass"], s["gate"])
        self.assertLess(s["p_one_sided"], c.ALPHA)
        self.assertLess(s["ci95"][0], s["mean_net_base"])

    def test_worst5_doubled_is_binding(self):
        net = np.r_[np.full(295, 5.0), np.full(5, -150.0)]
        net = net + np.random.default_rng(3).normal(0, 0.5, 300)
        s = c.cell_stats(cell_frame(net))
        # mean = (295*5 - 750)/300 ~ 2.42 > 0; doubled: (1475 - 1500)/300 < 0
        self.assertGreater(s["mean_net_base"], 0)
        self.assertLess(s["mean_worst5_doubled"], 0)
        self.assertFalse(s["gate"]["worst5_doubled_pos"])
        self.assertFalse(s["pass"])
        self.assertAlmostEqual(s["mean_ex_worst5"], net[np.argsort(net)[5:]].mean())

    def test_bad_year_fails(self):
        # 2017 and 2018 +$3000 each, 2019 -$7000: mean annual -333 -> years_ok False
        n = 250
        net = np.r_[np.full(n, 12.0), np.full(n, 12.0), np.full(n, -28.0)]
        f = cell_frame(net, start="2017-01-02")
        f["date"] = [f"{y}-{d}" for y in ("2017", "2018", "2019") for d in
                     pd.bdate_range("2017-01-02", periods=n).strftime("%m-%d")]
        self.assertFalse(c.cell_stats(f)["gate"]["years_ok"])
        # a mild losing year is allowed: -2000 vs mean annual (3000+3000-2000)/3 = 1333 -> limit -2667
        net2 = np.r_[np.full(n, 12.0), np.full(n, 12.0), np.full(n, -8.0)]
        f2 = f.assign(net_base=net2)
        self.assertTrue(c.cell_stats(f2)["gate"]["years_ok"])

    def test_stress_negative_fails(self):
        rng = np.random.default_rng(0)
        net = 10 + rng.normal(0, 20, 300)
        s = c.cell_stats(cell_frame(net, cost=12.0))
        self.assertFalse(s["gate"]["stress_pos"])
        self.assertFalse(s["pass"])

    def test_tail_numbers(self):
        net = np.r_[np.full(99, 2.0), -100.0]
        s = c.cell_stats(cell_frame(net))
        self.assertEqual(s["worst_day"], -100.0)
        self.assertEqual(s["n_big_loss"], 1)  # mean 0.98, -100 < -9.8
        self.assertAlmostEqual(s["cvar5"], (-100 + 4 * 2.0) / 5)
        self.assertAlmostEqual(s["return_on_margin_pct"], 100 * net.mean() / 5200)

    def test_window_verdict_needs_5m_on_both_symbols(self):
        rng = np.random.default_rng(0)
        good, bad = 10 + rng.normal(0, 20, 300), rng.normal(0, 20, 300)
        frames = lambda q5, s5, q30, s30: pd.concat([  # noqa: E731
            cell_frame(q5, symbol="QQQ", variant="5m"), cell_frame(s5, symbol="SPY", variant="5m"),
            cell_frame(q30, symbol="QQQ", variant="30m"), cell_frame(s30, symbol="SPY", variant="30m")])
        self.assertEqual(c.window_stats(frames(good, good, bad, bad))["verdict"], "PASS")
        self.assertEqual(c.window_stats(frames(good, bad, good, good))["verdict"], "FAIL")
        self.assertEqual(c.window_stats(frames(bad, good, good, good))["verdict"], "FAIL")
        missing = pd.concat([cell_frame(good, symbol="SPY", variant="5m")])
        self.assertEqual(c.window_stats(missing)["verdict"], "FAIL")


class WindowGuard(unittest.TestCase):
    def test_b_refused_before_a(self):
        with self.assertRaisesRegex(c.WindowGuardError, "needs window A"):
            c.check_window("B", [])

    def test_a_allowed_once(self):
        c.check_window("A", [])
        with self.assertRaisesRegex(c.WindowGuardError, "already opened"):
            c.check_window("A", [{"window": "A", "verdict": "PASS"}])

    def test_b_refused_after_a_fail_and_allowed_after_pass(self):
        with self.assertRaisesRegex(c.WindowGuardError, "failed"):
            c.check_window("B", [{"window": "A", "verdict": "FAIL"}])
        c.check_window("B", [{"window": "A", "verdict": "PASS"}])
        with self.assertRaisesRegex(c.WindowGuardError, "already opened"):
            c.check_window("B", [{"window": "A", "verdict": "PASS"}, {"window": "B", "verdict": "FAIL"}])

    def test_b_refused_when_a_undecided(self):
        with self.assertRaisesRegex(c.WindowGuardError, "verdict"):
            c.check_window("B", [{"window": "A"}])

    def test_unknown_window(self):
        with self.assertRaises(c.WindowGuardError):
            c.check_window("C", [])

    def test_forbidden_dates_refused(self):
        bad = {**c.WINDOWS, "A": {"QQQ": ("2016-01-04", "2022-06-30"), "SPY": ("2017-01-03", "2018-12-31")}}
        with mock.patch.object(c, "WINDOWS", bad), self.assertRaisesRegex(c.WindowGuardError, "forbidden"):
            c.check_window("A", [])

    def test_windows_match_plan(self):
        self.assertEqual(c.WINDOWS["A"], {"QQQ": ("2016-01-04", "2018-12-31"), "SPY": ("2017-01-03", "2018-12-31")})
        self.assertEqual(c.WINDOWS["B"], {"QQQ": ("2019-01-02", "2021-12-31"), "SPY": ("2019-01-02", "2021-12-31")})

    def test_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ledger.jsonl"
            self.assertEqual(c.read_ledger(p), [])
            p.write_text(json.dumps({"window": "A", "verdict": "FAIL"}) + "\n\n")
            self.assertEqual(c.read_ledger(p), [{"window": "A", "verdict": "FAIL"}])

    def test_hash_check_detects_change(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.py"
            f.write_text("a = 1\n")
            pre = {"frozen_sha256": {str(f): c.sha256(f)}}
            c.check_hashes(pre)
            f.write_text("a = 2\n")
            with self.assertRaisesRegex(c.WindowGuardError, "changed"):
                c.check_hashes(pre)

    def test_open_window_refuses_before_reading_data(self):
        """open_window checks hashes and the ledger before any day is loaded."""
        with tempfile.TemporaryDirectory() as d:
            led = Path(d) / "ledger.jsonl"
            led.write_text(json.dumps({"window": "A", "verdict": "FAIL"}) + "\n")
            with mock.patch.object(c, "LEDGER", led), mock.patch.object(c, "check_hashes"), \
                    mock.patch.object(c, "run_day", side_effect=AssertionError("read")), \
                    mock.patch.object(c, "window_days", side_effect=AssertionError("listed")):
                for w in ("A", "B"):
                    with self.assertRaises(c.WindowGuardError):
                        c.open_window(w)


if __name__ == "__main__":
    unittest.main()
