"""K2, OI-backed 4h moves continue (prereg/k2_oi_backed.json).

At every UTC 4h boundary T (signal bar = the 1m bar opening T-60):
    r   = ln(close at T / close at T-4h), all 240 bars of (T-4h, T] present and none stale
    dOI = ln(OI_T / OI_{T-4h}), Binance sum_open_interest asof each boundary with max_age 600 s
sd_r, sd_oi = sample std over the previous `lookback` valid boundaries (>= min_hist); the boundary joins the history
after it is used. Signal when |r| >= k * sd_r and dOI >= oi_z * sd_oi; side = sign(r). Stop = max(stop_atr * daily
ATR(14) of the last completed UTC day, min_stop_pct % of the decision close), no target, time exit after hold_h hours.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, daily_atr_before, end_by_time

WARMUP_DAYS = 40
H4 = 4 * 3600


def boundaries(m, feats) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(signal bar index, r, dOI, valid) for every 4h boundary in m."""
    s = np.flatnonzero((m.t + 60) % H4 == 0)
    if len(s) == 0:
        z = np.zeros(0)
        return s, z, z, z.astype(bool)
    T = m.t[s] + 60
    j = np.minimum(np.searchsorted(m.t, T - H4 - 60), m.n - 1)
    ok = (m.t[j] == T - H4 - 60) & (s - j == 240)
    cs = np.r_[0, np.cumsum(m.stale)]
    ok &= (cs[s + 1] - cs[j + 1]) == 0
    with np.errstate(invalid='ignore', divide='ignore'):
        r = np.log(m.c[s] / m.c[j])
        oi = feats.metrics(m.symbol)
        now, _ = oi.asof(T, max_age=600)
        before, _ = oi.asof(T - H4, max_age=600)
        d = np.log(now['sum_open_interest'] / before['sum_open_interest'])
    ok &= np.isfinite(r) & np.isfinite(d)
    return s, r, d, ok


def picks(r: np.ndarray, d: np.ndarray, ok: np.ndarray, p: dict) -> list[tuple[int, int]]:
    """(position in the boundary arrays, side) for every signal; history is updated after use."""
    hr, hd, out = [], [], []
    for i in np.flatnonzero(ok):
        if len(hr) >= p['min_hist']:
            sr = float(np.std(hr[-p['lookback']:], ddof=1))
            sd = float(np.std(hd[-p['lookback']:], ddof=1))
            if sr > 0 and sd > 0 and abs(r[i]) >= p['k'] * sr and d[i] >= p['oi_z'] * sd:
                out.append((int(i), 1 if r[i] > 0 else -1))
        hr.append(float(r[i]))
        hd.append(float(d[i]))
    return out


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    s, r, d, ok = boundaries(m, feats)
    atr = daily_atr_before(m, 14)
    out = []
    for i, side in picks(r, d, ok, params):
        b = int(s[i])
        if b + 1 >= m.n:
            continue
        a = atr(b)
        if not np.isfinite(a):
            continue
        stop = max(params['stop_atr'] * a, params['min_stop_pct'] / 100 * m.c[b])
        out.append(Signal(b, side, float(stop), None, end_by_time(m, b, params['hold_h'] * 3600)))
    return out
