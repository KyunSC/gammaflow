"""VWAP stretch long: buy ES or NQ when price is 2 ATR below session VWAP.

Sunny asked (2026-10-24): "check a strategy where it buys NQ or ES if the price is 2 ATR below the VWAP". Long only,
the threshold is his (K_ATR = 2). He did not say which ATR, where to get out or where the stop goes, so those are a
small grid fixed here, before any number was looked at, instead of being tuned. The app already has this rule:
vwapReversion.js with Entry 2.0 ATR and Short side off (its exit is 0.2 ATR below VWAP and it has no stop). The
prop survey (prop_survey_study.py, PR #6) tests the two-sided 1.2 ATR version of it; this one tests Sunny's rule.

Rules (fixed before any number was looked at):
  - data, exploration: Databento XNAS.ITCH SPY + QQQ ohlcv-1m sessions <= DISCOVERY_END (2025-03-26), loaded by
    amt_lucid_study.load_sessions (RTH 09:30-15:59 ET, >= 380 bars). Prices go to the futures plane (SPY x10.05 ~ ES
    $50/pt, QQQ x41.2 ~ NQ $20/pt, tick 0.25). Unlimited runs: these sessions have been read by other studies.
  - data, confirmation: Databento GLBX.MDP3 ES.v.0 and NQ.v.0 ohlcv-1m, RTH sessions 2012-01-03 -> 2021-12-31, from
    the es-ohlcv-1m-early (PR #10) and nq-ohlcv-1m-early (PR #11) download jobs. Scored ONCE (--confirm). Those
    folders are also the one-look sets of vp_claims_study.py and trader_playbooks_study.py: run --confirm here only
    after both of those are frozen (their prereg committed), so nothing seen here can steer their selection.
  - VWAP: session VWAP from 09:30 of typical price (H+L+C)/3 x volume on 1m bars, as of the signal bar's close.
  - ATR ("tf" grid): bars of tf minutes, 09:30-anchored, built from the 1m bars. True range = max(H-L, |H-Cprev|,
    |L-Cprev|), with H-L for a session's first bar (the overnight gap is not RTH range). ATR = mean true range of the
    last ATR_N = 14 such bars on the RTH tape, the signal bar included (as the app computes atr:14). tf = 5 is what
    the app's VWAP Fade means on a 5m chart; 1 and 15 bracket it. 2 ATR of 1m bars is a small stretch, 2 ATR of 15m
    bars a large one.
  - signal: a tf bar closing between 10:00 and 15:00 ET with close <= VWAP - K_ATR x ATR, while flat and armed.
    Entry = the next 1m bar's open + 1 tick. One position at a time. After an exit the rule re-arms only once a tf
    bar closes back above VWAP - K_ATR x ATR, so one stretch is one trade. No limit on trades per session.
  - target ("target" grid), frozen at entry (ref = the entry bar's open, before slippage):
      vwap   the signal bar's VWAP, rounded to the tick (~2 ATR above entry): the full reversion.
      half   ref + half the way to that VWAP (~1 ATR): a partial reversion.
    No trade if the target is not at least a tick above ref.
  - stop ("stop" grid): "1atr" = ref - 1 ATR, rounded to the tick; "none" = no stop (Sunny's rule as stated, and the
    app's). Every trade is flat at the 15:54 bar's close - 1 tick if neither is hit.
  - execution: on 1m bars. A bar that opens through the stop fills at its open, else at the stop, both 1 tick worse;
    a bar touching both counts as the stop (flagged "ambiguous"). The target fills at its price when a bar trades a
    tick THROUGH it, or at the open of a bar opening through it. Costs: $4.50 round trip per contract (ES $50/pt, NQ
    $20/pt), as ORDERFLOW_GEX_PREREG.md. R = (points - cost points) / ATR at the signal: 1 R is one ATR of that tf, in
    every cell, because the "none" stop has no risk unit of its own. Each trade is also replayed at doubled friction
    (2 ticks slippage per side, 2x commission) -> mean_2x, and with no costs -> gross.
  - twins, built from each trade's own session, stop and target distances and 15:54 exit:
      coin flip    the same entry bar, short, stop and target mirrored around ref. edge_flip = mean (r - r_flip)/2;
                   p_flip = share of N_RANDOM coin draws (r or r_flip per trade) whose mean >= mean r. On an
                   uptrending index a long-only rule beats this twin by drift alone, so it is reported, not gated.
      random time  the same long, at the same minute of day, on K_RAND other sessions of the tape drawn at random,
                   with the stop and target at the same multiples of that session's ATR (as of that minute) and
                   R in that ATR. It holds the clock, the exits and the drift fixed and changes only the condition:
                   is "2 ATR below VWAP" a better time to buy than any other day at that time? (Random minutes of
                   the trade's own session would be biased: that session is chosen because it fell after them.)
                   edge_rand = mean (r - mean of the trade's K_RAND replays); p_rand = share of N_RANDOM draws (one
                   replay per trade) whose mean >= mean r.
  - grid: tf in {1, 5, 15} x target in {vwap, half} x stop in {1atr, none} = 12 cells, one threshold (K_ATR = 2).
  - selection (--freeze, exploration only): the cell with >= MIN_TRADES trades on each of SPY and QQQ, mean net R > 0,
    mean_2x > 0, edge_flip > 0, edge_rand > 0 and p_rand < SELECT_P = 0.10 on both; the highest pooled mean net R. No
    such cell: the rule is dropped and ES / NQ are never read for it. (The p_rand gate is there because on a random
    walk with an up-drift several cells clear every "> 0" gate on both symbols: a long that holds to the close
    collects the drift, and the one look should not be spent on that.)
  - inference: moving-block bootstrap over trades in time order (blocks of 5, N_BOOT draws, seed 0).
  - verdict on each of ES and NQ (--confirm), ALPHA = 0.05 / 2: PASS when the one-sided lower bound of mean net R at
    ALPHA is > 0, p_rand < ALPHA and mean_2x > 0. Otherwise FAIL.

One look, enforced as in trader_playbooks_study.py: script_sha() hashes this file AND amt_lucid_study.py; the tests pin
it (SPEC_SHA). --freeze re-runs the exploration and writes vwap_stretch_prereg.json next to this script (commit it).
--confirm refuses when vwap_stretch_looks.log (committed) has a look, when the hash changed, or when either download
misses a year (>= 230 sessions in each of 2012-2021); then it appends the look before scoring.

    python functions/ml/vwap_stretch_study.py --explore
    python functions/ml/vwap_stretch_study.py --freeze          # then commit functions/ml/vwap_stretch_prereg.json
    python functions/ml/vwap_stretch_study.py --confirm         # ask first; then commit functions/ml/vwap_stretch_looks.log

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

OUT = amt.DATA / "vwap_stretch"
PREREG, LOOKS = HERE / "vwap_stretch_prereg.json", HERE / "vwap_stretch_looks.log"   # committed, unlike OUT
SPEC_FILES = (Path(__file__).resolve(), HERE / "amt_lucid_study.py")
FUT_DIRS = {"ES": amt.DATA / "databento" / "es-ohlcv-1m-early" / "ES",
            "NQ": amt.DATA / "databento" / "nq-ohlcv-1m-early" / "NQ"}
CONFIRM_START, CONFIRM_END = date(2012, 1, 3), date(2021, 12, 31)
MIN_SESSIONS_PER_YEAR = 230

INSTRUMENTS = {"SPY": dict(ratio=10.05, pv=50.0), "QQQ": dict(ratio=41.2, pv=20.0),
               "ES": dict(ratio=1.0, pv=50.0), "NQ": dict(ratio=1.0, pv=20.0)}
COMMISSION_RT = 4.50
SLIP = TICK

K_ATR = 2.0
ATR_N = 14
SIG_FIRST, SIG_LAST = 600, 900     # 10:00, 15:00: signal bar closes, and random-time entry bars, in this window
NO_STOP = 1e9

GRID = [dict(tf=tf, target=t, stop=s) for tf in (1, 5, 15) for t in ("vwap", "half") for s in ("1atr", "none")]
MIN_TRADES = 60
SELECT_P = 0.10
ALPHA = 0.05 / 2
K_RAND = 20
N_BOOT, BLOCK, N_RANDOM, SEED = 4000, 5, 5000, 0


def cell_name(p: dict) -> str:
    return "/".join(f"{k}={v}" for k, v in p.items())


def rt(x: float) -> float:
    return round(x / TICK) * TICK


# ---------------------------------------------------------------- data

def session(g: pd.DataFrame, ratio: float, inst=None) -> dict:
    return dict(O=g.open.to_numpy(float) * ratio, H=g.high.to_numpy(float) * ratio, L=g.low.to_numpy(float) * ratio,
                C=g.close.to_numpy(float) * ratio, V=g.volume.to_numpy(float), m=g.minute.to_numpy(int), inst=inst)


def load_xnas(symbol: str) -> dict[date, dict]:
    ratio = INSTRUMENTS[symbol]["ratio"]
    return {d: session(g, ratio) for d, g in amt.load_sessions(symbol, DISCOVERY_END).items()}


def load_fut(sym: str, start: date = CONFIRM_START, end: date = CONFIRM_END) -> dict[date, dict]:
    bars_dir = FUT_DIRS[sym]
    files = sorted(bars_dir.glob("*.parquet"))
    if not files:
        job = bars_dir.parent.name
        raise FileNotFoundError(f"no bars in {bars_dir}; run databento_fetch.py {job}")
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
    m: np.ndarray
    vwap: np.ndarray         # per 1m bar: session VWAP through this bar's close
    start: np.ndarray        # per session: first 1m index
    end: np.ndarray          # per session: last 1m index
    flat: np.ndarray         # per session: index of the 15:54 bar (last bar held)
    days: list
    pv: float


def session_vwap(H, L, C, V) -> np.ndarray:
    tp = (H + L + C) / 3
    cv = np.cumsum(V)
    return np.where(cv > 0, np.cumsum(tp * V) / np.where(cv > 0, cv, 1), tp)


def build_tape(sessions: dict[date, dict], pv: float) -> Tape:
    days = sorted(sessions)
    ss = [sessions[d] for d in days]
    lens = np.array([len(s["m"]) for s in ss])
    start = np.r_[0, np.cumsum(lens)[:-1]].astype(int)
    flat = np.array([st + int(np.flatnonzero(s["m"] >= FLAT)[0]) for st, s in zip(start, ss)])
    cat = {k: np.concatenate([s[k] for s in ss]) for k in ("O", "H", "L", "C", "m")}
    vwap = np.concatenate([session_vwap(s["H"], s["L"], s["C"], s["V"]) for s in ss])
    return Tape(vwap=vwap, start=start, end=start + lens - 1, flat=flat, days=days, pv=pv, **cat)


@dataclass
class Bars:
    """tf-minute bars of the tape, 09:30-anchored, never spanning sessions."""
    first: np.ndarray        # 1m index of the bar's first bar
    last: np.ndarray         # 1m index of its last bar
    close_min: np.ndarray    # minute the bar closes (its bucket end)
    C: np.ndarray
    sess: np.ndarray
    atr: np.ndarray          # ATR_N mean true range through this bar (nan before ATR_N bars)


def tf_bars(T: Tape, tf: int) -> Bars:
    first, last, cmin, sess = [], [], [], []
    for s, (a, b) in enumerate(zip(T.start, T.end)):
        bucket = (T.m[a:b + 1] - OPEN) // tf
        cut = np.flatnonzero(np.diff(bucket)) + 1
        f = np.r_[0, cut] + a
        l = np.r_[cut - 1, b - a] + a
        first.append(f)
        last.append(l)
        cmin.append(OPEN + (bucket[f - a] + 1) * tf)
        sess.append(np.full(len(f), s))
    first, last, cmin, sess = (np.concatenate(x).astype(int) for x in (first, last, cmin, sess))
    H = np.array([T.H[a:b + 1].max() for a, b in zip(first, last)])
    L = np.array([T.L[a:b + 1].min() for a, b in zip(first, last)])
    C = T.C[last]
    tr = H - L
    same = np.r_[False, sess[1:] == sess[:-1]]
    prev = np.r_[np.nan, C[:-1]]
    tr = np.where(same, np.maximum(tr, np.maximum(np.abs(H - prev), np.abs(L - prev))), tr)
    cs = np.r_[0.0, np.cumsum(tr)]
    atr = np.full(len(tr), np.nan)
    atr[ATR_N - 1:] = (cs[ATR_N:] - cs[:-ATR_N]) / ATR_N
    return Bars(first=first, last=last, close_min=cmin, C=C, sess=sess, atr=atr)


# ---------------------------------------------------------------- execution

def fill(T: Tape, d: int, j: int, entry: float, stop: float, target: float, last: int, slip: float,
         comm_pts: float) -> dict:
    """Net points of a bracket entered at bar j's open (`entry` includes the entry slippage)."""
    amb, i = False, last
    for i in range(j, last + 1):
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
    return dict(pts=(px - entry) * d - comm_pts, reason=why, amb=amb, exit=i)


def bracket(T: Tape, d: int, j: int, stop_d: float, tgt_d: float, last: int, slip: float, comm: float) -> dict:
    ref = float(T.O[j])
    return fill(T, d, j, ref + d * slip, ref - d * stop_d, ref + d * tgt_d, last, slip, comm)


def atr_by_minute(T: Tape, B: Bars) -> np.ndarray:
    """Per 1m bar: the ATR of the last tf bar closed at or before it (forward-filled along the tape)."""
    out = np.full(len(T.O), np.nan)
    out[B.last] = B.atr
    return pd.Series(out).ffill().to_numpy()


def random_time(T: Tape, atr1: np.ndarray, s: int, minute: int, stop_m: float, tgt_m: float, comm: float,
                rng: np.random.Generator) -> list[float]:
    """R of K_RAND longs at `minute` on other random sessions, stop / target at the same ATR multiples."""
    out, n, tries = [], len(T.start), 0
    while len(out) < K_RAND and tries < 50 * K_RAND and n > 1:
        tries += 1
        o = int(rng.integers(0, n - 1))
        o += o >= s
        a = int(T.start[o])
        j = a + int(np.searchsorted(T.m[a:T.end[o] + 1], minute))
        if j > T.flat[o] or not (atr1[j - 1] > 0):
            continue
        atr = float(atr1[j - 1])
        stop_d = NO_STOP if stop_m >= NO_STOP else stop_m * atr
        out.append(bracket(T, 1, j, stop_d, tgt_m * atr, int(T.flat[o]), SLIP, comm)["pts"] / atr)
    return out


def trade(T: Tape, atr1: np.ndarray, s: int, j: int, atr: float, vwap: float, p: dict,
          rng: np.random.Generator) -> dict | None:
    ref = float(T.O[j])
    full = rt(vwap) - ref
    tgt_d = full if p["target"] == "vwap" else rt(ref + full / 2) - ref
    if tgt_d < TICK:
        return None
    stop_d = max(TICK, ref - rt(ref - atr)) if p["stop"] == "1atr" else NO_STOP
    last = int(T.flat[s])
    comm = COMMISSION_RT / T.pv
    base = bracket(T, 1, j, stop_d, tgt_d, last, SLIP, comm)
    twice = bracket(T, 1, j, stop_d, tgt_d, last, 2 * SLIP, 2 * comm)
    gross = bracket(T, 1, j, stop_d, tgt_d, last, 0.0, 0.0)
    flip = bracket(T, -1, j, stop_d, tgt_d, last, SLIP, comm)
    rand = random_time(T, atr1, s, int(T.m[j]), NO_STOP if stop_d >= NO_STOP else stop_d / atr, tgt_d / atr, comm, rng)
    if len(rand) < K_RAND:
        return None
    return dict(day=T.days[s], j=j, r=base["pts"] / atr, r2x=twice["pts"] / atr, r_gross=gross["pts"] / atr,
                r_flip=flip["pts"] / atr, r_rand=rand, usd=base["pts"] * T.pv, reason=base["reason"],
                amb=base["amb"], exit=base["exit"], hold=int(base["exit"] - j + 1), atr_ticks=atr / TICK,
                tgt_atr=tgt_d / atr, minute=int(T.m[j]))


def run_cell(T: Tape, B: Bars, p: dict) -> list[dict]:
    rng = np.random.default_rng(SEED)
    atr1 = atr_by_minute(T, B)
    out, armed, busy, sess = [], True, -1, -1
    for k in range(len(B.C)):
        s = int(B.sess[k])
        if s != sess:
            sess, armed, busy = s, True, -1
        if B.last[k] < busy:                   # in a trade: this bar closes before the exit
            continue
        a = B.atr[k]
        cond = a > 0 and B.C[k] <= T.vwap[B.last[k]] - K_ATR * a
        if not cond:
            armed = True
            continue
        j = int(B.last[k]) + 1
        if not armed or not (SIG_FIRST <= B.close_min[k] <= SIG_LAST) or j > T.flat[s]:
            continue
        rec = trade(T, atr1, s, j, float(a), float(T.vwap[B.last[k]]), p, rng)
        if rec is None:
            continue
        out.append(rec)
        armed, busy = False, rec["exit"]
    return out


def run_cells(T: Tape, cells: list[dict] | None = None) -> dict[str, list[dict]]:
    cells = cells or GRID
    bars = {tf: tf_bars(T, tf) for tf in sorted({p["tf"] for p in cells})}
    return {cell_name(p): run_cell(T, bars[p["tf"]], p) for p in cells}


# ---------------------------------------------------------------- scoring

def block_idx(n: int, n_boot: int = N_BOOT) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    b = min(BLOCK, n)
    starts = rng.integers(0, n - b + 1, (n_boot, -(-n // b)))
    return (starts[:, :, None] + np.arange(b)).reshape(n_boot, -1)[:, :n]


def score(trades: list[dict], sessions: int) -> dict:
    n = len(trades)
    if not n:
        return dict(trades=0)
    r = np.array([t["r"] for t in trades])
    flip = np.array([t["r_flip"] for t in trades])
    rand = np.array([t["r_rand"] for t in trades])
    draws = r[block_idx(n)].mean(1)
    coin = np.random.default_rng(SEED + 1).random((N_RANDOM, n)) < 0.5
    coin_means = np.where(coin, r, flip).mean(1)
    pick = np.random.default_rng(SEED + 2).integers(0, K_RAND, (N_RANDOM, n))
    rand_means = rand[np.arange(n), pick].mean(1)
    pos = np.sort(r[r > 0])[::-1]
    years: dict[int, list[float]] = {}
    for t in trades:
        years.setdefault(t["day"].year, []).append(t["r"])
    return dict(
        trades=n, per_session=n / sessions, win=float((r > 0).mean()), mean=float(r.mean()),
        ci95=[float(np.quantile(draws, .025)), float(np.quantile(draws, .975))],
        lower_alpha=float(np.quantile(draws, ALPHA)),
        mean_2x=float(np.mean([t["r2x"] for t in trades])), gross=float(np.mean([t["r_gross"] for t in trades])),
        usd=float(np.mean([t["usd"] for t in trades])), usd_total=float(np.sum([t["usd"] for t in trades])),
        edge_flip=float(((r - flip) / 2).mean()),
        p_flip=float((1 + (coin_means >= r.mean()).sum()) / (1 + N_RANDOM)),
        rand_mean=float(rand.mean()), edge_rand=float((r - rand.mean(1)).mean()),
        p_rand=float((1 + (rand_means >= r.mean()).sum()) / (1 + N_RANDOM)),
        worst=float(r.min()), hold_median=float(np.median([t["hold"] for t in trades])),
        atr_ticks_median=float(np.median([t["atr_ticks"] for t in trades])),
        tgt_atr_median=float(np.median([t["tgt_atr"] for t in trades])),
        ambiguous=float(np.mean([t["amb"] for t in trades])),
        exits=pd.Series([t["reason"] for t in trades]).value_counts(normalize=True).round(3).to_dict(),
        top5_share=float(pos[:5].sum() / r.sum()) if r.sum() > 0 else None,
        by_year={y: dict(n=len(v), mean=float(np.mean(v))) for y, v in sorted(years.items())})


def eligible(c: dict) -> bool:
    return (c["trades"] >= MIN_TRADES and c["mean"] > 0 and c["mean_2x"] > 0 and c["edge_flip"] > 0
            and c["edge_rand"] > 0 and c["p_rand"] < SELECT_P)


def select(res: dict) -> dict | None:
    """The eligible cell (on both SPY and QQQ) with the highest pooled mean net R, or None."""
    best = None
    for p in GRID:
        name = cell_name(p)
        a, b = res["SPY"]["cells"][name], res["QQQ"]["cells"][name]
        if not (a["trades"] and b["trades"] and eligible(a) and eligible(b)):
            continue
        pooled = (a["mean"] * a["trades"] + b["mean"] * b["trades"]) / (a["trades"] + b["trades"])
        if best is None or pooled > best["pooled_mean"]:
            best = dict(cell=name, params=p, pooled_mean=pooled)
    return best


def verdict(c: dict) -> str:
    ok = c["trades"] and c["lower_alpha"] > 0 and c["p_rand"] < ALPHA and c["mean_2x"] > 0
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------- main

def script_sha() -> str:
    """Hash of the spec: this file and amt_lucid_study.py, whose constants and loader it uses."""
    h = hashlib.sha256()
    for f in SPEC_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def coverage_problems(sessions: dict) -> list[str]:
    per = {y: 0 for y in range(CONFIRM_START.year, CONFIRM_END.year + 1)}
    for d in sessions:
        per[d.year] = per.get(d.year, 0) + 1
    return [f"{y}: {n} sessions" for y, n in per.items() if n < MIN_SESSIONS_PER_YEAR]


def looks() -> list[str]:
    return [l for l in LOOKS.read_text().splitlines() if l.strip()] if LOOKS.exists() else []


def fmt(x, spec="+.3f") -> str:
    return "  n/a" if x is None else format(x, spec)


def report(sym: str, res: dict) -> None:
    print(f"\n{sym}  {res['sessions']} sessions {res['first']} -> {res['last']}   (R = ATR of the cell's tf)")
    print(f"  {'cell':<28} {'n':>5} {'/day':>5} {'win':>5} {'meanR':>7} {'95% CI':>17} {'2x':>7} {'gross':>7} "
          f"{'$/tr':>7} {'e_flip':>7} {'e_rand':>7} {'p_rand':>7} {'worst':>6} {'atr_t':>5} {'top5':>5}")
    for name, c in res["cells"].items():
        if not c["trades"]:
            print(f"  {name:<28} {0:>5}")
            continue
        print(f"  {name:<28} {c['trades']:>5} {c['per_session']:5.2f} {c['win']:5.2f} {c['mean']:+7.3f} "
              f"[{c['ci95'][0]:+.3f},{c['ci95'][1]:+.3f}] {c['mean_2x']:+7.3f} {c['gross']:+7.3f} {c['usd']:+7.1f} "
              f"{c['edge_flip']:+7.3f} {c['edge_rand']:+7.3f} {c['p_rand']:7.4f} {c['worst']:+6.2f} "
              f"{c['atr_ticks_median']:5.0f} {fmt(c['top5_share'], '5.2f')}")


def run(sessions: dict, sym: str, cells: list[dict] | None = None) -> dict:
    T = build_tape(sessions, INSTRUMENTS[sym]["pv"])
    return dict(sessions=len(sessions), first=str(min(sessions)), last=str(max(sessions)),
                cells={name: score(tr, len(sessions)) for name, tr in run_cells(T, cells).items()})


def explore(sha: str) -> dict:
    res = dict(script_sha=sha)
    for sym in ("SPY", "QQQ"):
        res[sym] = run(load_xnas(sym), sym)
        report(sym, res[sym])
    res["selected"] = c = select(res)
    print(f"\nselection (>= {MIN_TRADES} trades; mean R, 2x-cost R, edge_flip, edge_rand > 0 and p_rand < {SELECT_P} "
          f"on both; script {sha}):")
    print("  dropped: no cell qualified" if c is None else f"  {c['cell']}  pooled {c['pooled_mean']:+.3f}R")
    (OUT / "explore.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--explore", action="store_true", help="all cells on XNAS SPY + QQQ <= 2025-03-26 (repeatable)")
    mode.add_argument("--freeze", action="store_true", help="re-run the exploration, pick a cell, pin the script hash")
    mode.add_argument("--confirm", action="store_true", help="score the frozen cell once on ES and NQ 2012-2021")
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
    if not pin["selected"]:
        print("no cell qualified in exploration: nothing to confirm, ES / NQ left unread")
        return 0
    data = {sym: load_fut(sym) for sym in ("ES", "NQ")}
    gaps = [f"{sym} {g}" for sym, ss in data.items() for g in coverage_problems(ss)]
    if gaps:
        print(f"download incomplete ({', '.join(gaps)}; need >= {MIN_SESSIONS_PER_YEAR} a year); "
              "nothing scored, the look is not spent")
        return 1
    with LOOKS.open("a") as f:
        f.write(f"script={sha} sessions=ES:{len(data['ES'])},NQ:{len(data['NQ'])} "
                f"at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    print(f"look logged in {LOOKS.name}: commit it with the results")
    cell = pin["selected"]
    res = {}
    for sym, ss in data.items():
        res[sym] = run(ss, sym, [cell["params"]])
        report(f"{sym} (one look)", res[sym])
    res["verdicts"] = {sym: verdict(res[sym]["cells"][cell["cell"]]) for sym in data}
    print(f"\nVERDICTS {cell['cell']} (alpha {ALPHA:.4f}): {res['verdicts']}")
    (OUT / "results.json").write_text(json.dumps(dict(prereg=pin, result=res), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
