"""Performance statistics for a finished run. Port of frontend/lib/backtest/metrics.js.

Everything except the trade-level stats (hit rate, profit factor, expectancy) comes from the per-bar equity
curve. Annualisation uses the bars a trading day actually has, so 23-hour futures and RTH equities each get
their own clock.
"""
from __future__ import annotations

import math

import numpy as np

from .clock import trading_day
from .stats import sharpe_inference

TRADING_DAYS = 252
RTH_MINUTES = 390
INTRADAY_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "4h": 240}


def _js_round(x: float) -> int:
    """JavaScript Math.round: halves go up (Python's round() goes to even, so round(2.5) == 2)."""
    return math.floor(x + 0.5)


def periods_per_year(interval: str) -> float:
    m = INTRADAY_MINUTES.get(interval)
    if m:
        return TRADING_DAYS * max(1, _js_round(RTH_MINUTES / m))
    return {"1d": TRADING_DAYS, "1wk": 52, "1mo": 12}.get(interval, TRADING_DAYS)


def dataset_periods_per_year(ds) -> float:
    """Intraday: 252 x the median bars per trading day the data really has (needs 3+ days)."""
    fallback = periods_per_year(ds.interval)
    if ds.interval not in INTRADAY_MINUTES or not len(ds.time):
        return fallback
    hit = ds.cache.get("#ppy")
    if hit is not None:
        return hit
    day = trading_day(ds.time)
    counts = np.diff(np.r_[0, np.flatnonzero(day[1:] != day[:-1]) + 1, len(day)])
    ppy = TRADING_DAYS * float(np.median(counts)) if len(counts) >= 3 else fallback
    ds.cache["#ppy"] = ppy
    return ppy


def _mean(a) -> float:
    return float(np.cumsum(a)[-1]) / len(a) if len(a) else 0.0


def _std(a, ddof: int = 1) -> float:
    if len(a) <= ddof:
        return 0.0
    m = _mean(a)
    return math.sqrt(float(np.cumsum((np.asarray(a) - m) ** 2)[-1]) / (len(a) - ddof))


def sortino(returns, ppy: float) -> float:
    down = returns[returns < 0]
    if not len(down):
        return math.inf if _mean(returns) > 0 else 0.0
    dd = math.sqrt(float(np.cumsum(down ** 2)[-1]) / len(returns))
    return _mean(returns) / dd * math.sqrt(ppy) if dd > 0 else 0.0


def drawdown(equity) -> dict:
    """Max drawdown (positive fraction), the drawdown curve and the longest underwater stretch in bars."""
    eq = np.asarray(equity, dtype=np.float64)
    peak = eq[0] or 1.0
    max_dd = 0.0
    peak_idx = longest = trough = 0
    curve = np.zeros(len(eq))
    for i, e in enumerate(eq.tolist()):
        if e > peak:
            peak = e
            longest = max(longest, i - peak_idx)
            peak_idx = i
        dd = e / peak - 1 if peak > 0 else 0.0
        curve[i] = dd
        if dd < -max_dd:
            max_dd = -dd
            trough = i
    longest = max(longest, len(eq) - 1 - peak_idx)
    return dict(max_dd=max_dd, curve=curve, duration=longest, trough_idx=trough)


def compute_metrics(equity, returns, trades, bars_in_market: int, ppy: float, initial_capital: float) -> dict:
    n = len(equity)
    last = float(equity[-1]) if n else initial_capital
    total_return = last / initial_capital - 1 if initial_capital > 0 else 0.0
    years = n / ppy if n > 0 else 0.0
    cagr = (last / initial_capital) ** (1 / years) - 1 if years > 0 and last > 0 else 0.0
    dd = drawdown(equity)

    wins = 0
    gross_win = gross_loss = 0.0
    sum_bars = 0
    for t in trades:
        if t.pnl > 0:
            wins += 1
            gross_win += t.pnl
        else:
            gross_loss -= t.pnl
        sum_bars += t.bars
    nt = len(trades)
    losses = nt - wins
    inf = sharpe_inference(returns, ppy)
    max_dd = dd["max_dd"]
    return dict(
        total_return=total_return,
        final_equity=last,
        cagr=cagr,
        sharpe=inf["sharpe"],
        sortino=sortino(np.asarray(returns), ppy),
        vol_ann=_std(returns) * math.sqrt(ppy),
        max_dd=max_dd,
        max_dd_duration=dd["duration"],
        calmar=cagr / max_dd if max_dd > 0 else 0.0,
        hit_rate=wins / nt if nt else 0.0,
        profit_factor=gross_win / gross_loss if gross_loss > 0 else (math.inf if gross_win > 0 else 0.0),
        expectancy=(gross_win - gross_loss) / nt if nt else 0.0,
        avg_win=gross_win / wins if wins else 0.0,
        avg_loss=gross_loss / losses if losses else 0.0,
        n_trades=nt,
        avg_bars_held=sum_bars / nt if nt else 0.0,
        exposure=bars_in_market / n if n else 0.0,
        turnover=nt / years if years > 0 else 0.0,
        dd_curve=dd["curve"],
        periods_per_year=ppy,
        inference=inf,
    )


def buy_hold_curve(ds, initial_capital: float, start: int = 0) -> np.ndarray:
    """Buy-and-hold on the same capital, anchored at the first traded bar."""
    out = np.full(len(ds.close), float(initial_capital))
    out[start:] = (initial_capital * ds.close[start:]) / ds.close[start]
    return out
