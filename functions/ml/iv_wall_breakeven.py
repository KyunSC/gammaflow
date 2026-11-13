"""Breakeven-stop sweep on the frozen NQ IV-wall break (prereg iv_wall_breakeven_prereg.json). INFO ONLY: NQ is spent.

    cd functions/ml && .venv/bin/python -B iv_wall_breakeven.py

Output: data/iv_wall_breakeven/{results.json, trades_<cell>_<window>.csv}.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from gex0dte_wall_break import FRESH, ev_mods, run_one, trade_frame
from iv_wall_grid import IVGrid
from iv_wall_study import ML, VOL_CSV, load_vol
from vol_band_break import pooled

OUT = ML / "data" / "iv_wall_breakeven"
PREREG = ML / "iv_wall_breakeven_prereg.json"
TRIGGERS = (0.5, 0.75, 1.0, 1.25, 1.5)
CELLS = ("fixed",) + tuple(f"be_{t}" for t in TRIGGERS)


class BreakEven(IVGrid):
    """Frozen touch / 2R / 0.4 rule; after the trade has run T x risk in favour, stop goes to the entry fill."""

    def __init__(self, trigger, vd, vv):
        super().__init__("touch", "fixed", 0.4, vd, vv)
        self.trigger = trigger

    def _manage(self, bar, pos):
        d, c = pos["side"], bar["c"]
        pi = self.pos_info
        if pi is None:
            pi = self.pos_info = {"entry": pos["entry_px"], "init_stop": pos["stop"],
                                  "ext": bar["h"] if d > 0 else bar["l"], "be_armed": False}
            if self.order_wall:
                self.state[self.order_wall] = "used"
        else:
            pi["ext"] = max(pi["ext"], bar["h"]) if d > 0 else min(pi["ext"], bar["l"])
        if self.trigger is None:
            return None
        risk = abs(pi["entry"] - pi["init_stop"])
        if d * (pi["ext"] - pi["entry"]) >= self.trigger * risk:
            pi["be_armed"] = True
        if pi["be_armed"] and d * (pos["stop"] - pi["entry"]) < 0 and d * (c - pi["entry"]) > 0:
            return {"op": "stop", "price": pi["entry"]}
        return None


def pair(fx, be):
    """Match BE trades to the fixed control on (day, side) and label what the BE stop changed."""
    m = fx.merge(be, on=["day", "side"], suffixes=("_fx", "_be"))
    changed = m[(m.r_net_fx - m.r_net_be).abs() > 1e-9]
    saved = changed[(changed.exit_kind_fx == "stop") & (changed.r_net_be > changed.r_net_fx)]
    killed = changed[changed.r_net_be < changed.r_net_fx]
    other = changed.drop(saved.index.union(killed.index))
    return {"matched": len(m), "unmatched_fx": len(fx) - len(m), "unmatched_be": len(be) - len(m), "changed": len(changed),
            "saved": {"n": len(saved), "r": float((saved.r_net_be - saved.r_net_fx).sum())},
            "killed": {"n": len(killed), "r": float((killed.r_net_be - killed.r_net_fx).sum()),
                       "would_target": int((killed.exit_kind_fx == "target").sum()),
                       "would_flat_pos": int(((killed.exit_kind_fx == "flat") & (killed.r_net_fx > 0)).sum())},
            "other": {"n": len(other), "r": float((other.r_net_be - other.r_net_fx).sum())},
            "net_r": float((m.r_net_be - m.r_net_fx).sum())}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ev = ev_mods()
    vd, vv = load_vol(VOL_CSV["NQ"])
    windows = {s: ev["data"].load_split(s) for s in ("dev", "val1", "val2")}
    fr = ev["data"].load_window(FRESH[0] - timedelta(days=60), FRESH[1])
    i0 = next(i for i, s in enumerate(fr) if s.day >= FRESH[0])
    windows["fresh"] = (fr[max(0, i0 - 20):i0], fr[i0:])
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg": json.loads(PREREG.read_text()), "windows": {}, "pooled": {}, "pairing": {}}
    frames = {c: {} for c in CELLS}
    for w, (warm, trade) in windows.items():
        out["windows"][w] = {"sessions": len(trade), "first": trade[0].day.isoformat(), "last": trade[-1].day.isoformat()}
        for cell in CELLS:
            t = None if cell == "fixed" else float(cell[3:])
            tr, base, m = run_one(ev, warm, trade, BreakEven(t, vd, vv), 1)
            df = trade_frame(tr, base)
            df.to_csv(OUT / f"trades_{cell}_{w}.csv", index=False)
            frames[cell][w] = df
            if m:
                m["win_rate_net"] = float((df.r_net > 0).mean())
            out["windows"][w][cell] = m
            if m:
                print(f"{w} {cell}: n={m['trades']} R={m['mean_r_base']:+.3f} gross={m['gross_r']:+.3f} stress={m['mean_r_stress']:+.3f} "
                      f"p={m['twin']['p']:.4f} win={m['win_rate_net']:.2f} exits={m['exit_kinds']}", flush=True)
    for cell in CELLS:
        allw = [frames[cell][w] for w in ("dev", "val1", "val2")]
        p = pooled(allw)
        df = pd.concat(allw, ignore_index=True)
        p["win_rate"] = float((df.r_net > 0).mean())
        p["exit_kinds"] = df.exit_kind.value_counts().to_dict()
        p["max_dd_r"] = float((df.r_net.cumsum().cummax() - df.r_net.cumsum()).max())
        p["cum"] = {"day": df.day.tolist(), "r": df.r_net.cumsum().round(3).tolist()}
        p["splits"] = {w: float(frames[cell][w].r_net.mean()) if len(frames[cell][w]) else None for w in windows}
        out["pooled"][cell] = p
        print(f"POOLED {cell}: n={p['n']} R={p['r']:+.4f} CI[{p['ci'][0]:+.3f},{p['ci'][1]:+.3f}] usd={p['usd']:+.0f} "
              f"win={p['win_rate']:.2f} dd={p['max_dd_r']:.1f}R pos_years {p['pos_years']}/{p['years']}", flush=True)
        if cell != "fixed":
            fx = pd.concat([frames["fixed"][w] for w in ("dev", "val1", "val2")], ignore_index=True)
            out["pairing"][cell] = pair(fx, df)
            print("   pairing", {k: v for k, v in out["pairing"][cell].items()}, flush=True)
    # how far do trades run before they lose? MFE of fixed-rule stop-outs is approximated by BE outcomes above.
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
