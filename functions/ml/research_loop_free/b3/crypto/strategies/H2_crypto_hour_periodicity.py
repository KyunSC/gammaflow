"""H2, same-UTC-hour return periodicity; spec in prereg/H2_crypto_hour_periodicity.json.

At each UTC hour boundary: mu = mean of the same hour's log return over the previous N days (>= ceil(frac*N) valid);
side = sign(mu); 1:1 at stop_pct % of the close, time exit hold_s after entry. series='prev_hour' is the
report-only control (sign of the hour just ended).
"""
from __future__ import annotations

import math

import numpy as np

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 32


def bar_at(m, ts):
    """Index of the bar starting at ts (or -1), vectorised."""
    i = np.searchsorted(m.t, ts)
    ok = i < m.n
    j = np.where(ok, i, 0)
    hit = ok & (m.t[j] == ts) & ~m.stale[j]
    return np.where(hit, j, -1)


def hour_return(m, end_t):
    """ln(c[bar t == end_t] / c[bar t == end_t - 3600]); NaN when either bar is missing or stale."""
    b, a = bar_at(m, end_t), bar_at(m, end_t - 3600)
    ok = (a >= 0) & (b >= 0)
    out = np.full(len(end_t), np.nan)
    out[ok] = np.log(m.c[b[ok]] / m.c[a[ok]])
    return out


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    s_idx = np.flatnonzero((m.t + 60) % 3600 == 0)
    s_idx = s_idx[(s_idx + 1 < m.n) & ~m.stale[s_idx]]
    T = m.t[s_idx]
    if params.get('series', 'periodicity') == 'prev_hour':
        x = hour_return(m, T)
    else:
        n = params['N']
        r = np.stack([hour_return(m, T - d * 86400 + 3600) for d in range(1, n + 1)])
        valid = np.isfinite(r).sum(0)
        with np.errstate(invalid='ignore'):
            x = np.where(valid >= math.ceil(params['valid_frac'] * n), np.nanmean(np.where(np.isfinite(r), r, np.nan), 0), np.nan)
    out = []
    for s, v in zip(s_idx, x):
        if not np.isfinite(v) or v == 0:
            continue
        s = int(s)
        d = params['stop_pct'] / 100 * m.c[s]
        out.append(Signal(s, 1 if v > 0 else -1, d, d, end_by_time(m, s, params['hold_s'])))
    return out
