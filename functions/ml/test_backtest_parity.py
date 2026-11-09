"""JS vs Python backtest parity.

Runs the same configs through frontend/lib/backtest (under Node) and functions/ml/backtest, and requires the
same trades (entry/exit bar, side, reason, prices, P&L), the same equity curve bar for bar, and the same
metrics. Skipped when Node is not installed; no npm install is needed.

    cd functions/ml && python -m unittest test_backtest_parity -v
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backtest import Dataset, run_backtest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DATA = {s: FRONTEND / "public" / "backtest" / f"{s}_5m.json" for s in ("qqq", "spy")}
NODE = shutil.which("node")

# Futures-style sizing on ETF bars (QQQ -> NQ): exercises fixed contracts, tick slippage and bar extremes.
NQ = dict(pointValue=20, tickSize=0.25, contracts=2, commissionPerSide=1.5, slippageTicks=1, priceScale=41.2)
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
    # risk rules
    dict(strategy="smaCross", risk=dict(stopPct=0.3, targetPct=0.6)),
    dict(strategy="bbReversion", risk=dict(stopPct=0.2, flatAtSessionEnd=True)),
    dict(strategy="gexRegime", risk=dict(maxBars=6, allowShort=False)),
    dict(strategy="vwapReversion", risk=dict(flatByEt=15 * 60 + 30)),
    dict(strategy="gexRegime", risk=dict(newsBlackout=NEWS, flatAtSessionEnd=True)),
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(impact="medium", beforeMin=30, afterMin=30))),
    dict(strategy="smaCross", risk=dict(newsBlackout=dict(NEWS, maxBarMin=1))),   # skipped on 5m bars
    # costs
    dict(strategy="smaCross", costs=dict(slippageBps=0, commissionPerTrade=0)),
    dict(strategy="gexRegime", costs=dict(slippageBps=5, commissionPerTrade=2, sizePct=0.5, initialCapital=25000)),
    dict(strategy="smaCross", costs=dict(instrument=NQ), risk=dict(stopPct=0.25, targetPct=0.5, flatAtSessionEnd=True)),
    dict(strategy="gexRegime", costs=dict(instrument=NQ), risk=dict(flatByEt=15 * 60 + 45, newsBlackout=NEWS)),
    # a walk-forward style window: indicators warm up on the full history, trading starts at bar 1500
    dict(strategy="bbReversion", window=dict(start=1500, end=3200), risk=dict(stopPct=0.3)),
]

# A synthetic 23-hour futures week (18:00-17:00 ET, 5m bars) spanning the 2025-03-09 DST switch and the
# 2025-03-12 CPI print, with wide bars and session-open gaps. The real samples are RTH-only and rarely put a
# stop and a target in one bar, so this is where those paths get exercised.
GLOBEX_CASES = [
    dict(strategy="smaCross", params=dict(fast=3, slow=8, maType="sma"), risk=dict(stopPct=0.15, targetPct=0.15)),
    dict(strategy="bbReversion", params=dict(period=10, stdDev=1), risk=dict(stopPct=0.1, targetPct=0.2, flatByEt=16 * 60 + 45)),
    dict(strategy="vwapReversion", params=dict(entryAtr=1.0), costs=dict(instrument=dict(NQ, priceScale=1)),
         risk=dict(stopPct=0.2, targetPct=0.1, newsBlackout=NEWS, flatAtSessionEnd=True)),
    dict(strategy="smaCross", params=dict(fast=5, slow=13), risk=dict(maxBars=4, flatByEt=16 * 60)),
    dict(strategy="smaCross", params=dict(fast=5, slow=13), costs=dict(instrument=dict(NQ, priceScale=1)),
         risk=dict(newsBlackout=dict(impact="medium", beforeMin=10, afterMin=30))),
]


def globex_week(path: Path) -> None:
    rng = np.random.default_rng(7)
    t0 = 1741471200  # 2025-03-08T22:00Z = Sat 17:00 ET; first session opens Sun 18:00 ET (22:00Z, EDT from here)
    time, o, h, l, c = [], [], [], [], []
    px = 20000.0
    for d in range(5):
        start = t0 + 86400 + d * 86400  # Sun..Thu 22:00Z
        if d:
            px *= 1 + rng.normal(0, 0.004)  # overnight gap
        for b in range(276):
            op = px
            cl = op * (1 + rng.normal(0, 0.0015))
            hi = max(op, cl) * (1 + abs(rng.normal(0, 0.0012)))
            lo = min(op, cl) * (1 - abs(rng.normal(0, 0.0012)))
            time.append(start + b * 300); o.append(op); h.append(hi); l.append(lo); c.append(cl)
            px = cl
    n = len(time)
    vol = rng.integers(50, 5000, n).tolist()
    path.write_text(json.dumps(dict(symbol="SYN", interval="5m", bars=n, time=time, open=o, high=h, low=l, close=c,
                                    volume=vol, features={}, synthetic=True)))


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


@unittest.skipUnless(NODE, "node is not installed")
class Parity(unittest.TestCase):
    REL = 1e-12   # floats: equal to ~1e-12 relative (in practice they come out bit-identical)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        globex = Path(cls.tmp.name) / "globex.json"
        globex_week(globex)
        cls.sets = {s: (p, CASES) for s, p in DATA.items()}
        cls.sets["globex"] = (globex, GLOBEX_CASES)
        cls.js = {s: run_js(p, cases) for s, (p, cases) in cls.sets.items()}
        cls.ds = {s: Dataset.from_json(p) for s, (p, _) in cls.sets.items()}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_globex_week_hits_the_rare_paths(self):
        reasons = {t["reason"] for r in self.js["globex"]["results"] for t in r["trades"]}
        self.assertTrue({"stop", "target", "time", "session", "news"} <= reasons, reasons)
        # at least one bar where stop and target were both inside the range: the stop must win
        res = self.js["globex"]["results"][0]
        ds = self.ds["globex"]
        both = [t for t in res["trades"] if t["reason"] == "stop"
                and ds.high[t["exitIdx"]] >= t["entryPrice"] * 1.0015 and ds.low[t["exitIdx"]] <= t["entryPrice"] * 0.9985]
        self.assertTrue(both, "no bar spans both levels")

    def close(self, a, b, msg, rel=None):
        a, b = num(a), num(b)
        if isinstance(b, float) and math.isnan(b):
            self.assertTrue(math.isnan(a), msg)
        elif isinstance(b, float) and math.isinf(b):
            self.assertEqual(a, b, msg)
        else:
            self.assertLessEqual(abs(a - b), (rel or self.REL) * max(1.0, abs(b)), f"{msg}: py {a!r} js {b!r}")

    def arrays(self, py, js, msg):
        js = np.array([num(v) for v in js], dtype=np.float64)
        np.testing.assert_allclose(py, js, rtol=self.REL, atol=0, equal_nan=True, err_msg=msg)

    def test_default_params_match(self):
        from backtest import STRATEGIES
        for sid, strat in STRATEGIES.items():
            self.assertEqual(strat.defaults(), self.js["qqq"]["defaults"][sid], sid)

    def test_cases(self):
        for sym, ds in self.ds.items():
            for k, case in enumerate(self.sets[sym][1]):
                js = self.js[sym]["results"][k]
                w = case.get("window")
                with self.subTest(sym=sym, case=k, strategy=case["strategy"]):
                    py = run_backtest(ds, case["strategy"], case.get("params"), to_py(case.get("costs")),
                                      to_py(case.get("risk")), (w["start"], w["end"]) if w else None)
                    tag = f"{sym} case {k} {case}"
                    self.assertGreater(len(js["trades"]), 0, f"{tag}: case makes no trades, so it tests nothing")
                    self.assertEqual(len(py.trades), len(js["trades"]), f"{tag}: trade count")
                    if js["trades"]:
                        missing = {snake(k) for k in js["trades"][0]} - set(vars(py.trades[0]))
                        self.assertFalse(missing, f"JS trades carry fields the Python port lacks: {sorted(missing)}. "
                                                  "The JS engine changed; port the change to backtest/engine.py.")
                    for t, (a, b) in enumerate(zip(py.trades, js["trades"])):
                        for key, jv in b.items():
                            pv = getattr(a, snake(key))
                            if isinstance(jv, (str, bool)) or key in ("entryIdx", "exitIdx", "bars"):
                                self.assertEqual(pv, jv, f"{tag} trade {t} {key}")
                            else:
                                self.close(pv, jv, f"{tag} trade {t} {key}")
                    np.testing.assert_array_equal(py.positions, js["positions"], err_msg=f"{tag}: positions")
                    self.arrays(py.equity, js["equity"], f"{tag}: equity")
                    for key in ("barLo", "barHi", "barOpen"):
                        if js[key] is None:
                            self.assertIsNone(getattr(py, snake(key)), f"{tag} {key}")
                        else:
                            self.arrays(getattr(py, snake(key)), js[key], f"{tag}: {key}")
                    self.assertEqual(py.news_skipped, js["newsSkipped"], tag)
                    self.assertEqual(py.news_uncovered_bars, js["newsUncoveredBars"], tag)
                    for key, jv in js["metrics"].items():
                        pv = py.metrics[snake(key)]
                        if key == "inference":
                            for ik, iv in jv.items():
                                if ik == "ci":
                                    for x, y in zip(pv["ci"], iv):
                                        self.close(x, y, f"{tag} inference.ci", 1e-9)
                                else:
                                    self.close(pv[ik], iv, f"{tag} inference.{ik}", 1e-9)
                        else:
                            # Metrics go through pow/sqrt; V8 and libm may differ in the last bit there.
                            self.close(pv, jv, f"{tag} metric {key}", 1e-9)


if __name__ == "__main__":
    unittest.main()
