"""K1, Coinbase premium continuation (prereg/k1_cb_premium.json).

Per 5m Coinbase bar stamped t in [09:30, 16:00) ET on a NY weekday, all prices referring to t + 300:
    g_t = ln(CB close) - ln(Binance perp close of the 1m bar opening t+240) - ln(USDT-USD close stamped t)
          - ln(1 + Binance premium-index close of the 1m bar opening t+240)
G_d = mean g_t in bp (>= min_samples samples), z_d against the previous lookback_days valid days (>= min_hist).
Decision at the close of the 1m bar opening 15:59 ET; |z_d| >= z -> side = sign(z_d), stop = max(stop_atr * ATR14 of
the last completed UTC day, min_stop_pct % of the decision close), no target, time exit after hold_h hours.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from eval.config import ET
from eval.engine import Signal, daily_atr_before, end_by_time

WARMUP_DAYS = 90
CB = {'BTCUSDT': 'BTC-USD', 'ETHUSDT': 'ETH-USD'}
US_OPEN, US_CLOSE, DECIDE = 570, 960, 959      # NY minutes: 09:30, 16:00, bar opening 15:59


def _exact(stamps: np.ndarray, want: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index of the row stamped exactly `want` (ok mask, clipped index)."""
    if len(stamps) == 0:
        return np.zeros(len(want), bool), np.zeros(len(want), int)
    j = np.minimum(np.searchsorted(stamps, want), len(stamps) - 1)
    return stamps[j] == want, j


def ny_days(t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ny = pd.to_datetime(np.asarray(t, np.int64), unit='s', utc=True).tz_convert(ET)
    day = (ny.tz_localize(None).normalize() - pd.Timestamp(0)).days.to_numpy()
    return day, (ny.hour * 60 + ny.minute).to_numpy(), ny.dayofweek.to_numpy()


def gap_samples(m, feats, product: str) -> tuple[np.ndarray, np.ndarray]:
    """(NY day, g in log units) for every usable US-hours 5m sample."""
    cb, usdt, prem = feats.coinbase(product), feats.coinbase('USDT-USD'), feats.pmi('premium', m.symbol)
    t = cb.stamp
    if len(t) == 0:
        return np.zeros(0, int), np.zeros(0)
    day, mins, dow = ny_days(t)
    keep = (mins >= US_OPEN) & (mins < US_CLOSE) & (dow < 5)
    ok_b, i = _exact(m.t, t + 240)
    ok_b &= ~m.stale[i]
    ok_u, j = _exact(usdt.stamp, t)
    ok_p, k = _exact(prem.stamp, t + 240)
    ok = keep & ok_b & ok_u & ok_p
    with np.errstate(invalid='ignore', divide='ignore'):
        g = (np.log(cb.values['close']) - np.log(m.c[i]) - np.log(usdt.values['close'][j] if len(usdt) else np.nan)
             - np.log1p(prem.values['close'][k] if len(prem) else np.nan))
    ok &= np.isfinite(g)
    return day[ok], g[ok]


def daily_z(day: np.ndarray, g: np.ndarray, p: dict) -> dict[int, float]:
    """NY day -> z of that day's mean gap (bp) against the previous valid days; history updated after use."""
    out, hist = {}, []
    if len(day) == 0:
        return out
    u, inv = np.unique(day, return_inverse=True)
    n = np.bincount(inv)
    mean_bp = np.bincount(inv, g) / n * 1e4
    for d, cnt, G in zip(u, n, mean_bp):
        if cnt < p['min_samples']:
            continue
        h = hist[-p['lookback_days']:]
        if len(h) >= p['min_hist']:
            sd = float(np.std(h, ddof=1))
            if sd > 0:
                out[int(d)] = (G - float(np.mean(h))) / sd
        hist.append(float(G))
    return out


def signals(m, feats, params) -> list[Signal]:
    product = CB.get(m.symbol)
    if product is None or m.n == 0:
        return []
    zs = daily_z(*gap_samples(m, feats, product), params)
    at = np.flatnonzero(m.ny_min == DECIDE)
    atr = daily_atr_before(m, 14)
    out = []
    for s in at:
        z = zs.get(int(m.ny_date[s]))
        if z is None or abs(z) < params['z'] or m.stale[s] or s + 1 >= m.n:
            continue
        a = atr(int(s))
        if not np.isfinite(a):
            continue
        stop = max(params['stop_atr'] * a, params['min_stop_pct'] / 100 * m.c[s])
        out.append(Signal(int(s), 1 if z > 0 else -1, float(stop), None, end_by_time(m, int(s), params['hold_h'] * 3600)))
    return out
