"""K3, taker-flow continuation with a premium filter (prereg/k3_taker_flow.json).

Per completed UTC hour [h, h+1h) with 60 clean 1m bars:
    imb  = (2 * sum taker_buy_volume - sum volume) / sum volume
    prem = mean Binance premium-index 1m close of the bars opening in the hour (>= 50 rows)
z_flow, z_prem against the previous `lookback` valid hours (>= min_hist, ddof 1); the hour joins the history after use.
Signal at the close of the bar opening h+59m when |z_flow| >= Z: side = sign(z_flow), skipped if side * z_prem >=
prem_cap. Stop = max(stop_atr * daily ATR(14) of the last completed UTC day, min_stop_pct % of the decision close),
no target, time exit after hold_h hours.
"""
from __future__ import annotations

import numpy as np

from eval.engine import Signal, daily_atr_before, end_by_time
from eval.features import hourly_from_bars

WARMUP_DAYS = 35


def hours(m, feats) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(hour start, imb, prem, valid) for every UTC hour present in m."""
    tb = m.bars['taker_buy_volume'].to_numpy(float)
    h = hourly_from_bars(m.t, {'volume': m.v, 'tb': tb}, stale=m.stale)
    start = h.stamp
    vol, buy = h.values['volume'], h.values['tb']
    with np.errstate(invalid='ignore', divide='ignore'):
        imb = (2 * buy - vol) / vol
    ok = (h.values['bars'] == 60) & (h.values['stale_bars'] == 0) & (vol > 0) & np.isfinite(imb)
    pr = feats.pmi('premium', m.symbol)
    prem = np.full(len(start), np.nan)
    if len(pr):
        ph = pr.stamp // 3600 * 3600
        cl = pr.values['close']
        good = np.isfinite(cl)
        u, inv = np.unique(ph[good], return_inverse=True)
        n = np.bincount(inv)
        mean = np.bincount(inv, cl[good]) / n
        j = np.minimum(np.searchsorted(u, start), max(len(u) - 1, 0))
        if len(u):
            hit = (u[j] == start) & (n[j] >= 50)
            prem = np.where(hit, mean[j], np.nan)
    ok &= np.isfinite(prem)
    return start, imb, prem, ok


def picks(imb: np.ndarray, prem: np.ndarray, ok: np.ndarray, p: dict) -> list[tuple[int, int]]:
    """(hour position, side) for every signal; history is updated after use."""
    hf, hp, out = [], [], []
    for i in np.flatnonzero(ok):
        if len(hf) >= p['min_hist']:
            f, q = np.asarray(hf[-p['lookback']:]), np.asarray(hp[-p['lookback']:])
            sf, sq = float(np.std(f, ddof=1)), float(np.std(q, ddof=1))
            if sf > 0 and sq > 0:
                zf = (imb[i] - f.mean()) / sf
                zp = (prem[i] - q.mean()) / sq
                side = 1 if zf > 0 else -1
                if abs(zf) >= p['Z'] and side * zp < p['prem_cap']:
                    out.append((int(i), side))
        hf.append(float(imb[i]))
        hp.append(float(prem[i]))
    return out


def signals(m, feats, params) -> list[Signal]:
    if m.n == 0:
        return []
    start, imb, prem, ok = hours(m, feats)
    atr = daily_atr_before(m, 14)
    out = []
    for i, side in picks(imb, prem, ok, params):
        want = start[i] + 3540
        b = int(np.searchsorted(m.t, want))
        if b >= m.n or m.t[b] != want or b + 1 >= m.n:
            continue
        a = atr(b)
        if not np.isfinite(a):
            continue
        stop = max(params['stop_atr'] * a, params['min_stop_pct'] / 100 * m.c[b])
        out.append(Signal(b, side, float(stop), None, end_by_time(m, b, params['hold_h'] * 3600)))
    return out
