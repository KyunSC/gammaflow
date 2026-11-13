"""What if you enter anyway when NQ is already beyond an IV wall before the open? Rules: iv_wall_chase_prereg.json.

SPENT DATA, INFORMATION ONLY; the frozen rule (skip days that open outside the walls) is not changed.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_chase.py

Output: data/iv_wall/chase.json
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from iv_wall_grid import OUT, TARGET_R, VOL_CSV, IVGrid, _ev
from iv_wall_hours import S_MULT, SPLITS, coin_r, load_raw, net_r, sigma_table, summarize
from iv_wall_study import load_vol

ML = Path(__file__).resolve().parent
PREREG = ML / "iv_wall_chase_prereg.json"
ENTRIES = ("E0900", "E0930", "E0935")
BRACKETS = ("printed", "same_size")


def chase_trade(E, p, j, flat_j, si, day, sig, pc, bracket):
    """Market entry at the open of bar j of path p if that open is beyond a wall; None otherwise."""
    px = float(p.o[j])
    up, lo = E.snap(pc + sig, up=True), E.snap(pc - sig, up=False)
    d = 1 if px >= up else -1 if px <= lo else 0
    if d == 0:
        return None
    wall = pc + d * sig
    if bracket == "printed":
        stop = E.snap(wall - d * S_MULT * sig, up=d < 0)
        tgt = E.snap(wall + d * TARGET_R * S_MULT * sig, up=d > 0)
        if d * (px - tgt) >= 0:
            return "past_target"
    else:
        stop = E.snap(px - d * S_MULT * sig, up=d < 0)
        tgt = E.snap(px + d * TARGET_R * S_MULT * sig, up=d > 0)
    t = {"day": day, "si": si, "side": d, "entry_kind": "market", "entry_ref": px, "stop_init": stop, "target": tgt,
         "j_entry": j, "at_open": True, "entry_mod": int(p.mod[j]), "risk_pts": max(abs(px - stop), 0.25),
         "beyond_pts": d * (px - wall), "sigma": sig}
    n, jx = len(p.o), j
    r = E.check_bar(px, p.h[j], p.l[j], d, stop, tgt, allow_target=True)
    while r is None:
        jx += 1
        if jx >= n:
            r, jx = ("flat", p.c[-1]), n - 1
            break
        if jx >= flat_j:
            r = ("flat", p.o[jx])
            break
        r = E.check_bar(p.o[jx], p.h[jx], p.l[jx], d, stop, tgt, allow_target=True)
    t.update(exit_kind=r[0], exit_ref=float(r[1]), j_exit=jx, exit_mod=int(p.mod[jx]))
    return t


def one_split(ev, split, vd, vv):
    E, C = ev["engine"], ev["config"]
    warm, trade = ev["data"].load_split(split)
    strat = IVGrid("touch", "fixed", S_MULT, vd, vv)
    frozen = E.run(warm, trade, strat)["trades"]
    meta = sigma_table(warm + trade, vd, vv)
    raw = load_raw(ev, split)
    res = {"years": len(trade) / 252, "sessions": len(trade), "frozen": frozen, "rth_paths": dict(enumerate(trade)),
           "paths": {}, "cells": {f"{e}|{b}": [] for e in ENTRIES for b in BRACKETS}, "past_target": {e: 0 for e in ENTRIES},
           "counts": {"with_sigma": 0, "open_outside": 0, "on_cross_days": 0, "on_cross_open_inside": 0, "beyond_0900": 0,
                      "outside_back_in_0935": 0}}
    crossed = {}   # si -> set of sides whose wall was reached in Globex before 09:30
    for si, s in enumerate(trade):
        m = meta.get(s.day.isoformat())
        if m is None or m["prev_day"] is None or int(s.mod[0]) != 570:
            continue
        sig, pc = m["sigma"], m["pc"]
        res["counts"]["with_sigma"] += 1
        res["counts"]["open_outside"] += not m["inside"]
        t0 = int(pd.Timestamp(m["prev_day"]).tz_localize(C.TZ).replace(hour=18).tz_convert("UTC").timestamp())
        a, b = np.searchsorted(raw["t"], t0), np.searchsorted(raw["t"], int(s.t[0]))
        w = np.arange(a, b)
        w = w[raw["inst"][w] == s.inst]
        n_on = len(w)
        p = SimpleNamespace(o=np.concatenate([raw["o"][w], s.o]), h=np.concatenate([raw["h"][w], s.h]),
                            l=np.concatenate([raw["l"][w], s.l]), c=np.concatenate([raw["c"][w], s.c]),
                            mod=np.concatenate([raw["mod"][w], s.mod]))
        res["paths"][si] = p
        fl = np.flatnonzero(s.mod >= s.close_mod - 5)
        flat_j = n_on + (int(fl[0]) if len(fl) else len(s.o))
        if n_on:
            up, lo = E.snap(pc + sig, up=True), E.snap(pc - sig, up=False)
            cs = {d for d, hit in ((1, raw["h"][w].max() >= up), (-1, raw["l"][w].min() <= lo)) if hit}
            crossed[si] = cs
            res["counts"]["on_cross_days"] += bool(cs)
            res["counts"]["on_cross_open_inside"] += bool(cs) and m["inside"]
        # entry bars
        j900 = None
        if n_on:
            k = int(np.searchsorted(raw["t"][w], int(s.t[0]) - 1800))
            j900 = k if k < n_on else None
        k935 = np.flatnonzero(s.mod >= 575)
        j935 = n_on + int(k935[0]) if len(k935) else None
        for e, j, ok in (("E0900", j900, True), ("E0930", n_on, True), ("E0935", j935, not m["inside"])):
            if j is None or not ok:
                continue
            for bk in BRACKETS:
                t = chase_trade(E, p, j, flat_j, si, s.day.isoformat(), sig, pc, bk)
                if t == "past_target":
                    res["past_target"][e] += 1
                elif t is not None:
                    if e == "E0935":   # must still be beyond the wall it opened outside of
                        d0 = 1 if s.o[0] >= pc + sig else -1
                        if t["side"] != d0:
                            continue
                    t["open_inside"] = m["inside"]
                    res["cells"][f"{e}|{bk}"].append(t)
            if e == "E0900" and chase_trade(E, p, j, flat_j, si, "", sig, pc, "same_size") is not None:
                res["counts"]["beyond_0900"] += 1
        if not m["inside"] and j935 is not None and chase_trade(E, p, j935, flat_j, si, "", sig, pc, "same_size") is None:
            res["counts"]["outside_back_in_0935"] += 1
    for t in frozen:
        t["on_crossed"] = t["side"] in crossed.get(t["si"], set())
        t["on_any"] = bool(crossed.get(t["si"]))
    return res


def main():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    rng = np.random.default_rng(20261111)
    S = {sp: one_split(ev, sp, vd, vv) for sp in SPLITS}
    SC = {"all": SPLITS, "dev": ("dev",), "val1": ("val1",), "val2": ("val2",)}
    yrs = {k: sum(S[sp]["years"] for sp in v) for k, v in SC.items()}

    def pack(key, pathkey, scopes, keep=lambda t: True):
        r, rs, rl, rsh, tr = [], [], [], [], []
        for sp in scopes:
            x = [t for t in key(S[sp]) if keep(t)]
            if not x:
                continue
            a, b = coin_r(ev, S[sp][pathkey], x)
            r.append(net_r(ev, x)); rs.append(net_r(ev, x, "stress")); rl.append(a); rsh.append(b)
            tr += x
        cat = lambda z: np.concatenate(z) if z else np.zeros(0)
        return {"r": cat(r), "rs": cat(rs), "rl": cat(rl), "rsh": cat(rsh), "tr": tr}

    def summ(P, years, mask=None):
        m = np.ones(len(P["r"]), bool) if mask is None else np.asarray(mask, bool)
        kinds = [t["exit_kind"] for t, k in zip(P["tr"], m) if k]
        return summarize(P["r"][m], P["rs"][m], P["rl"][m], P["rsh"][m], kinds, years, rng)

    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "counts": {sp: {**S[sp]["counts"], "sessions": S[sp]["sessions"], "past_target": S[sp]["past_target"]} for sp in SPLITS},
           "cells": {}, "frozen": {}}
    for cell in S["dev"]["cells"]:
        row = {}
        for k in SC:
            P = pack(lambda s, c=cell: s["cells"][c], "paths", SC[k])
            row[k] = summ(P, yrs[k])
            if k == "all" and len(P["tr"]):
                sides = np.array([t["side"] for t in P["tr"]])
                row["long"], row["short"] = summ(P, yrs[k], sides > 0), summ(P, yrs[k], sides < 0)
                row["risk_pts_over_sigma_median"] = float(np.median([t["risk_pts"] / t["sigma"] for t in P["tr"]]))
                row["beyond_over_sigma_median"] = float(np.median([t["beyond_pts"] / t["sigma"] for t in P["tr"]]))
                if cell.startswith("E0900"):
                    ins = np.array([t["open_inside"] for t in P["tr"]])
                    row["then_open_inside"], row["then_open_outside"] = summ(P, yrs[k], ins), summ(P, yrs[k], ~ins)
        out["cells"][cell] = row
    for name, keep in (("all", lambda t: True), ("wall_crossed_overnight", lambda t: t["on_crossed"]),
                       ("other_wall_crossed_overnight", lambda t: t["on_any"] and not t["on_crossed"]),
                       ("no_overnight_cross", lambda t: not t["on_any"])):
        out["frozen"][name] = {k: summ(pack(lambda s: s["frozen"], "rth_paths", SC[k], keep), yrs[k]) for k in SC}
    (OUT / "chase.json").write_text(json.dumps(out, indent=1, default=str))

    def line(lab, x):
        if not x.get("n"):
            return f"{lab:34s} n    0"
        return (f"{lab:34s} n {x['n']:4d} ({x['per_year']:5.1f}/yr) mean {x['mean_r']:+.3f}R CI [{x['ci'][0]:+.3f},{x['ci'][1]:+.3f}] "
                f"stress {x['stress_r']:+.3f} coin {x['coin_r']:+.3f} edge {x['edge']:+.3f} win {x['win']:.0%} total {x['total_r']:+.1f}R {x['exits']}")
    for sp in SPLITS:
        print(sp, out["counts"][sp])
    for cell, row in out["cells"].items():
        print()
        print(line(cell, row["all"]), "| dev/val1/val2", *[f"{row[s]['mean_r']:+.2f}({row[s]['n']})" if row[s].get("n") else "na" for s in SPLITS])
        for k in ("long", "short", "then_open_inside", "then_open_outside"):
            if k in row:
                print(line(f"    {k}", row[k]))
        print(f"    median risk {row.get('risk_pts_over_sigma_median', float('nan')):.2f} sigma, entry {row.get('beyond_over_sigma_median', float('nan')):.2f} sigma past the wall")
    print()
    for name, row in out["frozen"].items():
        print(line(f"frozen: {name}", row["all"]), "| dev/val1/val2", *[f"{row[s]['mean_r']:+.2f}({row[s]['n']})" if row[s].get("n") else "na" for s in SPLITS])


if __name__ == "__main__":
    main()
