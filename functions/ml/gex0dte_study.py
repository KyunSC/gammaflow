"""0DTE GEX levels by gamma regime: do call wall / put wall / zero gamma touches carry an edge worth a Lucid account?

Data (discovery only): Databento XNAS 1m bars, QQQ -> MNQ (x41.2, $2/pt), SPY -> MES (x10.05, $5/pt), sessions
  <= 2025-03-26 that have a 0DTE expiry (thetadata_gex.py --expiries 0dte). QQQ after that date is the spent
  ORB holdout and SPY after it the reserved AMT holdout: neither is loaded here.

Levels: the latest 0DTE snapshot (call_wall, put_wall, zero_gamma; 5-minute, quotes and spot as of computed_at,
  OI = prior close) usable from the bar starting one minute after computed_at, dropped when > 20 minutes old.
  Regime of a touch = sign of that snapshot's 0DTE net GEX (pos = dealers long gamma).
  Control ("shf"): the same kind of level from a random other session (10 seeds), as a fraction of that
  session's snapshot spot at the same clock time, applied to this session's spot. Regime stays this session's.

Events on 1m bars (futures plane): armed on one side once a bar lies wholly >= A = S beyond the level; a touch
  is a bar trading one tick through it with the previous close still on the armed side (a wall jumping across
  price is not a touch). Touch bars 09:36-15:30 ET.
Trades (one position at a time per cell, several a day allowed):
  fade  - limit at the level, direction back toward the armed side.
  break - stop one tick through, filled one tick worse (or at the open - 1 tick on a gap through).
  S = pct x the session's open (pct 0.15% / 0.30%), target rr x S (1 / 2) needing a tick through. The touch
  bar stops the trade if its adverse extreme reaches the stop and never fills the target. Later bars: open
  through a level fills at the open; both touched -> stop; stop fills 1 tick worse; flat 15:54 close - 1 tick.
  Commission $0.50/side per micro.

Hypotheses fixed before any number: H+ fade the walls in positive gamma (walls hold); H- break the walls in
  negative gamma (moves accelerate). Zero gamma and the opposite pairings are exploratory.
Discovery gate per cell: on BOTH QQQ and SPY n >= 40, mean net R > 0, gross R above the shuffled-level twin,
  and first-touch-of-day LucidFlex 50K EV ($1,050 risk) above the twin's mean. A passing cell would go to the
  SPY holdout (2025-03-27 -> 2026-08-07) only with the user's approval.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from amt_lucid_study import DISCOVERY_END, INSTRUMENTS, load_sessions  # noqa: E402
import profile_nodes_study as pn  # noqa: E402

ET = "America/New_York"
TICK = 0.25
OUT = HERE / "data" / "gex0dte"
GEX_DIR = HERE / "data" / "thetadata_gex"
KINDS = ("call_wall", "put_wall", "zero_gamma")
WALLS = ("call_wall", "put_wall")
PCTS = (0.0015, 0.0030)
RRS = (1.0, 2.0)
SEEDS = 10
ENTRY0, ENTRY1, FLAT = 576, 930, 954  # 09:36, 15:30, 15:54
STALE_MIN = 20
COMM_RT_USD = 1.0


def load_snaps(symbol: str) -> dict[str, pd.DataFrame]:
    g = pd.read_parquet(GEX_DIR / f"{symbol.lower()}_gex_snapshots_0dte.parquet",
                        columns=["computed_at", "spot", *KINDS, "net_gex"])
    et = g.computed_at.dt.tz_convert(ET)
    g = g.assign(day=et.dt.strftime("%Y-%m-%d"), minute=et.dt.hour * 60 + et.dt.minute)
    g = g[et.dt.date <= DISCOVERY_END]
    return {d: x.sort_values("minute").reset_index(drop=True) for d, x in g.groupby("day")}


def level_series(m: np.ndarray, snap_min: np.ndarray, vals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bar: the usable snapshot's value (NaN if none or stale) and that snapshot's index (-1 if none)."""
    k = np.searchsorted(snap_min, m - 1, side="right") - 1
    ok = (k >= 0) & (m - snap_min[np.maximum(k, 0)] <= STALE_MIN)
    x = np.where(ok, vals[np.maximum(k, 0)], np.nan)
    return x, np.where(ok, k, -1)


def events(X, O, H, L, C, m, A) -> list[tuple[int, int]]:
    """(touch bar, approach side): +1 came down from above, -1 came up from below."""
    out, armed = [], 0
    for i in range(len(m)):
        x = X[i]
        if not np.isfinite(x) or x <= 0:
            armed = 0
            continue
        if i and armed == 1 and C[i - 1] <= x or i and armed == -1 and C[i - 1] >= x:
            armed = 0
        if i and armed == 1 and L[i] <= x - TICK:
            if ENTRY0 <= m[i] < ENTRY1:
                out.append((i, 1))
            armed = 0
        elif i and armed == -1 and H[i] >= x + TICK:
            if ENTRY0 <= m[i] < ENTRY1:
                out.append((i, -1))
            armed = 0
        if L[i] >= x + A:
            armed = 1
        elif H[i] <= x - A:
            armed = -1
    return out


def bracket(O, H, L, C, m, i, d, e, S, rr, pv) -> dict:
    stop, tgt = e - d * S, e + d * rr * S
    adv0 = L[i] if d > 0 else H[i]
    worst, best = d * (adv0 - e), max(0.0, d * ((H[i] if d > 0 else L[i]) - e))
    if d * (adv0 - stop) <= 0:
        return dict(why="stop", gross=-S, slip=TICK, j=i, mae=-S - TICK, mfe=0.0)
    for j in range(i + 1, len(m)):
        adv, fav = (L[j], H[j]) if d > 0 else (H[j], L[j])
        if d * (O[j] - stop) <= 0:
            g = d * (O[j] - e)
            return dict(why="stop", gross=g, slip=TICK, j=j, mae=min(worst, g - TICK), mfe=best)
        if d * (adv - stop) <= 0:
            return dict(why="stop", gross=-S, slip=TICK, j=j, mae=min(worst, -S - TICK), mfe=best)
        if d * (O[j] - tgt) >= 0:
            return dict(why="target", gross=d * (O[j] - e), slip=0.0, j=j, mae=worst, mfe=max(best, d * (O[j] - e)))
        if d * (fav - tgt) >= TICK:
            return dict(why="target", gross=rr * S, slip=0.0, j=j, mae=min(worst, d * (adv - e)), mfe=max(best, rr * S))
        worst, best = min(worst, d * (adv - e)), max(best, d * (fav - e))
        if m[j] >= FLAT:
            return dict(why="eod", gross=d * (C[j] - e), slip=TICK, j=j, mae=worst, mfe=best)
    return dict(why="eod", gross=d * (C[-1] - e), slip=TICK, j=len(m) - 1, mae=worst, mfe=best)


def day_job(args) -> list[dict]:
    symbol, day, bars, snap, shuffles = args
    ratio, pv = INSTRUMENTS[symbol]["ratio"], INSTRUMENTS[symbol]["pv"]
    O, H, L, C = (bars[k] * ratio for k in ("open", "high", "low", "close"))
    m = bars["minute"]
    sm = snap["minute"]
    net_sign = np.sign(snap["net_gex"])
    levels = {k: snap[k] * ratio for k in KINDS}
    for s, other in enumerate(shuffles):  # other session's level / spot at the same clock time
        if other is None:
            continue
        idx = np.searchsorted(other["minute"], sm)
        ok = (idx < len(other["minute"])) & (other["minute"][np.minimum(idx, len(other["minute"]) - 1)] == sm)
        for k in KINDS:
            rel = np.where(ok, other[k][np.minimum(idx, len(other[k]) - 1)] / other["spot"][np.minimum(idx, len(other[k]) - 1)], np.nan)
            levels[f"shf{s}_{k}"] = rel * snap["spot"] * ratio
    comm_pts = COMM_RT_USD / pv
    rows = []
    for pct in PCTS:
        S = max(4 * TICK, round(pct * O[0] / TICK) * TICK)
        for name, vals in levels.items():
            X, K = level_series(m, sm, vals)
            ev = events(X, O, H, L, C, m, S)
            if not ev:
                continue
            for setup in ("fade", "break"):
                for rr in RRS:
                    busy = {1.0: -1, -1.0: -1}
                    for i, a in ev:
                        reg = net_sign[K[i]]
                        if reg == 0 or i <= busy[reg]:
                            continue
                        x = X[i]
                        if setup == "fade":
                            d, e = a, x
                        else:
                            d, trig = -a, x - a * TICK
                            e = O[i] + d * TICK if d * (O[i] - trig) >= 0 else trig + d * TICK
                        r = bracket(O, H, L, C, m, i, d, e, S, rr, pv)
                        busy[reg] = r["j"]
                        net = r["gross"] - r["slip"] - comm_pts
                        rows.append(dict(product=symbol, date=day, kind=name, setup=setup, regime="pos" if reg > 0 else "neg",
                                         f=pct, rr=rr, S=S, side=a, entry_ns=int(m[i]), why=r["why"],
                                         gross_r=r["gross"] / S, net_r=net / S, net_pts=net, mae=r["mae"], mfe=r["mfe"]))
    return rows


def build(symbol: str, workers=8) -> pd.DataFrame:
    sessions = load_sessions(symbol, DISCOVERY_END)
    snaps = load_snaps(symbol)
    days = [d for d in sorted(sessions) if d.isoformat() in snaps]
    keys = [d.isoformat() for d in days]
    arr = {k: {c: v[c].to_numpy(float) if c != "minute" else v[c].to_numpy() for c in ("minute", "spot", *KINDS, "net_gex")}
           for k, v in snaps.items() if k in set(keys)}
    rng = np.random.default_rng(11)
    perms = [rng.permutation(len(keys)) for _ in range(SEEDS)]
    jobs = []
    for n, (d, k) in enumerate(zip(days, keys)):
        g = sessions[d]
        bars = {c: g[c].to_numpy(float) for c in ("open", "high", "low", "close")} | {"minute": g.minute.to_numpy()}
        shuf = [arr[keys[p[n]]] if keys[p[n]] != k else None for p in perms]
        jobs.append((symbol, k, bars, arr[k], shuf))
    with ProcessPoolExecutor(workers) as ex:
        rows = [r for rr in ex.map(day_job, jobs, chunksize=8) for r in rr]
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / f"trades_{symbol}.parquet")
    (OUT / f"sessions_{symbol}.json").write_text(json.dumps(keys))
    return df


def twin_of(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    return df[df.kind.str.startswith("shf") & df.kind.str.endswith(kind)]


def analyse(df: pd.DataFrame, symbol: str, sessions: list[str], first_only=False) -> pd.DataFrame:
    if first_only:
        df = df.sort_values("entry_ns").groupby(["kind", "setup", "regime", "f", "rr", "date"]).head(1)
    rows = []
    for kind in KINDS:
        tw_all = twin_of(df, kind)
        for (setup, reg, f, rr), c in df[df.kind == kind].groupby(["setup", "regime", "f", "rr"]):
            tw = tw_all[(tw_all.setup == setup) & (tw_all.regime == reg) & (tw_all.f == f) & (tw_all.rr == rr)]
            lo, hi = pn.excess_ci(c, tw, sessions, n=1000)
            rows.append(dict(product=symbol, kind=kind, setup=setup, regime=reg, f=f, rr=rr, n=len(c),
                             win=float((c.why == "target").mean()), gross_r=c.gross_r.mean(), net_r=c.net_r.mean(),
                             twin_gross=tw.gross_r.mean(), excess=c.gross_r.mean() - tw.gross_r.mean(),
                             excess_lo=lo, excess_hi=hi, cost_r=float((c.gross_r - c.net_r).mean())))
    return pd.DataFrame(rows)


def lucid(df: pd.DataFrame, symbol: str, sessions: list[str], cells) -> list[dict]:
    pv = INSTRUMENTS[symbol]["pv"]
    out = []
    for kind, setup, reg, f, rr in cells:
        sel = (df.setup == setup) & (df.regime == reg) & (df.f == f) & (df.rr == rr)
        node = pn.lucid_ev(pn.lucid_days(df[sel & (df.kind == kind)], sessions, pv), paths=20000)
        tw = np.array([pn.lucid_ev(pn.lucid_days(df[sel & (df.kind == f"shf{s}_{kind}")], sessions, pv), paths=4000, seed=s + 3)["ev"]
                       for s in range(SEEDS)])
        out.append(dict(product=symbol, kind=kind, setup=setup, regime=reg, f=f, rr=rr, **node,
                        twin_ev=float(tw.mean()), twin_min=float(tw.min()), twin_max=float(tw.max())))
        print(f"{symbol} {kind:<10} {setup:<5} {reg} {f:.4f} rr{rr:g}  EV {node['ev']:+7.1f} pass {node['pass_rate']:.1%} "
              f"trade-days {node['trade_days']:.0%} | shuffled twin {tw.mean():+7.1f} ({tw.min():+.0f}..{tw.max():+.0f})", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "analyse", "lucid"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    syms = ("QQQ", "SPY")
    if a.cmd == "build":
        for s in syms:
            df = build(s)
            print(s, len(df), "trades", df.date.nunique(), "sessions with trades", flush=True)
    pd.set_option("display.width", 250, "display.max_rows", 300)
    if a.cmd in ("build", "analyse"):
        for first in (False, True):
            res = pd.concat([analyse(pd.read_parquet(OUT / f"trades_{s}.parquet"), s,
                                     json.loads((OUT / f"sessions_{s}.json").read_text()), first) for s in syms])
            res.to_csv(OUT / f"cells{'_first' if first else ''}.csv", index=False)
            print("== first touch of day" if first else "== all touches")
            print(res.round(3).to_string(index=False))
    if a.cmd == "lucid":
        res = pd.read_csv(OUT / "cells.csv")
        rows = []
        for s in syms:
            df = pd.read_parquet(OUT / f"trades_{s}.parquet")
            cells = [tuple(r) for r in res[res["product"] == s][["kind", "setup", "regime", "f", "rr"]].itertuples(index=False)]
            rows += lucid(df, s, json.loads((OUT / f"sessions_{s}.json").read_text()), cells)
        (OUT / "lucid.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
