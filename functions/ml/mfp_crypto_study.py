"""MyFundedPerps crypto study on the TRAIN block: hypotheses C1–C5 (MFP_PLAN.md §5) on BTC and ETH, each against
coin-flip twins (§7). Validation and test are not touched here.

    python functions/ml/mfp_crypto_study.py                  # 2,000 twins per test, writes data/mfp_crypto/
    python functions/ml/mfp_crypto_study.py --twins 200 --ev-twins 50 --paths 100   # quick look (still logged)

Every run opens the train block once through crypto_holdout.open_block, which logs it. SPECS below were written and
committed before the first open; their hashes go in the results so a later freeze can name them.

Execution (the same for every spec, its twins and the controls):
    entry       market order at the open of the 1m bar after the signal bar
    exits       stop and target trigger on 1m highs/lows and fill as market orders; a stop gapped through fills at the
                bar's open; a bar touching both fills the stop; time exits fill at the bar's close
    costs       MFP Elite crypto, read from flybrain/fixtures/mfp_markets.json (exported from frontend perps.js):
                3 bp commission per fill on notional, worst-case published slippage per fill notional, 3 bp/day swap
                charged at every UTC hour crossed on the marked notional, no funding credited
    size        fixed risk RISK_USD per trade = stop distance x quantity, trimmed to the leverage cap; never reads
                the balance. R = net P&L / RISK_USD
    one book    one position per spec and symbol. Every trade is simulated both long and short (the mirror); a new
                signal is taken only once BOTH mirrors are flat, so the strategy and every twin share the same entry
                times, stops, targets, exit rules and sizes, and only the direction differs

Twins draw each trade's direction with P(long) = the strategy's long share (the fair coin is reported too). The
mean-R test is exact on the mirrors; the EV test replays each twin's equity through flybrain/prop.py on Elite 50K 3%
DLL with block-bootstrapped account lifecycles, on the same bootstrap seed as the strategy.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from close_auction_study import block_idx  # noqa: E402
from crypto_holdout import open_block  # noqa: E402
from flybrain.prop import resolve_plan, run_prop  # noqa: E402
from flybrain.stats import deflated_sharpe, sharpe_inference  # noqa: E402

ET = "America/New_York"
OUT = HERE / "data" / "mfp_crypto"
MARKETS = json.loads((HERE / "flybrain" / "fixtures" / "mfp_markets.json").read_text())["markets"]
SYMBOLS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
PLAN = resolve_plan("elite", "50k", True, firm="mfp")
RISK_USD = 0.01 * PLAN["startBalance"]
N_TWINS = 2000
EV_PATHS = 200
EV_BLOCK_DAYS = 7
EV_HORIZON_DAYS = 1460  # MFP has no time limit; a short horizon censors slow books into "eval-open" and drops them
EV_SEED = 42
R_BOOT = 4000
R_BOOT_BLOCK = 10
SEED = 7
LOOKAHEAD_FRAC = 0.25  # the planted bug peeks this far into each trade's time-exit window
COIN_CONTROLS = 200
STALE_RUN = 3  # consecutive zero-volume bars that count as a hole: the archive can fill an outage with flat bars

EXECUTION = dict(entry="next 1m open, market", exits="1m trigger, market fill, stop-first, gap-through at open",
                 risk_usd=RISK_USD, costs={k: {c: MARKETS[k][c] for c in ("commissionBps", "swapDailyBps", "slippage", "leverage")}
                                           for k in SYMBOLS.values()},
                 funding_credited=False, one_book="mirror-flat")

# Written before the train block was first opened. `primary` is the a-priori config; `grid` is everything tried.
SPECS = {
    "C1": dict(
        title="Daily trend: Donchian breakout",
        rule=("UTC daily bars. Long when the daily close is above the highest high of the prior n days, short when below "
              "the lowest low. Stop k x ATR20 (daily, through the signal day) from entry; after each completed UTC day "
              "the stop trails to the best daily close since entry minus the same distance. Time exit after 60 days. "
              "No target."),
        fixed=dict(atr_days=20, hold_days=60), primary=dict(n=20, k=3.0), grid=dict(n=[20, 50], k=[2.0, 3.0])),
    "C2": dict(
        title="Funding crowding fade",
        rule=("At each Binance funding print, compare the rate with the prior 270 prints (90 days at 8h). Short when it "
              "is strictly above their (1-q) quantile, long when strictly below their q quantile. Enter at the first "
              "bar at or after the print. Stop 1 x ATR20 (daily, last completed UTC day). Time exit after h hours. No "
              "target."),
        fixed=dict(window=270, atr_days=20, stop_atr=1.0), primary=dict(q=0.05, h=72), grid=dict(q=[0.05, 0.10], h=[24, 72])),
    "C3": dict(
        title="Liquidation-cascade reversal",
        rule=("UTC hourly bars. When an hour's |close - open| exceeds k x ATR (mean true range of the prior 168 hours) "
              "and its volume exceeds the 99th percentile of the prior 720 hours, fade it. Stop 0.25 ATR beyond the "
              "hour's extreme (distance measured from the hour's close), target m x the stop distance, time exit 24h."),
        fixed=dict(atr_hours=168, vol_hours=720, vol_q=0.99, pad_atr=0.25, hold_hours=24), primary=dict(k=3.0, m=1.0),
        grid=dict(k=[2.0, 3.0], m=[1.0, 2.0])),
    "C4": dict(
        title="US-open range breakout",
        rule=("NY weekdays. Range = high/low of the 30 one-minute bars 09:30-09:59 ET (all 30 must exist). The first "
              "1m close outside it between 10:00 and 14:59 ET enters in the break's direction. Stop at the opposite "
              "side of the range (stop=opposite) or its midpoint (stop=mid), distance measured from the breakout "
              "close; target m x that distance; flat at 16:00 ET. ET, not the plan's fixed 13:30 UTC, so the window "
              "follows the US cash open through DST."),
        fixed=dict(range_start="09:30", range_end="10:00", last_entry="15:00", flat="16:00"),
        primary=dict(stop="opposite", m=2.0), grid=dict(stop=["opposite", "mid"], m=[1.0, 2.0])),
    "C5": dict(
        title="CME weekend gap fill",
        rule=("Friday reference = close of the 16:59 ET bar (CME close). Sunday = close of the 18:00 ET bar (CME "
              "reopen). Gap G = Sunday - Friday. When |G| > g x ATR20 (daily, last completed UTC day), trade toward "
              "the Friday level: target |G|, stop s x |G|, both from the Sunday close; time exit Friday 16:00 ET. A "
              "week with either bar missing is skipped."),
        fixed=dict(atr_days=20), primary=dict(g=0.5, s=1.0), grid=dict(g=[0.25, 0.5], s=[1.0, 2.0])),
}


def configs(spec_id: str) -> list[dict]:
    g = SPECS[spec_id]["grid"]
    return [dict(zip(g, v)) for v in itertools.product(*g.values())]


def spec_hash(spec_id: str, params: dict) -> str:
    s = SPECS[spec_id]
    body = dict(id=spec_id, rule=s["rule"], fixed=s["fixed"], params=params, execution=EXECUTION)
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


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


def signals_c1(m: Market, n: int, k: float) -> list[Signal]:
    f = SPECS["C1"]["fixed"]
    d = aggregate(m, m.t // 86400)
    atr = d.atr(f["atr_days"])
    hi = pd.Series(d.h).shift(1).rolling(n).max().to_numpy()
    lo = pd.Series(d.l).shift(1).rolling(n).min().to_numpy()
    out = []
    for j in np.flatnonzero(np.isfinite(atr) & np.isfinite(hi)):
        side = 1 if d.c[j] > hi[j] else -1 if d.c[j] < lo[j] else 0
        if side:
            s = int(d.last[j])
            out.append(Signal(s, side, k * atr[j], None, end_by_time(m, s, f["hold_days"] * 86400), trail=k * atr[j]))
    return out


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


def signals_c2(m: Market, q: float, h: int) -> list[Signal]:
    f = SPECS["C2"]["fixed"]
    if m.funding.empty:
        return []
    fr = m.funding.sort_values("time")
    rate, ft = fr["funding_rate"].to_numpy(float), fr["time"].to_numpy(np.int64)
    roll = pd.Series(rate).shift(1).rolling(f["window"])
    hi, lo = roll.quantile(1 - q).to_numpy(), roll.quantile(q).to_numpy()
    atr = daily_atr_before(m, f["atr_days"])
    out = []
    for j in np.flatnonzero(np.isfinite(hi)):
        side = -1 if rate[j] > hi[j] else 1 if rate[j] < lo[j] else 0
        e = int(m.at_or_after(ft[j]))
        if side and 1 <= e < m.n and np.isfinite(a := atr(e)):
            out.append(Signal(e - 1, side, f["stop_atr"] * a, None, end_by_time(m, e - 1, h * 3600)))
    return out


def signals_c3(mk: Market, k: float, m: float) -> list[Signal]:
    f = SPECS["C3"]["fixed"]
    hb = aggregate(mk, mk.t // 3600)
    atr = pd.Series(true_range(hb.h, hb.l, hb.c)).shift(1).rolling(f["atr_hours"]).mean().to_numpy()
    vq = pd.Series(hb.v).shift(1).rolling(f["vol_hours"]).quantile(f["vol_q"]).to_numpy()
    move = hb.c - hb.o
    out = []
    for j in np.flatnonzero(np.isfinite(atr) & np.isfinite(vq) & (np.abs(move) > k * atr) & (hb.v > vq)):
        side = -int(np.sign(move[j]))
        stop = (hb.c[j] - hb.l[j] if side > 0 else hb.h[j] - hb.c[j]) + f["pad_atr"] * atr[j]
        s = int(hb.last[j])
        out.append(Signal(s, side, stop, m * stop, end_by_time(mk, s, f["hold_hours"] * 3600)))
    return out


def signals_c4(mk: Market, stop: str, m: float) -> list[Signal]:
    out = []
    first = run_starts(mk.ny_date)
    for a, b in zip(first, np.r_[first[1:], mk.n]):
        if mk.ny_dow[a] >= 5:
            continue
        mins = mk.ny_min[a:b]
        rng = np.flatnonzero((mins >= 570) & (mins < 600)) + a
        if len(rng) != 30:
            continue
        hi, lo = mk.h[rng].max(), mk.l[rng].min()
        win = np.flatnonzero((mins >= 600) & (mins < 900)) + a
        out_side = np.sign((mk.c[win] > hi).astype(int) - (mk.c[win] < lo).astype(int))
        hit = np.flatnonzero(out_side)
        flat = np.flatnonzero(mins < 960)
        if not len(hit) or not len(flat):
            continue
        s, side = int(win[hit[0]]), int(out_side[hit[0]])
        ref = lo if side > 0 else hi
        level = ref if stop == "opposite" else (hi + lo) / 2
        dist = abs(mk.c[s] - level)
        if dist > 0:
            out.append(Signal(s, side, dist, m * dist, int(flat[-1] + a)))
    return out


def signals_c5(m: Market, g: float, s: float) -> list[Signal]:
    atr = daily_atr_before(m, SPECS["C5"]["fixed"]["atr_days"])
    fri = np.flatnonzero((m.ny_dow == 4) & (m.ny_min == 16 * 60 + 59))
    out = []
    for i in fri:
        day = int(m.ny_date[i])
        sun = int(m.at_or_after(ny_time(day, 2, 18)))
        if sun >= m.n - 1 or m.ny_dow[sun] != 6 or m.ny_min[sun] != 18 * 60:
            continue
        gap = m.c[sun] - m.c[i]
        a = atr(sun)
        if not np.isfinite(a) or abs(gap) <= g * a:
            continue
        end = int(m.at_or_after(ny_time(day, 7, 16))) - 1
        out.append(Signal(sun, -int(np.sign(gap)), s * abs(gap), abs(gap), end))
    return out


SIGNALS = {"C1": signals_c1, "C2": signals_c2, "C3": signals_c3, "C4": signals_c4, "C5": signals_c5}


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
    with Pool(workers, initializer=_pool_init, initargs=(b,)) as pool:
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


def study_symbol(m: Market, n_twins: int) -> tuple[dict, dict]:
    """Every config of every spec on one symbol: book stats, twin tests, by-year, holes, controls on the primaries.
    Returns the result rows and each row's trades."""
    rows, books = {}, {}
    for sid in SPECS:
        for params in configs(sid):
            key = f"{sid} {json.dumps(params, sort_keys=True)}"
            trades = books[key] = run_book(m, SIGNALS[sid](m, **params))
            row = rows[key] = dict(spec=sid, params=params, hash=spec_hash(sid, params),
                                   primary=params == SPECS[sid]["primary"], book=describe(m, trades))
            if not trades:
                continue
            rl, rs, dirs = mirrors(trades)
            ok = ~np.array([t.holed for t in trades])
            row.update(twins=r_test(rl, rs, dirs, n_twins=n_twins), fair_coin=r_test(rl, rs, dirs, p_long=0.5, n_twins=n_twins),
                       twins_unholed=r_test(rl[ok], rs[ok], dirs[ok], n_twins=n_twins), years=by_year(m, trades, dirs))
            if row["primary"]:
                coins = [r_test(rl, rs, coin_dirs(len(trades), SEED + 100 + k), n_twins=n_twins, seed=SEED + k)
                         for k in range(COIN_CONTROLS)]
                row["controls"] = dict(lookahead=r_test(rl, rs, lookahead_dirs(m, trades), n_twins=n_twins), coin=coins[0],
                                       coin_pass_rate=float(np.mean([passes(c) for c in coins])))
    return rows, books


def daily(m: Market, trades: list[Trade], per_trade: np.ndarray) -> np.ndarray:
    """Per-trade values summed by UTC exit day over every day of the block, so every config has the same length."""
    out = np.zeros(int(m.t[-1] // 86400 - m.t[0] // 86400) + 1)
    if trades:
        np.add.at(out, np.array([m.t[t.legs[int(d)].exit] // 86400 for t, d in zip(trades, mirrors(trades)[2])]) - m.t[0] // 86400, per_trade)
    return out


def deflate(rows: list[dict], books: list[tuple[Market, list[Trade]]]) -> None:
    """Deflated Sharpe of each config's daily R against every config tried (both symbols): on net R, and on R over
    the twins. Daily, not per trade, because trade counts differ 40-fold across specs."""
    series = {"raw": [], "excess": []}
    for m, trades in books:
        rl, rs, dirs = mirrors(trades) if trades else (np.array([]),) * 3
        series["raw"].append(daily(m, trades, taken(rl, rs, dirs)))
        series["excess"].append(daily(m, trades, excess(rl, rs, dirs, long_share(dirs)) if trades else rl))
    for name, xs in series.items():
        infs = [sharpe_inference(x.tolist(), ppy=365) for x in xs]
        trials = [i["sr"] for i in infs]
        for row, inf in zip(rows, infs):
            row.setdefault("dsr", {})[name] = dict(sharpe=inf["sharpe"], **deflated_sharpe(inf, trials))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--twins", type=int, default=N_TWINS)
    ap.add_argument("--ev-twins", type=int, default=N_TWINS)
    ap.add_argument("--paths", type=int, default=EV_PATHS)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT / "train_results.json")
    a = ap.parse_args(argv)
    hashes = {sid: {json.dumps(p, sort_keys=True): spec_hash(sid, p) for p in configs(sid)} for sid in SPECS}
    results = dict(plan=f"{PLAN['firm']} {PLAN['plan']} {PLAN['size']} dll={PLAN['dll']}", risk_usd=RISK_USD,
                   execution=EXECUTION, configs_tried=sum(len(configs(s)) for s in SPECS) * len(SYMBOLS),
                   n_twins=a.twins, ev_twins=a.ev_twins, ev_paths=a.paths, hashes=hashes, symbols={})
    with open_block("train", purpose=f"MFP C1-C5 train study, {results['configs_tried']} configs, twins={a.twins}") as blk:
        markets, books = {}, {}
        for sym in SYMBOLS:
            m = markets[sym] = Market(sym, blk.bars(sym), blk.funding(sym))
            holes = m.holes()
            rows, books[sym] = study_symbol(m, a.twins)
            results["symbols"][sym] = dict(
                first=iso(m.t[0]), last=iso(m.t[-1]),
                bars=m.n, holes=len(holes), stale=m.stale_report(), missing_bars=int(sum(h["missing_bars"] for h in holes)),
                largest_holes=sorted(holes, key=lambda h: -h["missing_bars"])[:10], funding_prints=len(m.funding),
                funding_first=iso(m.funding["time"].min()) if len(m.funding) else None,
                rows=rows)
        keys = [(sym, k) for sym in SYMBOLS for k in books[sym]]
        deflate([results["symbols"][s]["rows"][k] for s, k in keys], [(markets[s], books[s][k]) for s, k in keys])
        # EV: each spec's a-priori config and its train-best config (by excess over twins), plus controls on C4's primary.
        for sym, m in markets.items():
            rows = results["symbols"][sym]["rows"]
            for sid in SPECS:
                cand = [k for k, r in rows.items() if r["spec"] == sid and "twins" in r]
                if not cand:
                    continue
                best = max(cand, key=lambda k: rows[k]["twins"]["excess"])
                for k in cand:
                    r = rows[k]
                    r["train_best"] = k == best
                    if not (r["primary"] or r["train_best"]):
                        continue
                    trades = books[sym][k]
                    _, _, dirs = mirrors(trades)
                    b = build_book(m, trades)
                    r["ev"] = ev_test(b, dirs, a.ev_twins, a.paths, a.workers)
                    if r["primary"] and sid == "C4":
                        r["ev_controls"] = dict(lookahead=ev_test(b, lookahead_dirs(m, trades), a.ev_twins, a.paths, a.workers),
                                                coin=ev_test(b, coin_dirs(len(trades), SEED + 100), a.ev_twins, a.paths, a.workers))
                    print(f"{sym} {k} ev={r['ev']['strategy']['ev']:.0f} twins={r['ev']['twin_ev_mean']:.0f} p={r['ev']['p']:.3f}", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(results, indent=1, default=float))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
