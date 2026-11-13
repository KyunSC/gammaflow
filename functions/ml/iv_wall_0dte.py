"""IV-wall break with the VXN-implied move swapped for a QQQ 0DTE-implied move (prereg iv_wall_0dte_prereg.json).
INFO ONLY: NQ val2 is spent for the IV-wall family.

    cd functions/ml && .venv/bin/python -B iv_wall_0dte.py

Output: data/iv_wall_0dte/{straddles.csv, results.json, trades_<cell>_<window>.csv}.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from gex0dte_wall_break import ev_mods, run_one, trade_frame
from iv_wall_grid import IVGrid
from iv_wall_study import ML, VOL_CSV, load_vol

OUT = ML / "data" / "iv_wall_0dte"
IV5 = ML / "data" / "thetadata" / "iv_5m" / "symbol=QQQ"
PREREG = ML / "iv_wall_0dte_prereg.json"
MAIN = (date(2023, 1, 1), date(2026, 8, 15))
FRESH = (date(2026, 8, 17), date(2026, 9, 26))
SNAP_MOD = 9 * 60 + 35
K_ABS = math.sqrt(2 / math.pi)   # E|X| / sigma for a normal move
CELLS = ("blend", "pure", "vxn_late")


def straddle_0935(day: str) -> dict | None:
    p = IV5 / f"date={day}"
    if not p.exists():
        return None
    d = pd.read_parquet(p, columns=["expiration", "strike", "right", "timestamp", "bid", "ask", "midpoint", "underlying_price"])
    d = d[(d.expiration.astype(str) == day) & (d.timestamp.dt.hour * 60 + d.timestamp.dt.minute == SNAP_MOD)]
    d = d[(d.bid > 0) & (d.ask > d.bid)]
    if d.empty:
        return None
    S = float(d.underlying_price.dropna().iloc[0])
    pv = d.pivot_table(index="strike", columns="right", values="midpoint", aggfunc="first").dropna()
    if not {"CALL", "PUT"} <= set(pv.columns) or pv.empty:
        return None
    st = (pv["CALL"] + pv["PUT"]).sort_index()
    ks = st.index.values
    lo, hi = ks[ks <= S], ks[ks >= S]
    if len(lo) and len(hi) and lo[-1] != hi[0]:
        k0, k1 = lo[-1], hi[0]
        strad = st[k0] + (st[k1] - st[k0]) * (S - k0) / (k1 - k0)
    else:
        strad = float(st.iloc[np.argmin(np.abs(ks - S))])
    return {"day": day, "qqq": S, "straddle": float(strad), "move_pct": float(strad / K_ABS / S)}


class ZeroDteWall(IVGrid):
    """Frozen IVGrid touch/fixed/0.4; walls (re)set at the decision of the bar starting 09:35."""

    def __init__(self, cell, strad: dict, vd, vv):
        super().__init__("touch", "fixed", 0.4, vd, vv)
        self.cell, self.strad = cell, strad
        self.meta0 = {}

    def _new_day(self, bar):
        super()._new_day(bar)          # VXN walls, HV, state reset; U is None if the VXN band is not available
        self.vxn = (self.U, self.L, self.sigma) if self.U is not None else None
        self.hv = None
        if len(self.rets) >= 20 and bar["prev_close"] is not None:
            self.hv = bar["prev_close"] * float(np.std(np.array(self.rets), ddof=1))
        self.pc, self.open = bar["prev_close"], bar["o"]
        self.U = self.L = self.sigma = None   # nothing until 09:35
        self.pending = True

    def _activate(self, bar):
        self.pending = False
        sd = self.strad.get(self.day)
        if sd is None:
            return
        if self.cell == "vxn_late":
            if self.vxn:
                self.U, self.L, self.sigma = self.vxn
            return
        nq0 = bar["o"]                       # = close of the 09:30-09:35 bar
        s0 = sd["move_pct"] * nq0
        if self.cell == "pure":
            self.U, self.L, self.sigma = nq0 + s0, nq0 - s0, s0
        else:
            if self.hv is None or self.pc is None:
                return
            sig = 0.5 * (s0 + self.hv)
            U, L = self.pc + sig, self.pc - sig
            if not (L < self.open < U):
                return
            self.U, self.L, self.sigma = U, L, sig
        self.meta0[self.day] = {"sigma": self.sigma, "s0": s0, "vxn_sigma": self.vxn[2] if self.vxn else None}

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._new_day(bar)
        if self.pending and bar["mod"] >= SNAP_MOD:
            self._activate(bar)
        return super().on_bar(bar, pos)


def split_window(ev, lo, hi, val2=None):
    if val2 is not None:
        warm2, trade2 = val2
        allss = warm2 + trade2
    else:
        allss = ev["data"].load_window(lo - timedelta(days=60), hi)
    i0 = next(i for i, s in enumerate(allss) if s.day >= lo)
    trade = [s for s in allss[i0:] if s.day < hi]
    return allss[max(0, i0 - 20):i0], trade


def by_year(df):
    return {y: {"n": len(g), "r": float(g.r_net.mean()), "usd": float(g.usd_1mnq.sum())}
            for y, g in df.groupby(df.day.str[:4])}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = json.loads(PREREG.read_text())
    ev = ev_mods()
    vd, vv = load_vol(VOL_CSV["NQ"])
    val2 = ev["data"].load_split("val2")
    windows = {"main": split_window(ev, *MAIN, val2=val2), "fresh": split_window(ev, *FRESH)}
    days = sorted({s.day.isoformat() for w in windows.values() for s in w[1]})
    rows = [r for r in (straddle_0935(d) for d in days) if r]
    sdf = pd.DataFrame(rows)
    sdf.to_csv(OUT / "straddles.csv", index=False)
    strad = {r["day"]: r for r in rows}
    print(f"straddles: {len(strad)}/{len(days)} sessions, median move {sdf.move_pct.median():.4%}", flush=True)
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg": spec, "windows": {}}
    for wname, (warm, trade) in windows.items():
        res = {"sessions": len(trade), "first": trade[0].day.isoformat(), "last": trade[-1].day.isoformat(),
               "sessions_with_straddle": sum(s.day.isoformat() in strad for s in trade)}
        frames = {}
        for cell in CELLS + ("ivwall",):
            strat = IVGrid("touch", "fixed", 0.4, vd, vv) if cell == "ivwall" else ZeroDteWall(cell, strad, vd, vv)
            tr, base, m = run_one(ev, warm, trade, strat, 1)
            df = trade_frame(tr, base)
            df.to_csv(OUT / f"trades_{cell}_{wname}.csv", index=False)
            frames[cell] = df
            if m is not None:
                m["by_year"] = by_year(df)
                if cell != "ivwall" and strat.meta0:
                    md = pd.DataFrame(strat.meta0.values()).dropna()
                    if len(md):
                        m["s0_over_vxn_sigma_median"] = float((md.s0 / md.vxn_sigma).median())
                        m["s0_vs_vxn_sigma_corr"] = float(np.corrcoef(md.s0, md.vxn_sigma)[0, 1])
                        m["band_days"] = len(strat.meta0)
                print(f"{wname} {cell}: n={m['trades']} R={m['mean_r_base']:+.3f} gross={m['gross_r']:+.3f} "
                      f"CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] stress={m['mean_r_stress']:+.3f} "
                      f"p={m['twin']['p']:.4f} $={m['total_usd'] if 'total_usd' in m else float(df.usd_1mnq.sum()):.0f} "
                      f"L {m['long']} S {m['short']}", flush=True)
            res[cell] = m
        iv = frames["ivwall"]
        if len(iv):
            ivkey = set(zip(iv.day, iv.side))
            ivday = iv.groupby("day").usd_1mnq.sum()
            for cell in CELLS:
                df = frames[cell]
                if not len(df) or res[cell] is None:
                    continue
                key = set(zip(df.day, df.side))
                cd = df.groupby("day").usd_1mnq.sum()
                diff = cd.reindex(cd.index.union(ivday.index), fill_value=0) - ivday.reindex(cd.index.union(ivday.index), fill_value=0)
                res[cell]["vs_ivwall"] = {"same_day_side": len(key & ivkey), "jaccard": len(key & ivkey) / len(key | ivkey),
                                          "usd_diff_total": float(diff.sum()),
                                          "usd_diff_ci": [float(x) for x in np.percentile(
                                              [np.random.default_rng(i).choice(diff.values, len(diff)).sum() for i in range(2000)], [2.5, 97.5])]}
        out["windows"][wname] = res
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
