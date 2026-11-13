"""G3 on a synthetic market: fades a big 12h move into 09:30 ET, nothing on small moves, weekends or gaps.
Outside tests/ because the manifest pins tests/*.py.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/b2/crypto/test_g3.py
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
from strategies import G3_us_open_fade as G3  # noqa: E402

T0 = 1_641_772_800            # 2022-01-10 00:00 UTC (Monday)
DAYS = 45
P = {"session": "us", "anchor_min": 569, "dows": [0, 1, 2, 3, 4], "lookback_s": 43200, "sd_days": 30, "stop_pct": 1.5,
     "hold_s": 23400, "m": 0.5}
DEC = T0 + 42 * 86400 + 14 * 3600 + 29 * 60     # 2022-02-21 (Mon) 09:29 ET bar (EST: UTC-5)


def market(jump=0.0, gap=False):
    t = np.arange(T0, T0 + DAYS * 86400, 60, dtype=np.int64)
    day = (t - T0) // 86400
    c = 100.0 * np.exp(0.01 * np.where(day % 2, 1, -1))       # daily UTC log returns of +-2%: sd ~ 0.02
    c = c * np.where(t >= DEC - 43200 + 60, np.exp(jump), 1.0)  # move starts right after the 21:29 ET bar
    c = c * np.where(t > DEC, np.exp(-jump), 1.0)               # and is undone after the decision bar
    df = pd.DataFrame({"time": t, "open": c, "high": c * 1.0001, "low": c * 0.9999, "close": c, "volume": np.ones(len(t))})
    if gap:
        df = df[df.time != DEC - 43200]
    return Market("BTCUSDT", df.reset_index(drop=True))


def at(m, s):
    return [int(m.t[x.sig]) for x in s]


def test_sandbox_ok():
    check_source((HERE / "strategies" / "G3_us_open_fade.py").read_text(), "G3")


def test_fades_big_overnight_move():
    m = market(jump=0.03)                                        # +3% vs 0.5 * 2% threshold
    s = [x for x in G3.signals(m, None, P) if m.t[x.sig] == DEC]
    assert len(s) == 1 and s[0].side == -1
    assert m.ny_min[s[0].end] == 959                            # held through the 15:59 ET bar
    m = market(jump=-0.03)
    s = [x for x in G3.signals(m, None, P) if m.t[x.sig] == DEC]
    assert len(s) == 1 and s[0].side == 1


def test_small_move_gap_and_weekend():
    assert DEC not in at(market(jump=0.005), G3.signals(market(jump=0.005), None, P))
    m = market(jump=0.03, gap=True)
    assert DEC not in at(m, G3.signals(m, None, P))             # 12h-earlier bar missing
    m = market(jump=0.03)
    assert all(m.ny_dow[x.sig] < 5 and m.ny_min[x.sig] == 569 for x in G3.signals(m, None, P))


def test_needs_30_complete_days():
    m = market(jump=0.03)
    first = min(m.t[x.sig] for x in G3.signals(m, None, P))
    assert first >= T0 + 31 * 86400


def test_asia_control_anchor():
    m = market()
    q = {**P, "session": "asia", "anchor_min": 1229, "dows": [6, 0, 1, 2, 3], "m": 0.0}
    s = G3.signals(m, None, q)
    assert s and all(m.ny_min[x.sig] == 1229 and m.ny_dow[x.sig] in (6, 0, 1, 2, 3) for x in s)
