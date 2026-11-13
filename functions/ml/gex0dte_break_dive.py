"""Deep dive on gex0dte_study's lead: breaking a 0DTE GEX wall in positive gamma. Discovery data only
(QQQ + SPY <= 2025-03-26); the SPY holdout is never loaded.

Same events, fills and costs as gex0dte_study.py. Per touch it records context, so one build answers:
  - surface: break, walls, both regimes, stop 0.10-0.40% x target 1-3R, vs the shuffled-level twin (10 seeds)
  - baseline: the same break rules on the running high / low of day (no GEX), labelled with the same regime
  - regime variants: 0DTE net GEX sign (primary), all-expiry net GEX sign, spot vs all-expiry zero gamma
  - execution: +1 tick each side, and entry at the next bar's open
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gex0dte_study as gs  # noqa: E402
from amt_lucid_study import DISCOVERY_END, INSTRUMENTS, load_sessions  # noqa: E402

TICK = gs.TICK
OUT = HERE / "data" / "gex0dte" / "dive"
PCTS = (0.0010, 0.0015, 0.0020, 0.0025, 0.0030, 0.0040)
RRS = (1.0, 1.5, 2.0, 3.0)
SEEDS = 10
WALLS = ("call_wall", "put_wall")


def load_all_expiry(symbol: str) -> dict[str, dict]:
    g = pd.read_parquet(gs.GEX_DIR / f"{symbol.lower()}_gex_snapshots.parquet", columns=["computed_at", "spot", "zero_gamma", "net_gex"])
    et = g.computed_at.dt.tz_convert(gs.ET)
    g = g.assign(day=et.dt.strftime("%Y-%m-%d"), minute=et.dt.hour * 60 + et.dt.minute)[et.dt.date <= DISCOVERY_END]
    return {d: {c: x.sort_values("minute")[c].to_numpy() for c in ("minute", "spot", "zero_gamma", "net_gex")} for d, x in g.groupby("day")}


def running(H, L):
    """Running high / low of the bars BEFORE each bar (NaN for the first 30 bars, so the range has formed)."""
    hi = np.r_[np.nan, np.maximum.accumulate(H)[:-1]]
    lo = np.r_[np.nan, np.minimum.accumulate(L)[:-1]]
    hi[:30] = lo[:30] = np.nan
    return hi, lo


def day_job(args) -> list[dict]:
    symbol, day, bars, snap, alle, shuffles = args
    ratio, pv = INSTRUMENTS[symbol]["ratio"], INSTRUMENTS[symbol]["pv"]
    O, H, L, C = (bars[k] * ratio for k in ("open", "high", "low", "close"))
    m = bars["minute"]
    sm = snap["minute"]
    net = snap["net_gex"]
    levels = {k: snap[k] * ratio for k in WALLS}
    for s, other in enumerate(shuffles):
        if other is None:
            continue
        idx = np.minimum(np.searchsorted(other["minute"], sm), len(other["minute"]) - 1)
        ok = other["minute"][idx] == sm
        for k in WALLS:
            levels[f"shf{s}_{k}"] = np.where(ok, other[k][idx] / other["spot"][idx], np.nan) * snap["spot"] * ratio
    # all-expiry regime per bar
    if alle is not None:
        ka = np.searchsorted(alle["minute"], m - 1, side="right") - 1
        oka = (ka >= 0) & (m - alle["minute"][np.maximum(ka, 0)] <= gs.STALE_MIN)
        all_sign = np.where(oka, np.sign(alle["net_gex"][np.maximum(ka, 0)]), 0)
        zg = alle["zero_gamma"][np.maximum(ka, 0)]
        above_zg = np.where(oka & np.isfinite(zg), np.sign(alle["spot"][np.maximum(ka, 0)] - zg), 0)
    else:
        all_sign = above_zg = np.zeros(len(m))
    hod, lod = running(H, L)
    comm_pts = gs.COMM_RT_USD / pv
    rows = []
    for pct in PCTS:
        S = max(4 * TICK, round(pct * O[0] / TICK) * TICK)
        series = {}
        for name, vals in levels.items():
            series[name] = gs.level_series(m, sm, vals)
        # running high / low of day as levels; the regime comes from the 0DTE snapshot usable at that bar
        _, K0 = gs.level_series(m, sm, net)
        series["hod"] = (np.where(K0 >= 0, hod, np.nan), K0)
        series["lod"] = (np.where(K0 >= 0, lod, np.nan), K0)
        for name, (X, K) in series.items():
            ev = gs.events(X, O, H, L, C, m, S)
            if name == "hod":
                ev = [e for e in ev if e[1] == -1]  # only breaks up through the high
            elif name == "lod":
                ev = [e for e in ev if e[1] == 1]
            for rr in RRS:
                for variant in ("base", "slip", "delay") if (name in WALLS and pct == 0.0015 and rr == 2.0) else ("base",):
                    busy = {1.0: -1, -1.0: -1}
                    for i, a in ev:
                        reg = np.sign(net[K[i]])
                        if reg == 0 or i <= busy[reg]:
                            continue
                        x = X[i]
                        d, trig = -a, x - a * TICK
                        j = i
                        if variant == "delay":  # enter at the next bar's open, 1 tick worse
                            j = i + 1
                            if j >= len(m) or m[j] >= gs.FLAT:
                                continue
                            e = O[j] + d * TICK
                        else:
                            e = O[i] + d * TICK if d * (O[i] - trig) >= 0 else trig + d * TICK
                        if variant == "slip":
                            e += d * TICK
                        r = gs.bracket(O, H, L, C, m, j, d, e, S, rr, pv)
                        busy[reg] = r["j"]
                        slip = r["slip"] + (TICK if variant == "slip" else 0.0)
                        netp = r["gross"] - slip - comm_pts
                        rows.append(dict(product=symbol, date=day, kind=name, variant=variant,
                                         regime="pos" if reg > 0 else "neg", all_regime=int(all_sign[i]), above_zg=int(above_zg[i]),
                                         f=pct, rr=rr, S=S, side=a, dir=d, minute=int(m[i]), entry_ns=int(m[i]), why=r["why"],
                                         bars_held=int(r["j"] - j), gross_r=r["gross"] / S, net_r=netp / S, net_pts=netp,
                                         mae=r["mae"], mfe=r["mfe"], net_gex=float(net[K[i]]),
                                         dist_open=float((x - O[0]) / O[0]), new_hod=bool(np.isfinite(hod[i]) and d > 0 and x >= hod[i] - TICK
                                                                                     or np.isfinite(lod[i]) and d < 0 and x <= lod[i] + TICK),
                                         close_r=float(d * (C[-1] - e) / S)))
    return rows


def build(symbol: str, workers=8) -> pd.DataFrame:
    sessions = load_sessions(symbol, DISCOVERY_END)
    snaps = gs.load_snaps(symbol)
    alle = load_all_expiry(symbol)
    days = [d for d in sorted(sessions) if d.isoformat() in snaps]
    keys = [d.isoformat() for d in days]
    arr = {k: {c: snaps[k][c].to_numpy() for c in ("minute", "spot", *gs.KINDS, "net_gex")} for k in keys}
    rng = np.random.default_rng(11)  # same permutations as gex0dte_study
    perms = [rng.permutation(len(keys)) for _ in range(SEEDS)]
    jobs = []
    for n, (d, k) in enumerate(zip(days, keys)):
        g = sessions[d]
        bars = {c: g[c].to_numpy(float) for c in ("open", "high", "low", "close")} | {"minute": g.minute.to_numpy()}
        jobs.append((symbol, k, bars, arr[k], alle.get(k), [arr[keys[p[n]]] if keys[p[n]] != k else None for p in perms]))
    with ProcessPoolExecutor(workers) as ex:
        rows = [r for rr in ex.map(day_job, jobs, chunksize=8) for r in rr]
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / f"trades_{symbol}.parquet")
    (OUT / f"sessions_{symbol}.json").write_text(json.dumps(keys))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for s in ("QQQ", "SPY"):
        df = build(s)
        print(s, len(df), "trades", flush=True)
