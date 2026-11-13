"""NQ IV-wall break by 'when was the wall first crossed', per calendar year. Rules: iv_wall_cases_prereg.json.

SPENT DATA, INFORMATION ONLY; the frozen rule is not changed.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_cases.py

Output: data/iv_wall/cases.json
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np

import iv_wall_chase as chase
from iv_wall_grid import OUT, TARGET_R, VOL_CSV, _ev
from iv_wall_hours import S_MULT, net_r, overnight_sim, sigma_table
from iv_wall_open930 import early_trade
from iv_wall_study import load_vol

ML = Path(__file__).resolve().parent
PREREG = ML / "iv_wall_cases_prereg.json"
SPLITS = ("val1", "val2")
CASES = ("frozen_all", "frozen_no_cross", "frozen_crossed", "early_0930", "rebreak", "chase_0930", "chase_0935", "overnight_rest")
ORDER_END, BOOTS = 930, 10_000


def rebreak_trade(E, s, si, e, m):
    """Second break of the wall that early trade e touched in 09:30-09:35 (see prereg), or None."""
    d, sig, pc = e["side"], m["sigma"], m["pc"]
    wall = pc + d * sig
    px, stop = E.snap(wall, up=d > 0), E.snap(wall - d * S_MULT * sig, up=d < 0)
    tgt = E.snap(wall + d * TARGET_R * abs(wall - (wall - d * S_MULT * sig)), up=d > 0)
    flat_mod, n, armed = s.close_mod - 5, len(s.o), False
    for j in range(n):
        mod = int(s.mod[j])
        if mod >= flat_mod or mod >= ORDER_END:
            return None
        if armed and mod >= 575:
            f = E.entry_fill(s.o[j], s.h[j], s.l[j], d, "stop", px)
            if f is not None:
                at_open = f == s.o[j]
                t = {"day": s.day.isoformat(), "si": si, "side": d, "entry_kind": "stop", "entry_ref": float(f), "stop_init": stop,
                     "target": tgt, "j_entry": j, "at_open": at_open, "entry_mod": mod, "risk_pts": max(abs(f - stop), 0.25)}
                r, jx = E.check_bar(f, s.h[j], s.l[j], d, stop, tgt, allow_target=at_open), j
                while r is None:
                    jx += 1
                    if jx >= n:
                        r, jx = ("flat", s.c[-1]), n - 1
                        break
                    if s.mod[jx] >= flat_mod:
                        r = ("flat", s.o[jx])
                        break
                    r = E.check_bar(s.o[jx], s.h[jx], s.l[jx], d, stop, tgt, allow_target=True)
                t.update(exit_kind=r[0], exit_ref=float(r[1]), j_exit=jx, exit_mod=int(s.mod[jx]))
                return t
        # a finished 5m bar (next 1m bar is in a later 5m slot) that closed back inside the wall arms the order
        last_of_5m = j + 1 >= n or int(s.mod[j + 1]) // 5 != mod // 5
        if not armed and last_of_5m and mod + 1 >= 575 and d * (s.c[j] - px) < 0:
            armed = True
    return None


def main():
    ev = _ev("NQ")
    E = ev["engine"]
    vd, vv = load_vol(VOL_CSV["NQ"])
    T = {c: [] for c in CASES}
    for sp in SPLITS:
        S = chase.one_split(ev, sp, vd, vv)
        warm, trade = ev["data"].load_split(sp)
        meta = sigma_table(warm + trade, vd, vv)
        fr = S["frozen"]
        T["frozen_all"] += fr
        T["frozen_no_cross"] += [t for t in fr if not t["on_any"]]
        T["frozen_crossed"] += [t for t in fr if t["on_crossed"]]
        T["chase_0930"] += S["cells"]["E0930|printed"]
        T["chase_0935"] += S["cells"]["E0935|printed"]
        n_early = 0
        for si, s in enumerate(trade):
            m = meta.get(s.day.isoformat())
            if m is None or m["prev_day"] is None or int(s.mod[0]) != 570:
                continue
            p = S["paths"][si]
            n_on = len(p.o) - len(s.o)
            if n_on:
                fl = np.flatnonzero(s.mod >= s.close_mod - 5)
                flat_j = n_on + (int(fl[0]) if len(fl) else len(s.o))
                T["overnight_rest"] += overnight_sim(E, p, n_on, flat_j, si, s.day.isoformat(), m["sigma"], m["pc"])
            if not m["inside"]:
                continue
            e = early_trade(E, s, si, m)
            if e is None:
                continue
            n_early += 1
            T["early_0930"].append(e)
            rb = rebreak_trade(E, s, si, e, m)
            if rb is not None:
                T["rebreak"].append(rb)
        print(sp, "frozen", len(fr), "early", n_early)
    rng = np.random.default_rng(20261111)
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(), "cases": {}}
    for c in CASES:
        tr = T[c]
        r = net_r(ev, tr)
        yr = np.array([int(str(t["day"])[:4]) for t in tr])
        rows = {}
        for y in range(2019, 2027):
            k = yr == y
            rows[y] = {"n": int(k.sum()), "total_r": float(r[k].sum()), "mean_r": float(r[k].mean()) if k.any() else None,
                       "win": float((r[k] > 0).mean()) if k.any() else None}
        k = yr >= 2021
        x = r[k]
        bs = rng.choice(x, (BOOTS, len(x))).mean(1) if len(x) else np.array([np.nan])
        kinds = [t["exit_kind"] for t, kk in zip(tr, k) if kk]
        out["cases"][c] = {"by_year": rows, "from_2021": {"n": int(k.sum()), "total_r": float(x.sum()), "mean_r": float(x.mean()) if len(x) else None,
                           "ci": [float(np.nanquantile(bs, .025)), float(np.nanquantile(bs, .975))], "win": float((x > 0).mean()) if len(x) else None,
                           "exits": {q: kinds.count(q) for q in sorted(set(kinds))}},
                           "all_2019_26": {"n": len(tr), "mean_r": float(r.mean()) if len(r) else None, "total_r": float(r.sum())}}
        f = out["cases"][c]["from_2021"]
        print(f"{c:16s} 2021-26 n {f['n']:4d} mean {f['mean_r']:+.3f}R CI [{f['ci'][0]:+.3f},{f['ci'][1]:+.3f}] total {f['total_r']:+6.1f}R win {f['win']:.0%} {f['exits']}"
              f" | 2019-26 n {len(tr)} mean {r.mean():+.3f}")
        print("   ", "  ".join(f"{y}: {v['n']:3d} {v['total_r']:+6.1f}R" for y, v in rows.items()))
    (OUT / "cases.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
