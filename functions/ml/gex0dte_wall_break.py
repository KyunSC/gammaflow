"""The frozen IV-wall break with the walls swapped for QQQ 0DTE GEX walls (prereg gex0dte_wall_break_prereg.json).

    cd functions/ml && ../../.venv/bin/python -B gex0dte_wall_break.py

Runs both cells (fixed / live walls) on NQ val2 2022-01..2026-08-14 with the frozen research_loop_nq evaluator, the
IV-wall break on the same sessions for comparison, and the fresh 2026-08-17..09-25 window and 2020-21 (both report only).
Output: data/gex0dte_wall/results.json (+ trades_<cell>_<window>.csv).
"""
from __future__ import annotations

import bisect
import importlib
import json
import math
from collections import deque
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from iv_wall_grid import IVGrid
from iv_wall_study import ML, VOL_CSV, load_vol

OUT = ML / "data" / "gex0dte_wall"
SNAPS = ML / "data" / "thetadata_gex" / "qqq_gex_snapshots_0dte.parquet"
# 2020-2021 built separately (thetadata_gex.py --expiries 0dte --start 2020-01-01 --end 2022-01-01 --out ...); QQQ had
# same-day expiries only on Fridays in 2020 and Mon/Wed/Fri from 2021, so most 2020-21 sessions have no walls (no trade)
SNAPS_PRE = ML / "data" / "thetadata_gex" / "qqq_gex_snapshots_0dte_2020_2021.parquet"
PREREG = ML / "gex0dte_wall_break_prereg.json"
ET = "America/New_York"
S, TARGET_R, LAST_SLOT, STALE = 0.4, 2.0, 71, 20
FIXED_LATEST_FIRST = 9 * 60 + 45   # "first usable snapshot (09:35)": allow a missing 09:35 print, not a late start
FRESH = (date(2026, 8, 17), date(2026, 9, 26))
PRE = (date(2020, 1, 1), date(2022, 1, 1))  # report only: before the 0DTE discovery window; NQ val1 (IV-wall tuning data)
CELLS = ("fixed", "live")


def load_snaps() -> dict[str, pd.DataFrame]:
    cols = ["computed_at", "spot", "call_wall", "put_wall", "net_gex"]
    g = pd.concat([pd.read_parquet(f, columns=cols) for f in (SNAPS_PRE, SNAPS) if f.exists()], ignore_index=True)
    et = g["computed_at"].dt.tz_convert(ET)
    g = g.assign(day=et.dt.strftime("%Y-%m-%d"), minute=et.dt.hour * 60 + et.dt.minute)
    g = g.dropna(subset=["spot"])
    return {d: x.sort_values("minute").reset_index(drop=True) for d, x in g.groupby("day")}


class GexWall:
    """Causal: sigma as IVWall (VXN close before the session, HV of completed sessions); a snapshot at minute m is
    used from the decision of the bar starting at m, converted with the NQ close of the bar ending at m."""

    def __init__(self, cell: str, snaps: dict, vol_days, vol_vals):
        assert cell in CELLS
        self.cell, self.snaps, self.vd, self.vv = cell, snaps, vol_days, vol_vals
        self.rets: deque = deque(maxlen=20)
        self.day = self.last_pc = None
        self.info = {}      # (day, side) -> order-time info of the trade's wall
        self.days = {}      # day -> {"sigma", "U0", "L0", "c0", "gamma0"}

    def _new_day(self, bar):
        pc = bar["prev_close"]
        if pc is not None and self.last_pc is not None:
            self.rets.append(math.log(pc / self.last_pc))
        self.last_pc = pc
        self.day = bar["day"]
        self.sigma = None
        self.snap = self.snaps.get(self.day)
        self.closes = {}                    # bar end minute -> NQ close
        self.state = {"U": "new", "L": "new"}   # new -> fresh | dead -> used
        self.rest = {}                      # wall resting during the next bar: side -> level
        self.fixed = None
        if pc is None or len(self.rets) < 20 or self.snap is None:
            return
        d = date.fromisoformat(self.day)
        i = bisect.bisect_left(self.vd, d) - 1
        if i < 0 or (d - self.vd[i]).days > 7:
            return
        s_iv = pc * self.vv[i] / 100.0 / math.sqrt(252)
        s_hv = pc * float(np.std(np.array(self.rets), ddof=1))
        self.sigma = 0.5 * (s_iv + s_hv)

    def _walls(self, mod):
        """(U, L, net_gex) in the NQ plane usable at the decision of the bar starting at mod, else None."""
        sn = self.snap
        if self.cell == "fixed":
            if self.fixed is None:
                r = sn.iloc[0]
                if r.minute > FIXED_LATEST_FIRST or r.minute > mod or r.minute not in self.closes:
                    return None
                k = self.closes[r.minute] / r.spot
                self.fixed = (r.call_wall * k, r.put_wall * k, r.net_gex)
            return self.fixed
        j = int(np.searchsorted(sn.minute.values, mod, side="right")) - 1
        if j < 0 or mod - sn.minute.iat[j] > STALE or sn.minute.iat[j] not in self.closes:
            return None
        r = sn.iloc[j]
        k = self.closes[r.minute] / r.spot
        return r.call_wall * k, r.put_wall * k, r.net_gex

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._new_day(bar)
        self.closes[bar["mod"] + 5] = bar["c"]
        if self.sigma is None:
            return None
        h, l, c = bar["h"], bar["l"], bar["c"]
        # a wall that rested during this bar (or was there while we were busy) and was traded through is used
        for w, lvl in self.rest.items():
            if self.state[w] == "fresh" and (h >= lvl if w == "U" else l <= lvl):
                self.state[w] = "used"
        self.rest = {}
        wl = self._walls(bar["mod"])
        if wl is None:
            return None
        U, L, ng = wl
        if not (np.isfinite(U) and np.isfinite(L)):
            return None
        if self.day not in self.days:
            self.days[self.day] = {"sigma": self.sigma, "U0": U, "L0": L, "c0": c, "gamma0": float(ng)}
        for w, lvl in (("U", U), ("L", L)):
            if self.state[w] == "new":
                self.state[w] = "fresh" if (c < lvl if w == "U" else c > lvl) else "dead"
            if self.state[w] == "fresh" and (c < lvl if w == "U" else c > lvl):
                self.rest[w] = lvl  # watched next bar whether or not it carries our order
        if pos is not None or not (1 <= bar["slot"] <= LAST_SLOT):
            return None
        cands = [(lvl - c if w == "U" else c - lvl, w, lvl) for w, lvl in self.rest.items()]
        if not cands:
            return None
        _, w, wall = min(cands)
        d = 1 if w == "U" else -1
        risk = S * self.sigma
        self.info[(self.day, d)] = {"wall": wall, "gamma": float(ng), "dist_sigma": abs(wall - c) / self.sigma,
                                    "U": U, "L": L}
        return {"op": "enter", "side": d, "type": "stop", "price": wall, "ttl": 1,
                "stop": wall - d * risk, "target": wall + d * TARGET_R * risk}


def ev_mods():
    return {m: importlib.import_module(f"research_loop_nq.eval.{m}") for m in ("config", "costs", "criteria", "data", "engine", "twins")}


def run_one(ev, warm, trade, strat, n_trials):
    tr = ev["engine"].run(warm, trade, strat)["trades"]
    sess = [s.day.isoformat() for s in trade]
    base, stress = ev["costs"].apply(tr, "base"), ev["costs"].apply(tr, "stress")
    if not tr:
        return tr, base, None
    rl, rs = ev["twins"].long_short_r(trade, tr)
    sides = np.array([t["side"] for t in tr])
    tw = ev["twins"].twin_test(base["r"], rl, rs, sides=list(sides))
    days = np.array([t["day"] for t in tr], dtype=object).astype(str)
    m = ev["criteria"].summarize(base["r"], base["usd"], stress["r"], days, sess, tw, n_trials)
    gross = base["gross_pts"] / np.array([t["risk_pts"] for t in tr])
    m.update({"gross_r": float(gross.mean()),
              "exit_kinds": {k: int(sum(t["exit_kind"] == k for t in tr)) for k in ("stop", "target", "market", "flat")},
              "long": {"n": int((sides > 0).sum()), "r": float(base["r"][sides > 0].mean()) if (sides > 0).any() else None},
              "short": {"n": int((sides < 0).sum()), "r": float(base["r"][sides < 0].mean()) if (sides < 0).any() else None},
              "coin_mean_r": float(((rl + rs) / 2).mean())})
    return tr, base, m


def trade_frame(tr, base, strat=None):
    rows = []
    for t, r, u, g in zip(tr, base["r"], base["usd"], base["gross_pts"]):
        x = {"day": t["day"], "side": "long" if t["side"] > 0 else "short", "entry_et": f"{t['entry_mod'] // 60:02d}:{t['entry_mod'] % 60:02d}",
             "entry": t["entry_ref"], "stop": t["stop_init"], "target": t["target"], "risk_pts": t["risk_pts"],
             "exit_et": f"{t['exit_mod'] // 60:02d}:{t['exit_mod'] % 60:02d}", "exit": t["exit_ref"], "exit_kind": t["exit_kind"],
             "r_gross": g / t["risk_pts"], "r_net": float(r), "usd_1mnq": float(u)}
        if strat is not None:
            i = strat.info.get((t["day"], t["side"]), {})
            x.update(gamma=i.get("gamma"), dist_sigma=i.get("dist_sigma"))
        rows.append(x)
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = json.loads(PREREG.read_text())
    ev = ev_mods()
    snaps = load_snaps()
    vd, vv = load_vol(VOL_CSV["NQ"])
    warm2, val2 = ev["data"].load_split("val2")
    fr_all = ev["data"].load_window(FRESH[0] - timedelta(days=60), FRESH[1])
    i0 = next(i for i, s in enumerate(fr_all) if s.day >= FRESH[0])
    pre_all = ev["data"].load_window(PRE[0] - timedelta(days=60), PRE[1])
    j0 = next(i for i, s in enumerate(pre_all) if s.day >= PRE[0])
    windows = {"pre2020_21": (pre_all[max(0, j0 - 20):j0], pre_all[j0:]),
               "val2": (warm2, val2), "fresh": (fr_all[max(0, i0 - 20):i0], fr_all[i0:])}
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg": spec, "windows": {}}
    for wname, (warm, trade) in windows.items():
        res = {"sessions": len(trade), "first": trade[0].day.isoformat(), "last": trade[-1].day.isoformat()}
        for cell in CELLS:
            strat = GexWall(cell, snaps, vd, vv)
            tr, base, m = run_one(ev, warm, trade, strat, len(CELLS))
            df = trade_frame(tr, base, strat)
            df.to_csv(OUT / f"trades_{cell}_{wname}.csv", index=False)
            if m is not None and wname == "val2":
                ok, why = ev["criteria"].gate(m, "val2")
                if not m["twin"]["p"] < 0.05 / len(CELLS):
                    ok, why = False, why + [f"twin p {m['twin']['p']:.4f} >= Bonferroni {0.05 / len(CELLS):.4f}"]
                m["gate_pass"], m["gate_fails"] = ok, why
            if m is not None and len(df):
                g = df["gamma"].astype(float)
                m["by_gamma"] = {k: {"n": int(mk.sum()), "r": float(df.r_net[mk].mean()) if mk.any() else None}
                                 for k, mk in (("pos", g > 0), ("neg", g <= 0))}
                m["by_side_gamma"] = {f"{sd}_{k}": {"n": int(mk.sum()), "r": float(df.r_net[mk].mean()) if mk.any() else None}
                                      for sd in ("long", "short") for k, mk in
                                      (("pos", (g > 0) & (df.side == sd)), ("neg", (g <= 0) & (df.side == sd)))}
                m["dist_sigma_median"] = float(df["dist_sigma"].median())
            dd = pd.DataFrame(strat.days.values())
            if len(dd):
                res.setdefault("walls", {})[cell] = {
                    "days_with_walls": len(dd),
                    "U_sigma_median": float(((dd.U0 - dd.c0) / dd.sigma).median()),
                    "L_sigma_median": float(((dd.c0 - dd.L0) / dd.sigma).median()),
                    "U_below_price_share": float((dd.U0 <= dd.c0).mean()), "L_above_price_share": float((dd.L0 >= dd.c0).mean())}
            res[cell] = m
            if m:
                print(f"{wname} {cell}: n={m['trades']} R={m['mean_r_base']:+.3f} gross={m['gross_r']:+.3f} "
                      f"CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] stress={m['mean_r_stress']:+.3f} "
                      f"p={m['twin']['p']:.4f} L {m['long']} S {m['short']} "
                      f"{'PASS' if m.get('gate_pass') else 'FAIL ' + str(m.get('gate_fails', ''))}", flush=True)
        iv = IVGrid("touch", "fixed", 0.4, vd, vv)
        tr, base, m = run_one(ev, warm, trade, iv, 1)
        ivdf = trade_frame(tr, base)
        ivdf.to_csv(OUT / f"trades_ivwall_{wname}.csv", index=False)
        res["ivwall"] = m
        exp_days = {s.day.isoformat() for s in trade} & set(snaps)
        res["sessions_with_0dte"] = len(exp_days)
        if len(ivdf):
            sub = ivdf[ivdf.day.isin(exp_days)]
            res["ivwall_on_0dte_days"] = {"n": len(sub), "r": float(sub.r_net.mean()) if len(sub) else None,
                                          "usd": float(sub.usd_1mnq.sum())}
        if m:
            print(f"{wname} ivwall: n={m['trades']} R={m['mean_r_base']:+.3f} p={m['twin']['p']:.4f}", flush=True)
        out["windows"][wname] = res
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
