"""IV-wall break grid (prereg iv_wall_grid_prereg.json): entry {touch, close, retest} x exit {fixed, be1, trail} x
stop s {0.4, 0.6} sigma. Tunes on 2011-2021 (dev + val1 pooled), picks one config by the frozen rule, and only then
may run the single val2 look on NQ.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_grid.py tune --product NQ|ES
    cd functions/ml && ../../.venv/bin/python -B iv_wall_grid.py final        # NQ val2, picked config only

Outputs: data/iv_wall/grid_<product>_tune.json, data/iv_wall/grid_NQ_val2.json.
"""
from __future__ import annotations

import argparse
import importlib
import itertools
import json
from datetime import datetime

import numpy as np

from iv_wall_study import EVAL_PKG, OUT, VOL_CSV, IVWall, load_vol

ENTRIES = ("touch", "close", "retest")
EXITS = ("fixed", "be1", "trail")
STOPS = (0.4, 0.6)
GRID = [{"entry": e, "exit": x, "s": s} for e, x, s in itertools.product(ENTRIES, EXITS, STOPS)]
TARGET_R = 2.0
LAST_SLOT = 71


class IVGrid(IVWall):
    def __init__(self, entry: str, exit: str, s: float, vol_days, vol_vals):
        super().__init__(s, 1.0, TARGET_R, vol_days, vol_vals, mode="break")
        assert entry in ENTRIES and exit in EXITS
        self.entry, self.exit = entry, exit
        self.state = {}
        self.pos_info = None
        self.order_wall = None

    def _new_day(self, bar):
        super()._new_day(bar)
        self.state = {"U": "fresh", "L": "fresh"}
        self.pos_info = None
        self.order_wall = None

    def _wall(self, w):
        return (self.U, 1) if w == "U" else (self.L, -1)

    def _enter(self, w, typ, c, price=None):
        wall, d = self._wall(w)
        stop = wall - d * self.s * self.sigma
        ref = wall if typ in ("stop", "limit") else c
        tgt = None if self.exit == "trail" else ref + d * TARGET_R * abs(ref - stop)
        self.order_wall = w
        act = {"op": "enter", "side": d, "type": typ, "stop": stop, "target": tgt}
        if typ != "market":
            act.update(price=wall, ttl=1)
        return act

    def _manage(self, bar, pos):
        d, c = pos["side"], bar["c"]
        pi = self.pos_info
        if pi is None:  # first decision with this position open
            pi = self.pos_info = {"entry": pos["entry_px"], "init_stop": pos["stop"], "ext": bar["h"] if d > 0 else bar["l"],
                                  "be_armed": False}
            if self.order_wall:
                self.state[self.order_wall] = "used"
        else:
            pi["ext"] = max(pi["ext"], bar["h"]) if d > 0 else min(pi["ext"], bar["l"])
        risk = abs(pi["entry"] - pi["init_stop"])
        new = None
        if self.exit == "be1":
            if d * (pi["ext"] - pi["entry"]) >= risk:
                pi["be_armed"] = True
            if pi["be_armed"] and d * (pos["stop"] - pi["entry"]) < 0:
                new = pi["entry"]
        elif self.exit == "trail":
            cand = pi["ext"] - d * self.s * self.sigma
            if d * (cand - pos["stop"]) > 0:
                new = cand
        if new is not None and d * (c - new) > 0:
            return {"op": "stop", "price": new}
        return None

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._new_day(bar)
        if self.U is None:
            return None
        c, h, l = bar["c"], bar["h"], bar["l"]
        if pos is None:
            self.pos_info = None
        # wall bookkeeping that does not depend on our order
        for w in ("U", "L"):
            wall, d = self._wall(w)
            st = self.state[w]
            if self.entry == "touch" and st == "fresh" and d * ((h if d > 0 else l) - wall) >= 0 and pos is None:
                self.state[w] = "used"  # touched without (or with) our fill; a fill is caught in _manage
            if self.entry in ("close", "retest") and st == "fresh" and d * (c - wall) > 0 and pos is not None:
                self.state[w] = "used"  # closed beyond while busy
            if self.entry == "retest" and st == "armed" and pos is None and not d * (c - wall) > 0:
                self.state[w] = "used"  # back at/inside the wall with no fill
        if pos is not None:
            return self._manage(bar, pos)
        if not (0 <= bar["slot"] <= LAST_SLOT):
            return None
        if self.entry == "touch":
            cands = []
            if self.state["U"] == "fresh" and c < self.U:
                cands.append((self.U - c, "U"))
            if self.state["L"] == "fresh" and c > self.L:
                cands.append((c - self.L, "L"))
            if not cands:
                return None
            return self._enter(min(cands)[1], "stop", c)
        for w in ("U", "L"):
            wall, d = self._wall(w)
            if self.state[w] == "fresh" and d * (c - wall) > 0:
                if self.entry == "close":
                    self.state[w] = "used"
                    return self._enter(w, "market", c)
                self.state[w] = "armed"
            if self.state[w] == "armed" and d * (c - wall) > 0:
                return self._enter(w, "limit", c)
        return None


def _ev(product):
    return {m: importlib.import_module(f"{EVAL_PKG[product]}.{m}") for m in ("config", "costs", "criteria", "data", "engine", "twins")}


def run_split(ev, split, cfg, vd, vv):
    warm, trade = ev["data"].load_split(split)
    strat = IVGrid(cfg["entry"], cfg["exit"], cfg["s"], vd, vv)
    tr = ev["engine"].run(warm, trade, strat)["trades"]
    base, stress = ev["costs"].apply(tr, "base"), ev["costs"].apply(tr, "stress")
    rl, rs = ev["twins"].long_short_r(trade, tr)
    return {"trades": tr, "r": base["r"], "usd": base["usd"], "rs": stress["r"], "gross": base["gross_pts"],
            "rl": rl, "rsh": rs, "sess": [s.day.isoformat() for s in trade]}


def metrics(ev, parts, n_trials):
    tr = [t for p in parts for t in p["trades"]]
    r = np.concatenate([p["r"] for p in parts])
    usd = np.concatenate([p["usd"] for p in parts])
    rs = np.concatenate([p["rs"] for p in parts])
    rl = np.concatenate([p["rl"] for p in parts])
    rsh = np.concatenate([p["rsh"] for p in parts])
    sess = [d for p in parts for d in p["sess"]]
    days = np.array([t["day"] for t in tr], dtype=object).astype(str)
    sides = np.array([t["side"] for t in tr])
    tw = ev["twins"].twin_test(r, rl, rsh, sides=list(sides))
    m = ev["criteria"].summarize(r, usd, rs, days, sess, tw, n_trials)
    risk = np.array([t["risk_pts"] for t in tr])
    gross = np.concatenate([p["gross"] for p in parts]) / risk if tr else np.array([])
    m.update({"gross_r": float(gross.mean()) if tr else float("nan"),
              "exit_kinds": {k: int(sum(t["exit_kind"] == k for t in tr)) for k in ("stop", "target", "market", "flat")},
              "long_r": float(r[sides > 0].mean()) if (sides > 0).any() else float("nan"),
              "short_r": float(r[sides < 0].mean()) if (sides < 0).any() else float("nan"),
              "n_long": int((sides > 0).sum())})
    return m


def key(c):
    return f"{c['entry']}/{c['exit']}/{c['s']}"


def tune(product):
    ev = _ev(product)
    vd, vv = load_vol(VOL_CSV[product])
    rows = []
    for cfg in GRID:
        dev = run_split(ev, "dev", cfg, vd, vv)
        v1 = run_split(ev, "val1", cfg, vd, vv)
        pooled = metrics(ev, [dev, v1], len(GRID))
        row = {**cfg, "pooled": pooled, "dev_r": float(dev["r"].mean()) if len(dev["r"]) else float("nan"),
               "val1_r": float(v1["r"].mean()) if len(v1["r"]) else float("nan"), "dev_n": len(dev["r"]), "val1_n": len(v1["r"])}
        rows.append(row)
        print(f"{product} {key(cfg):18s} n={pooled['trades']:4d} R={pooled['mean_r_base']:+.3f} (dev {row['dev_r']:+.3f}, "
              f"19-21 {row['val1_r']:+.3f}) gross={pooled['gross_r']:+.3f} stress={pooled['mean_r_stress']:+.3f} "
              f"p={pooled['twin']['p']:.4f} win={pooled['win_rate']:.2f} L/S {pooled['long_r']:+.2f}/{pooled['short_r']:+.2f}", flush=True)
    for row in rows:
        nb = [o for o in rows if sum(o[a] != row[a] for a in ("entry", "exit", "s")) == 1]
        p = row["pooled"]
        row["neighbour_mean_r"] = float(np.mean([o["pooled"]["mean_r_base"] for o in nb]))
        row["score"] = (p["mean_r_base"] + row["neighbour_mean_r"]) / 2
        row["eligible"] = bool(p["mean_r_base"] > 0 and row["dev_r"] > 0 and row["val1_r"] > 0 and p["mean_r_stress"] > 0
                               and p["twin"]["p"] < 0.05 / len(GRID) and p["trades"] >= 200)
    el = [r for r in rows if r["eligible"]]
    pick = max(el, key=lambda r: r["score"]) if el else None
    print(f"{product} eligible: {[key(r) for r in el]}")
    print(f"{product} pick: {key(pick) + f' score {pick['score']:+.3f}' if pick else 'NONE (val2 stays unopened)'}")
    out = {"product": product, "ran": datetime.now().isoformat(timespec="seconds"), "rows": rows,
           "pick": None if pick is None else {a: pick[a] for a in ("entry", "exit", "s")}}
    (OUT / f"grid_{product}_tune.json").write_text(json.dumps(out, indent=1, default=float))


def final():
    t = json.loads((OUT / "grid_NQ_tune.json").read_text())
    if t["pick"] is None:
        raise SystemExit("no eligible configuration on NQ: val2 stays unopened")
    if (OUT / "grid_NQ_val2.json").exists():
        raise SystemExit("val2 already looked at once")
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    cfg = t["pick"]
    part = run_split(ev, "val2", cfg, vd, vv)
    m = metrics(ev, [part], 1)
    ok, why = ev["criteria"].gate(m, "val2")
    (OUT / "grid_NQ_val2.json").write_text(json.dumps({"config": cfg, "metrics": m, "pass": ok, "fails": why,
                                                       "ran": datetime.now().isoformat(timespec="seconds")}, indent=1, default=float))
    print(f"NQ val2 {key(cfg)}: n={m['trades']} R={m['mean_r_base']:+.3f} CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] "
          f"stress={m['mean_r_stress']:+.3f} p={m['twin']['p']:.4f} -> {'PASS' if ok else 'FAIL'} {why}")
    print("by year", {y: (v["n"], round(v["mean_r"], 3)) for y, v in m["by_year"].items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    tp = sub.add_parser("tune")
    tp.add_argument("--product", choices=["ES", "NQ"], required=True)
    sub.add_parser("final")
    a = ap.parse_args()
    tune(a.product) if a.cmd == "tune" else final()
