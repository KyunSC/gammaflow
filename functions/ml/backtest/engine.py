"""Bar-by-bar simulation. Port of frontend/lib/backtest/engine.js; parity is tested trade for trade.

Order of events inside one bar, and why:
  1. fill any order queued on the previous bar, at THIS bar's open
  2. check stop / target against this bar's high and low
  3. check time, end-of-session, flat-by and news exits (filled at this bar's close)
  4. mark equity to this bar's close
  5. ask the strategy for a target position using data up to this close; a change queues an order for the
     next bar's open

Signals are always acted on one bar late. That rule is what separates a backtest from a look-ahead fantasy,
so the engine enforces it instead of trusting each strategy to.

Why a Python loop and not vectorised numpy: stops, targets, lockouts and "flat by 16:45" make each bar depend
on the position the previous bar left behind. That is a state machine, and a state machine is a loop.
Vectorised backtests (positions = signal.shift(1), pnl = positions * returns) are fine for always-in-market
signals, but they cannot express an intrabar stop honestly.
"""
from __future__ import annotations

import math
import time as _time
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .metrics import buy_hold_curve, compute_metrics, dataset_periods_per_year
from .news import bar_seconds, news_blackout_flags
from .series import flat_by_flags, get_series, session_end_flags

DEFAULT_COSTS = dict(
    initial_capital=100_000.0,
    slippage_bps=1.5,          # per side, applied inside the fill price
    commission_per_trade=0.5,  # per side, dollars
    size_pct=1.0,              # fraction of equity per position (ignored with an instrument)
    instrument=None,           # see `Instrument`
)

DEFAULT_RISK = dict(
    stop_pct=0.0,              # 0 = off
    target_pct=0.0,            # 0 = off
    max_bars=0,                # 0 = off
    flat_at_session_end=False,
    allow_short=True,
    flat_by_et=0,              # minutes after midnight ET to be flat by (16:45 = 1005); 0 = off
    # Flat through scheduled news: dict(impact='high'|'medium'|'low', before_min=5, after_min=15,
    # max_bar_min=None) or None. max_bar_min skips the rule on bars longer than that.
    news_blackout=None,
)


@dataclass
class Instrument:
    """Fixed-size futures sizing instead of a fraction of equity. `price_scale` turns ETF bars into futures
    points (QQQ -> NQ is ~41.2) and is 1 on real futures bars. Slippage is in ticks, commission per contract
    per side."""
    point_value: float
    tick_size: float
    contracts: int = 1
    commission_per_side: float = 0.0
    slippage_ticks: float = 0.0
    price_scale: float = 1.0


class Exit:
    SIGNAL = "signal"
    STOP = "stop"
    TARGET = "target"
    TIME = "time"
    SESSION = "session"
    NEWS = "news"
    END = "end-of-data"


@dataclass
class Trade:
    side: str            # 'long' | 'short'
    entry_idx: int
    entry_time: float    # epoch seconds
    entry_price: float   # fill, slippage included
    exit_idx: int
    exit_time: float
    exit_price: float
    qty: float           # shares, or contracts x point value
    pnl: float           # net of both commissions; slippage is already in the fills
    pnl_pct: float       # pnl / entry notional
    gross_pct: float
    fees: float
    bars: int
    reason: str
    mfe: float           # best excursion while open, as a fraction of entry
    mae: float


@dataclass
class BacktestResult:
    equity: np.ndarray
    returns: np.ndarray
    positions: np.ndarray
    trades: list
    metrics: dict
    buy_hold: np.ndarray
    window_start: int
    window_end: int
    bar_lo: np.ndarray | None = None
    bar_hi: np.ndarray | None = None
    bar_open: np.ndarray | None = None
    news_uncovered_bars: int = 0
    news_skipped: bool = False
    elapsed_ms: float = 0.0
    config: dict = field(default_factory=dict)

    def trades_frame(self) -> pd.DataFrame:
        """Trades as a DataFrame with UTC timestamps, for analysis in a notebook."""
        df = pd.DataFrame([asdict(t) for t in self.trades])
        if len(df):
            for k in ("entry_time", "exit_time"):
                df[k] = pd.to_datetime(df[k], unit="s", utc=True)
        return df


def _instrument(x):
    if x is None:
        return None
    inst = x if isinstance(x, Instrument) else Instrument(**x)
    return inst if inst.contracts > 0 and inst.point_value > 0 else None


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


def run_backtest(ds, strategy, params: dict | None = None, costs: dict | None = None, risk: dict | None = None,
                 window: tuple[int, int] | None = None) -> BacktestResult:
    """Run `strategy` over dataset `ds`. `window=(start, end)` trades only that inclusive bar range while
    indicators still see the full history, so a walk-forward fold gets the same warm-up as the full run."""
    t0 = _time.perf_counter()
    from .strategies import get_strategy
    if isinstance(strategy, str):
        strategy = get_strategy(strategy)
    p = {**strategy.defaults(), **(params or {})}
    c = {**DEFAULT_COSTS, **(costs or {})}
    r = {**DEFAULT_RISK, **(risk or {})}
    unknown = (set(c) - set(DEFAULT_COSTS)) | (set(r) - set(DEFAULT_RISK))
    if unknown:
        raise ValueError(f"unknown cost/risk keys: {sorted(unknown)}")
    n = len(ds.close)
    w_start = max(0, window[0] if window else 0)
    w_end = min(n - 1, window[1] if window else n - 1)

    inst = _instrument(c["instrument"])
    cap = float(c["initial_capital"])
    slip = c["slippage_bps"] / 10000
    slip_pts = (inst.slippage_ticks or 0) * (inst.tick_size or 0) if inst else 0.0
    commission = (inst.commission_per_side or 0) * inst.contracts if inst else c["commission_per_trade"]
    scale = inst.price_scale if inst and inst.price_scale > 0 else 1.0
    O, H, L, C = ((a if scale == 1 else a * scale).tolist() for a in (ds.open, ds.high, ds.low, ds.close))
    times = ds.time.tolist()

    state = strategy.prepare(ds, p)
    warmup = max(w_start, strategy.warmup(p, ds))
    session_break = session_end_flags(ds.time).tolist()
    session_end = session_break if r["flat_at_session_end"] else None
    flat_end = flat_blocked = None
    if r["flat_by_et"] > 0:
        e, b = flat_by_flags(ds.time, r["flat_by_et"])
        flat_end, flat_blocked = e.tolist(), b.tolist()
    rule = r["news_blackout"] if r["news_blackout"] and r["news_blackout"].get("impact") else None
    news_skipped = bool(rule and (rule.get("max_bar_min") or 0) > 0 and bar_seconds(ds) > rule["max_bar_min"] * 60)
    news_end = news_blocked = news_no_entry = None
    uncovered = 0
    if rule and not news_skipped:
        flags = get_series(ds, f"news:{rule['impact']}:{rule.get('before_min', 5)}:{rule.get('after_min', 15)}")
        e, b, ne, uncovered = news_blackout_flags(flags, w_start, w_end)
        news_end, news_blocked, news_no_entry = e.tolist(), b.tolist(), ne.tolist()

    equity = [cap] * n
    returns = [0.0] * n
    pos_series = np.zeros(n, dtype=np.int8)
    trades: list[Trade] = []
    bar_lo = [cap] * n if inst else None
    bar_hi = [cap] * n if inst else None
    bar_open = [cap] * n if inst else None

    # Mutable position state shared with the two helpers below (a namespace instead of a dozen `nonlocal`s).
    # pos is -1 short, 0 flat, +1 long.
    S = SimpleNamespace(cash=cap, eq=cap, pos=0, qty=0.0, entry_price=0.0, entry_idx=-1, stop_price=0.0,
                        target_price=0.0, mfe=0.0, mae=0.0, entry_fee=0.0)

    if inst:
        def buy_fill(px): return px + slip_pts
        def sell_fill(px): return max(0.0, px - slip_pts)
    else:
        def buy_fill(px): return px * (1 + slip)
        def sell_fill(px): return px * (1 - slip)

    def close_position(i, raw, reason):
        pos, qty, ep = S.pos, S.qty, S.entry_price
        fill = sell_fill(raw) if pos > 0 else buy_fill(raw)
        gross = (fill - ep) * qty if pos > 0 else (ep - fill) * qty
        S.cash += fill * qty if pos > 0 else -fill * qty
        S.cash -= commission
        fees = S.entry_fee + commission
        net = gross - fees
        notional = ep * qty
        trades.append(Trade(
            side="long" if pos > 0 else "short", entry_idx=S.entry_idx, entry_time=times[S.entry_idx],
            entry_price=ep, exit_idx=i, exit_time=times[i], exit_price=fill, qty=qty, pnl=net,
            pnl_pct=net / notional if notional > 0 else 0.0,
            gross_pct=fill / ep - 1 if pos > 0 else ep / fill - 1,
            fees=fees, bars=i - S.entry_idx, reason=reason, mfe=S.mfe, mae=S.mae))
        S.pos, S.qty, S.entry_idx, S.mfe, S.mae = 0, 0.0, -1, 0.0, 0.0

    def open_position(i, d, raw):
        fill = buy_fill(raw) if d > 0 else sell_fill(raw)
        if not fill > 0:
            return
        qty = inst.contracts * inst.point_value if inst else max(0.0, S.eq * c["size_pct"]) / fill
        if not qty > 0:
            S.qty = 0.0
            return
        S.qty = qty
        S.cash -= fill * qty if d > 0 else -fill * qty
        S.cash -= commission
        S.entry_fee = commission
        S.pos, S.entry_price, S.entry_idx, S.mfe, S.mae = d, fill, i, 0.0, 0.0
        sp, tp = r["stop_pct"], r["target_pct"]
        S.stop_price = (fill * (1 - sp / 100) if d > 0 else fill * (1 + sp / 100)) if sp > 0 else 0.0
        S.target_price = (fill * (1 + tp / 100) if d > 0 else fill * (1 - tp / 100)) if tp > 0 else 0.0

    pending = None      # target position queued for the next open
    bars_in_market = 0
    prev_target = 0
    # Direction closed by a stop, target or time exit. Re-entry that way waits until the strategy stops asking
    # for it or the session ends; otherwise a regime strategy whose condition is still true buys straight back
    # in and the "stop" becomes one-bar churn.
    lockout = 0
    max_bars = r["max_bars"]
    allow_short = r["allow_short"]
    signal = strategy.signal

    for i in range(w_start, w_end + 1):
        # 1. queued order fills at this bar's open
        if pending is not None:
            want, pending = pending, None
            if want != S.pos:
                if S.pos != 0:
                    close_position(i, O[i], Exit.SIGNAL)
                S.eq = S.cash
                if want != 0:
                    open_position(i, want, O[i])
        lo = hi = 0.0
        if inst:
            lo = hi = bar_open[i] = S.cash + S.pos * S.qty * O[i]

        # 2. intrabar stop / target. A bar that opens beyond a level fills at the open (you cannot fill at a
        # price the market gapped through). Stop is checked before target: when one bar spans both, the worse
        # fill is the only defensible assumption without tick data.
        if S.pos != 0:
            pos, ep = S.pos, S.entry_price
            if pos > 0:
                fav, adv = H[i] / ep - 1, L[i] / ep - 1
            else:
                fav, adv = ep / L[i] - 1, ep / H[i] - 1
            S.mfe = max(S.mfe, fav)
            S.mae = min(S.mae, adv)
            sp, tp, o = S.stop_price, S.target_price, O[i]
            stop_hit = sp > 0 and (L[i] <= sp if pos > 0 else H[i] >= sp)
            target_hit = tp > 0 and (H[i] >= tp if pos > 0 else L[i] <= tp)
            gap_stop = stop_hit and (o <= sp if pos > 0 else o >= sp)
            gap_target = target_hit and (o >= tp if pos > 0 else o <= tp)
            adv_eq = S.cash + pos * S.qty * (L[i] if pos > 0 else H[i])
            fav_eq = S.cash + pos * S.qty * (H[i] if pos > 0 else L[i])
            if gap_stop:
                close_position(i, o, Exit.STOP)
            elif gap_target:
                close_position(i, o, Exit.TARGET)
            elif stop_hit:
                close_position(i, sp, Exit.STOP)
            elif target_hit:
                close_position(i, tp, Exit.TARGET)
            if inst:
                lo = min(lo, S.cash if stop_hit else adv_eq)
                if not stop_hit:
                    hi = max(hi, S.cash if target_hit else fav_eq)
            if S.pos == 0:
                S.eq = S.cash
                lockout = pos
                prev_target = 0

        # 3. time, session, flat-by and news exits, filled at this bar's close
        if S.pos != 0 and max_bars > 0 and i - S.entry_idx >= max_bars:
            lockout = S.pos
            close_position(i, C[i], Exit.TIME)
            S.eq = S.cash
            prev_target = 0
        flat_now = bool((session_end and session_end[i]) or (flat_end and flat_end[i]))
        if flat_now:
            if S.pos != 0:
                close_position(i, C[i], Exit.SESSION)
                S.eq = S.cash
            prev_target = 0
        # News: flat at the close of the bar before the window. No lockout afterwards; re-entering after the
        # window is allowed and pays its own round trip.
        if news_end and news_end[i]:
            if S.pos != 0:
                close_position(i, C[i], Exit.NEWS)
                S.eq = S.cash
            prev_target = 0
        # A new session is a fresh start: yesterday's stop does not veto today.
        if session_break[i]:
            lockout = 0
        if S.pos != 0 and i == w_end:
            close_position(i, C[i], Exit.END)
            S.eq = S.cash

        # 4. mark to market
        S.eq = S.cash + S.pos * S.qty * C[i]
        equity[i] = S.eq
        if inst:
            bar_lo[i] = min(lo, S.eq)
            bar_hi[i] = max(hi, S.eq)
        returns[i] = equity[i] / equity[i - 1] - 1 if i > w_start and equity[i - 1] > 0 else 0.0
        pos_series[i] = S.pos
        if S.pos != 0:
            bars_in_market += 1

        # 5. the strategy speaks; its order lands on the next bar
        if warmup <= i < w_end:
            target = signal(i, state, ds, p, prev_target)
            if target is None or not math.isfinite(target):
                target = prev_target
            target = max(-1, min(1, _js_round(target)))
            if target < 0 and not allow_short:
                target = 0
            if flat_now or (flat_blocked and flat_blocked[i]):
                target = 0
            if news_blocked and news_blocked[i]:
                target = 0
            prev_target = target
            if lockout != 0:
                if target == lockout:
                    target = 0
                else:
                    lockout = 0
            # Nothing new on the bar before a news exit: it would fill at the next open and be closed at that
            # bar's close, a round trip for nothing.
            if news_no_entry and news_no_entry[i] and target != S.pos:
                target = 0
            if target != S.pos:
                pending = target

    equity_a = np.array(equity)
    returns_a = np.array(returns)
    metrics = compute_metrics(equity_a[w_start:w_end + 1], returns_a[w_start:w_end + 1], trades, bars_in_market,
                              dataset_periods_per_year(ds), cap)
    return BacktestResult(
        equity=equity_a, returns=returns_a, positions=pos_series, trades=trades, metrics=metrics,
        buy_hold=buy_hold_curve(ds, cap, w_start), window_start=w_start, window_end=w_end,
        bar_lo=np.array(bar_lo) if inst else None, bar_hi=np.array(bar_hi) if inst else None,
        bar_open=np.array(bar_open) if inst else None,
        news_uncovered_bars=uncovered if news_end is not None else 0, news_skipped=news_skipped,
        elapsed_ms=(_time.perf_counter() - t0) * 1000,
        config=dict(strategy_id=strategy.id, params=dict(p), costs=c, risk=r, dataset_id=ds.id, symbol=ds.symbol,
                    interval=ds.interval, bars=n))


def summarize(result: BacktestResult) -> dict:
    """The headline numbers only, for sweep cells and walk-forward folds."""
    m = result.metrics
    keys = ("sharpe", "sortino", "total_return", "max_dd", "hit_rate", "profit_factor", "n_trades", "exposure",
            "final_equity")
    return {"sr": m["inference"]["sr"], **{k: m[k] for k in keys}}
