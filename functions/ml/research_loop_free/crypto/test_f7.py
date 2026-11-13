"""F7 on a synthetic market: fades a big 1m move with a volume spike, never on the opposite cases.
Outside tests/ because the manifest pins tests/*.py.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/crypto/test_f7.py
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
from strategies import F7_liq_cascade_fade as F7  # noqa: E402

T0 = 1_600_000_000 // 60 * 60
P = {"win": 1440, "vol_mult": 5.0, "stop_pct": 1.5, "hold_s": 21600, "vol_mode": "spike", "k": 8}
N, SHOCK = 3000, 2000


def market(jump=0.02, vol=10.0, gap_at=None, n=N, shock=SHOCK, after=None):
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.0005, n)               # sd ~ 5 bps
    r[shock] = jump
    c = 100 * np.exp(np.cumsum(r))
    v = np.ones(n)
    v[shock] = vol
    if after is not None:                      # change every bar after the shock (causality check)
        c[shock + 1:] *= after
        v[shock + 1:] *= 100
    t = T0 + 60 * np.arange(n, dtype=np.int64)
    if gap_at is not None:
        t[gap_at:] += 120
    return Market("BTCUSDT", pd.DataFrame({"time": t, "open": c, "high": c * 1.0001, "low": c * 0.9999, "close": c,
                                           "volume": v}))


def test_sandbox_ok():
    check_source((HERE / "strategies" / "F7_liq_cascade_fade.py").read_text(), "F7")


def test_fades_up_spike():
    m = market()
    s = F7.signals(m, None, P)
    assert [x.sig for x in s] == [SHOCK] and s[0].side == -1
    assert s[0].stop == s[0].target == np.float64(0.015 * m.c[SHOCK])
    assert m.t[s[0].end] == m.t[SHOCK + 1] + 21600 - 60


def test_fades_down_spike():
    s = F7.signals(market(jump=-0.02), None, P)
    assert len(s) == 1 and s[0].side == 1


def test_never_without_spike_or_small_move_or_hole():
    assert F7.signals(market(vol=3.0), None, P) == []                 # volume 3x < 5x median
    assert F7.signals(market(jump=0.002), None, P) == []              # ~4 sd < 8 sd
    assert F7.signals(market(gap_at=SHOCK), None, P) == []            # bar before the shock is not 60 s earlier
    assert F7.signals(market(n=1400, shock=1300), None, P) == []      # under one window of history


def test_no_spike_control_is_the_complement():
    m = market(vol=3.0)
    s = F7.signals(m, None, {**P, "vol_mode": "no_spike"})
    assert [x.sig for x in s] == [SHOCK]
    assert F7.signals(market(), None, {**P, "vol_mode": "no_spike"}) == []


def test_causal_scale():
    """Changing bars after the shock never changes the shock's signal."""
    m1, m2 = market(), market(after=1.5)
    a = [(x.sig, x.side) for x in F7.signals(m1, None, P) if x.sig <= SHOCK]
    b = [(x.sig, x.side) for x in F7.signals(m2, None, P) if x.sig <= SHOCK]
    assert a == b
