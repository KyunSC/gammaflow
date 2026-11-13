"""G2, top-trader positioning fade (prereg/G2_toptrader_fade.json).

On each 1m bar whose close is a UTC 4h boundary: x = ln(latest count_toptrader_long_short_ratio, avail <= close,
age <= max_age); z vs the previous `win` grid samples (>= min_valid valid). z >= Z -> short, z <= -Z -> long.
Stop = target = stop_pct % of the decision close, time exit hold_s after entry.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 35


def grid(m, step):
    """1m indices whose close lands on a multiple of `step` seconds."""
    return np.flatnonzero((m.t + 60) % step == 0)


def samples(m, feats, idx, col, max_age):
    ser = feats.metrics(m.symbol)
    vals, _ = ser.asof(m.t[idx] + 60, max_age=max_age)
    v = vals[col]
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(v > 0, np.log(v), np.nan)


def zscores(x: np.ndarray, win: int, min_valid: int) -> np.ndarray:
    z = np.full(len(x), np.nan)
    for i in range(win, len(x)):
        if not np.isfinite(x[i]):
            continue
        h = x[i - win:i]
        h = h[np.isfinite(h)]
        if len(h) < min_valid:
            continue
        sd = h.std(ddof=1)
        if sd > 0:
            z[i] = (x[i] - h.mean()) / sd
    return z


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    idx = grid(m, params['step_s'])
    x = samples(m, feats, idx, params['col'], params['max_age'])
    z = zscores(x, params['win'], params['min_valid'])
    out = []
    for j in np.flatnonzero(np.isfinite(z) & (np.abs(z) >= params['Z'])):
        s = int(idx[j])
        if s + 1 >= m.n or m.stale[s]:
            continue
        side = -1 if z[j] > 0 else 1
        d = params['stop_pct'] / 100 * m.c[s]
        out.append(Signal(s, side, d, d, end_by_time(m, s, params['hold_s'])))
    return out
