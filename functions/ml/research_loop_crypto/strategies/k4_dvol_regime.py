"""K4, DVOL-vs-realized regime selects follow vs fade of N-day range breaks (prereg/k4_dvol_regime.json).

Per complete UTC day d (1,440 bars, none stale), needing days d-30..d all complete and consecutive:
    RV_d   = std(ddof 1) of the 30 daily log close-to-close returns ending at d * sqrt(365) * 100
    DVOL_d = Deribit DVOL close asof 00:00 of d+1 (max_age 7200 s)
    x_d    = ln(DVOL_d / RV_d); lo/hi = 1/3 and 2/3 quantiles of x over the previous `lookback` valid days (>= min_hist)
    break  = close_d > max(high of days d-N..d-1) (up) or close_d < min(low of days d-N..d-1) (down)
x_d >= hi: follow the break; x_d <= lo: fade it. The day joins the history after use. Decision on day d's last bar.
Stop = max(stop_atr * daily ATR(14) of the last UTC day completed before the decision bar's day, min_stop_pct %),
no target, time exit after hold_h hours.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, aggregate, daily_atr_before, end_by_time

WARMUP_DAYS = 230
CUR = {'BTCUSDT': 'BTC', 'ETHUSDT': 'ETH'}
DAY = 86400


def days(m, feats, p: dict):
    """Per UTC day in m: (last 1m index, x, break side, valid). break side: +1 up, -1 down, 0 none."""
    d = aggregate(m, m.t // DAY)
    day = m.t[d.first] // DAY
    cs = np.r_[0, np.cumsum(m.stale)]
    complete = ((d.last - d.first + 1) == 1440) & ((cs[d.last + 1] - cs[d.first]) == 0)
    n = len(day)
    W = p['rv_days']
    N = int(p['N'])
    x = np.full(n, np.nan)
    brk = np.zeros(n, int)
    ok = np.zeros(n, bool)
    dv = feats.dvol(CUR[m.symbol])
    T = (day + 1) * DAY
    vals, _ = dv.asof(T, max_age=7200)
    dvol = vals['close']
    logc = np.log(d.c)
    for i in range(W, n):
        win = slice(i - W, i + 1)
        if not complete[win].all() or day[i] - day[i - W] != W:
            continue
        rv = float(np.std(np.diff(logc[win]), ddof=1)) * np.sqrt(365) * 100
        if not (rv > 0 and np.isfinite(dvol[i]) and dvol[i] > 0):
            continue
        x[i] = np.log(dvol[i] / rv)
        hi, lo = d.h[i - N:i].max(), d.l[i - N:i].min()
        brk[i] = 1 if d.c[i] > hi else (-1 if d.c[i] < lo else 0)
        ok[i] = True
    return d.last, x, brk, ok


def picks(x: np.ndarray, brk: np.ndarray, ok: np.ndarray, p: dict) -> list[tuple[int, int]]:
    hist, out = [], []
    for i in np.flatnonzero(ok):
        if len(hist) >= p['min_hist'] and brk[i] != 0:
            h = np.asarray(hist[-p['lookback']:])
            lo, hi = np.quantile(h, 1 / 3), np.quantile(h, 2 / 3)
            if x[i] >= hi:
                out.append((int(i), int(brk[i])))
            elif x[i] <= lo:
                out.append((int(i), -int(brk[i])))
        hist.append(float(x[i]))
    return out


def signals(m, feats, params) -> list[Signal]:
    if m.symbol not in CUR or m.n == 0:
        return []
    last, x, brk, ok = days(m, feats, params)
    atr = daily_atr_before(m, 14)
    out = []
    for i, side in picks(x, brk, ok, params):
        b = int(last[i])
        if b + 1 >= m.n:
            continue
        a = atr(b)
        if not np.isfinite(a):
            continue
        stop = max(params['stop_atr'] * a, params['min_stop_pct'] / 100 * m.c[b])
        out.append(Signal(b, side, float(stop), None, end_by_time(m, b, params['hold_h'] * 3600)))
    return out
