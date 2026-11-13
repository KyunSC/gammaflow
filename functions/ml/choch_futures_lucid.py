"""Intraday change of character (CHoCH) on CME NQ and ES, 2011-2021, scored for a LucidFlex 50K account (C6L).

The rule is PR #16's CHoCH (choch_rule.py, imported unchanged), moved from 4h crypto bars to 15m RTH futures bars and
traded intraday only. SPEC below was written 2026-10-28 before any 2011-2021 bar was read for this rule; it is a
one-look test: `--confirm` writes the preregistration and the lock BEFORE a single bar is loaded and refuses forever
after. Execution, costs, Lucid replay and the data loader are orb15_2r_study's (its 2011-2021 confirmation path).

    python choch_futures_lucid.py --check     # coverage, sessions and roll dates only: no signal, trade or result
    python choch_futures_lucid.py --confirm   # THE one look: prereg + lock, then data/choch_futures/lucid_results.json

Prior use of 2011-2021 CME bars (see MEMORY): ORB and VWAP studies ran their confirmations on these years, and the
open-EMA study used 2016-2021. None of them traded swing structure; the window is not pristine but this rule never ran.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from choch_rule import choch_events  # noqa: E402
from open_ema_trail_study import ET, contract_segments  # noqa: E402
from orb15_2r_study import (CLOSE_M, COMM_SIDE, CONF_WINDOW, FUT_BARS, MAX_MICROS, MIN_PRICE, OPEN_M,  # noqa: E402
                            PT_USD, TICK, missing_months)

OUT = HERE / "data" / "choch_futures"
PRODUCTS = ("NQ", "ES")

SPEC = dict(
    id="C6L",
    title="Intraday 15m change of character on CME NQ/ES for LucidFlex 50K",
    source=("PR #16 CHoCH rule (choch_rule.py = choch_crypto_study.swing_points/choch_events, commit cfb9294) "
            "moved to CME futures intraday at Sunny's request, 2026-10-28"),
    data=("Databento GLBX.MDP3 fut-ohlcv-1m-cont NQ.v.0 / ES.v.0 (data/databento/fut-ohlcv-1m-cont), native points, "
          "sessions 2011-01-03 -> 2021-12-31, RTH 1m bars starting 09:30-15:59 ET, loaded like orb15_2r_study.load_fut "
          "but keeping every session with one instrument_id all session and an RTH bar starting at or after 15:30 ET "
          "(drops only scheduled early closes; the March 2020 halt days, ~376 bars, stay in), MIN_PRICE guard. Refuse if any month is missing."),
    bars=("tf-minute RTH bars anchored at 09:30 ET (15m: 09:30, 09:45, ... 15:45) from the 1m bars present. "
          "A contract segment is a run of consecutive kept sessions with one instrument_id (a flip back starts a new "
          "segment). Within a segment the tf series is continuous across sessions (overnight excluded, so swings from "
          "yesterday's RTH stay valid); swing state and ATR restart at every new segment. Bars of a segment's first "
          "session build swings and ATR, but no trade is entered that session."),
    rule=("choch_rule.choch_events(high, low, close, k) on each segment's tf bars, unchanged. A signal at a tf close is "
          "tradeable only if that close is at or before 15:00 ET. Entry at the open of the first 1m bar at or after "
          "the close in the same session, 1 tick adverse."),
    stop=("dist = side x (signal close - extreme) + 0.1 x ATR14 (simple mean of the true range of the 14 tf bars "
          "ending at the signal bar, within segment; the first bar of a segment has TR = high - low; fewer than 14 bars "
          "-> no signal), rounded to the nearest tick; skip if dist <= 1 tick. stop = entry - side x dist, "
          "target = entry + side x dist (1R)."),
    exits=("1m bars from the entry bar: a later bar opening through the stop fills at its open - 1 tick; a low (high "
           "for shorts) through the stop fills at stop - 1 tick; a bar trading 1 tick through the target fills at the "
           "target; stop first when one bar touches both; otherwise flat at the session's last RTH 1m bar close - 1 "
           "tick. Never overnight."),
    book=("One position at a time per product. Both directions of every taken signal are simulated (mirror legs); a "
          "signal is dropped if its entry bar is not after the exit bar of both mirror legs of the previous trade, so "
          "the trade set does not depend on direction (mfp_crypto_study.run_book). Signals on a segment's first session "
          "or after 15:00 are dropped and do not block. No daily trade cap."),
    costs=("$0.50 per micro per side plus the slippage above. contracts = min(40, floor(risk / (dist x PT_USD + 1))) "
           "with MNQ $2/pt, MES $5/pt; a trade sized 0 at the primary risk is skipped. net R = dollar P&L / "
           "(contracts x dist x PT_USD) = (pts x PT_USD - 1) / (dist x PT_USD); gross R = pts / dist."),
    statistics=("Per product and config: mean net R vs 2,000 coin-flip twins with P(long) = the strategy's long share "
                "(and a fair coin, reported) on the same trades, legs and sizing; p = (1 + #twins with mean >= "
                "strategy mean) / 2,001; excess = taken R - (p_long x long R + (1 - p_long) x short R) per trade, 95% "
                "CI by a 5-session block bootstrap (5,000 reps) over tradable sessions, ratio of resampled excess sums "
                "to trade counts. Also by-year excess, by-side mean R, exit reasons, trades per tradable session, "
                "MAX_MICROS cap share."),
    lucid=("LucidFlex 50K, $90.20 fee, replayed twice: with the $1,200 daily loss limit (flybrain default, as "
           "orb15_2r_study.lucid_ev and lucid_structure use; this one drives STRUCTURE-ONLY) and without it (same "
           "price at Lucid; reported). lucid_structure.replay -> "
           "flybrain.prop.simulate_account, 250-session horizon of iid session draws, every kept session a day, "
           "no-trade sessions included). Day P&L sums the session's trades; intraday lo/hi from each trade's MAE/MFE "
           "stacked on the running P&L. Risk $1,050 (primary) and $1,550; strategy 20,000 paths; coin-flip twins "
           "(P(long) = long share): 10 direction draws x 2,000 paths, EV averaged. Primary config only."),
    decision=("alpha = 0.025 per product. PASS only if the primary config's twin test has p < 0.025 AND excess CI "
              "lower bound > 0 on BOTH NQ and ES. Otherwise STRUCTURE-ONLY if the strategy's Lucid EV (DLL on) at $1,050 is > 0 "
              "on BOTH products (payout asymmetry, no entry edge). Otherwise FAIL."),
    fixed=dict(atr_bars=14, pad_atr=0.1, target_r=1.0, last_signal_et="15:00", min_last_bar_et="15:30", tick=TICK,
               comm_side=COMM_SIDE, max_micros=MAX_MICROS, pt_usd=PT_USD, risks=[1050, 1550], alpha=0.025,
               n_twins=2000, boot_block_sessions=5, boot_reps=5000, lucid_paths=20000, lucid_twins=10,
               lucid_twin_paths=2000, seed=20261028),
    window=[str(CONF_WINDOW[0]), str(CONF_WINDOW[1])],
    primary=dict(k=2, tf=15),
    grid=dict(k=[1, 2, 3, 5], tf=[5, 15, 30]),
)

F = SPEC["fixed"]
ATR_LEN, PAD_ATR, TARGET_R = F["atr_bars"], F["pad_atr"], F["target_r"]
LAST_SIGNAL_M = 15 * 60
MIN_LAST_M = 15 * 60 + 30
assert F["min_last_bar_et"] == "15:30"
RISKS = tuple(F["risks"])
ALPHA, N_TWINS, BLOCK, BOOT_REPS = F["alpha"], F["n_twins"], F["boot_block_sessions"], F["boot_reps"]
LUCID_PATHS, LUCID_TWINS, LUCID_TWIN_PATHS = F["lucid_paths"], F["lucid_twins"], F["lucid_twin_paths"]
SEED = F["seed"]
assert LAST_SIGNAL_M == 900 and F["last_signal_et"] == "15:00"


def configs() -> list[dict]:
    return [dict(k=k, tf=tf) for tf in SPEC["grid"]["tf"] for k in SPEC["grid"]["k"]]


def cfg_key(c: dict) -> str:
    return f"k{c['k']}/{c['tf']}m"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def spec_hash() -> dict:
    rule, me = sha256_file(HERE / "choch_rule.py"), sha256_file(Path(__file__).resolve())
    body = json.dumps(SPEC, sort_keys=True, default=str) + rule + me
    return dict(spec_hash=hashlib.sha256(body.encode()).hexdigest()[:16], choch_rule_sha256=rule,
                choch_futures_lucid_sha256=me)


# ---------------------------------------------------------------- tape and bars

@dataclass
class Tape:
    """Kept RTH sessions of one product. Per session: date, segment, first-of-segment flag, [s0, s1) into the 1m
    arrays. Per 1m bar: ET minute, session index, OHLC."""
    d: np.ndarray
    seg: np.ndarray
    first: np.ndarray
    s0: np.ndarray
    s1: np.ndarray
    m: np.ndarray
    sess: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray


def make_tape(bars, min_bars: int = 1, min_last_m: int = MIN_LAST_M) -> Tape:
    """bars: 1m OHLC + instrument_id, tz-aware index. Keeps RTH sessions with one instrument, >= min_bars bars and a bar
    starting at or after min_last_m (ET minutes), i.e. not a scheduled early close."""
    import pandas as pd
    bars = bars.sort_index()
    et = bars.index.tz_convert(ET)
    m = np.asarray(et.hour * 60 + et.minute)
    keep = (m >= OPEN_M) & (m < CLOSE_M)
    bars, m = bars[keep], m[keep]
    day = np.asarray(bars.index.tz_convert(ET).date)
    iid = bars.instrument_id.to_numpy()
    st = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    en = np.r_[st[1:], len(day)]
    ok = (((en - st) >= min_bars) & (np.maximum.reduceat(m, st) >= min_last_m)
          & (np.maximum.reduceat(iid, st) == np.minimum.reduceat(iid, st)))
    rows = np.concatenate([np.arange(a, b) for a, b, k in zip(st, en, ok) if k]) if ok.any() else np.array([], int)
    st, en = st[ok], en[ok]
    lens = en - st
    s0 = np.r_[0, np.cumsum(lens)[:-1]].astype(int)
    seg = contract_segments(pd.Series(iid[st])).to_numpy()
    first = np.r_[True, seg[1:] != seg[:-1]] if len(seg) else np.array([], bool)
    b = bars.iloc[rows]
    return Tape(d=day[st], seg=seg, first=first, s0=s0, s1=s0 + lens, m=m[rows],
                sess=np.repeat(np.arange(len(st)), lens), O=b.open.to_numpy(float), H=b.high.to_numpy(float),
                L=b.low.to_numpy(float), C=b.close.to_numpy(float))


@dataclass
class Bars:
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    sess: np.ndarray
    seg: np.ndarray
    start_m: np.ndarray
    close_m: np.ndarray
    last: np.ndarray  # index of the bar's last 1m bar in the tape


def tf_bars(tape: Tape, tf: int) -> Bars:
    """tf-minute bars anchored at 09:30 ET within each session, from the 1m bars present."""
    slot = (tape.m - OPEN_M) // tf
    key = tape.sess.astype(np.int64) * 10_000 + slot
    st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    en = np.r_[st[1:], len(key)] - 1
    sess = tape.sess[st]
    start = OPEN_M + slot[st] * tf
    return Bars(h=np.maximum.reduceat(tape.H, st), l=np.minimum.reduceat(tape.L, st), c=tape.C[en], sess=sess,
                seg=tape.seg[sess], start_m=start, close_m=start + tf, last=en)


def atr_simple(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = ATR_LEN) -> np.ndarray:
    """Mean true range of the n bars ending at each bar; the first bar's TR is high - low; NaN before n bars."""
    pc = np.r_[np.nan, c[:-1]]
    tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(h), np.nan)
    if len(h) >= n:
        cs = np.r_[0.0, np.cumsum(tr)]
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


@dataclass
class Signal:
    e: int        # entry 1m bar index
    side: int
    dist: float
    sess: int
    bar: int      # tf bar index of the signal close
    close_m: int


def raw_events(bars: Bars, k: int) -> list[tuple[int, int, float, float]]:
    """(tf bar, side, extreme, ATR at that bar) for every CHoCH, swings and ATR restarted per contract segment."""
    out = []
    st = np.flatnonzero(np.r_[True, bars.seg[1:] != bars.seg[:-1]])
    for a, b in zip(st, np.r_[st[1:], len(bars.seg)]):
        h, l, c = bars.h[a:b], bars.l[a:b], bars.c[a:b]
        atr = atr_simple(h, l, c)
        out += [(a + t, side, ext, float(atr[t])) for t, side, ext in choch_events(h, l, c, k)]
    return out


def signals(tape: Tape, bars: Bars, k: int) -> list[Signal]:
    out = []
    for b, side, ext, atr in raw_events(bars, k):
        s = int(bars.sess[b])
        if not np.isfinite(atr) or bars.close_m[b] > LAST_SIGNAL_M or tape.first[s]:
            continue
        e = int(bars.last[b]) + 1
        if e >= tape.s1[s]:
            continue
        dist = round((side * (bars.c[b] - ext) + PAD_ATR * atr) / TICK) * TICK
        if dist <= TICK:
            continue
        out.append(Signal(e, side, float(dist), s, int(b), int(bars.close_m[b])))
    return out


# ---------------------------------------------------------------- execution

def leg(tape: Tape, e: int, side: int, dist: float) -> dict:
    """orb15_2r_study.trade with a given stop distance and a 1R target. Shorts are mirrored longs."""
    sl = slice(e, int(tape.s1[tape.sess[e]]))
    if side > 0:
        O, H, L, C = tape.O[sl], tape.H[sl], tape.L[sl], tape.C[sl]
    else:
        O, H, L, C = -tape.O[sl], -tape.L[sl], -tape.H[sl], -tape.C[sl]
    n = len(O)
    entry = O[0] + TICK
    stop, target = entry - dist, entry + TARGET_R * dist
    hs, ht = np.flatnonzero(L <= stop), np.flatnonzero(H >= target + TICK)
    fs, ft = (hs[0] if len(hs) else n), (ht[0] if len(ht) else n)
    if fs < n and fs <= ft:
        x, why = int(fs), "stop"
        px = O[x] - TICK if x > 0 and O[x] <= stop else stop - TICK
        pre = slice(0, x)
    elif ft < n:
        x, why, px, pre = int(ft), "target", target, slice(0, int(ft))
    else:
        x, why, px, pre = n - 1, "time", C[-1] - TICK, slice(0, n)
    mae = min(float((L[pre] - entry).min(initial=0.0)), px - entry)  # bars before the exit bar, then the fill
    mfe = max(float((H[pre] - entry).max(initial=0.0)), px - entry)
    return dict(pts=float(px - entry), why=why, exit=e + x, mae=float(mae), mfe=float(mfe), entry=float(side * entry))


def contracts(dist: float, pt: float, risk: float) -> int:
    return int(min(MAX_MICROS, math.floor(risk / (dist * pt + 2 * COMM_SIDE))))


def uncapped(dist: float, pt: float, risk: float) -> int:
    return int(math.floor(risk / (dist * pt + 2 * COMM_SIDE)))


@dataclass
class Trade:
    sig: Signal
    n: int
    legs: dict


def run_book(tape: Tape, sigs: list[Signal], pt: float, risk: float = RISKS[0]) -> list[Trade]:
    out, busy = [], -1
    for sg in sorted(sigs, key=lambda s: s.e):
        if sg.e <= busy:
            continue
        n = contracts(sg.dist, pt, risk)
        if n < 1:
            continue
        legs = {s: leg(tape, sg.e, s, sg.dist) for s in (1, -1)}
        out.append(Trade(sg, n, legs))
        busy = max(legs[1]["exit"], legs[-1]["exit"])
    return out


def net_r(lg: dict, dist: float, pt: float) -> float:
    return (lg["pts"] * pt - 2 * COMM_SIDE) / (dist * pt)


# ---------------------------------------------------------------- statistics

def taken(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray) -> np.ndarray:
    return np.where(dirs > 0, rl, rs)


def session_block_ci(x: np.ndarray, rank: np.ndarray, n_sess: int, rng, reps: int = BOOT_REPS,
                     block: int = BLOCK) -> tuple[float, float]:
    """95% CI of the per-trade mean of x, resampling blocks of consecutive tradable sessions."""
    s = np.bincount(rank, weights=x, minlength=n_sess)
    c = np.bincount(rank, minlength=n_sess).astype(float)
    block = max(1, min(block, n_sess))
    nb = int(np.ceil(n_sess / block))
    starts = rng.integers(0, n_sess - block + 1, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)).reshape(reps, -1)[:, :n_sess]
    with np.errstate(invalid="ignore", divide="ignore"):
        m = s[idx].sum(1) / c[idx].sum(1)
    m = m[np.isfinite(m)]
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def r_test(rl, rs, dirs, rank, n_sess, p_long=None, n_twins=N_TWINS, seed=SEED) -> dict:
    """Mean net R of dirs vs twins drawing each trade's side with P(long) = p_long (default dirs' long share)."""
    n = len(dirs)
    if n == 0:
        return dict(trades=0)
    pl = float((dirs > 0).mean()) if p_long is None else float(p_long)
    r = taken(rl, rs, dirs)
    rng = np.random.default_rng(seed)
    twin = np.empty(n_twins)
    d = rl - rs
    for a in range(0, n_twins, 250):
        b = min(n_twins, a + 250)
        twin[a:b] = (rs.sum() + (rng.random((b - a, n)) < pl).astype(float) @ d) / n
    ex = r - (pl * rl + (1 - pl) * rs)
    lo, hi = session_block_ci(ex, rank, n_sess, rng)
    return dict(trades=n, p_long=pl, mean_r=float(r.mean()), twin_mean_r=float(twin.mean()),
                twin_p95=float(np.quantile(twin, 0.95)), excess=float(ex.mean()), excess_ci=[lo, hi],
                p=float((1 + (twin >= r.mean() - 1e-12).sum()) / (1 + n_twins)))


def passes(t: dict, alpha: float = ALPHA) -> bool:
    return t.get("trades", 0) > 0 and t["p"] < alpha and t["excess_ci"][0] > 0


def book_arrays(tape: Tape, trades: list[Trade], pt: float) -> dict:
    tradable = np.flatnonzero(~tape.first)
    sess = np.array([t.sig.sess for t in trades], int)
    return dict(dirs=np.array([t.sig.side for t in trades]),
                rl=np.array([net_r(t.legs[1], t.sig.dist, pt) for t in trades]),
                rs=np.array([net_r(t.legs[-1], t.sig.dist, pt) for t in trades]),
                gl=np.array([t.legs[1]["pts"] / t.sig.dist for t in trades]),
                gs=np.array([t.legs[-1]["pts"] / t.sig.dist for t in trades]),
                sess=sess, rank=np.searchsorted(tradable, sess), n_sess=len(tradable))


def summarize(tape: Tape, trades: list[Trade], product: str, n_twins: int = N_TWINS, seed: int = SEED) -> dict:
    pt = PT_USD[product]
    n_tradable = int((~tape.first).sum())
    if not trades:
        return dict(trades=0, tradable_sessions=n_tradable)
    a = book_arrays(tape, trades, pt)
    dirs, rl, rs = a["dirs"], a["rl"], a["rs"]
    r, g = taken(rl, rs, dirs), taken(a["gl"], a["gs"], dirs)
    tw = r_test(rl, rs, dirs, a["rank"], a["n_sess"], None, n_twins, seed)
    fair = r_test(rl, rs, dirs, a["rank"], a["n_sess"], 0.5, n_twins, seed + 1)
    pl = tw["p_long"]
    ex = r - (pl * rl + (1 - pl) * rs)
    years = np.array([tape.d[s].year for s in a["sess"]])
    dist = np.array([t.sig.dist for t in trades])
    return dict(
        trades=len(trades), tradable_sessions=n_tradable, trades_per_session=len(trades) / n_tradable,
        long_share=pl, mean_net_R=float(r.mean()), mean_gross_R=float(g.mean()), win_rate=float((r > 0).mean()),
        twins=tw, fair_coin=fair,
        by_side={("long" if s > 0 else "short"): dict(trades=int((dirs == s).sum()), mean_net_R=float(r[dirs == s].mean()))
                 for s in (1, -1) if (dirs == s).any()},
        exits=dict(Counter(t.legs[t.sig.side]["why"] for t in trades)),
        years={int(y): dict(trades=int((years == y).sum()), mean_net_R=float(r[years == y].mean()),
                            excess=float(ex[years == y].mean())) for y in np.unique(years)},
        median_dist_pts=float(np.median(dist)),
        cap_share={str(rk): float(np.mean([uncapped(x, pt, rk) > MAX_MICROS for x in dist])) for rk in RISKS},
        median_contracts=float(np.median([t.n for t in trades])),
        median_entry_m=float(np.median([tape.m[t.sig.e] for t in trades])))


# ---------------------------------------------------------------- Lucid

def lucid_days(tape: Tape, trades: list[Trade], dirs: np.ndarray, pt: float, risk: float) -> dict:
    """One replay day per kept session: summed P&L, intraday lo/hi from MAE/MFE on the running P&L (dollars)."""
    S = len(tape.d)
    pnl, lo, hi, nt = np.zeros(S), np.zeros(S), np.zeros(S), np.zeros(S, int)
    for t, d in zip(trades, dirs):
        n = contracts(t.sig.dist, pt, risk)
        if n < 1:
            continue
        lg, c, s = t.legs[int(d)], 2 * COMM_SIDE * n, t.sig.sess
        p = lg["pts"] * pt * n - c
        before = pnl[s]
        lo[s] = min(lo[s], before + min(0.0, lg["mae"] * pt * n - c / 2, p))
        hi[s] = max(hi[s], before + max(0.0, lg["mfe"] * pt * n, p))
        pnl[s] += p
        nt[s] += 1
    return dict(pnl=pnl, lo=lo, hi=hi, trades=nt)


def lucid_ev(d: dict, paths: int = 20000, seed: int = 1, dll: bool = True) -> dict:
    """orb15_2r_study.lucid_ev with the daily loss limit as a choice (orb15 always uses it)."""
    import math
    from lucid_structure import FLEX50_FEE, replay
    from flybrain.prop import resolve_plan
    takes, used, paid, passed, _ = replay(d, resolve_plan("flex", "50k", dll), paths, seed=seed)
    ev = takes.mean() - FLEX50_FEE
    se = takes.std(ddof=1) / math.sqrt(len(takes))
    return dict(ev=float(ev), ev_lo=float(ev - 1.96 * se), ev_hi=float(ev + 1.96 * se), pass_rate=float(passed.mean()),
                paid=float(paid.mean()), days_used=float(used.mean()), trade_days=float(d["trades"].mean()),
                accounts=int(paths), accounts_scored=int(len(takes)))


def lucid_block(tape: Tape, trades: list[Trade], product: str, paths: int = LUCID_PATHS, twins: int = LUCID_TWINS,
                twin_paths: int = LUCID_TWIN_PATHS, seed: int = SEED) -> dict:
    pt = PT_USD[product]
    dirs = np.array([t.sig.side for t in trades])
    pl = float((dirs > 0).mean()) if len(dirs) else 0.5
    out = {}
    for risk, dll in [(r, d) for d in (True, False) for r in RISKS]:
        rule = lucid_ev(lucid_days(tape, trades, dirs, pt, risk), paths=paths, seed=seed, dll=dll)
        rng = np.random.default_rng(seed + risk)
        tw = [lucid_ev(lucid_days(tape, trades, np.where(rng.random(len(dirs)) < pl, 1, -1), pt, risk),
                       paths=twin_paths, seed=seed + 1 + i, dll=dll) for i in range(twins)]
        ev = np.array([x["ev"] for x in tw])
        out[str(risk) if dll else f"{risk}_noDLL"] = dict(**rule, twin_ev=float(ev.mean()), twin_min=float(ev.min()), twin_max=float(ev.max()),
                              twin_paid=float(np.mean([x["paid"] for x in tw])),
                              twins_ge_rule=float((ev >= rule["ev"]).mean()))
    return out


# ---------------------------------------------------------------- run

def verdict(per: dict, lucid: dict) -> str:
    if all(passes(per[p].get("twins", {})) for p in PRODUCTS):
        return "PASS"
    if all(lucid[p][str(RISKS[0])]["ev"] > 0 for p in PRODUCTS):
        return "STRUCTURE-ONLY"
    return "FAIL"


def evaluate(tapes: dict, n_twins: int = N_TWINS, lucid_paths: int = LUCID_PATHS, lucid_twins: int = LUCID_TWINS,
             lucid_twin_paths: int = LUCID_TWIN_PATHS, grid: list[dict] | None = None) -> dict:
    grid = grid or configs()
    rows, books = {}, {}
    print(f"\n{'config':<10}{'sym':<4}{'trades':>7}{'/day':>6}{'long':>6}{'netR':>8}{'grossR':>8}{'twin p':>8}"
          f"{'excess CI95':>20}{'fair p':>8}{'cap$1050':>9}  exits")
    for c in grid:
        key = cfg_key(c)
        rows[key] = {}
        for i, p in enumerate(PRODUCTS):
            tape = tapes[p]
            trades = run_book(tape, signals(tape, tf_bars(tape, c["tf"]), c["k"]), PT_USD[p])
            books[(key, p)] = trades
            s = rows[key][p] = summarize(tape, trades, p, n_twins, SEED + 100 * c["k"] + c["tf"] + 7 * i)
            if not s["trades"]:
                print(f"{key:<10}{p:<4}{0:>7}")
                continue
            tw = s["twins"]
            print(f"{key:<10}{p:<4}{s['trades']:>7}{s['trades_per_session']:>6.2f}{s['long_share']:>6.0%}"
                  f"{s['mean_net_R']:>+8.3f}{s['mean_gross_R']:>+8.3f}{tw['p']:>8.3f}"
                  f"  [{tw['excess_ci'][0]:+.3f},{tw['excess_ci'][1]:+.3f}]{s['fair_coin']['p']:>8.3f}"
                  f"{s['cap_share'][str(RISKS[0])]:>9.0%}  {s['exits']}")
    prim = cfg_key(SPEC["primary"])
    print("\nLucidFlex 50K, primary config (strategy vs coin-flip twins with the strategy's long share)")
    lucid = {}
    for p in PRODUCTS:
        lucid[p] = lucid_block(tapes[p], books[(prim, p)], p, lucid_paths, lucid_twins, lucid_twin_paths)
        for risk, r in lucid[p].items():
            print(f"  {p} ${risk}: EV {r['ev']:+7.1f} [{r['ev_lo']:+.0f},{r['ev_hi']:+.0f}] pass {r['pass_rate']:.1%} "
                  f"paid {r['paid']:.1%} | twins EV {r['twin_ev']:+7.1f} ({r['twin_min']:+.0f}..{r['twin_max']:+.0f}) "
                  f"paid {r['twin_paid']:.1%}, twins >= rule {r['twins_ge_rule']:.0%}")
    v = verdict(rows[prim], lucid)
    for p in PRODUCTS:
        s = rows[prim][p]
        if s["trades"]:
            print(f"  {p} {prim} by year excess: " + " ".join(f"{y}:{x['excess']:+.3f}" for y, x in s["years"].items()))
    bits = []
    for p in PRODUCTS:
        tw = rows[prim][p].get("twins", {})
        bits.append(f"{p} p={tw.get('p', float('nan')):.3f} CIlo={tw.get('excess_ci', [float('nan')])[0]:+.3f} "
                    f"EV${RISKS[0]}={lucid[p][str(RISKS[0])]['ev']:+.0f}")
    print(f"\nVERDICT C6L {prim}: {v} ({'; '.join(bits)})")
    return dict(verdict=v, primary=prim, configs=rows, lucid=lucid)


# ---------------------------------------------------------------- data access (metadata or one look)

def load_rth(product: str):
    """orb15_2r_study.load_fut without its >= 380-bar session filter (make_tape applies the session filter)."""
    import pandas as pd
    from datetime import date
    from open_ema_trail_study import file_span
    lo, end_excl = CONF_WINDOW[0], date(2022, 1, 1)
    files = [f for f in sorted((FUT_BARS / product).glob("*.parquet")) if (sp := file_span(f)) and sp[0] < end_excl and sp[1] > lo]
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume", "instrument_id"]) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    et = bars.index.tz_convert(ET)
    m = np.asarray(et.hour * 60 + et.minute)
    bars = bars[(m >= OPEN_M) & (m < CLOSE_M)]
    bars = bars[(bars.index >= pd.Timestamp(lo, tz=ET)) & (bars.index < pd.Timestamp(end_excl, tz=ET))]
    assert bars.low.min() > MIN_PRICE[product], f"{product}: prices below {MIN_PRICE[product]}"
    return bars


def load_tape(product: str) -> Tape:
    return make_tape(load_rth(product))


def check() -> int:
    """Coverage, kept sessions and roll dates only. Computes no signal, trade or result."""
    bad = False
    for p in PRODUCTS:
        miss = missing_months(p)
        print(f"{p}: missing months {miss if miss else 'none'}")
        bad |= bool(miss)
    if bad:
        return 2
    for p in PRODUCTS:
        t = load_tape(p)
        rolls = [str(d) for d in t.d[t.first]]
        per_year = Counter(d.year for d in t.d)
        print(f"{p}: {len(t.d)} kept RTH sessions {t.d[0]} -> {t.d[-1]}, {t.seg.max()} contract segments, "
              f"{int((~t.first).sum())} tradable (first session of each segment excluded)")
        print(f"  sessions per year: {dict(sorted(per_year.items()))}")
        print(f"  segment starts: {' '.join(rolls)}")
    return 0


def confirm() -> int:
    lock, prereg, results = OUT / "lucid.lock", OUT / "lucid_prereg.json", OUT / "lucid_results.json"
    if lock.exists():
        print(f"one look already taken ({lock.read_text().strip()}); refusing")
        return 1
    miss = {p: missing_months(p) for p in PRODUCTS}
    if any(miss.values()):
        print(f"missing months, refusing before the lock: {miss}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    h = spec_hash()
    now = datetime.now(timezone.utc).isoformat()
    prereg.write_text(json.dumps(dict(spec=SPEC, **h, written=now), indent=1, default=str))
    lock.write_text(f"C6L spec {h['spec_hash']} locked {now} before any bar was loaded\n")
    print(f"prereg {prereg} (spec {h['spec_hash']}); lock written; loading bars")
    tapes = {p: load_tape(p) for p in PRODUCTS}
    for p, t in tapes.items():
        print(f"{p}: {len(t.d)} sessions {t.d[0]} -> {t.d[-1]}, {t.seg.max()} segments")
    res = evaluate(tapes)
    results.write_text(json.dumps(dict(spec_hash=h["spec_hash"], **res), indent=1, default=float))
    lock.write_text(lock.read_text() + f"finished {datetime.now(timezone.utc).isoformat()} verdict {res['verdict']}\n")
    print(f"wrote {results}")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="coverage, sessions and rolls only (no signals or trades)")
    g.add_argument("--confirm", action="store_true", help="THE one look at 2011-2021 (writes prereg + lock first)")
    args = ap.parse_args(argv)
    return check() if args.check else confirm()


if __name__ == "__main__":
    raise SystemExit(main())
