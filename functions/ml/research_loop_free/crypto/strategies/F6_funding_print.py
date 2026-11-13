"""F6, funding-print positioning (prereg/F6_funding_print.json).

At each funding print P (floored to the minute) whose |rate| is STRICTLY above the q-quantile of |rate| over the prior
prints in [P - 30d, P) (>= min_prints of them): signal on the 1m bar starting at P (the rate is fixed at the print, so
it is known at that bar's close), side = +1 if rate > 0 else -1, entry at print + 1 min, stop = target = stop_pct % of
the decision close, time exit at print + 4h.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, end_by_time

WARMUP_DAYS = 35
DAY = 86400


def prints(feats, symbol):
    f = feats.funding(symbol)
    return (f.stamp // 60) * 60, f.values['rate']


def picks(P: np.ndarray, rate: np.ndarray, p: dict) -> list[tuple[int, int]]:
    """(print index, side) of qualifying prints; uses prior prints only."""
    out = []
    a = np.abs(rate)
    lb = p['lookback_days'] * DAY
    for i in range(len(P)):
        lo = int(np.searchsorted(P, P[i] - lb, side='left'))
        if i - lo < p['min_prints'] or rate[i] == 0 or not np.isfinite(rate[i]):
            continue
        q = float(np.quantile(a[lo:i], p['q']))
        if a[i] > q:
            out.append((i, 1 if rate[i] > 0 else -1))
    return out


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    P, rate = prints(feats, m.symbol)
    out = []
    for i, side in picks(P, rate, params):
        s = int(np.searchsorted(m.t, P[i]))
        if s + 1 >= m.n or m.t[s] != P[i] or m.stale[s]:
            continue
        d = params['stop_pct'] / 100 * m.c[s]
        out.append(Signal(s, side, d, d, end_by_time(m, s, params['hold_s'])))
    return out
