"""What if the NQ IV-wall OCO goes live at 09:30 instead of 09:35? Rules: iv_wall_open930_prereg.json.

SPENT DATA, INFORMATION ONLY; the frozen rule stays 09:35.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_open930.py

Output: data/iv_wall/open930.json
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from iv_wall_grid import OUT, TARGET_R, VOL_CSV, IVGrid, _ev
from iv_wall_study import load_vol

ML = Path(__file__).resolve().parent
PREREG = ML / "iv_wall_open930_prereg.json"
COIN_SEEDS, BOOTS, S_MULT = 40, 10_000, 0.4


def early_trade(E, s, si, m):
    """The 09:30-09:35 stop-entry trade of session s with walls from meta m, or None (engine fill rules)."""
    snap, check_bar, entry_fill = E.snap, E.check_bar, E.entry_fill
    sig, pc = m["sigma"], m["pc"]
    orders = []
    for d in (1, -1):
        wall = pc + d * sig
        stop = wall - d * S_MULT * sig
        tgt = wall + d * TARGET_R * abs(wall - stop)
        orders.append({"side": d, "px": snap(wall, up=d > 0), "stop": snap(stop, up=d < 0), "target": snap(tgt, up=d > 0)})
    a, z = int(s.b5["a"][0]), int(s.b5["b"][0])
    assert int(s.b5["slot"][0]) == 0
    flat_mod = s.close_mod - 5
    for j in range(a, z + 1):
        hits = [(o, entry_fill(s.o[j], s.h[j], s.l[j], o["side"], "stop", o["px"])) for o in orders]
        hits = [(o, f) for o, f in hits if f is not None]
        if not hits:
            continue
        if len(hits) == 2:  # both walls in one 1m bar: take the one nearer the bar open (never happened in checks)
            hits.sort(key=lambda x: abs(x[0]["px"] - s.o[j]))
        o, f = hits[0]
        at_open = f == s.o[j]
        d = o["side"]
        t = {"day": s.day.isoformat(), "si": si, "side": d, "entry_kind": "stop", "entry_ref": float(f),
             "stop_init": o["stop"], "target": o["target"], "j_entry": j, "at_open": at_open,
             "entry_mod": int(s.mod[j]), "risk_pts": max(abs(f - o["stop"]), 0.25), "both_walls_bar": len(hits) == 2}
        r = check_bar(f, s.h[j], s.l[j], d, o["stop"], o["target"], allow_target=at_open)
        jx = j
        while r is None:
            jx += 1
            if jx >= len(s.o):
                r, jx = ("flat", s.c[-1]), len(s.o) - 1
                break
            if s.mod[jx] >= flat_mod:
                r = ("flat", s.o[jx])
                break
            r = check_bar(s.o[jx], s.h[jx], s.l[jx], d, o["stop"], o["target"], allow_target=True)
        t.update(exit_kind=r[0], exit_ref=float(r[1]), j_exit=jx, exit_mod=int(s.mod[jx]))
        return t
    return None


def net_r(ev, trades, scen="base"):
    if not trades:
        return np.zeros(0)
    risk = np.array([t["risk_pts"] * 2.0 for t in trades])
    return np.asarray(ev["costs"].apply(trades, scen)["usd"]) / risk


def coin(ev, sessions, trades):
    if not trades:
        return float("nan")
    rl = net_r(ev, [ev["twins"]._one(sessions[t["si"]], t, 1) for t in trades])
    rs = net_r(ev, [ev["twins"]._one(sessions[t["si"]], t, -1) for t in trades])
    return float(np.mean([np.where(np.random.default_rng(k).random(len(rl)) < 0.5, rl, rs).mean()
                          for k in range(1, COIN_SEEDS + 1)]))


def one_split(ev, split, vd, vv):
    E = ev["engine"]
    warm, trade = ev["data"].load_split(split)
    strat = IVGrid("touch", "fixed", S_MULT, vd, vv)
    base = E.run(warm, trade, strat)["trades"]
    early, variant, dropped = [], [], []
    by_si = {}
    for t in base:
        by_si.setdefault(t["si"], []).append(t)
    for si, s in enumerate(trade):
        m = strat.meta.get(s.day.isoformat())
        e = early_trade(E, s, si, m) if m is not None else None
        rest = by_si.get(si, [])
        if e is None:
            variant += rest
            continue
        early.append(e)
        variant.append(e)
        for t in rest:
            assert t["side"] != e["side"], "frozen rule traded a wall touched 09:30-09:35"
            keep = (t["entry_mod"] - 570) // 5 > (e["exit_mod"] - 570) // 5
            (variant if keep else dropped).append(t)
    return trade, base, early, variant, dropped


def stats(ev, sessions, trades, n_years):
    r, rs = net_r(ev, trades), net_r(ev, trades, "stress")
    c = coin(ev, sessions, trades)
    return {"n": len(trades), "per_year": len(trades) / n_years, "mean_r": float(r.mean()) if len(r) else float("nan"),
            "stress_r": float(rs.mean()) if len(rs) else float("nan"), "r_per_year": float(r.sum() / n_years),
            "coin_r": c, "edge": float(r.mean() - c) if len(r) else float("nan"),
            "win": float((r > 0).mean()) if len(r) else float("nan"),
            "exits": pd.Series([t["exit_kind"] for t in trades]).value_counts().to_dict()}


def main():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    rng = np.random.default_rng(20261106)
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest()}
    pooled = {"base": [], "early": [], "variant": [], "dropped": [], "diff": [], "years": 0.0}
    yrows = []
    for split in ("val1", "val2"):
        sessions, base, early, variant, dropped = one_split(ev, split, vd, vv)
        ny = len(sessions) / 252
        rb, rv = net_r(ev, base), net_r(ev, variant)
        db = pd.Series(rb).groupby([t["day"] for t in base]).sum()
        dv = pd.Series(rv).groupby([t["day"] for t in variant]).sum()
        days = [s.day.isoformat() for s in sessions]
        diff = (dv.reindex(days).fillna(0) - db.reindex(days).fillna(0)).to_numpy()
        bs = rng.choice(diff, (BOOTS, len(diff))).sum(1)
        out[split] = {"frozen_0935": stats(ev, sessions, base, ny), "early_only": stats(ev, sessions, early, ny),
                      "variant_0930": stats(ev, sessions, variant, ny), "dropped_later_trades": len(dropped),
                      "dropped_r": float(net_r(ev, dropped).sum()) if dropped else 0.0,
                      "paired_total_diff_r": float(diff.sum()),
                      "paired_ci": [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))],
                      "both_walls_bar": int(sum(t["both_walls_bar"] for t in early))}
        for y in sorted({s.day.year for s in sessions}):
            f = lambda tr, r: float(sum(x for t, x in zip(tr, r) if t["day"].startswith(str(y))))
            re_ = net_r(ev, early)
            yrows.append({"year": y, "frozen": f(base, rb), "variant": f(variant, rv), "early_n": sum(t["day"].startswith(str(y)) for t in early),
                          "early_r": f(early, re_)})
        pooled["base"] += [(sessions, t) for t in base]
        pooled["early"] += [(sessions, t) for t in early]
        pooled["variant"] += [(sessions, t) for t in variant]
        pooled["dropped"] += dropped
        pooled["diff"].append(diff)
        pooled["years"] += ny
    # pooled numbers (coins per split are averaged by trade count)
    ny = pooled["years"]
    P = {}
    for k in ("base", "early", "variant"):
        tr = [t for _, t in pooled[k]]
        r, rs = net_r(ev, tr), net_r(ev, tr, "stress")
        n1 = out["val1"][{"base": "frozen_0935", "early": "early_only", "variant": "variant_0930"}[k]]
        n2 = out["val2"][{"base": "frozen_0935", "early": "early_only", "variant": "variant_0930"}[k]]
        c = (n1["coin_r"] * n1["n"] + n2["coin_r"] * n2["n"]) / (n1["n"] + n2["n"])
        P[k] = {"n": len(tr), "per_year": len(tr) / ny, "mean_r": float(r.mean()), "stress_r": float(rs.mean()),
                "r_per_year": float(r.sum() / ny), "coin_r": float(c), "edge": float(r.mean() - c),
                "win": float((r > 0).mean()), "exits": pd.Series([t["exit_kind"] for t in tr]).value_counts().to_dict()}
    d = np.concatenate(pooled["diff"])
    bs = rng.choice(d, (BOOTS, len(d))).sum(1)
    P["paired_total_diff_r"] = float(d.sum())
    P["paired_ci"] = [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))]
    P["dropped_later_trades"] = len(pooled["dropped"])
    P["dropped_r"] = float(net_r(ev, pooled["dropped"]).sum()) if pooled["dropped"] else 0.0
    er = net_r(ev, [t for _, t in pooled["early"]])
    eb = rng.choice(er, (BOOTS, len(er))).mean(1)
    P["early_ci"] = [float(np.quantile(eb, .025)), float(np.quantile(eb, .975))]
    out["pooled"], out["by_year"] = P, yrows
    (OUT / "open930.json").write_text(json.dumps(out, indent=1, default=str))
    for k, lab in (("base", "frozen 09:35"), ("early", "09:30-09:35 trades only"), ("variant", "live from 09:30")):
        x = P[k]
        print(f"{lab:25s} n {x['n']:3d} ({x['per_year']:4.1f}/yr)  mean {x['mean_r']:+.3f}R  stress {x['stress_r']:+.3f}  "
              f"R/yr {x['r_per_year']:+5.2f}  coin {x['coin_r']:+.3f}  edge {x['edge']:+.3f}  win {x['win']:.0%}  {x['exits']}")
    print(f"early mean CI [{P['early_ci'][0]:+.3f}, {P['early_ci'][1]:+.3f}]")
    print(f"paired 09:30 minus 09:35: {P['paired_total_diff_r']:+.2f}R CI [{P['paired_ci'][0]:+.2f}, {P['paired_ci'][1]:+.2f}]  "
          f"later trades lost: {P['dropped_later_trades']} ({P['dropped_r']:+.2f}R)")
    for w in ("val1", "val2"):
        x = out[w]
        print(f"{w}: frozen {x['frozen_0935']['mean_r']:+.3f} ({x['frozen_0935']['n']})  early {x['early_only']['mean_r']:+.3f} "
              f"({x['early_only']['n']}, stress {x['early_only']['stress_r']:+.3f}, edge {x['early_only']['edge']:+.3f})  "
              f"variant {x['variant_0930']['mean_r']:+.3f} ({x['variant_0930']['n']})  paired {x['paired_total_diff_r']:+.2f} "
              f"CI [{x['paired_ci'][0]:+.2f}, {x['paired_ci'][1]:+.2f}]  both-wall bars {x['both_walls_bar']}")
    for y in yrows:
        print(f"  {y['year']}: frozen {y['frozen']:+6.2f}  from 09:30 {y['variant']:+6.2f}  early {y['early_n']:2d} trades {y['early_r']:+6.2f}R")


if __name__ == "__main__":
    main()
