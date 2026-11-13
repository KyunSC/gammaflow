"""G3, fade the 12h overnight move into the US equity session start; spec in prereg/G3_us_open_fade.json.

Decision on the bar with ny_min == anchor_min (09:29 ET, closing 09:30) on the listed ET weekdays. move = c[s] -
c[12h earlier]; scale = sd(30 complete-UTC-day log returns before the decision day) * c[s]. |move| >= m * scale ->
trade against the move at the next open, 1:1 at stop_pct %, exit hold_s after entry. session='asia' is the
report-only control (anchor 20:29 ET, Sun-Thu); its params come in the same dict.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 35


def daily_closes(m):
    """UTC day number -> close of that day's 23:59 bar."""
    i = np.flatnonzero((m.t + 60) % 86400 == 0)
    return dict(zip((m.t[i] // 86400).tolist(), m.c[i].tolist()))


def daily_sd(closes, day, n):
    c = [closes.get(d) for d in range(day - n - 1, day)]
    if any(x is None or x <= 0 for x in c):
        return None
    r = np.diff(np.log(np.asarray(c)))
    return float(r.std(ddof=1))


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    closes = daily_closes(m)
    dows = set(params['dows'])
    out = []
    for s in np.flatnonzero(m.ny_min == params['anchor_min']):
        s = int(s)
        if s + 1 >= m.n or int(m.ny_dow[s]) not in dows or m.stale[s]:
            continue
        a = int(np.searchsorted(m.t, m.t[s] - params['lookback_s']))
        if a >= m.n or m.t[a] != m.t[s] - params['lookback_s'] or m.stale[a]:
            continue
        sd = daily_sd(closes, int(m.t[s] // 86400), params['sd_days'])
        if sd is None or sd <= 0:
            continue
        move = m.c[s] - m.c[a]
        if abs(move) < params['m'] * sd * m.c[s] or move == 0:
            continue
        d = params['stop_pct'] / 100 * m.c[s]
        out.append(Signal(s, -1 if move > 0 else 1, d, d, end_by_time(m, s, params['hold_s'])))
    return out
