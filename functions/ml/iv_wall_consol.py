"""IV-wall break: take profit when an open winner consolidates near its peak (prereg iv_wall_consol_prereg.json).
Spent data, information only; the frozen rule is unchanged.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_consol.py

Output: data/iv_wall/consol.json
"""
from __future__ import annotations

import itertools
import json
from datetime import datetime

import numpy as np

from iv_wall_grid import IVGrid, _ev
from iv_wall_study import ML, OUT, VOL_CSV, load_vol

SPEC = json.loads((ML / "iv_wall_consol_prereg.json").read_text())
G = SPEC["grid"]
CELLS = [{"P": p, "N": n, "W": w} for p, n, w in itertools.product(G["P_R"], G["N_hours"], G["W_sigma"])]
SPLITS = ("dev", "val1", "val2")
BARS_PER_HOUR = 12


class Consol(IVGrid):
    def __init__(self, P, N, W, vd, vv):
        super().__init__("touch", "fixed", 0.4, vd, vv)
        self.P, self.nb, self.W = P, N * BARS_PER_HOUR, W
        self.hist = []

    def _new_day(self, bar):
        super()._new_day(bar)
        self.hist = []

    def _manage(self, bar, pos):
        first = self.pos_info is None
        act = super()._manage(bar, pos)  # fixed exit: always None, keeps pos_info / ext
        if first:
            self.hist = []  # the entry bar is not part of any window
            return act
        self.hist.append((bar["h"], bar["l"]))
        pi, d = self.pos_info, pos["side"]
        risk = abs(pi["entry"] - pi["init_stop"])
        if len(self.hist) < self.nb or d * (bar["c"] - pi["entry"]) < self.P * risk:
            return act
        win = self.hist[-self.nb:]
        hi, lo = max(h for h, _ in win), min(l for _, l in win)
        lim = self.W * self.sigma
        near = (pi["ext"] - hi) if d > 0 else (lo - pi["ext"])
        if hi - lo <= lim and near <= lim:
            return {"op": "exit"}
        return act


def run(ev, split, strat):
    warm, trade = ev["data"].load_split(split)
    tr = ev["engine"].run(warm, trade, strat)["trades"]
    base, stress = ev["costs"].apply(tr, "base"), ev["costs"].apply(tr, "stress")
    return {"trades": tr, "r": np.asarray(base["r"]), "rs": np.asarray(stress["r"]), "n_sess": len(trade)}


def by_day(part):
    out = {}
    for t, r in zip(part["trades"], part["r"]):
        out[t["day"]] = out.get(t["day"], 0.0) + float(r)
    return out


def paired(b, v, rng):
    days = sorted(set(b) | set(v))
    diff = np.array([v.get(d, 0.0) - b.get(d, 0.0) for d in days])
    boots = [diff[rng.integers(0, len(diff), len(diff))].sum() for _ in range(2000)]
    return float(diff.sum()), [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))], len(diff)


def main():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    years = {}
    base = {}
    for sp in SPLITS:
        base[sp] = run(ev, sp, IVGrid("touch", "fixed", 0.4, vd, vv))
        warm, trade = ev["data"].load_split(sp)
        years[sp] = len(trade) / 252
        b = base[sp]
        print(f"baseline {sp}: n={len(b['r'])} R={b['r'].mean():+.3f} sum={b['r'].sum():+.1f}R", flush=True)
    rng = np.random.default_rng(20261109)
    rows = []
    for c in CELLS:
        row = {**c, "splits": {}}
        allb, allv = {}, {}
        for sp in SPLITS:
            v = run(ev, sp, Consol(c["P"], c["N"], c["W"], vd, vv))
            b = base[sp]
            bd, vdd = by_day(b), by_day(v)
            allb.update(bd)
            allv.update(vdd)
            cut_days = {t["day"] for t in v["trades"] if t["exit_kind"] == "market"}
            ends = {}
            for t in b["trades"]:
                if t["day"] in cut_days:
                    ends[t["exit_kind"]] = ends.get(t["exit_kind"], 0) + 1
            dsum, ci, _ = paired(bd, vdd, rng)
            row["splits"][sp] = {"n": len(v["r"]), "r": float(v["r"].mean()), "r_stress": float(v["rs"].mean()),
                                 "r_per_year": float(v["r"].sum() / years[sp]), "cut": len(cut_days),
                                 "cut_baseline_ends": ends, "diff_sum_r": dsum, "diff_ci": ci}
        dsum, ci, nd = paired(allb, allv, rng)
        row["pooled"] = {"diff_sum_r": dsum, "diff_ci": ci, "sessions": nd,
                         "cut": sum(row["splits"][s]["cut"] for s in SPLITS)}
        rows.append(row)
        s = row["splits"]
        print(f"P={c['P']} N={c['N']}h W={c['W']}: cut {row['pooled']['cut']:3d}  diff {dsum:+6.1f}R "
              f"CI[{ci[0]:+.1f},{ci[1]:+.1f}]  by window " +
              "  ".join(f"{sp} {s[sp]['diff_sum_r']:+.1f}R ({s[sp]['r']:+.3f}/tr)" for sp in SPLITS) +
              "  cut trades ended (baseline): " + str({k: sum(s[sp]['cut_baseline_ends'].get(k, 0) for sp in SPLITS)
                                                      for k in ("target", "flat", "stop")}), flush=True)
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg": SPEC,
           "baseline": {sp: {"n": len(base[sp]["r"]), "r": float(base[sp]["r"].mean()),
                             "r_per_year": float(base[sp]["r"].sum() / years[sp])} for sp in SPLITS},
           "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "consol.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
