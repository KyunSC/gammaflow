"""JS vs Python backtest parity.

Runs the same configs through frontend/lib/backtest (under Node) and functions/ml/backtest, and requires the
same trades (entry/exit bar, side, reason, prices, P&L), the same equity, returns, positions and benchmark curves
bar for bar (exactly, not to a tolerance), and the same metrics. Three layers:

  Parity.test_cases   hand-picked configs on the bundled QQQ/SPY samples and on synthetic Globex weeks built
                      to hit rare paths (stop and target in one bar, price ties, zero/missing volume, NaN
                      features, a DST switch, a CPI print, bars past the news calendar's coverage)
  FuzzParity          a seeded random differential test: random bars, random strategy, params, costs and rules

No npm install is needed. Without Node the tests skip locally, but fail when CI is set, so a CI job that
forgot to install Node cannot report a green run that compared nothing.

    cd functions/ml && python -m unittest test_backtest_parity -v
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backtest import STRATEGIES, Dataset, run_backtest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DATA = {s: FRONTEND / "public" / "backtest" / f"{s}_5m.json" for s in ("qqq", "spy")}
NODE = shutil.which("node")
ET = ZoneInfo("America/New_York")

if not NODE and os.environ.get("CI"):
    raise RuntimeError("CI is set but node is not installed: the parity tests would silently skip")

# Futures-style sizing on ETF bars (QQQ -> NQ): exercises fixed contracts, tick slippage and bar extremes.
NQ = dict(pointValue=20, tickSize=0.25, contracts=2, commissionPerSide=1.5, slippageTicks=1, priceScale=41.2)
NQ1 = dict(NQ, priceScale=1)
NEWS = dict(impact="high", beforeMin=5, afterMin=15)

CASES = [
    # every ported strategy on its defaults, default costs, no risk rules
    *[dict(strategy=s) for s in ("smaCross", "bbReversion", "vwapReversion", "gexWallFade", "gexRegime", "mlSignal")],
    # parameter variants that change code paths
    dict(strategy="smaCross", params=dict(fast=5, slow=20, maType="sma", shortSide=False)),
    dict(strategy="bbReversion", params=dict(period=30, stdDev=1.5)),
    dict(strategy="vwapReversion", params=dict(entryAtr=0.8, exitAtr=0, atrPeriod=10)),
    dict(strategy="gexWallFade", params=dict(regimeGate=False, band=1.0)),
    dict(strategy="gexRegime", params=dict(minStrength=0.2, lookback=3)),
    dict(strategy="mlSignal", params=dict(mode="follow", thresholdBp=1)),
    # fractional periods: JS Math.round(2.5) is 3, Python's round(2.5) is 2
    dict(strategy="mlSignal", params=dict(holdBars=2.5, thresholdBp=1)),
    dict(strategy="gexRegime", params=dict(lookback=6.5)),
    dict(strategy="smaCross", params=dict(fast=4.5, slow=20.5)),
    # risk rules
    dict(strategy="smaCross", risk=dict(stopPct=0.3, targetPct=0.6)),
    dict(strategy="bbReversion", risk=dict(stopPct=0.2, flatAtSessionEnd=True)),
    dict(strategy="gexRegime", risk=dict(maxBars=6, allowShort=False)),
    dict(strategy="vwapReversion", risk=dict(flatByEt=15 * 60 + 30)),
    dict(strategy="gexRegime", risk=dict(newsBlackout=NEWS, flatAtSessionEnd=True)),
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(impact="medium", beforeMin=30, afterMin=30))),
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(impact="high"))),                        # default window
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(impact="medium", beforeMin=0, afterMin=0))),  # print bar
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(NEWS, maxBarMin=1))),                    # skipped on 5m
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(NEWS, maxBarMin=5))),                    # 5m: not skipped
    # costs
    dict(strategy="smaCross", costs=dict(slippageBps=0, commissionPerTrade=0)),
    dict(strategy="gexRegime", costs=dict(slippageBps=5, commissionPerTrade=2, sizePct=0.5, initialCapital=25000)),
    dict(strategy="smaCross", costs=dict(instrument=NQ), risk=dict(stopPct=0.25, targetPct=0.5, flatAtSessionEnd=True)),
    dict(strategy="gexRegime", costs=dict(instrument=NQ), risk=dict(flatByEt=15 * 60 + 45, newsBlackout=NEWS)),
    # a walk-forward style window: indicators warm up on the full history, trading starts at bar 1500
    dict(strategy="bbReversion", window=dict(start=1500, end=3200), risk=dict(stopPct=0.3)),
]

# Synthetic 23-hour futures weeks (18:00-17:00 ET, 5m bars) with wide bars, session-open gaps, prices on a
# 0.25 tick grid (so averages tie), zero and missing volume, and GEX/ML columns with NaN runs.
#   dst:  2025-03-09.. across the DST switch and the 2025-03-12 CPI print
#   late: 2026-10-11.. runs past the news calendar's coverage (2026-10-16 for some high-impact types)
SYNTH_CASES = [
    dict(strategy="smaCross", params=dict(fast=3, slow=8, maType="sma"), risk=dict(stopPct=0.15, targetPct=0.15)),
    dict(strategy="bbReversion", params=dict(period=10, stdDev=1), risk=dict(stopPct=0.1, targetPct=0.2, flatByEt=16 * 60 + 45)),
    dict(strategy="vwapReversion", params=dict(entryAtr=1.0), costs=dict(instrument=NQ1),
         risk=dict(stopPct=0.2, targetPct=0.1, newsBlackout=NEWS, flatAtSessionEnd=True)),
    dict(strategy="smaCross", params=dict(fast=5, slow=13), risk=dict(maxBars=4, flatByEt=16 * 60)),
    dict(strategy="smaCross", params=dict(fast=5, slow=13), costs=dict(instrument=NQ1),
         risk=dict(newsBlackout=dict(impact="medium", beforeMin=10, afterMin=30))),
    dict(strategy="smaCross", params=dict(fast=2, slow=3, maType="sma"), risk=dict(newsBlackout=NEWS)),
    dict(strategy="gexRegime", params=dict(lookback=4)),          # close_vs_sma20 has NaN runs: SMA fallback
    dict(strategy="gexWallFade", params=dict(band=1.5, regimeGate=False)),
    dict(strategy="mlSignal", params=dict(holdBars=3.5, thresholdBp=0.5)),
]


def bars(path: Path, *, seed: int, first_session: date, sessions: int, globex: bool = True, interval: str = "5m",
         gap_p: float = 0.0, flat_p: float = 0.1, tick: float = 0.25, start_px: float = 20000.0, vol: float = 0.0015,
         features: bool = True) -> int:
    """Write a synthetic dataset in the research-JSON format; returns its bar count."""
    rng = np.random.default_rng(seed)
    step = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}[interval]
    times = []
    day, made = first_session, 0
    while made < sessions:
        if globex and day.weekday() in (6, 0, 1, 2, 3):        # Sun-Thu 18:00 ET to next day 17:00 ET
            t0 = datetime(day.year, day.month, day.day, 18, tzinfo=ET).timestamp()
            nxt = day + timedelta(days=1)
            t1 = datetime(nxt.year, nxt.month, nxt.day, 17, tzinfo=ET).timestamp()
        elif not globex and day.weekday() < 5:                  # RTH 09:30-16:00 ET
            t0 = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp()
            t1 = datetime(day.year, day.month, day.day, 16, tzinfo=ET).timestamp()
        else:
            day += timedelta(days=1)
            continue
        times += range(int(t0), int(t1), step)
        made += 1
        day += timedelta(days=1)
    t = np.array(times, dtype=np.int64)
    if gap_p:
        keep = rng.random(len(t)) > gap_p
        keep[0] = keep[-1] = True
        t = t[keep]
    n = len(t)
    snap = (lambda x: round(round(x / tick) * tick, 6)) if tick else (lambda x: x)
    o, h, l, c = [], [], [], []
    px = start_px
    for k in range(n):
        if k and t[k] - t[k - 1] > 3600:
            px *= 1 + rng.normal(0, vol * 3)                   # overnight / data-gap jump
        op = snap(px)
        cl = op if rng.random() < flat_p else snap(op * (1 + rng.normal(0, vol)))
        hi = max(op, cl, snap(max(op, cl) * (1 + abs(rng.normal(0, vol * 0.8)))))
        lo = min(op, cl, snap(min(op, cl) * (1 - abs(rng.normal(0, vol * 0.8)))))
        o.append(op); h.append(hi); l.append(lo); c.append(cl)
        px = cl
    volume = rng.integers(0, 5000, n).astype(float)
    volume[rng.random(n) < 0.05] = 0
    volume = [None if rng.random() < 0.03 else v for v in volume.tolist()]
    volume[0] = 0.0                                           # a session that opens on zero volume
    feats, ml = {}, None

    def nanify(a, p):
        a = a.astype(float)
        a[rng.random(n) < p] = np.nan
        s = int(rng.integers(0, n))
        a[s:s + int(rng.integers(10, 80))] = np.nan             # a NaN run
        return [None if math.isnan(x) else float(x) for x in a]

    if features:
        feats = dict(
            above_zero_gamma=nanify((np.cumsum(rng.normal(0, 1, n)) > 0).astype(float), 0.02),
            gamma_regime_strength=nanify(rng.uniform(-1, 1, n), 0.02),
            close_vs_sma20=nanify(rng.normal(0, 0.003, n), 0.3),
            dist_call_wall_atr=nanify(np.cumsum(rng.normal(0, 0.3, n)) % 4 - 1, 0.02),
            dist_put_wall_atr=nanify(1 - np.cumsum(rng.normal(0, 0.3, n)) % 4, 0.02),
            call_wall_strength=nanify(rng.uniform(0, 1, n), 0.02),
            put_wall_strength=nanify(rng.uniform(0, 1, n), 0.02),
        )
        pred = rng.normal(0, 0.0005, n)
        pred[: n // 5] = np.nan
        ml = dict(pred=nanify(pred, 0.1), target_return=[0.0] * n)
    path.write_text(json.dumps(dict(symbol="SYN", interval=interval, bars=n, time=t.tolist(), open=o, high=h, low=l,
                                    close=c, volume=volume, features=feats, synthetic=True,
                                    **({"ml": ml} if ml else {}))))
    return n


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def to_py(obj):
    """camelCase config -> the Python engine's snake_case keys (strategy params keep their JS names)."""
    if isinstance(obj, dict):
        return {snake(k): to_py(v) for k, v in obj.items()}
    return obj


def num(v):
    return {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}.get(v, v) if isinstance(v, str) else v


def run_js(dataset: Path, cases: list) -> dict:
    out = subprocess.run([NODE, "--no-warnings", "scripts/backtest-parity.mjs"], cwd=FRONTEND, check=True,
                         input=json.dumps(dict(dataset=str(dataset), cases=cases)), capture_output=True, text=True)
    return json.loads(out.stdout)


def run_py(ds, case):
    return run_backtest(ds, case["strategy"], case.get("params"), to_py(case.get("costs")), to_py(case.get("risk")),
                        case.get("window"))


class ParityAsserts(unittest.TestCase):
    METRIC_REL = 1e-9   # metrics go through pow (cagr, skew); V8 and libm may differ in the last bit there

    def same(self, a, b, msg, rel=0.0):
        a, b = num(a), num(b)
        if isinstance(b, float) and math.isnan(b):
            self.assertTrue(isinstance(a, float) and math.isnan(a), f"{msg}: py {a!r} js NaN")
        elif isinstance(b, float) and math.isinf(b):
            self.assertEqual(a, b, msg)
        else:
            self.assertLessEqual(abs(a - b), rel * max(1.0, abs(b)), f"{msg}: py {a!r} js {b!r}")

    def curve(self, py, js, msg):
        js = np.array([num(v) for v in js], dtype=np.float64)
        np.testing.assert_array_equal(np.asarray(py, dtype=np.float64), js, err_msg=msg)  # NaN == NaN here

    def assert_parity(self, py, js, tag):
        self.assertEqual(len(py.trades), len(js["trades"]), f"{tag}: trade count")
        if js["trades"]:
            missing = {snake(k) for k in js["trades"][0]} - set(vars(py.trades[0]))
            self.assertFalse(missing, f"JS trades carry fields the Python port lacks: {sorted(missing)}. "
                                      "The JS engine changed; port the change to backtest/engine.py.")
        for t, (a, b) in enumerate(zip(py.trades, js["trades"])):
            for key, jv in b.items():
                pv = getattr(a, snake(key))
                if isinstance(jv, bool) or key in ("side", "reason", "entryIdx", "exitIdx", "bars"):
                    self.assertEqual(pv, jv, f"{tag} trade {t} {key}")
                else:
                    self.same(pv, jv, f"{tag} trade {t} {key}")
        np.testing.assert_array_equal(py.positions, js["positions"], err_msg=f"{tag}: positions")
        for key in ("equity", "returns", "buyHold"):
            self.curve(getattr(py, snake(key)), js[key], f"{tag}: {key}")
        self.curve(py.metrics["dd_curve"], js["ddCurve"], f"{tag}: ddCurve")
        for key in ("barLo", "barHi", "barOpen"):
            if js[key] is None:
                self.assertIsNone(getattr(py, snake(key)), f"{tag} {key}")
            else:
                self.curve(getattr(py, snake(key)), js[key], f"{tag}: {key}")
        self.assertEqual(py.news_skipped, js["newsSkipped"], tag)
        self.assertEqual(py.news_uncovered_bars, js["newsUncoveredBars"], tag)
        self.assertEqual({snake(k) for k in js["metrics"]}, set(py.metrics) - {"dd_curve"}, f"{tag}: metric keys")
        for key, jv in js["metrics"].items():
            pv = py.metrics[snake(key)]
            if key == "inference":
                self.assertEqual(set(jv), set(pv), f"{tag}: inference keys")
                for ik, iv in jv.items():
                    for x, y in (zip(pv[ik], iv) if ik == "ci" else [(pv[ik], iv)]):
                        self.same(x, y, f"{tag} inference.{ik}", self.METRIC_REL)
            else:
                self.same(pv, jv, f"{tag} metric {key}", self.METRIC_REL)


@unittest.skipUnless(NODE, "node is not installed")
class Parity(ParityAsserts):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.sets = {s: (p, CASES) for s, p in DATA.items()}
        bars(tmp / "dst.json", seed=7, first_session=date(2025, 3, 9), sessions=5)
        bars(tmp / "late.json", seed=8, first_session=date(2026, 10, 11), sessions=7, gap_p=0.02)
        cls.sets["dst"] = (tmp / "dst.json", SYNTH_CASES)
        cls.sets["late"] = (tmp / "late.json", SYNTH_CASES)
        cls.js = {s: run_js(p, cases) for s, (p, cases) in cls.sets.items()}
        cls.ds = {s: Dataset.from_json(p) for s, (p, _) in cls.sets.items()}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_default_params_match(self):
        for sid, strat in STRATEGIES.items():
            self.assertEqual(strat.defaults(), self.js["qqq"]["defaults"][sid], sid)

    def test_synthetic_weeks_hit_the_rare_paths(self):
        """Guards the fixtures: if a generator change stopped producing these, the parity cases would quietly
        stop covering them."""
        res = [r for s in ("dst", "late") for r in self.js[s]["results"]]
        reasons = {t["reason"] for r in res for t in r["trades"]}
        self.assertTrue({"stop", "target", "time", "session", "news", "signal"} <= reasons, reasons)
        ds = self.ds["dst"]
        both = [t for t in self.js["dst"]["results"][0]["trades"] if t["reason"] == "stop"
                and ds.high[t["exitIdx"]] >= t["entryPrice"] * 1.0015 and ds.low[t["exitIdx"]] <= t["entryPrice"] * 0.9985]
        self.assertTrue(both, "no bar spans both stop and target")
        self.assertTrue(any(r["newsUncoveredBars"] > 0 for r in self.js["late"]["results"]), "no uncovered bars")
        sma = self.js["dst"]["results"][5]
        self.assertGreater(len(sma["trades"]), 0)

    def test_cases(self):
        for sym, ds in self.ds.items():
            for k, case in enumerate(self.sets[sym][1]):
                js = self.js[sym]["results"][k]
                with self.subTest(sym=sym, case=k, strategy=case["strategy"]):
                    tag = f"{sym} case {k} {case}"
                    self.assertGreater(len(js["trades"]), 0, f"{tag}: case makes no trades, so it tests nothing")
                    self.assert_parity(run_py(ds, case), js, tag)


# ---------------------------------------------------------------------------------------------- fuzz

SCHEMA = {
    "smaCross": dict(fast=(2, 30, 1), slow=(3, 80, 1), maType=["sma", "ema"], shortSide=bool),
    "bbReversion": dict(period=(5, 40, 1), stdDev=(0.5, 4, 0.1), shortSide=bool),
    "vwapReversion": dict(entryAtr=(0.1, 5, 0.1), exitAtr=(0, 3, 0.1), atrPeriod=(2, 40, 1), shortSide=bool),
    "gexWallFade": dict(band=(0.05, 3, 0.05), exitBand=(0.1, 6, 0.1), minWallStrength=(0, 0.9, 0.01),
                        regimeGate=bool, shortSide=bool),
    "gexRegime": dict(lookback=(1, 40, 1), revertZ=(0.01, 2, 0.01), momentumBp=(0, 100, 1),
                      minStrength=(0, 1, 0.02), shortSide=bool),
    "mlSignal": dict(thresholdBp=(0, 50, 0.5), holdBars=(1, 40, 1), mode=["hold", "follow"], shortSide=bool),
}


def random_case(rng, n):
    sid = str(rng.choice(sorted(SCHEMA)))
    params = {}
    for k, spec in SCHEMA[sid].items():
        if rng.random() < 0.3:
            continue
        if spec is bool:
            params[k] = bool(rng.random() < 0.5)
        elif isinstance(spec, list):
            params[k] = str(rng.choice(spec))
        else:
            lo, hi, step = spec
            v = lo + step * int(rng.integers(0, round((hi - lo) / step) + 1))
            params[k] = int(v) if step == 1 else round(v, 6)
            if step == 1 and rng.random() < 0.15:
                params[k] = params[k] + 0.5            # off-grid half: Math.round vs round()
    case = dict(strategy=sid, params=params)
    costs, risk = {}, {}
    if rng.random() < 0.5:
        costs.update(slippageBps=float(rng.choice([0, 1.5, 5])), commissionPerTrade=float(rng.choice([0, 0.5, 3])))
    if rng.random() < 0.3:
        costs["instrument"] = dict(pointValue=float(rng.choice([5, 20, 50])), tickSize=0.25,
                                   contracts=int(rng.integers(1, 4)), commissionPerSide=1.0,
                                   slippageTicks=float(rng.choice([0, 1, 2])), priceScale=1)
    for key, p, val in (("stopPct", 0.4, lambda: round(float(rng.uniform(0.05, 1)), 2)),
                        ("targetPct", 0.4, lambda: round(float(rng.uniform(0.05, 1.5)), 2)),
                        ("maxBars", 0.2, lambda: int(rng.integers(1, 30))),
                        ("flatAtSessionEnd", 0.3, lambda: True),
                        ("allowShort", 0.2, lambda: False),
                        ("flatByEt", 0.2, lambda: int(rng.choice([15 * 60 + 30, 16 * 60, 16 * 60 + 45]))),
                        ("newsBlackout", 0.3, lambda: dict(impact=str(rng.choice(["high", "medium", "low"])),
                                                           beforeMin=int(rng.choice([0, 5, 30])),
                                                           afterMin=int(rng.choice([0, 15, 60]))))):
        if rng.random() < p:
            risk[key] = val()
    if rng.random() < 0.2:
        a = int(rng.integers(0, n // 2))
        case["window"] = dict(start=a, end=int(rng.integers(a + 10, n)))
    return dict(case, costs=costs, risk=risk)


@unittest.skipUnless(NODE, "node is not installed")
class FuzzParity(ParityAsserts):
    """Seeded random differential test. Change SEED (or set BACKTEST_FUZZ_SEED) to explore; a failure prints the
    seed, dataset and case, which is enough to reproduce it."""
    SEED = int(os.environ.get("BACKTEST_FUZZ_SEED", 2026))
    DATASETS, CASES_EACH = 12, 12

    def test_random_configs(self):
        rng = np.random.default_rng(self.SEED)
        traded = 0
        with tempfile.TemporaryDirectory() as tmp:
            for d in range(self.DATASETS):
                path = Path(tmp) / f"fz{d}.json"
                spec = dict(seed=int(rng.integers(1 << 30)), globex=bool(rng.random() < 0.5),
                            interval=str(rng.choice(["1m", "5m", "5m", "15m", "1h"])),
                            first_session=date(2022, 1, 3) + timedelta(days=int(rng.integers(0, 4 * 365 + 280))),
                            gap_p=float(rng.choice([0, 0.03])), flat_p=float(rng.choice([0, 0.1, 0.3])),
                            tick=float(rng.choice([0.25, 0.01])), start_px=float(rng.choice([50, 400, 20000])),
                            vol=float(rng.uniform(0.0005, 0.004)))
                spec["sessions"] = 2 if spec["interval"] == "1m" else int(rng.integers(3, 8))
                n = bars(path, **spec)
                cases = [random_case(rng, n) for _ in range(self.CASES_EACH)]
                js = run_js(path, cases)
                ds = Dataset.from_json(path)
                for k, case in enumerate(cases):
                    with self.subTest(seed=self.SEED, dataset=d, case=k):
                        traded += bool(js["results"][k]["trades"])
                        self.assert_parity(run_py(ds, case), js["results"][k],
                                           f"seed {self.SEED} dataset {d} {spec} case {k} {case}")
        self.assertGreater(traded, self.DATASETS * self.CASES_EACH // 2, "most fuzz cases should trade")


if __name__ == "__main__":
    unittest.main()
