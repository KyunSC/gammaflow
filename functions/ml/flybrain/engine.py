"""Fixed-size ETF-to-futures replay; next-open entry and session-close exit.

Optional exits (`exit_rule`): an ATR bracket that holds until its stop, its target or the session close, and the
Lucid daily loss limit, which flattens an open position where the session's P&L reaches -DLL and blocks new entries
for the rest of that session. `readout.dan_path` mirrors the same rule so the DAN learns from the trades it takes."""
from dataclasses import dataclass
import math
import numpy as np
from . import config

@dataclass
class Result:
    equity: np.ndarray
    bar_lo: np.ndarray
    bar_hi: np.ndarray
    bar_open: np.ndarray
    trades: list
    time: np.ndarray
    position: np.ndarray
    initial_capital: float

    @property
    def returns(self):
        return np.r_[0., np.divide(self.equity[1:], self.equity[:-1], out=np.ones(len(self.equity)-1), where=self.equity[:-1] > 0) - 1]


def exit_rule(params):
    """Bracket and Lucid daily-loss exits from run params; None keeps the plain hold-H-bars exit."""
    rr = float(params.get('rr', 0) or 0)
    dll = bool(params.get('lucid_dll', False))
    if not rr and not dll:
        return None
    stop_atr = float(params.get('stop_atr', 1.0))
    if rr < 0 or stop_atr <= 0:
        raise ValueError('rr must be >= 0 and stop_atr > 0')
    from .prop import resolve_plan
    return dict(rr=rr, stop_atr=stop_atr, dll=float(resolve_plan()['dailyLossLimit'] or 0) if dll else 0.)


def costs(symbol, n_contracts=config.N_CONTRACTS, slippage_ticks=config.SLIPPAGE_TICKS):
    """ETF-to-futures scale, dollars per scaled point, slippage per side and commission per side."""
    spec = config.CONTRACTS[config.SYMBOLS[symbol]]
    return config.RATIO[symbol], spec['point_value'] * n_contracts, slippage_ticks * spec['tick'], config.COMMISSION_PER_SIDE * n_contracts


def bracket(side, open_price, atr, rule):
    """(stop, target) around the entry bar's open, sized from the prior bar's ATR; (None, None) without a bracket."""
    if not rule or not rule['rr'] or not atr > 0:
        return None, None
    risk = rule['stop_atr'] * atr
    return open_price - side * risk, open_price + side * rule['rr'] * risk


def exit_fill(side, o, h, l, stop=None, target=None, floor=None):
    """Price where a position leaves this bar through its stop, the daily-loss floor or its target, else None.

    Adverse levels are checked first, so a bar that touches both sides fills the stop; a gap through a level
    fills at the open. Returns (price, adverse)."""
    adverse = [x for x in (stop, floor) if x is not None]
    if adverse:
        level = max(adverse) if side > 0 else min(adverse)  # the first one touched on the way against the trade
        if side * (o - level) <= 0:
            return o, True
        if (l if side > 0 else h) * side <= level * side:
            return level, True
    if target is not None:
        if side * (o - target) >= 0:
            return o, False
        if (h if side > 0 else l) * side >= target * side:
            return target, False
    return None, False


def daily_floor(side, qty, cash, day_base, dll):
    """Scaled price at which equity cash + side*qty*p falls to day_base - dll."""
    return side * (day_base - dll - cash) / qty if dll else None


def backtest(df, signal, symbol, max_hold, n_contracts=config.N_CONTRACTS, slippage_ticks=config.SLIPPAGE_TICKS, initial_capital=None, entry_holds=None, exits=None):
    if len(df) != len(signal) or max_hold < 1 or n_contracts < 1:
        raise ValueError('Invalid signal length, hold or contract count')
    if initial_capital is None:
        from .prop import resolve_plan
        initial_capital = resolve_plan()['startBalance']
    scale, qty, slip, fee = costs(symbol, n_contracts, slippage_ticks)
    dll = exits['dll'] if exits else 0.
    if exits and exits['rr']:
        if 'atr_14' not in df:
            raise ValueError('A bracket exit needs atr_14')
        ATR = (df.atr_14.to_numpy(float) * scale).tolist()
    n = len(df)
    equity, lo, hi, opening = np.zeros((4, n))
    positions = np.zeros(n, dtype=np.int8)
    # Python lists: per-element numpy scalar access dominates this loop.
    O,H,L,C = [(df[c].to_numpy(float) * scale).tolist() for c in ('open','high','low','close')]
    sessions = df.session.to_numpy().tolist()
    cash, side, pending, entry, entry_price = initial_capital, 0, 0, -1, 0.
    stop = target = None; day_base = cash; blocked = None
    trades=[]
    for i in range(n):
        end = i == n-1 or sessions[i+1] != sessions[i]
        if i == 0 or sessions[i] != sessions[i-1]:
            day_base = cash
        if pending and i and sessions[i] == sessions[i-1]:
            side, entry = pending, i
            entry_price = O[i] + side * slip
            trade_hold = int(entry_holds[i-1]) if entry_holds is not None else math.inf if exits and exits['rr'] else max_hold
            cash -= side * qty * entry_price + fee
            if exits and exits['rr']:
                stop, target = bracket(side, O[i], ATR[i-1], exits)
        pending = 0
        opening[i] = cash + side * qty * O[i]
        worst, best = (L[i], H[i]) if side > 0 else (H[i], L[i])
        fill, adverse = (exit_fill(side, O[i], H[i], L[i], stop, target, daily_floor(side, qty, cash, day_base, dll))
                         if side and exits else (None, False))
        if adverse:
            worst = fill
        low = min(opening[i], cash + side * qty * worst)
        high = max(opening[i], cash + side * qty * best)
        if side and (fill is not None or i-entry+1 >= trade_hold or end):
            raw = C[i] if fill is None else fill
            exit_price = raw - side * slip
            cash += side * qty * exit_price - fee
            trades.append(dict(entry_idx=entry, exit_idx=i, entry_price=entry_price, exit_price=exit_price,
                               raw_entry_price=O[entry]/scale, raw_exit_price=raw/scale, side=side,
                               pnl=side*qty*(exit_price-entry_price)-2*fee, hold=i-entry+1))
            side=0; stop = target = None
            if dll and cash - day_base <= -dll + 1e-9:
                blocked = sessions[i]
        equity[i] = cash + side * qty * C[i]
        lo[i], hi[i] = min(low,equity[i]), max(high,equity[i])
        positions[i]=side
        if not side and not end and sessions[i] != blocked:
            pending=int(signal[i])
    return Result(equity,lo,hi,opening,trades,df.date.astype('int64').to_numpy()/1e9,positions,initial_capital)
