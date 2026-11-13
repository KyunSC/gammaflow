"""H2 on a synthetic market: follows a recurring same-hour move. Outside tests/ (manifest pins tests/*.py).

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/b3/crypto/test_h2.py
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
from strategies import H2_crypto_hour_periodicity as H2  # noqa: E402

T0 = 1_640_995_200
DAYS = 40
P = {"series": "periodicity", "stop_pct": 1.5, "hold_s": 3540, "valid_frac": 0.8, "N": 7}


def market(drop_days=()):
    """Price rises 1% during UTC hour 14 every day and falls 1% during hour 20; flat otherwise."""
    t = np.arange(T0, T0 + DAYS * 86400, 60, dtype=np.int64)
    hr, mi = (t % 86400) // 3600, (t % 3600) // 60
    step = np.where(hr == 14, 0.01 / 60, 0.0) - np.where(hr == 20, 0.01 / 60, 0.0)
    c = 100 * np.exp(np.cumsum(step) + 1e-6 * np.sin(np.arange(len(t))))
    df = pd.DataFrame({"time": t, "open": c, "high": c * 1.0001, "low": c * 0.9999, "close": c, "volume": np.ones(len(t))})
    for d in drop_days:                                      # drop the hour-14 end bar on day d
        df = df[df.time != T0 + d * 86400 + 14 * 3600 + 59 * 60]
    return Market("BTCUSDT", df.reset_index(drop=True))


def by_hour(m, s):
    return {int((m.t[x.sig] + 60) % 86400 // 3600): x.side for x in s if m.t[x.sig] >= T0 + 30 * 86400}


def test_sandbox_ok():
    check_source((HERE / "strategies" / "H2_crypto_hour_periodicity.py").read_text(), "H2")


def test_follows_same_hour():
    m = market()
    s = H2.signals(m, None, P)
    h = by_hour(m, s)
    assert h[14] == 1 and h[20] == -1
    x = [x for x in s if (m.t[x.sig] + 60) % 86400 == 14 * 3600][0]
    assert m.t[x.end] - m.t[x.sig + 1] == 3480 and abs(x.stop / m.c[x.sig] - 0.015) < 1e-12


def test_needs_valid_days():
    m = market(drop_days=range(20, 40))                    # hour-14 history missing from day 20 on
    s = H2.signals(m, None, P)
    assert 14 not in by_hour(m, s)
    assert 20 in by_hour(m, s)


def test_prev_hour_control():
    m = market()
    h = by_hour(m, H2.signals(m, None, {**P, "series": "prev_hour"}))
    assert h[15] == 1 and h[21] == -1                       # the hour just ended was 14 (up) / 20 (down)


def test_causal():
    m = market()
    cut = T0 + 35 * 86400
    a = [(x.sig, x.side) for x in H2.signals(m, None, P) if m.t[x.sig] + 60 <= cut - 3600]
    df = m.bars[m.bars.time < cut].reset_index(drop=True)
    m2 = Market("BTCUSDT", df)
    b = [(x.sig, x.side) for x in H2.signals(m2, None, P) if m2.t[x.sig] + 60 <= cut - 3600]
    assert a == b
