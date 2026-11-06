"""Lucid Flex 50K sizing for the frozen NQ IV-wall break (touch / fixed 2R / 0.4 sigma) on its spent val2 trades,
against a random-direction baseline. Information only: val2 2022-01 -> 2026-08 was already looked at once.

Each trade is sized to floor($risk / (risk_pts * $2)) MNQ (0 contracts -> skipped). The equity series has one point
per trade (with its intrabar worst/best from 1m bars, for the daily loss limit) plus one flat point per session with no
trade, and goes through flybrain.prop.run_prop. The baseline keeps every trade's entry, risk and target but takes a
50/50 random side per trade (the side's own stop/target outcome from research_loop_nq.eval.twins), 40 seeds: one
seed's mean R varies by ~0.04R, so a handful of seeds is not enough.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_lucid.py [--paths 2000]

Output: data/iv_wall/lucid_sizing.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import numpy as np

from flybrain.prop import resolve_plan, run_prop
from iv_wall_grid import IVGrid, OUT, VOL_CSV, _ev
from iv_wall_study import load_vol

RISKS = (300, 500, 700, 1050, 1550)
SEEDS = tuple(range(1, 41))
CAPITAL = 50000.0


def excursion(s, t) -> tuple[float, float]:
    """Worst and best open P&L in points (per contract, before costs) while the trade was on."""
    d, ref, j0, j1 = t["side"], t["entry_ref"], t["j_entry"], t["j_exit"]
    hi, lo = s.h[j0:j1 + 1], s.l[j0:j1 + 1]
    fav = (hi.max() - ref) if d > 0 else (ref - lo.min())
    adv = (lo.min() - ref) if d > 0 else (ref - hi.max())
    realized = d * (t["exit_ref"] - ref)
    # The exit bar can run past the fill; never count more than the stop distance (plus the realized slip) as risk.
    adv = max(adv, min(realized, -t["risk_pts"])) if t["exit_kind"] == "stop" else adv
    fav = min(fav, max(realized, 0.0)) if t["exit_kind"] == "target" else fav
    return float(min(adv, realized, 0.0)), float(max(fav, realized, 0.0))


def series(sessions, trades, usd_per_ct, risk_usd):
    """Equity points for run_prop: trades in order, plus a flat point on sessions with no trade."""
    by_si = {}
    for t, u in zip(trades, usd_per_ct):
        by_si.setdefault(t["si"], []).append((t, u))
    eq = CAPITAL
    out = {k: [] for k in ("equity", "barLo", "barHi", "barOpen", "time")}
    n_taken = 0
    for si, s in enumerate(sessions):
        rows = by_si.get(si)
        if not rows:
            out["time"].append(float(s.t[-1]))
            for k in ("equity", "barLo", "barHi", "barOpen"):
                out[k].append(eq)
            continue
        for t, u in rows:
            ct = int(risk_usd // (t["risk_pts"] * 2.0))
            out["time"].append(float(s.t[t["j_exit"]]))
            out["barOpen"].append(eq)
            if ct == 0:
                out["barLo"].append(eq), out["barHi"].append(eq), out["equity"].append(eq)
                continue
            n_taken += 1
            adv, fav = excursion(s, t)
            fee = u - 2.0 * (t["exit_ref"] - t["entry_ref"]) * t["side"]  # costs per contract (<= 0)
            pnl = ct * u
            out["barLo"].append(eq + min(ct * (adv * 2.0 + fee), pnl, 0.0))
            out["barHi"].append(eq + max(ct * fav * 2.0, pnl, 0.0))
            eq += pnl
            out["equity"].append(eq)
    res = {k: np.array(v) for k, v in out.items() if k != "time"}
    res["initialCapital"] = CAPITAL
    return res, np.array(out["time"]), n_taken


def lucid(sessions, trades, usd, risk_usd, plan, paths):
    res, time, n = series(sessions, trades, usd, risk_usd)
    r = run_prop(res, time, plan=plan, initial_capital=CAPITAL, paths=paths, keep_attempts=False)
    b, h = r["bootstrap"], r["historical"]
    return {"taken": n, "ev": b["ev"], "passRate": b["passRate"], "pPayout": b["pPayout"], "meanTake": b["meanTake"],
            "hist_ev": h["ev"], "hist_pass": h["passRate"], "cashPnl": r["cashPnl"]}


def main(paths: int):
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    warm, trade = ev["data"].load_split("val2")
    tr = ev["engine"].run(warm, trade, IVGrid("touch", "fixed", 0.4, vd, vv))["trades"]
    real = ev["costs"].apply(tr, "base")
    print(f"val2 trades {len(tr)}, mean R {real['r'].mean():+.3f}, sessions {len(trade)}", flush=True)
    # Twins: each trade taken long and taken short on its own stop/target (same entry, risk, target distance).
    longs = [ev["twins"]._one(trade[t["si"]], t, 1) for t in tr]
    shorts = [ev["twins"]._one(trade[t["si"]], t, -1) for t in tr]
    ul, us = ev["costs"].apply(longs, "base")["usd"], ev["costs"].apply(shorts, "base")["usd"]
    plan = resolve_plan("flex", "50k", True)
    rows = []
    for risk in RISKS:
        row = {"risk": risk, "real": lucid(trade, tr, real["usd"], risk, plan, paths), "coin": []}
        for seed in SEEDS:
            coin = np.random.default_rng(seed).random(len(tr)) < 0.5
            tw = [lg if c else sh for c, lg, sh in zip(coin, longs, shorts)]
            cu = np.where(coin, ul, us)
            row["coin"].append({**lucid(trade, tw, cu, risk, plan, paths), "seed": seed,
                                "mean_r": float(np.mean(cu / (2.0 * np.array([t["risk_pts"] for t in tr]))))})
        ce = np.array([c["ev"] for c in row["coin"]])
        row["coin_ev_mean"], row["coin_ev_sd"] = float(ce.mean()), float(ce.std(ddof=1))
        row["edge_ev"] = row["real"]["ev"] - row["coin_ev_mean"]
        row["coin_ev_ge_real"] = float((ce >= row["real"]["ev"]).mean())
        rows.append(row)
        print(f"${risk}: taken {row['real']['taken']}/{len(tr)}  real EV {row['real']['ev']:+.0f} "
              f"(pass {row['real']['passRate']:.0%}, payout {row['real']['pPayout']:.0%}, hist EV {row['real']['hist_ev']:+.0f})  "
              f"coin EV {row['coin_ev_mean']:+.0f} +/- {row['coin_ev_sd']:.0f} "
              f"(pass {np.mean([c['passRate'] for c in row['coin']]):.0%}, seeds >= real {row['coin_ev_ge_real']:.0%})  "
              f"edge adds {row['edge_ev']:+.0f}", flush=True)
    risk_pts = np.array([t["risk_pts"] for t in tr])
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "paths": paths, "plan": "lucid flex 50k dll",
           "price": plan["price"], "n_trades": len(tr), "mean_r": float(real["r"].mean()),
           "risk_usd_per_mnq": {"median": float(np.median(risk_pts) * 2), "p90": float(np.quantile(risk_pts, .9) * 2)},
           "coin_mean_r": float(np.mean([c["mean_r"] for c in rows[0]["coin"]])), "rows": rows}
    (OUT / "lucid_sizing.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=2000)
    main(ap.parse_args().paths)
