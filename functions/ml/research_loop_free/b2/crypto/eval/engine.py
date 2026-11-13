"""Execution model, twin tests and Elite EV replay of the crypto perp loop.

Verbatim port of mfp_crypto_study.py (MFP branch 416dbd4) lines 124-221, 238-251 and 334-638: market data,
signals container, 1m execution (next-1m-open entry, stop-first, gap-through at open, hourly swap, fixed $500 risk
under the leverage cap), mirror-flat books, side-matched twins, block bootstrap, Elite 50K 3% DLL EV and the planted
look-ahead / coin controls. Only the imports and constants block above the port differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from multiprocessing import Pool

import numpy as np
import pandas as pd

from .config import (COIN_CONTROLS, ET, EV_BLOCK_DAYS, EV_HORIZON_DAYS, EV_PATHS, EV_SEED, LOOKAHEAD_FRAC,  # noqa: F401
                     MARKETS, MAX_WORKERS, N_TWINS, R_BOOT, R_BOOT_BLOCK, SEED, STALE_RUN, SYMBOLS)
from .prop import resolve_plan, run_prop
from .stats import block_idx

PLAN = resolve_plan("elite", "50k", True, firm="mfp")
RISK_USD = 0.01 * PLAN["startBalance"]

# ---------------------------------------------------------------- market data

def iso(t) -> str:
    return pd.Timestamp(int(t), unit="s", tz="UTC").isoformat()


def run_starts(key: np.ndarray) -> np.ndarray:
    """Index of the first element of each run of equal values."""
    return np.r_[0, np.flatnonzero(np.diff(key)) + 1]


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    prev = np.r_[np.nan, c[:-1]]
    return np.fmax(h - l, np.fmax(np.abs(h - prev), np.abs(l - prev)))


@dataclass
class Market:
    symbol: str
    bars: pd.DataFrame
    funding: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __post_init__(self):
        b = self.bars
        self.t = b["time"].to_numpy(np.int64)
        self.o, self.h, self.l, self.c, self.v = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        self.n = len(self.t)
        ny = pd.to_datetime(self.t, unit="s", utc=True).tz_convert(ET)
        self.ny_min = (ny.hour * 60 + ny.minute).to_numpy()
        self.ny_dow = ny.dayofweek.to_numpy()
        self.ny_date = (ny.tz_localize(None).normalize() - pd.Timestamp(0)).days.to_numpy()
        # holes_before[i]: missing or stale bars between bar 0 and bar i. A trade spans a hole when it differs at its ends.
        self.stale = self._stale_runs()
        self.holes_before = np.cumsum(np.r_[False, np.diff(self.t) > 60] | self.stale)
        self.market = MARKETS[SYMBOLS.get(self.symbol, self.symbol)]

    def _zero_runs(self) -> list[tuple[int, int]]:
        """[start, end) of each run of zero-volume bars."""
        edges = np.flatnonzero(np.diff(np.r_[False, self.v == 0, False].astype(int)))
        return list(zip(edges[::2], edges[1::2]))

    def _stale_runs(self) -> np.ndarray:
        out = np.zeros(self.n, bool)
        for a, b in self._zero_runs():
            if b - a >= STALE_RUN:
                out[a:b] = True
        return out

    def stale_report(self) -> dict:
        runs = sorted(((b - a, a) for a, b in self._zero_runs()), reverse=True)
        return dict(zero_volume_bars=int((self.v == 0).sum()), stale_bars=int(self.stale.sum()),
                    longest=[dict(at=iso(self.t[a]), bars=int(k)) for k, a in runs[:10]])

    def holes(self) -> list[dict]:
        i = np.flatnonzero(np.diff(self.t) > 60)
        return [dict(after=iso(self.t[k]), missing_bars=int((self.t[k + 1] - self.t[k]) // 60 - 1)) for k in i]

    def at_or_after(self, ts) -> np.ndarray:
        return np.searchsorted(self.t, ts, side="left")


@dataclass
class Bars:
    """Bars aggregated over contiguous runs of `key`; first/last are 1m indices."""
    first: np.ndarray
    last: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    def atr(self, n: int) -> np.ndarray:
        return pd.Series(true_range(self.h, self.l, self.c)).rolling(n).mean().to_numpy()


def aggregate(m: Market, key: np.ndarray) -> Bars:
    first = run_starts(key)
    last = np.r_[first[1:] - 1, m.n - 1]
    return Bars(first, last, m.o[first], np.maximum.reduceat(m.h, first), np.minimum.reduceat(m.l, first), m.c[last],
                np.add.reduceat(m.v, first))


# ---------------------------------------------------------------- signals

@dataclass
class Signal:
    sig: int            # 1m index of the bar whose close fires the signal; entry is sig + 1
    side: int
    stop: float         # price distance
    target: float | None
    end: int            # last 1m index the trade may be held through
    trail: float | None = None


def end_by_time(m: Market, sig: int, seconds: float) -> int:
    return int(m.at_or_after(m.t[sig + 1] + seconds)) - 1 if sig + 1 < m.n else m.n - 1


def daily_atr_before(m: Market, n: int):
    """i -> ATR(n) of the last UTC day completed before 1m index i."""
    d = aggregate(m, m.t // 86400)
    atr = d.atr(n)

    def at(i: int) -> float:
        j = int(np.searchsorted(d.last, i, side="left"))
        return atr[j - 1] if j > 0 else np.nan
    return at


def ny_time(day: int, days: int = 0, hours: float = 0) -> int:
    """Epoch seconds of a wall-clock time in New York, `days` and `hours` after midnight of NY day number `day`."""
    return int((pd.Timestamp(day, unit="D") + pd.Timedelta(days=days, hours=hours)).tz_localize(ET).timestamp())

# ---------------------------------------------------------------- execution

def slip_bps(market: dict, notional: float) -> float:
    for ceiling, bps in market["slippage"]:
        if ceiling is None or notional <= ceiling:
            return bps
    return market["slippage"][-1][1]


@dataclass
class Leg:
    side: int
    exit: int
    reason: str
    pnl: float
    r: float
    qty: float
    costs: float
    # Hourly equity segments, P&L relative to the trade's start: [time, open, lo, hi, close, position-at-close]
    seg: np.ndarray


def simulate(m: Market, e: int, sg: Signal, side: int) -> Leg:
    """One side of a signal on 1m bars. Prices are mapped to x = side * price so one long-only rule covers both."""
    sl = slice(e, sg.end + 1)
    xo, xc = side * m.o[sl], side * m.c[sl]
    xh, xl = (m.h[sl], m.l[sl]) if side > 0 else (-m.l[sl], -m.h[sl])
    px0, x0 = m.o[e], side * m.o[e]
    stop = np.full(len(xo), x0 - sg.stop)
    if sg.trail is not None:
        dayend = np.r_[np.diff(m.t[sl] // 86400) != 0, False]
        best = np.maximum.accumulate(np.where(dayend, xc, -np.inf))
        stop = np.maximum(stop, np.r_[-np.inf, best[:-1]] - sg.trail)
    tgt = x0 + sg.target if sg.target is not None else np.inf
    hit_s, hit_t = xl <= stop, xh >= tgt
    hit = hit_s | hit_t
    j = int(np.argmax(hit)) if hit.any() else len(xo) - 1
    if hit[j] and hit_s[j]:
        xf, reason = min(xo[j], stop[j]), "stop"
    elif hit[j]:
        xf, reason = tgt, "target"
    else:
        xf, reason = xc[j], "block-end" if sg.end == m.n - 1 and j == len(xo) - 1 else "time"

    mk = m.market
    lev_cap = mk["leverage"] * PLAN["startBalance"]
    qty = min(RISK_USD / sg.stop, lev_cap / px0)
    px1 = abs(xf)
    slip0, slip1 = slip_bps(mk, qty * px0) / 1e4, slip_bps(mk, qty * px1) / 1e4
    xe, xx = x0 + slip0 * px0, xf - slip1 * px1
    fee0, fee1 = mk["commissionBps"] / 1e4 * qty * px0, mk["commissionBps"] / 1e4 * qty * px1
    hours = np.r_[0, np.diff(m.t[e:e + j + 1] // 3600)]
    swap = np.cumsum(hours * mk["swapDailyBps"] / 1e4 / 24 * qty * m.o[e:e + j + 1])
    pnl = qty * (xx - xe) - fee0 - fee1 - swap[-1]

    held = slice(0, j + 1)
    base = -fee0 - swap
    lo = qty * (xl[held] - xe) + base
    hi = qty * (xh[held] - xe) + base
    op = qty * (xo[held] - xe) + base
    cl = qty * (xc[held] - xe) + base
    # On the exit bar, prices beyond the fill came after it.
    at_fill = qty * (xf - xe) + base[-1]
    if reason == "stop":
        lo[-1] = max(lo[-1], at_fill)
    elif reason == "target":
        hi[-1] = min(hi[-1], at_fill)
    cl[-1] = pnl
    lo[-1], hi[-1] = min(lo[-1], pnl), max(hi[-1], pnl)
    hr = m.t[e:e + j + 1] // 3600
    f = run_starts(hr)
    last = np.r_[f[1:] - 1, j]
    pos = np.full(len(f), float(side))
    pos[-1] = 0.0
    seg = np.column_stack([m.t[e + f], op[f], np.minimum.reduceat(lo, f), np.maximum.reduceat(hi, f), cl[last], pos])
    return Leg(side, e + j, reason, float(pnl), float(pnl / RISK_USD), float(qty), float(fee0 + fee1 + swap[-1] + qty * (slip0 * px0 + slip1 * px1)), seg)


@dataclass
class Trade:
    sig: Signal
    entry: int
    legs: dict
    holed: bool

    @property
    def exit(self) -> int:
        return max(self.legs[1].exit, self.legs[-1].exit)


def run_book(m: Market, sigs: list[Signal]) -> list[Trade]:
    """Signals in time order, taken only when both mirrors are flat."""
    out, busy = [], -1
    for sg in sorted(sigs, key=lambda s: s.sig):
        e = sg.sig + 1
        if e <= busy or e >= m.n or sg.end < e:
            continue
        legs = {s: simulate(m, e, sg, s) for s in (1, -1)}
        tr = Trade(sg, e, legs, False)
        tr.holed = bool(m.holes_before[tr.exit] > m.holes_before[sg.sig])
        out.append(tr)
        busy = tr.exit
    return out


# ---------------------------------------------------------------- twin tests

def mirrors(trades: list[Trade]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rl = np.array([t.legs[1].r for t in trades])
    rs = np.array([t.legs[-1].r for t in trades])
    return rl, rs, np.array([t.sig.side for t in trades])


def long_share(dirs: np.ndarray) -> float:
    return float((dirs > 0).mean())


def taken(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray) -> np.ndarray:
    """Net R of each trade on the side `dirs` took."""
    return np.where(dirs > 0, rl, rs)


def excess(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray, p_long: float) -> np.ndarray:
    """Net R per trade over the twins' expectation on that same trade."""
    return taken(rl, rs, dirs) - (p_long * rl + (1 - p_long) * rs)


def coin(rng: np.random.Generator, shape, p_long: float) -> np.ndarray:
    """+1 with probability p_long, else -1."""
    return np.where(rng.random(shape) < p_long, 1, -1)


def r_test(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray, p_long: float | None = None, n_twins: int = N_TWINS,
           seed: int = SEED) -> dict:
    """Mean net R of `dirs` against twins drawing each trade's side with P(long) = p_long (default: dirs' long share)."""
    n = len(dirs)
    if n == 0:
        return dict(trades=0)
    pl = long_share(dirs) if p_long is None else p_long
    r = taken(rl, rs, dirs)
    rng = np.random.default_rng(seed)
    twin = taken(rl, rs, coin(rng, (n_twins, n), pl)).mean(1)
    ex = excess(rl, rs, dirs, pl)
    boot = ex[block_idx(n, R_BOOT, min(R_BOOT_BLOCK, n), rng)].mean(1)
    return dict(trades=n, p_long=pl, mean_r=float(r.mean()), twin_mean_r=float(twin.mean()),
                twin_p95=float(np.quantile(twin, 0.95)), excess=float(ex.mean()),
                excess_ci=[float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
                p=float((1 + (twin >= r.mean()).sum()) / (1 + n_twins)))


def passes(t: dict, alpha: float = 0.05) -> bool:
    return t.get("trades", 0) > 0 and t["p"] < alpha and t["excess_ci"][0] > 0


# ---------------------------------------------------------------- account replay

@dataclass
class Book:
    """Bar pieces in time order for every trade's two legs plus flat days, assembled per direction vector."""
    time: np.ndarray
    vals: np.ndarray        # open, lo, hi, close relative to the owner's start
    pos: np.ndarray
    owner: np.ndarray       # trade index whose base applies (count of trades done, for flat bars)
    side: np.ndarray        # +1/-1 for a leg's bars, 0 for flat bars
    pnl_l: np.ndarray
    pnl_s: np.ndarray


def build_book(m: Market, trades: list[Trade]) -> Book:
    pieces = []  # (time, open, lo, hi, close, pos, owner, side)

    def flat(days, k):
        for d in days:
            pieces.append(np.array([[ny_time(d, hours=12), 0, 0, 0, 0, 0, k, 0]], float))

    day0, last = int(m.ny_date[0]), int(m.ny_date[-1])
    prev = day0 - 1
    for k, t in enumerate(trades):
        d_in, d_out = int(m.ny_date[t.entry]), int(m.ny_date[t.exit])
        flat(range(prev + 1, d_in), k)
        for s in (1, -1):
            leg = t.legs[s]
            seg = leg.seg
            pieces.append(np.column_stack([seg, np.full(len(seg), k), np.full(len(seg), s)]))
            # Days this leg is flat but its mirror still holds, so every leg covers the same calendar days.
            d_leg = int(m.ny_date[leg.exit])
            for d in range(d_leg + 1, d_out + 1):
                pieces.append(np.array([[ny_time(d), leg.pnl, leg.pnl, leg.pnl, leg.pnl, 0, k, s]], float))
        prev = d_out
    flat(range(prev + 1, last + 1), len(trades))
    a = np.concatenate(pieces) if pieces else np.zeros((0, 8))
    return Book(a[:, 0], a[:, 1:5], a[:, 5], a[:, 6].astype(int), a[:, 7].astype(int),
                np.array([t.legs[1].pnl for t in trades]), np.array([t.legs[-1].pnl for t in trades]))


def book_result(b: Book, dirs: np.ndarray) -> tuple[dict, np.ndarray]:
    keep = (b.side == 0) | (b.side == np.r_[dirs, 0][b.owner])
    pnl = taken(b.pnl_l, b.pnl_s, dirs)
    base = PLAN["startBalance"] + np.r_[0, np.cumsum(pnl)][b.owner[keep]]
    v = b.vals[keep] + base[:, None]
    return dict(equity=v[:, 3].tolist(), barOpen=v[:, 0].tolist(), barLo=v[:, 1].tolist(), barHi=v[:, 2].tolist(),
                positions=b.pos[keep].tolist(), initialCapital=PLAN["startBalance"]), b.time[keep]


def account_ev(b: Book, dirs: np.ndarray, paths: int = EV_PATHS) -> dict:
    """Elite 50K 3% DLL bootstrap. Inactivity is not modelled (no `trades` key): a slow book is assumed to place a
    keep-alive micro trade, the same for strategy and twins."""
    result, time = book_result(b, dirs)
    s = run_prop(result, time, PLAN, PLAN["startBalance"], paths=paths, block_size=EV_BLOCK_DAYS, horizon=EV_HORIZON_DAYS,
                 seed=EV_SEED, keep_attempts=False, replay_history=False)["bootstrap"]
    return {k: s[k] for k in ("ev", "passRate", "pPayout", "meanTake", "meanPayouts", "outcomes", "censored")}


_POOL_BOOK: Book | None = None


def _pool_init(b: Book):
    global _POOL_BOOK
    _POOL_BOOK = b


def _pool_ev(args):
    dirs, paths = args
    return account_ev(_POOL_BOOK, dirs, paths)["ev"]


def ev_test(b: Book, dirs: np.ndarray, n_twins: int, paths: int, workers: int, seed: int = SEED) -> dict:
    """Strategy EV vs twins' EV on the same bootstrap seed, twins with P(long) = the strategy's long share."""
    own = account_ev(b, dirs, paths)
    pl = long_share(dirs)
    rng = np.random.default_rng(seed + 1)
    jobs = [(coin(rng, len(dirs), pl), paths) for _ in range(n_twins)]
    with Pool(min(workers, MAX_WORKERS), initializer=_pool_init, initargs=(b,)) as pool:
        evs = np.array(pool.map(_pool_ev, jobs, chunksize=max(1, n_twins // (workers * 8))))
    return dict(strategy=own, twins=n_twins, paths=paths, twin_ev_mean=float(evs.mean()),
                twin_ev_p05=float(np.quantile(evs, 0.05)), twin_ev_p95=float(np.quantile(evs, 0.95)),
                ev_over_twins=float(own["ev"] - evs.mean()), p=float((1 + (evs >= own["ev"]).sum()) / (1 + n_twins)))


# ---------------------------------------------------------------- controls

def lookahead_dirs(m: Market, trades: list[Trade], frac: float = LOOKAHEAD_FRAC) -> np.ndarray:
    """Planted bug: the side of the price `frac` of the way from entry to the time exit. Must pass."""
    e = np.array([t.entry for t in trades])
    later = e + (frac * (np.array([t.sig.end for t in trades]) - e)).astype(int)
    return np.where(m.c[later] >= m.o[e], 1, -1)


def coin_dirs(n: int, seed: int) -> np.ndarray:
    return coin(np.random.default_rng(seed), n, 0.5)


# ---------------------------------------------------------------- reporting

def by_year(m: Market, trades: list[Trade], dirs: np.ndarray) -> dict:
    rl, rs, _ = mirrors(trades)
    r, ex = taken(rl, rs, dirs), excess(rl, rs, dirs, long_share(dirs))
    yr = pd.to_datetime(m.t[[t.entry for t in trades]], unit="s", utc=True).year.to_numpy()
    return {int(y): dict(trades=int((yr == y).sum()), mean_r=float(r[yr == y].mean()), excess=float(ex[yr == y].mean()))
            for y in np.unique(yr)}


def describe(m: Market, trades: list[Trade]) -> dict:
    if not trades:
        return dict(trades=0)
    _, _, dirs = mirrors(trades)
    legs = [t.legs[int(d)] for t, d in zip(trades, dirs)]
    hold_h = np.array([(m.t[lg.exit] - m.t[t.entry]) / 3600 for t, lg in zip(trades, legs)])
    capped = np.array([lg.qty * m.o[t.entry] >= m.market["leverage"] * PLAN["startBalance"] * (1 - 1e-9) for t, lg in zip(trades, legs)])
    return dict(trades=len(trades), long_share=long_share(dirs), median_hold_h=float(np.median(hold_h)),
                cost_r=float(np.mean([lg.costs for lg in legs]) / RISK_USD), lev_capped=int(capped.sum()),
                exits=pd.Series([lg.reason for lg in legs]).value_counts().to_dict(),
                holed=int(sum(t.holed for t in trades)))


def daily(m: Market, trades: list[Trade], per_trade: np.ndarray) -> np.ndarray:
    """Per-trade values summed by UTC exit day over every day of the block, so every config has the same length."""
    out = np.zeros(int(m.t[-1] // 86400 - m.t[0] // 86400) + 1)
    if trades:
        np.add.at(out, np.array([m.t[t.legs[int(d)].exit] // 86400 for t, d in zip(trades, mirrors(trades)[2])]) - m.t[0] // 86400, per_trade)
    return out
