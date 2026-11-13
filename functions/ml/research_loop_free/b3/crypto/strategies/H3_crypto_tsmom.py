"""H3, crypto time-series momentum; spec in prereg/H3_crypto_tsmom.json.

Daily decision on the 23:59 UTC bar: side = sign(c[s] / c[L days earlier] - 1), entry at 00:00 UTC, 1:1 bracket of
max(30-day daily sd, floor) x price, time exit hold_s after entry. series='always_long' is the report-only control.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 32


def daily_closes(m):
    i = np.flatnonzero((m.t + 60) % 86400 == 0)
    return dict(zip((m.t[i] // 86400).tolist(), m.c[i].tolist()))


def daily_sd(closes, day, n):
    c = [closes.get(d) for d in range(day - n, day + 1)]
    if any(x is None or x <= 0 for x in c):
        return None
    return float(np.diff(np.log(np.asarray(c))).std(ddof=1))


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    closes = daily_closes(m)
    lag = params['L'] * 86400
    out = []
    for s in np.flatnonzero((m.t + 60) % 86400 == 0):
        s = int(s)
        if s + 1 >= m.n or m.stale[s]:
            continue
        a = int(np.searchsorted(m.t, m.t[s] - lag))
        if a >= m.n or m.t[a] != m.t[s] - lag or m.stale[a]:
            continue
        r = m.c[s] / m.c[a] - 1
        if r == 0:
            continue
        sd = daily_sd(closes, int(m.t[s] // 86400), params['sd_days'])
        if sd is None:
            continue
        side = 1 if params.get('series', 'tsmom') == 'always_long' else (1 if r > 0 else -1)
        d = max(sd, params['floor_pct'] / 100) * m.c[s]
        out.append(Signal(s, side, d, d, end_by_time(m, s, params['hold_s'])))
    return out
