"""G5 on a synthetic market: follows top-trader position lean minus the all-accounts lean at a 4h boundary.
Outside tests/ because the manifest pins tests/*.py.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/b2/crypto/test_g5.py
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
from strategies import G5_smart_vs_retail as G5  # noqa: E402

T0 = 1_640_995_200
DAYS = 40
P = {"step_s": 14400, "max_age": 900, "win": 180, "min_valid": 150, "stop_pct": 1.5, "hold_s": 28800,
     "top_col": "sum_toptrader_long_short_ratio", "all_col": "count_long_short_ratio", "series": "divergence", "D": 2.0}
B = T0 + 35 * 86400


def market():
    t = np.arange(T0, T0 + DAYS * 86400, 60, dtype=np.int64)
    c = np.full(len(t), 100.0)
    return Market("BTCUSDT", pd.DataFrame({"time": t, "open": c, "high": c + .1, "low": c - .1, "close": c,
                                           "volume": np.ones(len(t))}))


class Feats:
    """Both ratios wiggle around 1.5 (out of phase); optional spikes on the row available at boundary B."""
    def __init__(self, top=None, all_=None, lag=0):
        st = np.arange(T0, T0 + DAYS * 86400, 300, dtype=np.int64)
        n = np.arange(len(st))
        a, b = 1.5 + 0.05 * np.sin(n), 1.5 + 0.05 * np.cos(n)
        self.k = int(np.searchsorted(st, B - 300 - lag))
        if top is not None:
            a[self.k] = top
        if all_ is not None:
            b[self.k] = all_
        self.ser = Series(st, st + 300, {P["top_col"]: a, P["all_col"]: b})

    def metrics(self, symbol):
        return self.ser


def test_sandbox_ok():
    check_source((HERE / "strategies" / "G5_smart_vs_retail.py").read_text(), "G5")


def test_follows_divergence_both_ways():
    m = market()
    s = G5.signals(m, Feats(top=3.0), P)
    assert [m.t[x.sig] + 60 for x in s] == [B] and s[0].side == 1
    assert m.t[s[0].end] + 60 == B + 28800 and abs(s[0].stop - 1.5) < 1e-9
    s = G5.signals(m, Feats(all_=3.0), P)                       # retail leans long, top traders don't -> short
    assert len(s) == 1 and s[0].side == -1


def test_no_trade_when_both_lean_together_or_stale():
    m = market()
    assert G5.signals(m, Feats(), P) == []
    assert G5.signals(m, Feats(top=3.0, all_=3.0), P) == []    # same lean: divergence ~ 0
    assert G5.signals(m, Feats(top=3.0, lag=1200), P) == []    # row too old at the boundary


def test_top_only_control():
    m = market()
    s = G5.signals(m, Feats(top=3.0, all_=3.0), {**P, "series": "top_only"})
    assert len(s) == 1 and s[0].side == 1


def test_causal():
    m = market()
    a = [(x.sig, x.side) for x in G5.signals(m, Feats(top=3.0), P)]
    f = Feats(top=3.0)
    for c in (P["top_col"], P["all_col"]):
        f.ser.values[c][f.k + 1:] = 9.0
    assert a == [(x.sig, x.side) for x in G5.signals(m, f, P) if m.t[x.sig] + 60 <= B]
