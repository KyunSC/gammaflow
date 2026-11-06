"""Every Lucid plan (Flex / Pro / Daily / Direct x 25K-150K, mandatory daily loss limit) on the frozen NQ IV-wall break's
spent val2 trades (2022-01 -> 2026-08), against a random-direction baseline. Information only: no new data is read.

Same method as iv_wall_lucid.py: MNQ = floor($risk / stop $), one equity point per trade plus flat sessions,
flybrain.prop.run_prop bootstrap (5-day blocks). Each plan is run at every risk level in RISKS up to 80% of its max
loss. The baseline keeps entries, stops and targets and flips each trade's side by coin (SEEDS seeds).
EV is per account at list price; EV at the usual coupon adds promoPct x price (one-time fees, no rebill).
LucidDaily's +/-1 min news flat is not modelled.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_lucid_plans.py [--paths 2000] [--seeds 20]

Output: data/iv_wall/lucid_plans.json
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import numpy as np

from flybrain.prop import _plans, run_prop
from iv_wall_grid import IVGrid, OUT, VOL_CSV, _ev
from iv_wall_lucid import CAPITAL, series
from iv_wall_study import load_vol

RISKS = (300, 400, 500, 700, 1050, 1550, 2100, 3000)
PLANS = ("flex", "pro", "daily", "direct")
SIZES = ("25k", "50k", "100k", "150k")
_STATE = {}


def _init():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    warm, trade = ev["data"].load_split("val2")
    tr = ev["engine"].run(warm, trade, IVGrid("touch", "fixed", 0.4, vd, vv))["trades"]
    longs = [ev["twins"]._one(trade[t["si"]], t, 1) for t in tr]
    shorts = [ev["twins"]._one(trade[t["si"]], t, -1) for t in tr]
    _STATE.update(trade=trade, tr=tr, real=ev["costs"].apply(tr, "base")["usd"], longs=longs, shorts=shorts,
                  ul=ev["costs"].apply(longs, "base")["usd"], us=ev["costs"].apply(shorts, "base")["usd"])


def _sim(trades, usd, risk, plan, paths, seed):
    res, time, n = series(_STATE["trade"], trades, usd, risk)
    # The day table is P&L relative to CAPITAL; run_stage starts each account at plan["startBalance"] itself.
    b = run_prop(res, time, plan=plan, initial_capital=CAPITAL, paths=paths, seed=seed,
                 keep_attempts=False, replay_history=False)["bootstrap"]
    return {k: float(b[k]) for k in ("ev", "passRate", "pPayout", "meanTake", "meanPayouts", "medianDaysToPass",
                                     "meanDaysUsed", "evP05", "evP50", "evP95")}


def job(args):
    plan, risk, paths, seeds = args
    if not _STATE:
        _init()
    S = _STATE
    real = _sim(S["tr"], S["real"], risk, plan, paths, 42)
    coin = []
    for s in range(1, seeds + 1):
        c = np.random.default_rng(s).random(len(S["tr"])) < 0.5
        tw = [a if k else z for k, a, z in zip(c, S["longs"], S["shorts"])]
        coin.append(_sim(tw, np.where(c, S["ul"], S["us"]), risk, plan, paths, 42 + s))
    agg = {k: float(np.mean([x[k] for x in coin])) for k in coin[0]}
    agg["ev_sd"] = float(np.std([x["ev"] for x in coin], ddof=1))
    return {"plan": plan["plan"], "size": plan["size"], "risk": risk, "real": real, "coin": agg}


def main(paths: int, seeds: int):
    plans = [p for p in _plans() if p["firm"] == "lucid" and p["dll"]]
    jobs = []
    for p in plans:
        p = dict(p)
        for r in RISKS:
            if r <= 0.8 * p["maxLoss"]:
                jobs.append((p, r, paths, seeds))
    print(f"{len(jobs)} plan x risk cells, {seeds} coin seeds, {paths} paths", flush=True)
    rows = []
    with ProcessPoolExecutor() as ex:
        for row in ex.map(job, jobs):
            rows.append(row)
            print(f"{row['plan']:6s} {row['size']:5s} ${row['risk']:5d}: real EV {row['real']['ev']:+6.0f} "
                  f"pass {row['real']['passRate']:.0%}  coin EV {row['coin']['ev']:+6.0f}  "
                  f"edge {row['real']['ev'] - row['coin']['ev']:+6.0f}", flush=True)
    meta = {f"{p['plan']}|{p['size']}": {k: p[k] for k in ("price", "promoPct", "maxLoss", "dailyLossLimit", "profitTarget",
                                                             "hasEval", "fundedDrawdown", "maxPayouts")} for p in plans}
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "paths": paths, "seeds": seeds, "risks": RISKS,
           "plans": meta, "rows": rows}
    (OUT / "lucid_plans.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args()
    main(a.paths, a.seeds)
