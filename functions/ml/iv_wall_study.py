"""IV-wall fade (prereg iv_wall_prereg.json): fade the first test of prior close +/- 1 sigma on ES/NQ, where sigma
blends the VIX/VXN-implied daily move with 20-day historical vol. Tight stop beyond the wall, 2R target.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_study.py --product ES|NQ
    cd functions/ml && ../../.venv/bin/python -B iv_wall_study.py --mode break --split val1 --product ES|NQ

--mode break (iv_wall_break_prereg.json) trades through the wall instead: stop entry at the wall, stop back inside.

Runs the frozen research_loop (ES) / research_loop_nq (NQ) evaluator on the dev split only, one look per product.
Outputs go to data/iv_wall/ (gitignored).
"""
from __future__ import annotations

import argparse
import bisect
import importlib
import json
import math
from collections import deque
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ML = Path(__file__).resolve().parent
OUT = ML / "data" / "iv_wall"
PREREG = {"fade": ML / "iv_wall_prereg.json", "break": ML / "iv_wall_break_prereg.json"}
VOL_CSV = {"ES": ML / "data" / "research_loop_volsig" / "cboe" / "VIX_History.csv",
           "NQ": OUT / "cboe" / "VXN_History.csv"}
EVAL_PKG = {"ES": "research_loop.eval", "NQ": "research_loop_nq.eval"}


def load_vol(path: Path) -> tuple[list[date], list[float]]:
    df = pd.read_csv(path)
    df["d"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y").dt.date
    df = df.dropna(subset=["CLOSE"]).sort_values("d")
    return list(df["d"]), [float(x) for x in df["CLOSE"]]


class IVWall:
    """Causal: sigma uses the vol-index close dated before the session and HV from completed sessions only."""

    def __init__(self, s: float, k: float, target_r: float, vol_days, vol_vals, first_slot=0, last_slot=71,
                 mode: str = "fade"):
        assert mode in ("fade", "break")
        self.mode = mode
        self.s, self.k, self.tr = s, k, target_r
        self.vd, self.vv = vol_days, vol_vals
        self.first_slot, self.last_slot = first_slot, last_slot
        self.rets: deque = deque(maxlen=20)
        self.day = None
        self.last_prev_close = None
        self.U = self.L = self.sigma = None
        self.used = set()
        self.meta = {}  # day -> {"sigma", "sigma_iv", "sigma_hv", "idx"}

    def _new_day(self, bar):
        pc = bar["prev_close"]
        if pc is not None and self.last_prev_close is not None:
            self.rets.append(math.log(pc / self.last_prev_close))
        self.last_prev_close = pc
        self.day = bar["day"]
        self.U = self.L = self.sigma = None
        self.used = set()
        if pc is None or len(self.rets) < 20:
            return
        d = date.fromisoformat(bar["day"])
        i = bisect.bisect_left(self.vd, d) - 1
        if i < 0 or (d - self.vd[i]).days > 7:
            return
        idx = self.vv[i]
        s_iv = pc * idx / 100.0 / math.sqrt(252)
        s_hv = pc * float(np.std(np.array(self.rets), ddof=1))
        sig = 0.5 * (s_iv + s_hv)
        U, L = pc + self.k * sig, pc - self.k * sig
        if not (L < bar["o"] < U):  # opened outside the band
            return
        self.U, self.L, self.sigma = U, L, sig
        self.meta[bar["day"]] = {"sigma": sig, "sigma_iv": s_iv, "sigma_hv": s_hv, "idx": idx, "pc": pc}

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._new_day(bar)
        if self.U is None:
            return None
        if bar["h"] >= self.U:
            self.used.add("U")
        if bar["l"] <= self.L:
            self.used.add("L")
        if pos is not None or not (self.first_slot <= bar["slot"] <= self.last_slot):
            return None
        c, risk = bar["c"], self.s * self.sigma
        cands = []
        if "U" not in self.used and c < self.U:
            cands.append((self.U - c, -1, self.U))
        if "L" not in self.used and c > self.L:
            cands.append((c - self.L, 1, self.L))
        if not cands:
            return None
        _, side, wall = min(cands)
        if self.mode == "break":  # buy stop at U / sell stop at L, stop back inside the band
            side = -side
        return {"op": "enter", "side": side, "type": "limit" if self.mode == "fade" else "stop", "price": wall, "ttl": 1,
                "stop": wall - side * risk, "target": wall + side * self.tr * risk}


def run(product: str, mode: str = "fade", split: str = "dev") -> dict:
    spec = json.loads(PREREG[mode].read_text())
    g = spec["grid"]
    ev = {m: importlib.import_module(f"{EVAL_PKG[product]}.{m}") for m in ("config", "costs", "criteria", "data", "engine", "twins")}
    C = ev["config"]
    assert C.PRODUCT == product
    warm, trade = ev["data"].load_split(split)
    vd, vv = load_vol(VOL_CSV[product])
    sess = [s.day.isoformat() for s in trade]
    results = []
    for s in g["s"]:
        strat = IVWall(s, g["k"], g["target_r"], vd, vv, mode=mode)
        res = ev["engine"].run(warm, trade, strat)
        tr = res["trades"]
        base, stress = ev["costs"].apply(tr, "base"), ev["costs"].apply(tr, "stress")
        rl, rs = ev["twins"].long_short_r(trade, tr)
        tw = ev["twins"].twin_test(base["r"], rl, rs, sides=[t["side"] for t in tr])
        days = np.array([t["day"] for t in tr], dtype=object).astype(str)
        m = ev["criteria"].summarize(base["r"], base["usd"], stress["r"], days, sess, tw, len(g["s"]))
        risk = np.array([t["risk_pts"] for t in tr])
        gross = base["gross_pts"] / risk
        ok, why = ev["criteria"].gate(m, split)
        if mode == "break" and split != "dev" and not tw["p"] < 0.05 / len(g["s"]):
            ok, why = False, why + [f"twin p {tw['p']:.4f} >= Bonferroni {0.05 / len(g['s']):.4f}"]
        side = np.array([t["side"] for t in tr])
        idx = np.array([strat.meta[t["day"]]["idx"] for t in tr])
        terc = np.quantile(idx, [1 / 3, 2 / 3])
        extra = {
            "gross_r": float(gross.mean()), "cost_r": float((gross - base["r"]).mean()),
            "risk_pts_median": float(np.median(risk)),
            "exit_kinds": {k: int(sum(t["exit_kind"] == k for t in tr)) for k in ("stop", "target", "market", "flat")},
            "long": {"n": int((side > 0).sum()), "r": float(base["r"][side > 0].mean())},
            "short": {"n": int((side < 0).sum()), "r": float(base["r"][side < 0].mean())},
            "vol_tercile_r": [float(base["r"][(idx <= terc[0])].mean()),
                              float(base["r"][(idx > terc[0]) & (idx <= terc[1])].mean()),
                              float(base["r"][idx > terc[1]].mean())],
            "band_days": len(strat.meta), "sessions": len(sess),
            "touch_days": len(set(days)),
        }
        results.append({"s": s, "gate_pass": ok, "gate_fails": why, "metrics": m, "extra": extra})
        print(f"{mode} {product} {split} s={s}: n={m['trades']} R={m['mean_r_base']:+.3f} gross={extra['gross_r']:+.3f} "
              f"cost={extra['cost_r']:.3f} CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] "
              f"stress={m['mean_r_stress']:+.3f} twin p={tw['p']:.4f} win={m['win_rate']:.2f} "
              f"-> {'PASS' if ok else 'FAIL'}", flush=True)
    for i, r in enumerate(results):  # neighbour stability
        nb = [j for j in (i - 1, i + 1) if 0 <= j < len(results)]
        bad = [results[j]["s"] for j in nb if not results[j]["metrics"]["mean_r_base"] > 0]
        r["pass"] = r["gate_pass"] and not bad
        if bad:
            r["gate_fails"].append(f"neighbours not positive: {bad}")
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"product": product, "mode": mode, "split": split, "ran": datetime.now().isoformat(timespec="seconds"),
           "prereg": spec, "results": results}
    name = f"{product}_dev.json" if mode == "fade" and split == "dev" else f"{mode}_{product}_{split}.json"
    (OUT / name).write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", choices=["ES", "NQ"], required=True)
    ap.add_argument("--mode", choices=["fade", "break"], default="fade")
    ap.add_argument("--split", choices=["dev", "val1", "val2"], default="dev")
    a = ap.parse_args()
    run(a.product, a.mode, a.split)
