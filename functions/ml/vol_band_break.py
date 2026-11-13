"""ATR / Keltner / HV-only versions of the frozen IV-wall break on ES and NQ (prereg vol_band_break_prereg.json).
INFO ONLY: ES/NQ 2011-26 are spent for this family.

    cd functions/ml && .venv/bin/python -B vol_band_break.py

Output: data/vol_band_break/{results.json, trades_<product>_<cell>_<split>.csv}.
"""
from __future__ import annotations

import importlib
import json
import math
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd

from gex0dte_wall_break import run_one, trade_frame
from iv_wall_grid import IVGrid
from iv_wall_study import EVAL_PKG, ML, VOL_CSV, load_vol

OUT = ML / "data" / "vol_band_break"
PREREG = ML / "vol_band_break_prereg.json"
CELLS = ("hv", "atr", "keltner")
SPLITS = ("dev", "val1", "val2")


class VolBand(IVGrid):
    """Frozen IVGrid touch/fixed/0.4 with the band built from realized range instead of a vol index. Causal: only
    completed RTH sessions feed HV / ATR / EMA."""

    def __init__(self, cell):
        super().__init__("touch", "fixed", 0.4, [], [])
        assert cell in CELLS
        self.cell = cell
        self.trs: deque = deque(maxlen=20)
        self.closes = 0
        self.ema = None
        self.cur = None          # running {"h", "l", "c", "pc"} of the current session
        self.unit_vs = {}        # day -> band unit, for reporting

    def _finish_day(self, next_pc, next_open):
        cur = self.cur
        if cur is None:
            return
        pc = cur["pc"]
        tr = (max(cur["h"], pc) - min(cur["l"], pc)) if pc is not None else cur["h"] - cur["l"]
        self.trs.append(tr)
        close = next_pc if next_pc is not None else cur["c"]
        if self.ema is None:
            self.ema = close
        else:
            self.ema += 2 / 21 * (close - self.ema)
        self.closes += 1
        if next_pc is None and next_open is not None:   # roll: shift the EMA onto the new contract
            self.ema += next_open - cur["c"]

    def _new_day(self, bar):
        pc = bar["prev_close"]
        self._finish_day(pc, bar["o"])
        if pc is not None and self.last_prev_close is not None:
            self.rets.append(math.log(pc / self.last_prev_close))
        self.last_prev_close = pc
        self.day = bar["day"]
        self.U = self.L = self.sigma = None
        self.used = set()
        self.state = {"U": "fresh", "L": "fresh"}
        self.pos_info = None
        self.order_wall = None
        self.cur = {"h": bar["h"], "l": bar["l"], "c": bar["c"], "pc": pc}
        if pc is None:
            return
        if self.cell == "hv":
            if len(self.rets) < 20:
                return
            unit = pc * float(np.std(np.array(self.rets), ddof=1))
            U, L = pc + unit, pc - unit
        elif self.cell == "atr":
            if len(self.trs) < 20:
                return
            unit = float(np.mean(self.trs))
            U, L = pc + unit, pc - unit
        else:
            if len(self.trs) < 10 or self.closes < 20:
                return
            unit = float(np.mean(list(self.trs)[-10:]))
            U, L = self.ema + 2 * unit, self.ema - 2 * unit
        if not (L < bar["o"] < U):
            return
        self.U, self.L, self.sigma = U, L, unit
        self.unit_vs[self.day] = {"U": U, "L": L, "unit": unit, "pc": pc}

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._new_day(bar)
        else:
            self.cur["h"] = max(self.cur["h"], bar["h"])
            self.cur["l"] = min(self.cur["l"], bar["l"])
            self.cur["c"] = bar["c"]
        return super().on_bar(bar, pos)


def ev_for(product):
    return {m: importlib.import_module(f"{EVAL_PKG[product]}.{m}") for m in ("config", "costs", "criteria", "data", "engine", "twins")}


def pooled(dfs):
    df = pd.concat([d for d in dfs if len(d)], ignore_index=True)
    if not len(df):
        return None
    r = df.r_net.values
    rng = np.random.default_rng(0)
    bs = [rng.choice(r, len(r)).mean() for _ in range(4000)]
    yrs = df.groupby(df.day.str[:4]).agg(n=("r_net", "size"), r=("r_net", "mean"), usd=("usd_1mnq", "sum"))
    return {"n": len(df), "r": float(r.mean()), "gross_r": float(df.r_gross.mean()), "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "usd": float(df.usd_1mnq.sum()), "pos_years": int((yrs.r > 0).sum()), "years": len(yrs),
            "long_r": float(df.r_net[df.side == "long"].mean()), "short_r": float(df.r_net[df.side == "short"].mean()),
            "by_year": {y: {"n": int(v.n), "r": float(v.r), "usd": float(v.usd)} for y, v in yrs.iterrows()}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg": json.loads(PREREG.read_text()), "products": {}}
    for product in ("NQ", "ES"):
        ev = ev_for(product)
        assert ev["config"].PRODUCT == product
        vd, vv = load_vol(VOL_CSV[product])
        res = {c: {} for c in CELLS + ("ivwall",)}
        frames = {c: [] for c in res}
        for split in SPLITS:
            warm, trade = ev["data"].load_split(split)
            split_frames = {}
            for cell in CELLS + ("ivwall",):
                strat = IVGrid("touch", "fixed", 0.4, vd, vv) if cell == "ivwall" else VolBand(cell)
                tr, base, m = run_one(ev, warm, trade, strat, 1)
                df = trade_frame(tr, base)
                df.to_csv(OUT / f"trades_{product}_{cell}_{split}.csv", index=False)
                frames[cell].append(df)
                split_frames[cell] = df
                if m is not None and cell != "ivwall" and strat.unit_vs:
                    u = pd.DataFrame(strat.unit_vs.values())
                    m["band_half_width_pct_median"] = float((((u.U - u.L) / 2) / u.pc).median())
                res[cell][split] = m
                if m:
                    print(f"{product} {split} {cell}: n={m['trades']} R={m['mean_r_base']:+.3f} gross={m['gross_r']:+.3f} "
                          f"CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] stress={m['mean_r_stress']:+.3f} "
                          f"p={m['twin']['p']:.4f} L {m['long']['r']} S {m['short']['r']}", flush=True)
            iv = split_frames["ivwall"]
            ivkey = set(zip(iv.day, iv.side)) if len(iv) else set()
            for cell in CELLS:
                df, m = split_frames[cell], res[cell][split]
                if m is not None and len(df):
                    key = set(zip(df.day, df.side))
                    m["overlap_ivwall"] = {"same_day_side": len(key & ivkey), "jaccard": len(key & ivkey) / max(1, len(key | ivkey))}
        for cell in res:
            res[cell]["pooled"] = pooled(frames[cell])
            p = res[cell]["pooled"]
            if p:
                print(f"{product} POOLED {cell}: n={p['n']} R={p['r']:+.3f} CI[{p['ci'][0]:+.3f},{p['ci'][1]:+.3f}] "
                      f"usd={p['usd']:+.0f} pos_years {p['pos_years']}/{p['years']}", flush=True)
        out["products"][product] = res
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
