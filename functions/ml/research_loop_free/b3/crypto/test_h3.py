"""H3 on a synthetic market. Outside tests/ because the manifest pins tests/*.py.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/b3/crypto/test_h3.py
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
from strategies import H3_crypto_tsmom as H3  # noqa: E402

T0 = 1_640_995_200
DAYS = 60
P = {"series": "tsmom", "sd_days": 30, "floor_pct": 1.5, "hold_s": 86280, "L": 7}


def market(drift=0.01, vol=0.04, drop=None):
    t = np.arange(T0, T0 + DAYS * 86400, 60, dtype=np.int64)
    day = (t - T0) // 86400
    c = 100.0 * np.exp(drift * day + vol * np.where(day % 2, 0.5, -0.5))
    df = pd.DataFrame({"time": t, "open": c, "high": c * 1.0001, "low": c * 0.9999, "close": c, "volume": np.ones(len(t))})
    if drop is not None:
        df = df[df.time != drop]
    return Market("BTCUSDT", df.reset_index(drop=True))


def test_sandbox_ok():
    check_source((HERE / "strategies" / "H3_crypto_tsmom.py").read_text(), "H3")


def test_follows_trend_both_ways_daily():
    m = market(drift=0.01)
    s = H3.signals(m, None, P)
    assert s and all(x.side == 1 for x in s) and all((m.t[x.sig] + 60) % 86400 == 0 for x in s)
    assert all(m.t[x.end] - m.t[x.sig + 1] == 86220 for x in s if x.end < m.n - 1)   # through the 23:57 bar
    m = market(drift=-0.01)
    assert all(x.side == -1 for x in H3.signals(m, None, P))


def test_bracket_and_floor():
    m = market(drift=0.01, vol=0.04)
    x = H3.signals(m, None, P)[0]
    sd = np.diff(np.log([100 * np.exp(0.01 * d + 0.04 * (0.5 if d % 2 else -0.5)) for d in range(0, 31)])).std(ddof=1)
    assert abs(x.stop / m.c[x.sig] - sd) < 1e-9 and x.target == x.stop
    m = market(drift=0.001, vol=0.0)
    x = H3.signals(m, None, P)[0]
    assert abs(x.stop / m.c[x.sig] - 0.015) < 1e-12


def test_needs_history_and_lag_bar():
    m = market()
    first = min(int(m.t[x.sig]) for x in H3.signals(m, None, P))
    assert first + 60 >= T0 + 31 * 86400                      # 31 closes, days 0..30
    gap = T0 + 40 * 86400 - 60 - 7 * 86400                     # the 23:59 bar 7 days before day-39's decision
    m = market(drop=gap)
    assert T0 + 40 * 86400 - 60 not in [int(m.t[x.sig]) for x in H3.signals(m, None, P)]


def test_always_long_control():
    m = market(drift=-0.01)
    assert all(x.side == 1 for x in H3.signals(m, None, {**P, "series": "always_long"}))
