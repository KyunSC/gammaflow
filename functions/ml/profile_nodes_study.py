"""Profile-node study: do touches of the prior session's POC / HVN / LVN carry an edge worth a Lucid account?

Data: local Databento trades, RTH (09:25-16:00 ET) only, research side of the verify seal.
  NQ 2025-10-24 -> 2026-08-14, ES 2026-04-24 -> 2026-08-14. Both windows were spent on the absorption /
  GEX studies (orderflow_backtest.py), whose "touch" control already saw plain prior-LVN touches, so this
  is an exploratory screen, not a clean out-of-sample test.

Levels: the prior RTH session's (09:30-16:00, same contract) POC, HVNs (<= 3) and LVNs, found with a port of
  frontend/lib/orderFlow.js profileNodesFromTicks (80 rows, Gaussian sigma 1.5, 10% prominence).
  Control: 5 uniform-random prices in the prior session's [low, high] a day, 20 seeds ("rnd"), same rules.

Events: a level is armed once a whole second trades at least A = S beyond it on one side; the first print
  one tick through it from that side is a touch (then it disarms). Touches 09:35-15:30 ET.
Trades (each cell holds one position at a time, several a day allowed):
  fade  - limit at the level, filled by the trade-through print; direction = back toward the armed side.
  break - stop order one tick through, filled one tick worse; direction = the way price crossed.
  Stop S = f x prior RTH range (f = 0.04 / 0.08, >= 4 ticks), target rr x S (rr = 1 / 2) needing a print
  one tick through; stop fills at the stop minus a draw from the measured stop-slip PMF (fill_study);
  flat at 15:55 with one tick slip. Commission $0.50/side per micro (MNQ $2/pt, MES $5/pt).

Pre-declared "potential" rule (per cell, 24 node cells per product):
  1. NQ: net mean R > 0 and gross R above the pooled random-level twin (session-bootstrap 95% CI > 0).
  2. ES: net mean R > 0 and gross excess over random > 0.
  3. NQ excess over random > 0 in both halves of the window.
  4. Lucid Flex 50K (risk $1,050/trade, first touch of the day) EV above the random twin's EV on NQ.
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
import orderflow_backtest as ob  # noqa: E402
from holdout import research_sessions  # noqa: E402

TICK = 0.25
PRODUCTS = {
    "NQ": dict(dir=HERE / "data/databento/nq-trades/NQ", pt_usd=2.0),
    "ES": dict(dir=HERE / "data/databento/es-trades/ES", pt_usd=5.0),
}
COMM_RT_USD = 1.0
FRACS = (0.04, 0.08)
RRS = (1.0, 2.0)
KINDS = ("poc", "hvn", "lvn")
N_RND, RND_SEEDS = 5, 20
OUT = HERE / "data" / "profile_nodes"
SEC_ENTRY0, SEC_ENTRY1 = 600, 300 + 360 * 60  # 09:35, 15:30 on the 09:25 second grid
RISK_USD, MAX_MICROS = 1050.0, 40


def _slip_pmf():
    res = json.loads((HERE / "data/fill_study/results.json").read_text())
    w = {k: v["n"] for k, v in res["stop_by_clock"].items()}
    acc: dict[int, float] = {}
    for bucket, pmf in res["stop_slip_pmf"].items():
        for t, p in pmf.items():
            acc[int(t)] = acc.get(int(t), 0.0) + w[bucket] * p
    t = np.array(sorted(acc))
    p = np.array([acc[k] for k in t])
    return t, p / p.sum()


SLIP_T, SLIP_P = _slip_pmf()


def gaussian_smooth(v: np.ndarray, sigma=1.5) -> np.ndarray:
    half = max(1, math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    return np.convolve(np.pad(v, half, mode="edge"), k / k.sum(), "valid")


def profile_nodes(px: np.ndarray, sz: np.ndarray, rows=80, max_hvn=3) -> dict:
    """Port of profileNodesFromTicks (POC, HVN peaks, LVN valleys between kept peaks)."""
    t = np.round(px / TICK).astype(np.int64)
    lo, hi = int(t.min()), int(t.max())
    rt = max(1, math.ceil((hi - lo + 1) / rows))
    base = lo // rt
    n = hi // rt - base + 1
    hist = np.bincount(t // rt - base, weights=sz, minlength=n)
    mid = lambda i: ((base + i) * rt + (rt - 1) / 2) * TICK  # noqa: E731
    poc = int(np.argmax(hist))
    s = gaussian_smooth(hist)
    top = s.max()

    def on_poc_hump(i):
        a, b = min(i, poc), max(i, poc)
        return s[a:b + 1].min() >= 0.9 * min(s[i], s[poc])

    peaks = []
    for i in range(1, n - 1):
        if s[i - 1] >= s[i] or s[i + 1] > s[i]:
            continue
        lm = rm = s[i]
        j = i - 1
        while j >= 0 and s[j] <= s[i]:
            lm = min(lm, s[j]); j -= 1
        j = i + 1
        while j < n and s[j] <= s[i]:
            rm = min(rm, s[j]); j += 1
        prom = s[i] - max(lm, rm)
        if prom >= 0.1 * top:
            peaks.append((i, prom, on_poc_hump(i)))
    peaks.sort(key=lambda p: -p[1])
    kept, nh, pp = [], 0, False
    for i, prom, is_poc in peaks:
        if (pp if is_poc else nh >= max_hvn):
            continue
        if is_poc:
            pp = True
        else:
            nh += 1
        kept.append((i, is_poc))
    kept.sort()
    lvn = []
    for (a, _), (b, _) in zip(kept, kept[1:]):
        v = a + 1 + int(np.argmin(s[a + 1:b])) if b > a + 1 else a + 1
        lvn.append(mid(v))
    return dict(poc=mid(poc), hvn=[mid(i) for i, ip in kept if not ip], lvn=lvn)


def files(product: str) -> list[Path]:
    fs = sorted(PRODUCTS[product]["dir"].glob("*.parquet"))
    keep = set(research_sessions([pd.Timestamp(f.name[:10]).date() for f in fs]))
    return [f for f in fs if pd.Timestamp(f.name[:10]).date() in keep]


def summary_job(path: Path) -> dict | None:
    day = ob.load_day(path)
    if day is None or day.rth0 >= len(day.px):
        return None
    px, sz = day.px[day.rth0:], day.sz[day.rth0:]
    return dict(date=day.date, instrument=day.instrument, high=float(px.max()), low=float(px.min()),
                **profile_nodes(px, sz))


def events(day, x: float, A: float) -> list[tuple[int, int]]:
    """(print index, approach side a) touches of level x; a = +1 from above, -1 from below."""
    full = day.s_hi > -np.inf
    arrs = [full & (day.s_lo <= x - TICK), full & (day.s_hi >= x + TICK),  # touch down / up
            full & (day.s_lo >= x + A), full & (day.s_hi <= x - A)]  # arm above / below
    marks = []
    for typ, arr in enumerate(arrs):
        for sec in np.flatnonzero(arr & ~np.r_[False, arr[:-1]]):
            marks.append((int(sec), typ))
    marks.sort()  # touches (0, 1) before arms (2, 3) within a second
    state, out = 0, []
    for sec, typ in marks:
        if typ == 2:
            state = 1
        elif typ == 3:
            state = -1
        elif (typ == 0 and state == 1) or (typ == 1 and state == -1):
            a = state
            state = 0
            if not SEC_ENTRY0 <= sec < SEC_ENTRY1:
                continue
            i0, i1 = day.s_bounds[sec], day.s_bounds[sec + 1]
            seg = day.px[i0:i1]
            hit = np.flatnonzero(seg <= x - TICK) if a == 1 else np.flatnonzero(seg >= x + TICK)
            out.append((int(i0 + hit[0]), a))
    return out


def simulate(day, e: int, d: int, entry: float, S: float, rr: float, flat_end: int, rng) -> dict:
    stop, tgt = entry - d * S, entry + d * rr * S
    j0, step = e + 1, 2000
    exit_i, why = flat_end - 1, "eod"
    while j0 < flat_end:
        j1 = min(flat_end, j0 + step)
        seg = day.px[j0:j1]
        hs = np.flatnonzero(d * (seg - stop) <= 0)
        ht = np.flatnonzero(d * (seg - tgt) >= TICK)
        fs = hs[0] if len(hs) else None
        ft = ht[0] if len(ht) else None
        if fs is not None or ft is not None:
            if ft is None or (fs is not None and fs <= ft):
                exit_i, why = j0 + int(fs), "stop"
            else:
                exit_i, why = j0 + int(ft), "target"
            break
        j0, step = j1, step * 4
    path = d * (day.px[e:exit_i + 1] - entry)
    if why == "stop":
        gross = -S
        slip = float(rng.choice(SLIP_T, p=SLIP_P)) * TICK
    elif why == "target":
        gross, slip = rr * S, 0.0
    else:
        gross, slip = d * (day.px[exit_i] - entry), TICK
    return dict(exit_i=exit_i, why=why, gross=gross, slip=slip, mae=float(path.min()), mfe=float(path.max()))


def day_job(args) -> list[dict]:
    path, prev, product = args
    day = ob.load_day(path)
    if day is None or prev is None or prev["instrument"] != day.instrument:
        return []
    rng_lv = np.random.default_rng(int(day.date.replace("-", "")))
    rng = np.random.default_rng(int(day.date.replace("-", "")) + 7)
    rngs = prev["high"] - prev["low"]
    levels = {"poc": [prev["poc"]], "hvn": prev["hvn"], "lvn": prev["lvn"]}
    for s in range(RND_SEEDS):
        levels[f"rnd{s}"] = list(np.round(rng_lv.uniform(prev["low"], prev["high"], N_RND) / TICK) * TICK)
    flat_end = int(day.bounds[385])
    comm_pts = COMM_RT_USD / PRODUCTS[product]["pt_usd"]
    rows = []
    for f in FRACS:
        S = max(4 * TICK, round(f * rngs / TICK) * TICK)
        for kind, xs in levels.items():
            ev = sorted(set((i, a, x) for x in xs for i, a in events(day, x, S)))
            for setup in ("fade", "break"):
                for rr in RRS:
                    busy = -1
                    for i, a, x in ev:
                        if i <= busy or i >= flat_end - 1:
                            continue
                        d, entry = (a, x) if setup == "fade" else (-a, x - a * 2 * TICK)
                        r = simulate(day, i, d, entry, S, rr, flat_end, rng)
                        busy = r["exit_i"]
                        net = r["gross"] - r["slip"] - comm_pts
                        rows.append(dict(product=product, date=day.date, kind=kind, setup=setup, f=f, rr=rr,
                                         S=S, level=x, side=a, entry_ns=int(day.ts[i]), why=r["why"],
                                         gross_r=r["gross"] / S, net_r=net / S, net_pts=net,
                                         mae=r["mae"], mfe=r["mfe"]))
    return rows


def build(product: str, workers=8) -> pd.DataFrame:
    fs = files(product)
    with ProcessPoolExecutor(workers) as ex:
        summ = list(ex.map(summary_job, fs))
        (OUT / f"nodes_{product}.json").write_text(json.dumps(summ, indent=0))
        jobs = [(f, summ[k - 1] if k else None, product) for k, f in enumerate(fs)]
        trades = [r for rows in ex.map(day_job, jobs) for r in rows]
    df = pd.DataFrame(trades)
    df.to_parquet(OUT / f"trades_{product}.parquet")
    return df


def boot_ci(vals_by_day: pd.Series, sessions: list[str], stat=np.mean, n=2000, seed=0):
    """Session bootstrap of a per-trade mean (keeps intraday clustering)."""
    rng = np.random.default_rng(seed)
    groups = [vals_by_day.get(s, np.array([])) for s in sessions]
    out = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        v = np.concatenate([groups[k] for k in pick])
        out.append(v.mean() if len(v) else np.nan)
    return np.nanpercentile(out, [2.5, 97.5])


def excess_ci(node: pd.DataFrame, rnd: pd.DataFrame, sessions, n=2000, seed=0):
    """Session bootstrap of mean gross R (node) - mean gross R (pooled random twin), paired by session."""
    rng = np.random.default_rng(seed)
    gn = node.groupby("date")["gross_r"].agg(["sum", "count"]).reindex(sessions, fill_value=0).to_numpy()
    gr = rnd.groupby("date")["gross_r"].agg(["sum", "count"]).reindex(sessions, fill_value=0).to_numpy()
    out = []
    for _ in range(n):
        k = rng.integers(0, len(sessions), len(sessions))
        a, b = gn[k].sum(0), gr[k].sum(0)
        out.append(a[0] / max(a[1], 1) - b[0] / max(b[1], 1))
    return np.percentile(out, [2.5, 97.5])


def analyse(df: pd.DataFrame, product: str) -> pd.DataFrame:
    sessions = sorted(df["date"].unique())
    half = sessions[len(sessions) // 2]
    rows = []
    rnd = df[df["kind"].str.startswith("rnd")]
    for (setup, f, rr), g in df[df["kind"].isin(KINDS)].groupby(["setup", "f", "rr"]):
        tw = rnd[(rnd.setup == setup) & (rnd.f == f) & (rnd.rr == rr)]
        seed_means = tw.groupby("kind")["gross_r"].mean()
        for kind, c in g.groupby("kind"):
            lo, hi = excess_ci(c, tw, sessions)
            ex_h = [c[m]["gross_r"].mean() - tw[mt]["gross_r"].mean()
                    for m, mt in ((c.date < half, tw.date < half), (c.date >= half, tw.date >= half))]
            rows.append(dict(product=product, kind=kind, setup=setup, f=f, rr=rr, n=len(c),
                             per_day=len(c) / len(sessions), win=float((c.why == "target").mean()),
                             gross_r=c.gross_r.mean(), net_r=c.net_r.mean(), rnd_gross=tw.gross_r.mean(),
                             rnd_net=tw.net_r.mean(), excess=c.gross_r.mean() - tw.gross_r.mean(),
                             excess_lo=lo, excess_hi=hi, ex_h1=ex_h[0], ex_h2=ex_h[1],
                             seed_rank=float((seed_means >= c.gross_r.mean()).mean()),
                             cost_r=float((c.gross_r - c.net_r).mean()), median_S=float(c.S.median())))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Lucid replay
def lucid_days(trades: pd.DataFrame, sessions, pt_usd: float, k=1, mode="fixed") -> dict:
    """One replay bar per session (no-trade sessions are flat days); size to RISK_USD per trade."""
    pnl, lo, hi, nt = [], [], [], []
    by = {d: g.sort_values("entry_ns") for d, g in trades.groupby("date")}
    for s in sessions:
        g = by.get(s)
        cum, dlo, dhi, cnt = 0.0, 0.0, 0.0, 0
        if g is not None:
            for _, t in g.head(k).iterrows():
                n = int(min(MAX_MICROS, max(1, math.floor(RISK_USD / (t.S * pt_usd)))))
                comm = COMM_RT_USD * n
                dlo = min(dlo, cum + t.mae * pt_usd * n - comm / 2)
                dhi = max(dhi, cum + t.mfe * pt_usd * n)
                cum += t.net_pts * pt_usd * n
                dlo, dhi, cnt = min(dlo, cum), max(dhi, cum), cnt + 1
                if mode == "until_win" and t.why == "target":
                    break
        pnl.append(cum); lo.append(dlo); hi.append(dhi); nt.append(cnt)
    return dict(pnl=np.array(pnl), lo=np.array(lo), hi=np.array(hi), trades=np.array(nt))


def lucid_ev(d: dict, paths=20000, seed=1) -> dict:
    from lucid_structure import FLEX50_FEE, replay
    from flybrain.prop import resolve_plan
    takes, used, paid, passed, _ = replay(d, resolve_plan("flex", "50k", True), paths, seed=seed)
    ev = takes.mean() - FLEX50_FEE
    se = takes.std(ddof=1) / math.sqrt(len(takes))
    return dict(ev=float(ev), ev_lo=float(ev - 1.96 * se), ev_hi=float(ev + 1.96 * se), pass_rate=float(passed.mean()),
                paid=float(paid.mean()), days=float(used.mean()), ev_day=float(ev / used.mean()),
                trade_days=float((d["trades"] > 0).mean()), day_mean=float(d["pnl"].mean()))


def lucid_table(df: pd.DataFrame, product: str, cells: list[tuple], k=1, mode="fixed", outer=0) -> list[dict]:
    """EV of each (kind, setup, f, rr) cell vs its random-level twin (seeds pooled into one day pool per seed)."""
    pt = PRODUCTS[product]["pt_usd"]
    sessions = sorted(df["date"].unique())
    out = []
    for kind, setup, f, rr in cells:
        sel = (df.setup == setup) & (df.f == f) & (df.rr == rr)
        node = lucid_ev(lucid_days(df[sel & (df.kind == kind)], sessions, pt, k, mode))
        twins = [lucid_ev(lucid_days(df[sel & (df.kind == f"rnd{s}")], sessions, pt, k, mode), paths=4000, seed=s + 3)
                 for s in range(0, RND_SEEDS, 2)]
        tw_ev = np.array([t["ev"] for t in twins])
        row = dict(product=product, kind=kind, setup=setup, f=f, rr=rr, k=k, mode=mode, **node,
                   twin_ev=float(tw_ev.mean()), twin_ev_min=float(tw_ev.min()), twin_ev_max=float(tw_ev.max()),
                   twin_rank=float((tw_ev >= node["ev"]).mean()))
        if outer:  # day-pool bootstrap: uncertainty from having only these sessions
            rng = np.random.default_rng(5)
            d = lucid_days(df[sel & (df.kind == kind)], sessions, pt, k, mode)
            evs = []
            for b in range(outer):
                ix = rng.integers(0, len(sessions), len(sessions))
                evs.append(lucid_ev({kk: v[ix] for kk, v in d.items()}, paths=3000, seed=100 + b)["ev"])
            row["ev_boot_lo"], row["ev_boot_hi"] = (float(x) for x in np.percentile(evs, [2.5, 97.5]))
        out.append(row)
        print(f"{product} {kind:<4}{setup:<6}f{f:<5}rr{rr:<4}k{k} {mode:<9} EV {node['ev']:+7.1f} "
              f"[{node['ev_lo']:+.1f},{node['ev_hi']:+.1f}] pass {node['pass_rate']:.1%} paid {node['paid']:.1%} "
              f"trade-days {node['trade_days']:.0%} | random twin {tw_ev.mean():+7.1f} ({tw_ev.min():+.0f}..{tw_ev.max():+.0f})"
              + (f" | boot [{row['ev_boot_lo']:+.0f},{row['ev_boot_hi']:+.0f}]" if outer else ""), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "analyse", "lucid"])
    ap.add_argument("--products", default="NQ,ES")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    prods = a.products.split(",")
    if a.cmd == "build":
        for p in prods:
            df = build(p)
            print(p, len(df), "trades", df.date.nunique(), "sessions", flush=True)
    if a.cmd in ("build", "analyse"):
        res = pd.concat([analyse(pd.read_parquet(OUT / f"trades_{p}.parquet"), p) for p in prods])
        res.to_csv(OUT / "cells.csv", index=False)
        pd.set_option("display.width", 250, "display.max_rows", 200)
        print(res.round(3).to_string(index=False))
    if a.cmd == "lucid":
        res = pd.read_csv(OUT / "cells.csv")
        rows = []
        for p in prods:
            df = pd.read_parquet(OUT / f"trades_{p}.parquet")
            cells = [tuple(r) for r in res[res["product"] == p][["kind", "setup", "f", "rr"]].itertuples(index=False)]
            rows += lucid_table(df, p, cells, k=1, outer=100)
        (OUT / "lucid.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
