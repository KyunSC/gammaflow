"""G2 on a synthetic market: fades an extreme top-trader lean at a 4h boundary, never otherwise.
Outside tests/ because the manifest pins tests/*.py.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/b2/crypto/test_g2.py
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
from strategies import G2_toptrader_fade as G2  # noqa: E402

T0 = 1_640_995_200            # 2022-01-01 00:00 UTC
DAYS = 40
P = {"step_s": 14400, "max_age": 900, "win": 180, "min_valid": 150, "stop_pct": 1.5, "hold_s": 28800,
     "col": "count_toptrader_long_short_ratio", "Z": 2.0}
COL = P["col"]


def market():
    t = np.arange(T0, T0 + DAYS * 86400, 60, dtype=np.int64)
    c = np.full(len(t), 100.0)
    return Market("BTCUSDT", pd.DataFrame({"time": t, "open": c, "high": c + .1, "low": c - .1, "close": c,
                                           "volume": np.ones(len(t))}))


class Feats:
    """5m metrics rows; ratio wiggles around 1.5, with an optional spike stamped just before a chosen boundary."""
    def __init__(self, spike_at=None, spike=3.0, lag=0):
        st = np.arange(T0, T0 + DAYS * 86400, 300, dtype=np.int64)
        r = 1.5 + 0.05 * np.sin(np.arange(len(st)))
        if spike_at is not None:
            k = int(np.searchsorted(st, spike_at - 300 - lag))   # avail = stamp + 300 <= boundary
            r[k] = spike
            self.k = k
        self.ser = Series(st, st + 300, {COL: r})

    def metrics(self, symbol):
        return self.ser


B = T0 + 35 * 86400           # a 4h boundary with 35 days of history


def test_sandbox_ok():
    check_source((HERE / "strategies" / "G2_toptrader_fade.py").read_text(), "G2")


def test_fades_long_lean_and_short_lean():
    m = market()
    s = G2.signals(m, Feats(spike_at=B, spike=3.0), P)
    assert [m.t[x.sig] + 60 for x in s] == [B] and s[0].side == -1
    assert m.t[s[0].end] + 60 == B + 28800
    s = G2.signals(m, Feats(spike_at=B, spike=0.75), P)
    assert len(s) == 1 and s[0].side == 1


def test_never_without_extreme_or_off_grid_or_stale_row():
    m = market()
    assert G2.signals(m, Feats(), P) == []                               # sin wiggle: |z| < 2
    assert G2.signals(m, Feats(spike_at=B + 600, spike=3.0), P) == []    # spike lands between boundaries (and is stale by then)
    assert G2.signals(m, Feats(spike_at=B, spike=3.0, lag=1200), P) == []  # row older than max_age at the boundary


def test_needs_history():
    m = market()
    assert G2.signals(m, Feats(spike_at=T0 + 10 * 86400, spike=3.0), P) == []   # < 150 prior samples


def test_causal():
    m = market()
    a = [(x.sig, x.side) for x in G2.signals(m, Feats(spike_at=B, spike=3.0), P)]
    f = Feats(spike_at=B, spike=3.0)
    f.ser.values[COL][f.k + 1:] = 9.0                                       # every later row changes
    b = [(x.sig, x.side) for x in G2.signals(m, f, P) if m.t[x.sig] + 60 <= B]
    assert a == b
