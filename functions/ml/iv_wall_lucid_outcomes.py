"""What to expect to pay, win and lose on Lucid Flex at today's 1 MNQ: the spread of outcomes, not just the EV.
Spent val2 trades (2022-01 -> 2026-08) of the frozen NQ IV-wall break, each risking $348 (today's 1-MNQ stop; see
iv_wall_lucid_today.py). Information only: no new data is read.

Two views on the same 5-day block bootstrap as flybrain.prop.run_prop (250-session horizon):
  once  - buy one account; net = 90% of payouts - fee.
  year  - buy one; whenever it fails (eval breach, funded breach) or graduates, buy the next the following session,
          for 250 sessions. Net = all payouts - all fees. Open accounts at the end count only payouts taken.
Real directions vs random sides (same entries/stops/targets, side by coin; COIN_SEEDS seeds pooled).
Copied accounts share the same trades, so N copies = N x one account's outcome (the page scales it).
Also: drawdowns in dollars at 1 MNQ on the real trade sequence (max, one-year windows, losing streak).

    cd functions/ml && ../../.venv/bin/python -B iv_wall_lucid_outcomes.py [--paths 4000]

Output: data/iv_wall/lucid_outcomes.json
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import numpy as np

import iv_wall_lucid_today as T
from flybrain.prop import build_day_table, mulberry32, resolve_plan, simulate_account
from iv_wall_grid import OUT
from iv_wall_lucid import CAPITAL

STOP = 348.0
HORIZON, BLOCK = 250, 5
COIN_SEEDS = tuple(range(1, 11))
PLANS = (("flex", "50k", 1), ("flex", "25k", 1))
Q = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _paths(days, plan, paths, seed):
    """One-try and one-year outcomes per bootstrap path (same path drives both)."""
    rng = mulberry32(seed)
    n = days["n"]
    bl = max(1, min(BLOCK, n))
    once, year = [], []
    for _ in range(paths):
        seq = []

        def at(k):
            while len(seq) <= k:
                if len(seq) >= HORIZON:
                    return -1
                b = math.floor(rng() * max(1, n - bl + 1))
                for j in range(bl):
                    if len(seq) < HORIZON:
                        seq.append((b + j) % n)
            return seq[k]

        first = simulate_account(days, at, plan)
        once.append((first["take"], first["outcome"]))
        off, bought, take, a = 0, 0, 0.0, first
        while True:
            bought += 1
            take += a["take"]
            if a["outcome"] in ("eval-open", "funded-open"):
                break
            off += max(1, a["daysUsed"])
            if off >= HORIZON:
                break
            o = off
            a = simulate_account(days, lambda k, o=o: at(o + k), plan)
        year.append((take, bought))
    return once, year


def job(args):
    size, mnq, seed, paths = args
    if not T._S:
        T._init()
    S = T._S
    if seed == 0:
        res, time = T.series(S["tr"], S["real"], mnq * STOP)
    else:
        c = np.random.default_rng(seed).random(len(S["tr"])) < 0.5
        tw = [a if x else z for x, a, z in zip(c, S["lg"], S["sh"])]
        res, time = T.series(tw, np.where(c, S["ul"], S["us"]), mnq * STOP)
    days = build_day_table(res, time, CAPITAL)
    plan = resolve_plan("flex", size, True)
    once, year = _paths(days, plan, paths, 42 + seed)
    return size, mnq, seed, once, year, (res["equity"] if seed == 0 else None)


def summarize(once, year, price, credit):
    """Dollar outcomes at fee = price - credit."""
    fee = price - credit
    resolved = [(t, o) for t, o in once if o != "eval-open"]
    on = np.array([t - fee for t, _ in resolved])
    yt = np.array([t for t, _ in year])
    yb = np.array([b for _, b in year])
    yn = yt - yb * fee
    yf = yb * fee

    def dist(x):
        return {"mean": float(x.mean()), **{f"p{int(q * 100):02d}": float(np.quantile(x, q)) for q in Q},
                "pLoss": float((x < 0).mean()), "meanLossIfLoss": float(x[x < 0].mean()) if (x < 0).any() else 0.0,
                "meanWinIfWin": float(x[x > 0].mean()) if (x > 0).any() else 0.0}

    return {
        "fee": fee,
        "once": {**dist(on), "pNoPayout": float(np.mean([t <= 0 for t, _ in resolved])),
                 "pFailEval": float(np.mean([o == "failed" for _, o in resolved]))},
        "year": {**dist(yn), "fees": {"mean": float(yf.mean()), **{f"p{int(q * 100):02d}": float(np.quantile(yf, q)) for q in Q}},
                 "bought": {"mean": float(yb.mean()), "p50": float(np.median(yb)), "p90": float(np.quantile(yb, .9)),
                            "max": int(yb.max())},
                 "pAnyPayout": float((yt > 0).mean()),
                 "payouts": {"mean": float(yt.mean()), "p50": float(np.median(yt)), "p90": float(np.quantile(yt, .9))}},
    }


def drawdowns(equity, sessions_per_year=HORIZON):
    """Equity is one point per trade plus one per no-trade session; DD in dollars at the given size."""
    eq = np.asarray(equity, float)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    win = []
    for s in range(0, max(1, len(eq) - sessions_per_year), 5):
        w = eq[s:s + sessions_per_year]
        win.append(float((np.maximum.accumulate(w) - w).max()))
    d = np.diff(eq)
    trades = d[d != 0]
    streak = cur = 0
    for x in trades:
        cur = cur + 1 if x < 0 else 0
        streak = max(streak, cur)
    return {"max": float(dd.max()), "year_p50": float(np.median(win)), "year_p90": float(np.quantile(win, .9)),
            "year_max": float(max(win)), "longest_losing_streak": int(streak), "trades": int(len(trades))}


def main(paths: int):
    jobs = [(size, mnq, s, paths) for _, size, mnq in PLANS for s in (0, *COIN_SEEDS)]
    got = {}
    with ProcessPoolExecutor() as ex:
        for size, mnq, seed, once, year, eq in ex.map(job, jobs):
            g = got.setdefault((size, mnq), {"real": None, "coin_once": [], "coin_year": [], "eq": None})
            if seed == 0:
                g["real"], g["eq"] = (once, year), eq
            else:
                g["coin_once"] += once
                g["coin_year"] += year
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "stop_per_mnq": STOP, "paths": paths,
           "coin_seeds": len(COIN_SEEDS), "horizon": HORIZON, "plans": {}}
    for (size, mnq), g in got.items():
        plan = resolve_plan("flex", size, True)
        price, credit = plan["price"], plan["promoPct"] * plan["price"]
        row = {"price": price, "maxLoss": plan["maxLoss"], "mnq": mnq, "drawdown": drawdowns(g["eq"])}
        for label, cr in (("list", 0.0), ("coupon", credit)):
            row[label] = {"real": summarize(*g["real"], price, cr), "coin": summarize(g["coin_once"], g["coin_year"], price, cr)}
        out["plans"][f"flex|{size}|{mnq}"] = row
        r, c = row["list"]["real"], row["list"]["coin"]
        print(f"Flex {size} {mnq} MNQ  once: mean {r['once']['mean']:+.0f} (coin {c['once']['mean']:+.0f}) "
              f"p05 {r['once']['p05']:+.0f} p50 {r['once']['p50']:+.0f} p90 {r['once']['p90']:+.0f} p95 {r['once']['p95']:+.0f} "
              f"no payout {r['once']['pNoPayout']:.0%}", flush=True)
        print(f"   year: mean {r['year']['mean']:+.0f} (coin {c['year']['mean']:+.0f}) p05 {r['year']['p05']:+.0f} "
              f"p25 {r['year']['p25']:+.0f} p50 {r['year']['p50']:+.0f} p75 {r['year']['p75']:+.0f} p95 {r['year']['p95']:+.0f} "
              f"loss {r['year']['pLoss']:.0%} (coin {c['year']['pLoss']:.0%}); fees mean {r['year']['fees']['mean']:.0f} "
              f"p90 {r['year']['fees']['p90']:.0f}; bought p50 {r['year']['bought']['p50']:.0f} max {r['year']['bought']['max']}",
              flush=True)
        print(f"   drawdown at {mnq} MNQ: {row['drawdown']}", flush=True)
    (OUT / "lucid_outcomes.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=4000)
    main(ap.parse_args().paths)
