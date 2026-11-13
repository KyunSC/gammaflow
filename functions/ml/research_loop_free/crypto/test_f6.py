"""F6 on a synthetic market: fires on an unusually large funding print, never on the opposite cases.
Outside tests/ because the manifest pins tests/*.py.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/crypto/test_f6.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from controller import check_source  # noqa: E402
from eval.engine import Market  # noqa: E402
from eval.features import Series  # noqa: E402
from strategies import F6_funding_print as F6  # noqa: E402

T0 = 1_600_000_000 // 86400 * 86400          # a UTC midnight in 2020
PARAMS = {"lookback_days": 30, "min_prints": 80, "stop_pct": 1.5, "hold_s": 14340, "q": 0.9}


def market(days=40):
    t = np.arange(T0, T0 + days * 86400, 60, dtype=np.int64)
    c = np.full(len(t), 100.0)
    return Market("BTCUSDT", pd.DataFrame({"time": t, "open": c, "high": c + 0.1, "low": c - 0.1, "close": c,
                                           "volume": np.ones(len(t))}))


class Feats:
    def __init__(self, rates, offset_s=0):
        self.P = T0 + np.arange(len(rates), dtype=np.int64) * 8 * 3600 + offset_s
        self.r = np.asarray(rates, float)

    def funding(self, symbol):
        return Series(self.P, self.P.copy(), {"rate": self.r})


def base_rates(n=100, last=None):
    r = list(np.where(np.arange(n) % 3 == 0, 0.0002, 0.0001))   # mostly default prints, some higher
    if last is not None:
        r[-1] = last
    return r


def test_sandbox_ok():
    check_source((HERE / "strategies" / "F6_funding_print.py").read_text(), "F6")


def test_fires_long_on_large_positive_print():
    m, f = market(), Feats(base_rates(last=0.0010))
    sigs = F6.signals(m, f, PARAMS)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == 1 and m.t[s.sig] == f.P[-1]
    assert s.stop == s.target == 1.5
    assert m.t[s.end] == f.P[-1] + 4 * 3600 - 60          # held through the bar ending at print + 4h


def test_fires_short_on_large_negative_print_with_ms_offset():
    m, f = market(), Feats(base_rates(last=-0.0010), offset_s=0)
    f.P = f.P.copy()
    f.P[-1] += 5                                            # print stamped a few seconds late: floored to the minute
    sigs = F6.signals(m, f, PARAMS)
    assert len(sigs) == 1 and sigs[0].side == -1 and m.t[sigs[0].sig] == (f.P[-1] // 60) * 60


def test_never_on_default_prints_or_ties():
    m = market()
    assert F6.signals(m, Feats([0.0001] * 100), PARAMS) == []        # all ties at the default: strict > never fires
    assert F6.signals(m, Feats(base_rates(last=0.0002)), PARAMS) == []  # equals the quantile: not strictly above


def test_needs_history_and_bar():
    m = market()
    assert F6.signals(m, Feats(base_rates(n=60, last=0.0010)), PARAMS) == []   # < 80 prior prints
    m2 = market()
    m2.stale[:] = True
    assert F6.signals(m2, Feats(base_rates(last=0.0010)), PARAMS) == []        # stale decision bar


def test_uses_prior_prints_only():
    r = base_rates(last=0.0010)
    r_future = r + [0.01] * 5                                       # later huge prints must not change the decision
    m = market(days=45)
    a = [s for s in F6.signals(m, Feats(r), PARAMS)]
    b = [s for s in F6.signals(m, Feats(r_future), PARAMS) if m.t[s.sig] <= Feats(r).P[-1]]
    assert [(s.sig, s.side) for s in a] == [(s.sig, s.side) for s in b]
