"""Every Lucid plan at today's contract size: the frozen NQ IV-wall break's spent val2 trades (2022-01 -> 2026-08), each
scaled to risk k x STOP_PER_MNQ dollars (k whole MNQ at today's stop, fractional contracts on the historical days), against
a random-direction baseline. Information only: no new data is read.

iv_wall_lucid_plans.py sized each trade by floor($budget / stop $) on 2022-26 stops (median ~$186 per MNQ), so small-stop
days traded 2+ MNQ for the same budget. Today 1 MNQ already risks ~$348, so this run fixes the dollar risk per trade at
what k MNQ costs now. Sizes above 80% of a plan's max loss are skipped. Same bootstrap (5-day blocks, 2000 paths) and
coin baseline (same entries/stops/targets, side by coin, SEEDS seeds) as iv_wall_lucid_plans.py.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_lucid_today.py [--stop 348] [--paths 2000] [--seeds 40]

Output: data/iv_wall/lucid_today.json
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import numpy as np

from flybrain.prop import _plans, run_prop
from iv_wall_grid import IVGrid, OUT, VOL_CSV, _ev
from iv_wall_lucid import CAPITAL, excursion
from iv_wall_study import load_vol

MNQ = (1, 2, 3, 4, 6, 8)
KEYS = ("ev", "passRate", "pPayout", "meanTake", "meanPayouts", "medianDaysToPass", "meanDaysUsed", "evP95")
_S = {}


def _init():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    warm, trade = ev["data"].load_split("val2")
    tr = ev["engine"].run(warm, trade, IVGrid("touch", "fixed", 0.4, vd, vv))["trades"]
    lg = [ev["twins"]._one(trade[t["si"]], t, 1) for t in tr]
    sh = [ev["twins"]._one(trade[t["si"]], t, -1) for t in tr]
    _S.update(trade=trade, tr=tr, real=ev["costs"].apply(tr, "base")["usd"], lg=lg, sh=sh,
              ul=ev["costs"].apply(lg, "base")["usd"], us=ev["costs"].apply(sh, "base")["usd"])


def series(trades, usd, risk):
    """Like iv_wall_lucid.series, but each trade carries risk / (risk_pts x $2) contracts (fixed dollar risk)."""
    by = {}
    for t, u in zip(trades, usd):
        by.setdefault(t["si"], []).append((t, u))
    eq = CAPITAL
    o = {k: [] for k in ("equity", "barLo", "barHi", "barOpen", "time")}
    for si, s in enumerate(_S["trade"]):
        rows = by.get(si)
        if not rows:
            o["time"].append(float(s.t[-1]))
            for k in ("equity", "barLo", "barHi", "barOpen"):
                o[k].append(eq)
            continue
        for t, u in rows:
            ct = risk / (t["risk_pts"] * 2.0)
            o["time"].append(float(s.t[t["j_exit"]]))
            o["barOpen"].append(eq)
            adv, fav = excursion(s, t)
            fee = u - 2.0 * (t["exit_ref"] - t["entry_ref"]) * t["side"]
            pnl = ct * u
            o["barLo"].append(eq + min(ct * (adv * 2.0 + fee), pnl, 0.0))
            o["barHi"].append(eq + max(ct * fav * 2.0, pnl, 0.0))
            eq += pnl
            o["equity"].append(eq)
    res = {k: np.array(v) for k, v in o.items() if k != "time"}
    res["initialCapital"] = CAPITAL
    return res, np.array(o["time"])


def _sim(trades, usd, risk, plan, paths, seed):
    res, time = series(trades, usd, risk)
    b = run_prop(res, time, plan=plan, initial_capital=CAPITAL, paths=paths, seed=seed,
                 keep_attempts=False, replay_history=False)["bootstrap"]
    return {k: float(b[k]) for k in KEYS}


def job(args):
    plan, k, risk, paths, seed = args
    if not _S:
        _init()
    if seed == 0:
        return plan["plan"], plan["size"], k, 0, _sim(_S["tr"], _S["real"], risk, plan, paths, 42)
    c = np.random.default_rng(seed).random(len(_S["tr"])) < 0.5
    tw = [a if x else z for x, a, z in zip(c, _S["lg"], _S["sh"])]
    return plan["plan"], plan["size"], k, seed, _sim(tw, np.where(c, _S["ul"], _S["us"]), risk, plan, paths, 42 + seed)


def main(stop: float, paths: int, seeds: int):
    plans = [dict(p) for p in _plans() if p["firm"] == "lucid" and p["dll"]]
    jobs = [(p, k, k * stop, paths, s) for p in plans for k in MNQ if k * stop <= 0.8 * p["maxLoss"]
            for s in range(seeds + 1)]
    print(f"{len(jobs) // (seeds + 1)} plan x size cells, {seeds} coin seeds, {paths} paths, ${stop:.0f} per MNQ", flush=True)
    cells = {}
    with ProcessPoolExecutor() as ex:
        for plan, size, k, seed, v in ex.map(job, jobs, chunksize=4):
            c = cells.setdefault((plan, size, k), {"plan": plan, "size": size, "mnq": k, "risk": k * stop, "coin_runs": []})
            if seed == 0:
                c["real"] = v
            else:
                c["coin_runs"].append(v)
    rows = []
    for c in cells.values():
        runs = c.pop("coin_runs")
        c["coin"] = {q: float(np.nanmean([r[q] for r in runs])) if not all(math.isnan(r[q]) for r in runs) else None
                     for q in KEYS}
        c["coin"]["ev_sd"] = float(np.std([r["ev"] for r in runs], ddof=1))
        rows.append(c)
        print(f"{c['plan']:6s} {c['size']:5s} {c['mnq']} MNQ: real EV {c['real']['ev']:+6.0f} pass {c['real']['passRate']:.0%} "
              f"coin EV {c['coin']['ev']:+6.0f}  edge {c['real']['ev'] - c['coin']['ev']:+6.0f}", flush=True)
    meta = {f"{p['plan']}|{p['size']}": {k: p[k] for k in ("price", "promoPct", "maxLoss", "dailyLossLimit", "profitTarget",
                                                             "hasEval", "fundedDrawdown", "maxPayouts")} for p in plans}
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "stop_per_mnq": stop, "paths": paths, "seeds": seeds,
           "mnq": MNQ, "plans": meta, "rows": rows}
    (OUT / "lucid_today.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", type=float, default=348.0)
    ap.add_argument("--paths", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=40)
    a = ap.parse_args()
    main(a.stop, a.paths, a.seeds)
