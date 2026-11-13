"""G5, follow top traders' position lean against the all-accounts lean (prereg/G5_smart_vs_retail.json).

On each 1m bar whose close is a UTC 4h boundary: z_top = z(ln sum_toptrader_long_short_ratio), z_all =
z(ln count_long_short_ratio), each against its previous `win` grid samples (>= min_valid valid). d = z_top - z_all;
|d| >= D -> side = sign(d). series='top_only' (report-only control) uses z_top alone. Stop = target = stop_pct %, hold_s exit.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 35


def grid(m, step):
    return np.flatnonzero((m.t + 60) % step == 0)


def samples(vals, col):
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
    vals, _ = feats.metrics(m.symbol).asof(m.t[idx] + 60, max_age=params['max_age'])
    zt = zscores(samples(vals, params['top_col']), params['win'], params['min_valid'])
    series = params.get('series', 'divergence')
    if series == 'divergence':
        d = zt - zscores(samples(vals, params['all_col']), params['win'], params['min_valid'])
    elif series == 'top_only':
        d = zt
    else:
        raise ValueError('unknown series')
    out = []
    for j in np.flatnonzero(np.isfinite(d) & (np.abs(d) >= params['D'])):
        s = int(idx[j])
        if s + 1 >= m.n or m.stale[s]:
            continue
        dist = params['stop_pct'] / 100 * m.c[s]
        out.append(Signal(s, 1 if d[j] > 0 else -1, dist, dist, end_by_time(m, s, params['hold_s'])))
    return out
