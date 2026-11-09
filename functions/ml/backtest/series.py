"""Indicators and session flags. Port of the parts of frontend/lib/backtest/series.js the engine and the
ported strategies use.

Why plain loops instead of pandas.rolling: parity. The JS SMA keeps a running sum (add the new bar, subtract
the old one); pandas sums each window afresh. Both are "correct", but they round differently in the last bit,
and a moving-average crossover compares two nearly equal numbers, so one ulp can move a trade by a bar. Each
function here repeats the JS arithmetic in the same order. Where numpy can do that exactly (np.cumsum is a
sequential left-to-right sum) it is used; np.sum is not, because it sums pairwise.

Warm-up positions are NaN. The engine reads NaN as "no opinion", which keeps the first N bars flat.
"""
from __future__ import annotations

import math

import numpy as np

from .clock import et_minute_of_day, trading_day

NA = math.nan


def sma(src, period: int) -> np.ndarray:
    src = np.asarray(src, dtype=np.float64)
    n = len(src)
    out = np.full(n, NA)
    period = int(period)
    if period < 1 or n < period:
        return out
    s = 0.0
    x = src.tolist()
    for i in range(n):
        s += x[i]
        if i >= period:
            s -= x[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(src, period: int) -> np.ndarray:
    src = np.asarray(src, dtype=np.float64)
    n = len(src)
    out = np.full(n, NA)
    period = int(period)
    if period < 1 or n < period:
        return out
    k = 2 / (period + 1)
    x = src.tolist()
    seed = 0.0
    for i in range(period):
        seed += x[i]
    prev = seed / period
    out[period - 1] = prev
    for i in range(period, n):
        prev = (x[i] - prev) * k + prev
        out[i] = prev
    return out


def stdev(src, period: int) -> np.ndarray:
    """Population standard deviation over a trailing window, around that window's SMA."""
    src = np.asarray(src, dtype=np.float64)
    n = len(src)
    out = np.full(n, NA)
    period = int(period)
    if period < 2 or n < period:
        return out
    mean = sma(src, period)
    win = np.lib.stride_tricks.sliding_window_view(src, period)          # row r = src[r : r + period]
    sq = (win - mean[period - 1:, None]) ** 2
    out[period - 1:] = np.sqrt(np.cumsum(sq, axis=1)[:, -1] / period)    # cumsum: same order as the JS loop
    return out


def rsi(src, period: int) -> np.ndarray:
    x = np.asarray(src, dtype=np.float64).tolist()
    n = len(x)
    out = np.full(n, NA)
    period = int(period)
    if n <= period:
        return out
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = x[i] - x[i - 1]
        if d >= 0:
            gain += d
        else:
            loss -= d
    gain /= period
    loss /= period
    out[period] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for i in range(period + 1, n):
        d = x[i] - x[i - 1]
        gain = (gain * (period - 1) + max(d, 0.0)) / period
        loss = (loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def atr(ds, period: int) -> np.ndarray:
    """Simple-average true range (not Wilder's smoothing), matching the JS and the chart."""
    h, l, c = ds.high, ds.low, ds.close
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    return sma(tr, period)


def vwap(ds) -> np.ndarray:
    """Session-anchored VWAP on typical price; resets each trading day (18:00 ET for Globex)."""
    day = trading_day(ds.time).tolist()
    h, l, c, v = ds.high.tolist(), ds.low.tolist(), ds.close.tolist(), ds.volume.tolist()
    n = len(c)
    out = np.full(n, NA)
    cur = None
    pv = vv = 0.0
    for i in range(n):
        if day[i] != cur:
            cur, pv, vv = day[i], 0.0, 0.0
        tp = (h[i] + l[i] + c[i]) / 3
        vol = v[i] if v[i] == v[i] else 0.0  # NaN volume counts as 0, like `volume[i] || 0`
        pv += tp * vol
        vv += vol
        out[i] = pv / vv if vv > 0 else tp
    return out


def session_end_flags(time) -> np.ndarray:
    """True on the last bar of each trading day (flat-at-close)."""
    day = trading_day(time)
    out = np.ones(len(day), dtype=bool)
    out[:-1] = day[1:] != day[:-1]
    return out


def flat_by_flags(time, cutoff_minute: int):
    """Prop-firm "flat by" cutoff (e.g. 16:45 ET = 1005). `end[i]`: last bar of the trading day that opens
    before the cutoff (positions close at its close). `blocked[i]`: bars at or after the cutoff, before the
    18:00 ET reopen, which may not open anything."""
    m = et_minute_of_day(time)
    blocked = (m >= cutoff_minute) & (m < 18 * 60)
    day = trading_day(time)
    nxt_blocked = np.r_[blocked[1:], True]          # past the end counts as "next is blocked"
    new_day = np.r_[day[1:] != day[:-1], True]
    end = ~blocked & (nxt_blocked | new_day)
    return end, blocked


def get_series(ds, key: str) -> np.ndarray:
    """Named-series resolver with the JS key grammar (`sma:20`, `bbUpper:20:2`, `f:net_gex`, `ml:pred`, ...),
    memoised on the dataset so a parameter sweep computes each distinct series once."""
    hit = ds.cache.get(key)
    if hit is not None:
        return hit
    built = _build(ds, key)
    ds.cache[key] = built
    return built


def _build(ds, key: str) -> np.ndarray:
    n = len(ds.close)
    name, *args = str(key).split(":")

    def p(idx, default):
        return default if idx >= len(args) else float(args[idx])

    if name in ("open", "high", "low", "close", "volume"):
        return getattr(ds, name)
    if name == "hl2":
        return (ds.high + ds.low) / 2
    if name == "typical":
        return (ds.high + ds.low + ds.close) / 3
    if name == "sma" or name == "bbMid":
        return sma(ds.close, int(p(0, 20)))
    if name == "ema":
        return ema(ds.close, int(p(0, 21)))
    if name == "rsi":
        return rsi(ds.close, int(p(0, 14)))
    if name == "atr":
        return atr(ds, int(p(0, 14)))
    if name == "stdev":
        return stdev(ds.close, int(p(0, 20)))
    if name == "vwap":
        return vwap(ds)
    if name in ("bbUpper", "bbLower"):
        period, mult = int(p(0, 20)), p(1, 2)
        mid, sd = sma(ds.close, period), stdev(ds.close, period)
        sign = 1 if name == "bbUpper" else -1
        return mid + sign * mult * sd  # NaN propagates through the warm-up, as in the JS guard
    if name == "news":
        from .news import news_window_flags
        return news_window_flags(ds, min_impact=args[0] if args else "high", before_min=p(1, 5), after_min=p(2, 15))
    if name == "f":
        col = ds.features.get(":".join(args))
        return col if col is not None else np.full(n, NA)
    if name == "ml":
        col = ds.ml.get(":".join(args))
        return col if col is not None else np.full(n, NA)
    raise KeyError(f"series {key!r} is not ported to Python yet (see backtest/README.md)")
