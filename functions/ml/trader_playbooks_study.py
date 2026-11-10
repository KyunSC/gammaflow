"""Named-trader playbooks: the codable parts of what Fabio Valentini, Carmine Rosato and Patrick Nill teach.

Sunny asked (2026-10-24) to find and backtest what these three trade. None publishes a rulebook; what follows is
pieced together from interviews, webinars and playbook write-ups (sources and the discretionary parts that cannot be
coded are in /mnt/project-files/studies/named-traders/FINDINGS.md). Their shared core is auction market theory:
classify balance vs imbalance, wait for price to return to a volume-profile location, enter only on visible
order-flow aggression or absorption, tight stop, 2-5R target. The order-flow trigger needs prints or MBO; it was
already tested once in this repo (orderflow_backtest.py --study absorb: absorption at prior-session LVNs / high /
low / VWAP, NQ discovery +0.05R, ES one look -0.26R). This study tests the *location and structure* half on 1m bars,
with a bar-shape stand-in for "aggression". If the location half shows nothing, buying ticks to add the trigger is a
poor bet; if it shows something, the trigger is the next test.

Rules (fixed before any number was looked at):
  - data, exploration: Databento XNAS.ITCH SPY + QQQ ohlcv-1m sessions <= DISCOVERY_END (2025-03-26), loaded by
    amt_lucid_study.load_sessions (RTH 09:30-15:59 ET, >= 380 bars). Prices go to the futures plane (SPY x10.05 ~ ES
    $50/pt, QQQ x41.2 ~ NQ $20/pt, tick 0.25). Unlimited runs: these sessions have been read by other studies.
  - data, confirmation: Databento GLBX.MDP3 NQ.v.0 ohlcv-1m, RTH sessions 2012-01-03 -> 2021-12-31
    (databento_fetch.py nq-ohlcv-1m-early), a folder no other script reads. Scored ONCE (--confirm). 2018-05 on
    shares calendar days with amt_nq_confirm.py's QQQ window and 2012-2021 with vp_claims_study.py's ES window;
    their rules differ, but the markets are correlated, so the three confirmations are not independent evidence.
  - tape: sessions in date order, concatenated. ATR = mean RTH range (high - low) of the previous 14 sessions; a
    session without 14 earlier ones is not traded. On NQ a contract change starts a new run: nothing is held into
    it and the prior-session profile of its first session is not used.
  - leg profile (shared): the 1m bars of a leg, each bar's volume spread evenly over its [low, high], summed into
    N_BINS = 20 equal bins over the leg's range (the leg must span >= 20 ticks). LVN = the lowest bin among bins
    3..16 (the outer 15% at each end excluded), if <= 0.5x the median bin and with a bin >= the median on each side.
    Zone = that bin's [low, high]. 1m bars blur a fast leg: this is the thin-trade region, not a print-level LVN.
  - trigger (shared), "entry" grid: for a long (short mirrors), waiting for a pullback down into the zone:
      touch   limit buy at the zone midpoint (tick below); fills when a bar trades a tick through it. Nill's
              resting-limit style; Valentini says he does NOT rest limits at the LVN, he waits for aggression.
      reject  a bar trades into the zone (low <= zone top), closes back above the zone top and above its open;
              market buy at the next bar's open + 1 tick. The bar-level stand-in for Valentini's "aggression" and
              Rosato's "bid filled and held".
    Stop: below the zone bottom (reject: or the bar's low, if lower) by max(2 ticks, 0.05x the leg), at least 4
    ticks from the entry.
  - setup L  lvn_leg  (Valentini "trend model", Rosato "LVN retest"). Signals 09:30-12:30 ET (NY open; Rosato's first
    2-3 hours). At each 1m close: an up leg is the move from the lowest low of the last LEG_BARS = 30 bars to this
    bar's high, if this bar makes the high since that low and the move >= q x ATR (down mirrors). An active leg
    extends while price makes new extremes (zone recomputed) and dies if price trades through its origin; a fresh
    leg in the other direction replaces it. Trade with the leg on its pullback (trigger above). Target: "extreme"
    = the leg's extreme, skipped unless >= 2R (Valentini's minimum); "3R" = 3x the stop (Rosato's 3-5R). Valentini's
    own target, "the previous balance POC", needs a balance picked by eye, so it is not coded. One
    position at a time, a new leg needed after each exit, no new trade after the 3rd loss of a session (Valentini).
    grid: q in {0.3, 0.5} x entry in {touch, reject} x target in {extreme, 3R}.
  - setup R  lvn_reclaim  (Valentini "mean-reversion model": failed breakout, reclaim, pullback, target POC). Prior
    session profile at tick resolution (amt_lucid_study.value_area: POC, 70% VA). The 09:30 open is inside the
    prior VA. The first bar trading a tick beyond VAH (VAL) starts a probe; it must be reclaimed by a 5m close
    (09:30-anchored) back inside the VA within 60 minutes, without the other edge being probed; else no trade.
    Reclaim leg = from the probe extreme to the furthest price since, extending while it makes new extremes; its LVN
    (leg profile above) is where the pullback is traded, back toward value (short after an upside probe). Void if
    price trades beyond the probe extreme, reaches the POC first, or it is 14:00. Stop: "lvn" = the trigger's stop;
    "extreme" = the probe extreme + 2 ticks. Target: the prior POC, skipped unless >= 2R. One trade per session.
    grid: entry in {touch, reject} x stop in {lvn, extreme}.
  - setup P  pbd  (Nill's "PBD": impulse -> balance -> breakout, retest entry with a limit, 15m chart, holds hours to
    days). 15m bars, 09:30-anchored. ATR15 = mean true range of the previous 14 15m bars of the run. Impulse: a run
    of 1-4 15m bars in one session whose close-minus-first-open >= k x ATR15 (as of the run's first bar), the
    largest such run ending at this bar. Balance: from the next bar, a box [min low, max high] that stays within
    0.5x the impulse; it needs >= 3 bars and dies after 16 bars, when it would grow too tall, or on a close beyond
    its far side. Breakout: a 15m close beyond the box in the impulse's direction (with >= 3 box bars). Nill: don't
    buy the breakout; a limit at the broken box edge for the retest, live from the next bar until 15:45 of the
    same session or 8 bars, cancelled if the target is traded first. Fill: a 1m bar a tick through the limit.
    Stop: "mid" = box midpoint, "far" = the box's far side, 1 tick beyond (>= 4 ticks). Target: rr x the stop.
    Hold until the target, the stop or the 15:54 close of the third session (entry session = 1); overnight gaps
    fill a stop at the open. One position at a time. Weekly value-area zones, his context filter, are not coded.
    grid: k in {2, 3} x stop in {mid, far} x rr in {2, 4}.
  - execution: on 1m bars of the tape. A bar that opens through the stop fills at its open, else the stop, both 1
    tick worse; a bar touching stop and target counts as the stop (flagged "ambiguous"). A target fills at its price
    when a bar trades a tick THROUGH it, or at the open of a bar opening through it. A limit fill happens on the way
    to its bar's far extreme (the low, for a buy), so that extreme is checked first; the other extreme counts only if
    the bar's colour puts it later (O-L-H-C for an up bar, O-H-L-C for a down bar). Otherwise flat at the last bar's
    close - 1 tick (15:54). Costs: $4.50 round trip per contract (ES $50/pt, NQ $20/pt), as ORDERFLOW_GEX_PREREG.md.
    R = (points - cost points) / stop distance from the fill. Every entry is also replayed at doubled friction (2
    ticks slippage, 2x commission) -> mean_2x, and with no costs -> gross.
  - coin-flip twin: each trade's direction-pair, both entered at one bar's open with 1 tick slippage and the trade's
    stop and target distances, mirrored for the opposite side: the entry bar for a market entry (r_dir = R), the
    bar after the fill for a limit entry (a limit fill is conditioned on price moving through it, which a mirror
    cannot copy on 1m bars). edge = mean (r_dir - r_flip) / 2; p = share of N_RANDOM coin draws (r_dir or r_flip per
    trade) whose mean >= mean r_dir. The session sequence (one at a time, 3-loss stop) is the strategy's. On a
    path-consistent random walk (tests) edge ~ 0 and touch-entry gross R ~ -0.2: a tick-through limit fill with a
    6-tick stop gives up about a tick, which is real queue risk, not an artifact.
  - selection (--freeze, exploration only), per setup: the cell with >= MIN_TRADES trades on each of SPY and QQQ,
    mean net R > 0, mean_2x > 0 and edge > 0 on both; the highest pooled mean net R. No such cell: the setup is
    dropped and never confirmed.
  - inference: moving-block bootstrap over trades in time order (blocks of 5, N_BOOT draws, seed 0).
  - verdict per frozen setup on NQ (--confirm): PASS when the one-sided lower bound of mean net R at ALPHA =
    0.05 / 3 is > 0, coin-flip p < ALPHA, and mean_2x > 0. Otherwise FAIL.

One look, enforced as in vp_claims_study.py: script_sha() hashes this file AND amt_lucid_study.py; the tests pin it
(SPEC_SHA). --freeze re-runs the exploration and writes trader_playbooks_prereg.json next to this script (commit it).
--confirm refuses when trader_playbooks_looks.log (committed) has a look, when the hash changed, or when the NQ
download misses a year (>= 230 sessions in each of 2012-2021); then it appends the look before scoring.

    python functions/ml/trader_playbooks_study.py --explore
    python functions/ml/trader_playbooks_study.py --freeze          # then commit functions/ml/trader_playbooks_prereg.json
    python functions/ml/databento_fetch.py nq-ohlcv-1m-early --start 2012-01-01 --end 2022-01-01            # free quote
    python functions/ml/databento_fetch.py nq-ohlcv-1m-early --start 2012-01-01 --end 2022-01-01 --download --max-cost 30
    python functions/ml/trader_playbooks_study.py --confirm         # then commit functions/ml/trader_playbooks_looks.log

Specification: everything above was written down before the first run and not changed after it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import amt_lucid_study as amt  # noqa: E402

ET = amt.ET
TICK = amt.TICK
OPEN, FLAT, CLOSE = amt.OPEN, amt.FLAT, amt.CLOSE    # 09:30, 15:54, 16:00
MIN_BARS = amt.MIN_BARS
DISCOVERY_END = amt.DISCOVERY_END

OUT = amt.DATA / "trader_playbooks"
PREREG, LOOKS = HERE / "trader_playbooks_prereg.json", HERE / "trader_playbooks_looks.log"   # committed, unlike OUT
SPEC_FILES = (Path(__file__).resolve(), HERE / "amt_lucid_study.py")
NQ_DIR = amt.DATA / "databento" / "nq-ohlcv-1m-early" / "NQ"
CONFIRM_START, CONFIRM_END = date(2012, 1, 3), date(2021, 12, 31)
NQ_MIN_SESSIONS_PER_YEAR = 230

INSTRUMENTS = {"SPY": dict(ratio=10.05, pv=50.0), "QQQ": dict(ratio=41.2, pv=20.0), "NQ": dict(ratio=1.0, pv=20.0)}
COMMISSION_RT = 4.50
SLIP = TICK

ATR_SESSIONS = 14
N_BINS, EDGE_BINS, LVN_MULT = 20, 3, 0.5
STOP_BUF, MIN_STOP_TICKS = 0.05, 4
MIN_RR = 2.0

L_LAST = 750                 # 12:30, bar start minute: no signal bar at or after it
LEG_BARS = 30
MAX_LOSSES = 3
R_LAST = amt.LAST_ENTRY      # 14:00
R_PERIOD, R_RECLAIM_MIN = 5, 60
P_BAR, P_MAX_RUN, P_ATR_BARS = 15, 4, 14
P_BOX_FRAC, P_MIN_BOX, P_MAX_BOX, P_RETEST_BARS = 0.5, 3, 16, 8
P_LAST_FILL = 945            # 15:45
P_HOLD_SESSIONS = 3

GRID = {
    "lvn_leg": [dict(q=q, entry=e, target=t) for q in (0.3, 0.5) for e in ("touch", "reject") for t in ("extreme", "3R")],
    "lvn_reclaim": [dict(entry=e, stop=s) for e in ("touch", "reject") for s in ("lvn", "extreme")],
    "pbd": [dict(k=k, stop=s, rr=r) for k in (2, 3) for s in ("mid", "far") for r in (2, 4)],
}
MIN_TRADES = 60
ALPHA = 0.05 / 3
N_BOOT, BLOCK, N_RANDOM, SEED = 4000, 5, 5000, 0


def cell_name(setup: str, p: dict) -> str:
    return setup + "/" + "/".join(f"{k}={v}" for k, v in p.items())


def rt(x: float) -> float:
    return round(x / TICK) * TICK


# ---------------------------------------------------------------- data

def session(g: pd.DataFrame, ratio: float, inst=None) -> dict:
    return dict(O=g.open.to_numpy(float) * ratio, H=g.high.to_numpy(float) * ratio, L=g.low.to_numpy(float) * ratio,
                C=g.close.to_numpy(float) * ratio, V=g.volume.to_numpy(float), m=g.minute.to_numpy(int), inst=inst)


def load_xnas(symbol: str) -> dict[date, dict]:
    ratio = INSTRUMENTS[symbol]["ratio"]
    return {d: session(g, ratio) for d, g in amt.load_sessions(symbol, DISCOVERY_END).items()}


def load_nq(bars_dir: Path = NQ_DIR, start: date = CONFIRM_START, end: date = CONFIRM_END) -> dict[date, dict]:
    files = sorted(bars_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bars in {bars_dir}; run databento_fetch.py nq-ohlcv-1m-early")
    cutoff = pd.Timestamp(end + pd.Timedelta(days=1), tz=ET).tz_convert("UTC")
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    bars = pd.concat([pd.read_parquet(f, columns=cols, filters=[("ts_event", "<", cutoff)]) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    assert (bars.index < cutoff).all(), "LEAK: bar read reaches past the confirmation window"
    et = bars.index.tz_convert(ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= OPEN) & (bars.minute < CLOSE) & (bars.day >= start) & (bars.day <= end)]
    out = {}
    for d, g in bars.groupby("day", sort=True):
        if (len(g) >= MIN_BARS and g.minute.iloc[0] == OPEN and g.minute.iloc[-1] >= FLAT
                and g.instrument_id.nunique() == 1):
            out[d] = session(g, 1.0, int(g.instrument_id.iloc[0]))
    return out


@dataclass
class Tape:
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray
    m: np.ndarray
    start: np.ndarray        # per session: first bar index
    flat: np.ndarray         # per session: index of the 15:54 bar (last bar held)
    days: list
    inst: list
    atr: np.ndarray          # per session: mean range of the previous ATR_SESSIONS sessions (nan before)
    run_end: np.ndarray      # per session: last session of its contract run
    pv: float


def build_tape(sessions: dict[date, dict], pv: float) -> Tape:
    days = sorted(sessions)
    ss = [sessions[d] for d in days]
    lens = np.array([len(s["m"]) for s in ss])
    start = np.r_[0, np.cumsum(lens)[:-1]]
    flat = np.array([st + int(np.flatnonzero(s["m"] >= FLAT)[0]) for st, s in zip(start, ss)])
    cat = {k: np.concatenate([s[k] for s in ss]) for k in ("O", "H", "L", "C", "V", "m")}
    rng = np.array([s["H"].max() - s["L"].min() for s in ss])
    atr = np.full(len(ss), np.nan)
    for i in range(ATR_SESSIONS, len(ss)):
        atr[i] = rng[i - ATR_SESSIONS:i].mean()
    inst = [s["inst"] for s in ss]
    run_end = np.zeros(len(ss), int)
    last = len(ss) - 1
    for i in range(len(ss) - 1, -1, -1):
        if i < len(ss) - 1 and inst[i] != inst[i + 1]:
            last = i
        run_end[i] = last
    return Tape(start=start, flat=flat, days=days, inst=inst, atr=atr, run_end=run_end, pv=pv, **cat)


# ---------------------------------------------------------------- execution

@dataclass(frozen=True)
class Plan:
    d: int                   # +1 long, -1 short
    j: int                   # tape index of the entry bar
    ref: float               # limit price, or the entry bar's open (before slippage)
    stop: float
    target: float
    last: int                # tape index of the last bar held (exit at its close)
    limit: bool


def fill(T: Tape, d: int, j: int, entry: float, stop: float, target: float, last: int, through: int | None,
         slip: float, comm_pts: float) -> dict:
    """Exit of a bracket entered at `entry` on bar j. through: the direction of a limit order filled during bar j
    (None: entered at bar j's open). Such a fill happens on the way to the bar's far extreme (the low, for a buy
    limit), so that extreme comes after it; the other extreme counts only when the bar's color puts it later
    (O -> L -> H -> C for an up bar, O -> H -> L -> C for a down bar). The same path is used for either direction."""
    stop_d = (entry - stop) * d
    amb, i, px = False, last, None
    for i in range(j, last + 1):
        if i == j and through is not None:
            x, y = (T.L[i], T.H[i]) if through > 0 else (T.H[i], T.L[i])
            for v in ((x, y) if (T.C[i] - T.O[i]) * through >= 0 else (x,)):
                if (v - stop) * d <= 0:
                    px, why = stop - d * slip, "stop"
                    break
                if (v - target) * d >= TICK:
                    px, why = target, "target"
                    break
            if px is not None:
                break
            continue
        o, adv, fav = T.O[i], (T.L[i] if d > 0 else T.H[i]), (T.H[i] if d > 0 else T.L[i])
        if i > j and (o - stop) * d <= 0:
            px, why = o - d * slip, "stop"
        elif (adv - stop) * d <= 0:
            px, why = stop - d * slip, "stop"
            amb = (fav - target) * d >= TICK
        elif i > j and (o - target) * d >= 0:
            px, why = o, "target"
        elif (fav - target) * d >= TICK:
            px, why = target, "target"
        else:
            continue
        break
    else:
        px, why = T.C[last] - d * slip, "time"
    return dict(r=((px - entry) * d - comm_pts) / stop_d, reason=why, amb=amb, exit=i, stop_d=stop_d)


def execute(T: Tape, p: Plan) -> dict:
    """The plan at base cost, plus its doubled-friction and gross replays, and the coin-flip pair: the trade and its
    mirror (stop and target mirrored around the reference price), both entered at a bar's open with 1 tick of
    slippage. For a market entry that is the entry bar, so r_dir is the trade itself. A limit fill is conditioned on
    price moving through it, which no mirror can copy without an intrabar path, so its pair enters at the next
    bar's open with the same stop and target distances: on a random walk both sides then expect the same R."""
    comm = COMMISSION_RT / T.pv
    thr = p.d if p.limit else None
    e = lambda slip: p.ref if p.limit else p.ref + p.d * slip
    base = fill(T, p.d, p.j, e(SLIP), p.stop, p.target, p.last, thr, SLIP, comm)
    twice = fill(T, p.d, p.j, e(2 * SLIP), p.stop, p.target, p.last, thr, 2 * SLIP, 2 * comm)
    gross = fill(T, p.d, p.j, e(0.0), p.stop, p.target, p.last, thr, 0.0, 0.0)
    jj, ref = (p.j + 1, float(T.O[p.j + 1])) if p.limit else (p.j, p.ref)
    stop, target = ref - (p.ref - p.stop), ref + (p.target - p.ref)
    pair = [fill(T, d, jj, ref + d * SLIP, ref + d * (stop - ref) * p.d, ref + d * (target - ref) * p.d, p.last,
                 None, SLIP, comm)["r"] for d in (p.d, -p.d)]
    sess = int(np.searchsorted(T.start, p.j, side="right") - 1)
    return dict(day=T.days[sess], d=p.d, r=base["r"], r2x=twice["r"], r_gross=gross["r"], r_dir=pair[0],
                r_flip=pair[1], reason=base["reason"], amb=base["amb"], exit=base["exit"],
                stop_ticks=base["stop_d"] / TICK, overnight=bool(base["exit"] > T.flat[sess]))


# ---------------------------------------------------------------- shared pieces

def leg_lvn(T: Tape, a: int, b: int) -> tuple[float, float] | None:
    """(zone low, zone high) of the LVN of bars a..b, or None."""
    H, L, V = T.H[a:b + 1], T.L[a:b + 1], T.V[a:b + 1]
    lo, hi = L.min(), H.max()
    if hi - lo < N_BINS * TICK:
        return None
    e = np.linspace(lo, hi, N_BINS + 1)
    rng = H - L
    over = np.clip(np.minimum(H[:, None], e[None, 1:]) - np.maximum(L[:, None], e[None, :-1]), 0, None)
    w = np.where(rng[:, None] > 0, over / np.where(rng > 0, rng, 1)[:, None], 0.0)
    for i in np.flatnonzero(rng <= 0):                      # a one-price bar: all of it in its bin
        w[i, min(N_BINS - 1, int(np.searchsorted(e, L[i], side="right") - 1))] = 1.0
    vol = (w * V[:, None]).sum(0)
    med = np.median(vol)
    k = EDGE_BINS + int(np.argmin(vol[EDGE_BINS:N_BINS - EDGE_BINS]))
    if vol[k] > LVN_MULT * med or vol[:k].max() < med or vol[k + 1:].max() < med:
        return None
    return float(e[k]), float(e[k + 1])


def trigger(T: Tape, k: int, d: int, zone: tuple[float, float], entry: str, f: int):
    """(entry index, ref price, limit, far price) when bar k triggers a pullback entry into the zone, else None."""
    z_lo, z_hi = zone
    near, far = (z_hi, z_lo) if d > 0 else (z_lo, z_hi)
    back = T.L[k] if d > 0 else T.H[k]
    if entry == "touch":
        lim = (np.floor if d > 0 else np.ceil)((z_lo + z_hi) / 2 / TICK) * TICK
        if (back - lim) * d <= -TICK:
            return k, float(lim), True, far
        return None
    if ((back - near) * d <= 0 and (T.C[k] - near) * d > 0 and (T.C[k] - T.O[k]) * d > 0 and k + 1 < f):
        return k + 1, float(T.O[k + 1]), False, (min(far, back) if d > 0 else max(far, back))
    return None


def zone_stop(d: int, ref: float, far: float, leg: float) -> float:
    buf = max(2 * TICK, STOP_BUF * leg)
    stop = (np.floor if d > 0 else np.ceil)((far - d * buf) / TICK) * TICK
    if (ref - stop) * d < MIN_STOP_TICKS * TICK:
        stop = ref - d * MIN_STOP_TICKS * TICK
    return float(stop)


# ---------------------------------------------------------------- setup L: impulse-leg LVN pullback

def new_leg(T: Tape, i0: int, k: int, q: float, U: float):
    """(d, origin index) of the largest qualifying leg that bar k completes, or None."""
    best = None
    w0 = max(i0, k - LEG_BARS + 1)
    for d in (1, -1):
        back, ext = (T.L, T.H) if d > 0 else (T.H, T.L)
        a = w0 + int(np.argmin(back[w0:k + 1] * d))
        if (ext[a:k + 1] * d).max() > ext[k] * d:
            continue
        size = (ext[k] - back[a]) * d
        if size >= q * U and (best is None or size > best[2]):
            best = (d, a, size)
    return best and best[:2]


def lvn_leg_session(T: Tape, s: int, q: float, entry: str, target: str) -> list[dict]:
    U = T.atr[s]
    if not np.isfinite(U):
        return []
    i0, f = int(T.start[s]), int(T.flat[s])
    out, losses, leg, k = [], 0, None, i0
    while k < f and T.m[k] < L_LAST:
        if leg is not None:
            d, a, b, zone = leg
            back, ext = (T.L, T.H) if d > 0 else (T.H, T.L)
            if (ext[k] - ext[b]) * d > 0:
                leg = (d, a, k, leg_lvn(T, a, k))
                k += 1
                continue
            if (back[k] - back[a]) * d < 0:
                leg = None
            elif zone is not None and (hit := trigger(T, k, d, zone, entry, f)):
                j, ref, limit, far = hit
                size = (ext[b] - back[a]) * d
                stop = zone_stop(d, ref, far, size)
                risk = (ref - stop) * d
                tgt = ext[b] if target == "extreme" else rt(ref + d * 3 * risk)
                leg = None
                if (tgt - ref) * d >= MIN_RR * risk:
                    rec = execute(T, Plan(d, j, ref, stop, float(tgt), f, limit))
                    out.append(rec)
                    losses += rec["r"] < 0
                    if losses >= MAX_LOSSES:
                        break
                    k = rec["exit"] + 1
                    continue
        nl = new_leg(T, i0, k, q, U)
        if nl and (leg is None or nl[0] != leg[0]):
            leg = (nl[0], nl[1], k, leg_lvn(T, nl[1], k))
        k += 1
    return out


# ---------------------------------------------------------------- setup R: failed breakout, reclaim, pullback

def prior_levels(T: Tape, s: int) -> dict:
    """Session s's VAH / VAL / POC at tick resolution (amt_lucid_study's value-area rule)."""
    i, j = T.start[s], (T.start[s + 1] if s + 1 < len(T.start) else len(T.m))
    lo, hi = np.rint(T.L[i:j] / TICK).astype(np.int64), np.rint(T.H[i:j] / TICK).astype(np.int64)
    base = int(lo.min())
    vols = np.zeros(int(hi.max()) - base + 1)
    for a, b, v in zip(lo - base, hi - base, T.V[i:j]):
        vols[a:b + 1] += v / (b - a + 1)
    return amt.value_area(vols, base, 100 * TICK)      # one amt "cent" bin is one tick here


def lvn_reclaim_session(T: Tape, s: int, entry: str, stop: str) -> list[dict]:
    if s == 0 or T.inst[s - 1] != T.inst[s] or not np.isfinite(T.atr[s]):
        return []
    lv = prior_levels(T, s - 1)
    vah, val, poc = lv["vah"], lv["val"], lv["poc"]
    i0, f = int(T.start[s]), int(T.flat[s])
    if not (val <= T.O[i0] <= vah):
        return []
    m = T.m
    probe = next((k for k in range(i0, f) if T.H[k] >= vah + TICK or T.L[k] <= val - TICK), None)
    if probe is None or m[probe] >= R_LAST:
        return []
    up, dn = T.H[probe] >= vah + TICK, T.L[probe] <= val - TICK
    if up and dn:
        return []
    d = -1 if up else 1                                     # the trade fades the probe
    e = None
    for k in range(probe, f):
        other = T.H[k] >= vah + TICK if d > 0 else T.L[k] <= val - TICK
        if other:
            return []                                       # the other edge probed before a reclaim
        if m[k] - m[probe] > R_RECLAIM_MIN or m[k] >= R_LAST:
            return []
        end = k + 1 >= f or (m[k + 1] - OPEN) // R_PERIOD != (m[k] - OPEN) // R_PERIOD
        if end and val <= T.C[k] <= vah:
            e = k
            break
    if e is None:
        return []
    back, ext = (T.L, T.H) if d > 0 else (T.H, T.L)         # back = probe side, ext = the reclaim leg's direction
    a = probe + int(np.argmin(back[probe:e + 1] * d))       # probe extreme
    X = back[a]
    b = a + int(np.argmax(ext[a:e + 1] * d))
    zone = leg_lvn(T, a, b)
    for k in range(e + 1, f):
        if m[k] >= R_LAST or (back[k] - X) * d < 0 or (ext[k] - poc) * d >= 0:
            return []
        if (ext[k] - ext[b]) * d > 0:
            b, zone = k, leg_lvn(T, a, k)
            continue
        if zone is None or not (hit := trigger(T, k, d, zone, entry, f)):
            continue
        j, ref, limit, far = hit
        stp = zone_stop(d, ref, far, (ext[b] - X) * d) if stop == "lvn" else float(X - d * 2 * TICK)
        if (ref - stp) * d < MIN_STOP_TICKS * TICK or (poc - ref) * d < MIN_RR * (ref - stp) * d:
            return []
        return [execute(T, Plan(d, j, ref, stp, float(poc), f, limit))]
    return []


# ---------------------------------------------------------------- setup P: Nill's PBD on 15m bars

def bars15(T: Tape) -> dict:
    """15m bars of the tape: OHLC, first / last 1m index, session, and ATR15 (previous 14 bars of the run)."""
    sess = np.repeat(np.arange(len(T.start)), np.diff(np.r_[T.start, len(T.m)]))
    key = sess * 100 + (T.m - OPEN) // P_BAR
    first = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    last = np.r_[first[1:] - 1, len(T.m) - 1]
    O, C = T.O[first], T.C[last]
    H = np.maximum.reduceat(T.H, first)
    L = np.minimum.reduceat(T.L, first)
    s = sess[first]
    run = T.run_end[s]
    prev_c = np.r_[np.nan, C[:-1]]
    prev_c[1:][run[1:] != run[:-1]] = np.nan
    tr = np.where(np.isnan(prev_c), H - L, np.maximum(H - L, np.maximum(abs(H - prev_c), abs(L - prev_c))))
    atr = np.full(len(first), np.nan)
    for i in range(len(first)):
        lo = i - P_ATR_BARS
        if lo >= 0 and run[lo] == run[i]:
            atr[i] = tr[lo:i].mean()
    return dict(O=O, H=H, L=L, C=C, first=first, last=last, sess=s, run=run, atr=atr)


def impulse(B: dict, t: int, k: float):
    """(d, size) of the largest 1-4 bar impulse ending at 15m bar t, within one session, or None."""
    best = None
    for s in range(t, max(-1, t - P_MAX_RUN), -1):
        if B["sess"][s] != B["sess"][t]:
            break
        move = B["C"][t] - B["O"][s]
        if np.isfinite(B["atr"][s]) and abs(move) >= k * B["atr"][s] and (best is None or abs(move) > best[1]):
            best = (1 if move > 0 else -1, abs(move))
    return best


def pbd(T: Tape, k: float, stop: str, rr: float) -> list[dict]:
    B = bars15(T)
    n, out, t = len(B["O"]), [], 0
    while t < n:
        imp = impulse(B, t, k)
        if imp is None:
            t += 1
            continue
        d, size = imp
        lo = hi = None
        cnt, u, brk = 0, t + 1, None
        while u < n and B["run"][u] == B["run"][t]:       # a box may span the close; a roll ends it
            if cnt >= P_MIN_BOX and (B["C"][u] - (hi if d > 0 else lo)) * d > 0:
                brk = u
                break
            if cnt >= P_MIN_BOX and (B["C"][u] - (lo if d > 0 else hi)) * d < 0:
                break
            nlo = B["L"][u] if lo is None else min(lo, B["L"][u])
            nhi = B["H"][u] if hi is None else max(hi, B["H"][u])
            if nhi - nlo > P_BOX_FRAC * size or cnt >= P_MAX_BOX:
                break
            lo, hi, cnt, u = nlo, nhi, cnt + 1, u + 1
        if brk is None:
            t = max(t + 1, u)
            continue
        lim = hi if d > 0 else lo
        far = lo if d > 0 else hi
        stp = rt((lo + hi) / 2 if stop == "mid" else far) - d * TICK
        if (lim - stp) * d < MIN_STOP_TICKS * TICK:
            stp = lim - d * MIN_STOP_TICKS * TICK
        tgt = rt(lim + d * rr * (lim - stp) * d)
        s = int(B["sess"][brk])
        hold_to = int(T.flat[min(s + P_HOLD_SESSIONS - 1, int(T.run_end[s]))])
        j, done = None, False
        for v in range(brk + 1, min(n, brk + 1 + P_RETEST_BARS)):
            if B["sess"][v] != s:
                break
            for i in range(B["first"][v], B["last"][v] + 1):
                if T.m[i] >= P_LAST_FILL:
                    done = True
                    break
                if ((T.L[i] if d > 0 else T.H[i]) - lim) * d <= -TICK:
                    j = i
                    break
                if ((T.H[i] if d > 0 else T.L[i]) - tgt) * d >= 0:
                    done = True
                    break
            if j is not None or done:
                break
        if j is None:
            t = brk + 1
            continue
        rec = execute(T, Plan(d, j, float(lim), float(stp), float(tgt), hold_to, True))
        out.append(rec)
        t = int(np.searchsorted(B["first"], rec["exit"], side="right"))
    return out


# ---------------------------------------------------------------- cells

def run_cells(T: Tape, cells: dict[str, list[dict]] | None = None) -> dict[str, list[dict]]:
    cells = cells or GRID
    out = {}
    for setup, ps in cells.items():
        for p in ps:
            if setup == "pbd":
                trades = pbd(T, **p)
            else:
                fn = lvn_leg_session if setup == "lvn_leg" else lvn_reclaim_session
                trades = [r for s in range(len(T.start)) for r in fn(T, s, **p)]
            out[cell_name(setup, p)] = trades
    return out


# ---------------------------------------------------------------- scoring

def block_idx(n: int, n_boot: int = N_BOOT) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    b = min(BLOCK, n)
    starts = rng.integers(0, n - b + 1, (n_boot, -(-n // b)))
    return (starts[:, :, None] + np.arange(b)).reshape(n_boot, -1)[:, :n]


def score(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return dict(trades=0)
    r = np.array([t["r"] for t in trades])
    rd, flip = np.array([t["r_dir"] for t in trades]), np.array([t["r_flip"] for t in trades])
    draws = r[block_idx(n)].mean(1)
    coin = np.random.default_rng(SEED + 1).random((N_RANDOM, n)) < 0.5
    coin_means = np.where(coin, rd, flip).mean(1)
    pos = np.sort(r[r > 0])[::-1]
    years: dict[int, list[float]] = {}
    for t in trades:
        years.setdefault(t["day"].year, []).append(t["r"])
    return dict(
        trades=n, win=float((r > 0).mean()), mean=float(r.mean()),
        ci95=[float(np.quantile(draws, .025)), float(np.quantile(draws, .975))],
        lower_alpha=float(np.quantile(draws, ALPHA)),
        mean_2x=float(np.mean([t["r2x"] for t in trades])), gross=float(np.mean([t["r_gross"] for t in trades])),
        friction_r=float(np.mean([t["r_gross"] - t["r"] for t in trades])),
        edge=float(((rd - flip) / 2).mean()),
        coin=dict(mean=float(coin_means.mean()), p=float((1 + (coin_means >= rd.mean()).sum()) / (1 + N_RANDOM))),
        stop_ticks_median=float(np.median([t["stop_ticks"] for t in trades])),
        ambiguous=float(np.mean([t["amb"] for t in trades])),
        overnight=float(np.mean([t["overnight"] for t in trades])),
        exits=pd.Series([t["reason"] for t in trades]).value_counts(normalize=True).round(3).to_dict(),
        longs=float(np.mean([t["d"] > 0 for t in trades])),
        top5_share=float(pos[:5].sum() / r.sum()) if r.sum() > 0 else None,
        by_year={y: dict(n=len(v), mean=float(np.mean(v))) for y, v in sorted(years.items())})


def eligible(c: dict) -> bool:
    return c["trades"] >= MIN_TRADES and c["mean"] > 0 and c["mean_2x"] > 0 and c["edge"] > 0


def select(res: dict) -> dict:
    """Per setup: the eligible cell (on both SPY and QQQ) with the highest pooled mean net R, or None."""
    chosen = {}
    for setup, ps in GRID.items():
        best = None
        for p in ps:
            name = cell_name(setup, p)
            a, b = res["SPY"]["cells"][name], res["QQQ"]["cells"][name]
            if not (a["trades"] and b["trades"] and eligible(a) and eligible(b)):
                continue
            pooled = (a["mean"] * a["trades"] + b["mean"] * b["trades"]) / (a["trades"] + b["trades"])
            if best is None or pooled > best["pooled_mean"]:
                best = dict(cell=name, params=p, pooled_mean=pooled)
        chosen[setup] = best
    return chosen


def verdict(c: dict) -> str:
    ok = c["trades"] and c["lower_alpha"] > 0 and c["coin"]["p"] < ALPHA and c["mean_2x"] > 0
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------- main

def script_sha() -> str:
    """Hash of the spec: this file and amt_lucid_study.py, whose constants, loader and value-area rule it uses."""
    h = hashlib.sha256()
    for f in SPEC_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def coverage_problems(sessions: dict) -> list[str]:
    per = {y: 0 for y in range(CONFIRM_START.year, CONFIRM_END.year + 1)}
    for d in sessions:
        per[d.year] = per.get(d.year, 0) + 1
    return [f"{y}: {n} sessions" for y, n in per.items() if n < NQ_MIN_SESSIONS_PER_YEAR]


def looks() -> list[str]:
    return [l for l in LOOKS.read_text().splitlines() if l.strip()] if LOOKS.exists() else []


def fmt(x, spec="+.3f") -> str:
    return "  n/a" if x is None else format(x, spec)


def report(sym: str, res: dict) -> None:
    print(f"\n{sym}  {res['sessions']} sessions {res['first']} -> {res['last']}")
    print(f"  {'cell':<44} {'n':>5} {'win':>5} {'meanR':>7} {'95% CI':>17} {'2x':>7} {'gross':>7} {'edge':>7} "
          f"{'coin p':>7} {'stop':>5} {'amb':>5} {'top5':>5}")
    for name, c in res["cells"].items():
        if not c["trades"]:
            print(f"  {name:<44} {0:>5}")
            continue
        print(f"  {name:<44} {c['trades']:>5} {c['win']:5.2f} {c['mean']:+7.3f} "
              f"[{c['ci95'][0]:+.3f},{c['ci95'][1]:+.3f}] {c['mean_2x']:+7.3f} {c['gross']:+7.3f} {c['edge']:+7.3f} "
              f"{c['coin']['p']:7.4f} {c['stop_ticks_median']:5.0f} {c['ambiguous']:5.2f} {fmt(c['top5_share'], '5.2f')}")


def run(sessions: dict, sym: str, cells: dict | None = None) -> dict:
    T = build_tape(sessions, INSTRUMENTS[sym]["pv"])
    return dict(sessions=len(sessions), first=str(min(sessions)), last=str(max(sessions)),
                cells={name: score(tr) for name, tr in run_cells(T, cells).items()})


def explore(sha: str) -> dict:
    res = dict(script_sha=sha)
    for sym in ("SPY", "QQQ"):
        res[sym] = run(load_xnas(sym), sym)
        report(sym, res[sym])
    res["selected"] = select(res)
    print(f"\nselection (>= {MIN_TRADES} trades, mean R, 2x-cost R and edge > 0 on both; script {sha}):")
    for setup, c in res["selected"].items():
        print(f"  {setup:<12} " + ("dropped: no cell qualified" if c is None else f"{c['cell']}  pooled {c['pooled_mean']:+.3f}R"))
    (OUT / "explore.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--explore", action="store_true", help="all cells on XNAS SPY + QQQ <= 2025-03-26 (repeatable)")
    mode.add_argument("--freeze", action="store_true", help="re-run the exploration, pick cells, pin the script hash")
    mode.add_argument("--confirm", action="store_true", help="score the frozen cells once on NQ 2012-2021")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sha = script_sha()

    if args.explore:
        explore(sha)
        return 0

    if args.freeze:
        if PREREG.exists() or looks():
            print(f"already frozen ({PREREG}) or already scored ({LOOKS}); refusing")
            return 1
        chosen = explore(sha)["selected"]
        PREREG.write_text(json.dumps(dict(script_sha=sha, selected=chosen, alpha=ALPHA,
                                          frozen_at=pd.Timestamp.now(tz="UTC").isoformat()), indent=1) + "\n")
        print(f"frozen script {sha}. Commit {PREREG.name} now.")
        return 0

    if looks() or (OUT / "results.json").exists():
        print(f"already scored ({'; '.join(looks()) or OUT / 'results.json'}); refusing a second look")
        return 1
    if not PREREG.exists():
        print("run --explore and --freeze first")
        return 1
    pin = json.loads(PREREG.read_text())
    if pin["script_sha"] != sha:
        print(f"spec changed since --freeze ({pin['script_sha']} -> {sha}); refusing")
        return 1
    live = {s: c for s, c in pin["selected"].items() if c}
    if not live:
        print("no setup qualified in exploration: nothing to confirm, NQ left unread")
        return 0
    sessions = load_nq()
    if gaps := coverage_problems(sessions):
        print(f"NQ download incomplete ({', '.join(gaps)}; need >= {NQ_MIN_SESSIONS_PER_YEAR} a year); "
              "nothing scored, the look is not spent")
        return 1
    with LOOKS.open("a") as f:
        f.write(f"script={sha} sessions={len(sessions)} at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    print(f"look logged in {LOOKS.name}: commit it with the results")
    res = run(sessions, "NQ", {s: [c["params"]] for s, c in live.items()})
    report("NQ (one look)", res)
    res["verdicts"] = {c["cell"]: verdict(res["cells"][c["cell"]]) for c in live.values()}
    print(f"\nVERDICTS (alpha {ALPHA:.4f}): {res['verdicts']}")
    (OUT / "results.json").write_text(json.dumps(dict(prereg=pin, result=res), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
