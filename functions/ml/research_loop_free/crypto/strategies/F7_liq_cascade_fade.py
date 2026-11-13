"""F7, liquidation-cascade fade (prereg/F7_liq_cascade_fade.json).

1m bar i with |ln(c_i/c_{i-1})| >= k x sd of the previous `win` 1m returns and volume >= vol_mult x their median
volume -> fade at the next bar's open, stop = target = stop_pct % of c_i, time exit hold_s after entry. vol_mode
'no_spike' (report-only control) keeps the return condition but requires volume < vol_mult x median.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 2


def features(m, win: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(r, sd_before, medv_before), all aligned to bar i and using bars before i only for sd / medv."""
    c = m.c
    r = np.full(m.n, np.nan)
    r[1:] = np.log(c[1:] / c[:-1])
    bad = np.r_[True, np.diff(m.t) != 60] | m.stale | np.r_[True, m.stale[:-1]]
    r[bad] = np.nan
    sd = pd.Series(r).rolling(win, min_periods=win).std().shift(1).to_numpy()
    medv = pd.Series(m.v).rolling(win, min_periods=win).median().shift(1).to_numpy()
    return r, sd, medv


def pick(r, sd, medv, v, p: dict) -> np.ndarray:
    with np.errstate(invalid='ignore'):
        big = np.abs(r) >= p['k'] * sd
        spike = v >= p['vol_mult'] * medv
    ok = np.isfinite(r) & np.isfinite(sd) & (sd > 0) & np.isfinite(medv) & (medv > 0) & (r != 0)
    if p['vol_mode'] == 'spike':
        return np.flatnonzero(ok & big & spike)
    if p['vol_mode'] == 'no_spike':
        return np.flatnonzero(ok & big & ~spike)
    raise ValueError('unknown vol_mode')


def signals(m, feats, params) -> list[Signal]:
    if m.n < params['win'] + 2:
        return []
    r, sd, medv = features(m, params['win'])
    out = []
    for i in pick(r, sd, medv, m.v, params):
        i = int(i)
        if i + 1 >= m.n:
            continue
        side = -1 if r[i] > 0 else 1
        d = params['stop_pct'] / 100 * m.c[i]
        out.append(Signal(i, side, d, d, end_by_time(m, i, params['hold_s'])))
    return out
