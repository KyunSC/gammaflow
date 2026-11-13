"""Step 4 driver: one plan on the real tape, coin-flip direction (rules frozen in data/prop_realtape/state.json
`step4_rules` before any result was seen).

  ../../.venv/bin/python prop_realtape/run_plan.py <plan id from state.json plans_queue> [--fee-mult 0.6 --tag promo40]

Outputs data/prop_realtape/results/<id>[_<tag>].json and prints a summary. Strategy-free: direction is a seeded
coin per calendar date, so no entry edge is tested and no validation window is spent.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

PKG = Path(__file__).resolve().parent
sys.path[:0] = [str(PKG), str(PKG.parent)]
import lucid_structure as L  # noqa: E402
import realdays as R  # noqa: E402
import replay as RP  # noqa: E402

HERE = PKG.parent
OUT = HERE / "data" / "prop_realtape"
ERAS = ("2011-18", "2019-21", "2022-26")
ENTRIES = ("0935", "1000", "1100", "1300")
RULES = ("fixed", "rel_atr", "rel_vix", "abs_atr", "abs_vix")
N_COIN, PATHS = 64, 2000                 # headline cell
N_COIN_GRID, PATHS_GRID = 16, 1000       # grid cells
WORKERS = 3
T63 = 1.998                              # t(0.975, 63); grid uses t(0.975, 15) = 2.131
T15 = 2.131

_G: dict = {}                            # tables shared with forked workers


APEX_FLAT = 16 * 60 + 59               # Apex closes 16:59 ET (step4_rules.flat_by)
APEX_EVAL_LIMIT = 21                   # apex_study.EVAL_LIMIT: 30 calendar days ~ 21 trading days, late = failed


def resolve(entry: dict):
    firm, name = entry["firm"], entry["plan"]
    rows = json.loads((HERE / entry["headline"]).read_text())
    if firm == "apex":                 # provisional rules, read-only from data/prop_structure/apex/apex_study.py
        import importlib.util
        spec = importlib.util.spec_from_file_location("apex_study", HERE / "data/prop_structure/apex/apex_study.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.EVAL_LIMIT == APEX_EVAL_LIMIT
        base, fees = mod.SETUPS[name]
        row = next(r for r in rows if r["setup"] == name and r["scheme"] == entry["scheme"])
        price, act = fees[entry["scheme"]]
        n = int(min(base["fundedStartMinis"] * 10, max(1, round(row["risk"] / 150))))      # apex_study.bracket
        plan = dict(base, flatByEt=APEX_FLAT, _apex=dict(price=price, activation=act, scheme=entry["scheme"],
                                                          alt={k: v for k, v in fees.items() if k != entry["scheme"]}))
        h = dict(plan=name, risk=row["risk"], stop_ticks=row["stop_ticks"], contracts=n, ev=row["ev"], ev_ci=row["ev_ci"],
                 pass_rate=row["pass_rate"], p_paid=row["p_paid"], days_used=row["days"], ev_per_day=row["ev"] / row["days"],
                 fee=row["cost"])
        return plan, h
    plan = next(p for p in L.all_plans(firm) if L.plan_name(p) == name)
    h = next(r for r in rows if r["plan"] == name)
    return plan, h


def cell_table(plan, h, product, entry, rule, k_abs=None):
    scheme = "fixed" if rule == "fixed" else rule.split("_")[1]
    P = R.load_day_paths(product, entry, scheme)
    dr = RP.day_results(P, h["risk"], h["contracts"], product, plan.get("commissionPerSide", L.COMM_SIDE),
                        plan.get("flatByEt") or RP.DEFAULT_FLAT, rule="fixed" if rule == "fixed" else rule[:3],
                        k_abs=k_abs, cap=RP.plan_cap(plan), mode=RP.compress_mode(plan))
    return P["days"], dr, RP.table_from_bars(dr["bars"])


def apex_summarize(done: list, plan: dict) -> dict:
    """apex_study.run + ev: an evaluation longer than EVAL_LIMIT days counts as failed (no take, no activation);
    EV = take - price - activation x pass rate."""
    ax = plan["_apex"]
    late = np.array([a["evalDays"] > APEX_EVAL_LIMIT for a in done])
    passed = np.array([a["outcome"] != "failed" for a in done]) & ~late
    take = np.where(late, 0.0, [a["take"] for a in done])
    paid = np.array([bool(a["payouts"]) for a in done]) & ~late
    days = np.array([min(a["daysUsed"], APEX_EVAL_LIMIT) if x else a["daysUsed"] for a, x in zip(done, late)], float)
    fee = ax["price"] + ax["activation"] * float(passed.mean())
    ev = float(take.mean()) - fee
    return dict(n=len(done), fee=fee, ev=ev, pass_rate=float(passed.mean()), p_paid=float(paid.mean()),
                mean_take=float(take.mean()), days_used=float(days.mean()), ev_per_day=ev / float(days.mean()),
                late=float(late.mean()))


def _job(args):
    key, kind, idx, seq, paths, seed, fee = args
    days, table, plan = _G[key]
    dates = days["date"].tolist()
    sides = np.zeros(len(dates), int) if seq < 0 else RP.coin_sides(dates, seq)
    gen = RP.block_seqs(idx, sides, paths, seed=seed) if kind == "boot" else RP.hist_seqs(idx, sides)
    done = RP.run(table, gen, plan)
    return apex_summarize(done, plan) if "_apex" in plan else RP.summarize(done, plan, fee)


def agg(rows, t):
    ev = np.array([r["ev"] for r in rows])
    m = lambda k: float(np.mean([r[k] for r in rows]))
    se = ev.std(ddof=1) / math.sqrt(len(ev)) if len(ev) > 1 else float("nan")
    return dict(ev=float(ev.mean()), ev_ci=[float(ev.mean() - t * se), float(ev.mean() + t * se)], ev_sd_across_coins=float(ev.std(ddof=1)) if len(ev) > 1 else None,
                pass_rate=m("pass_rate"), p_paid=m("p_paid"), mean_take=m("mean_take"), fee=m("fee"),
                days_used=m("days_used"), ev_per_day=float(ev.mean()) / m("days_used"), n_coins=len(rows), accounts=int(sum(r["n"] for r in rows)),
                **({"late": m("late")} if "late" in rows[0] else {}))


def era_idx(days, era):
    if era == "pooled":
        return np.flatnonzero(days["era"].isin(ERAS).to_numpy())
    return np.flatnonzero((days["era"] == era).to_numpy())


def run_cell(pool, key, days, eras, n_coin, paths, fee, t, hist=False, long_line=True, mask=None):
    out = {}
    for era in eras:
        idx = era_idx(days, era)
        if mask is not None:
            idx = idx[mask[idx]]                      # schemes compared on the common valid-day set
        jobs = [(key, "boot", idx, s, paths, 1000 + s, fee) for s in range(n_coin)]
        res = dict(boot=agg(pool.map(_job, jobs), t))
        if hist:
            res["hist"] = agg(pool.map(_job, [(key, "hist", idx, s, 0, 0, fee) for s in range(n_coin)]), t)
        if long_line:
            res["always_long_boot"] = _job((key, "boot", idx, -1, paths * 4, 999, fee))
            if hist:
                res["always_long_hist"] = _job((key, "hist", idx, -1, 0, 0, fee))
        out[era] = res
    return out


def exits(days, dr):
    o = {}
    for era in ERAS:
        m = (days["era"] == era).to_numpy()
        c = dr["code"][m]
        o[era] = dict(zip(("stop", "target", "flat"), (np.bincount(c.ravel(), minlength=3) / c.size).round(4).tolist()))
        o[era]["capped_share"] = float(dr["capped"][m].mean())
        o[era]["mean_risk"] = float(dr["risk"][m].mean())
        o[era]["mean_stop_ticks"] = float(dr["st"][m].mean())
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_id")
    ap.add_argument("--fee-mult", type=float, default=1.0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    state = json.loads((OUT / "state.json").read_text())
    entry = next(e for e in state["plans_queue"] if e["id"] == a.plan_id)
    plan, h = resolve(entry)
    fee = (plan["_apex"]["price"] if "_apex" in plan else L.fee_of(plan)) * a.fee_mult
    if a.fee_mult != 1.0:
        plan = dict(plan, price=plan["price"] * a.fee_mult)
    t0 = time.time()
    res = dict(plan_id=a.plan_id, plan=entry["plan"], firm=entry["firm"], tag=a.tag or None, fee_mult=a.fee_mult,
               fee_flat=fee, synthetic=dict(ev=h["ev"], ev_ci=h["ev_ci"], pass_rate=h["pass_rate"], p_paid=h["p_paid"],
                                            days_used=h["days_used"], ev_per_day=h["ev_per_day"], fee=h["fee"]),
               risk=h["risk"], contracts=h["contracts"], cap=RP.plan_cap(plan), flat_by=plan.get("flatByEt") or RP.DEFAULT_FLAT,
               compress_mode=RP.compress_mode(plan), realdays_sha256=state["frozen"]["realdays_sha256"],
               rules=state["step4_rules"])
    # declared absolute-stop constants: st0 / median vol_ticks over 2022-26, per product and measure
    kabs = {}
    for prod in ("NQ", "ES"):
        st0 = RP.base_bracket(h["risk"], h["contracts"], prod)
        for meas in ("atr", "vix"):
            d = R.load_day_paths(prod, "0935", meas)["days"]
            kabs[f"{prod}_{meas}"] = round(st0 / float(d.loc[d["era"] == "2022-26", "vol_ticks"].median()), 2)
    res["k_abs"] = kabs

    ctx = mp.get_context("fork")
    # 1. headline cell: NQ, 09:35, fixed, 64 coins, bootstrap + historical, pooled + eras; ES alongside
    for prod in ("NQ", "ES"):
        days, dr, table = cell_table(plan, h, prod, "0935", "fixed")
        _G[(prod, "head")] = (days, table, plan)
        with ctx.Pool(WORKERS) as pool:
            res[f"headline_{prod}"] = run_cell(pool, (prod, "head"), days, ("pooled",) + ERAS, N_COIN, PATHS, fee, T63, hist=True)
        res[f"headline_{prod}"]["exits"] = exits(days, dr)
        print(f"[{time.time() - t0:5.0f}s] headline {prod}", {e: round(res[f'headline_{prod}'][e]['boot']['ev'], 1) for e in ("pooled",) + ERAS}, flush=True)
    # 2. grid: product x entry x rule, 16 coins, bootstrap, pooled + eras, common valid-day set
    grid = []
    for prod in ("NQ", "ES"):
        common = None
        for meas in ("atr", "vix"):
            d = R.load_day_paths(prod, "0935", meas)["days"]
            ok = set(d.loc[np.isfinite(d["vol_ticks"]) & np.isfinite(d["scale"]), "date"])
            common = ok if common is None else common & ok
        for ent in ENTRIES:
            for rule in RULES:
                kk = kabs[f"{prod}_{rule.split('_')[1]}"] if rule.startswith("abs") else None
                days, dr, table = cell_table(plan, h, prod, ent, rule, kk)
                keep = days["date"].isin(common).to_numpy()
                key = (prod, ent, rule)
                _G[key] = (days, table, plan)
                with ctx.Pool(WORKERS) as pool:
                    cell = run_cell(pool, key, days, ("pooled",) + ERAS, N_COIN_GRID, PATHS_GRID, fee, T15,
                                    long_line=(rule == "fixed"), mask=keep)
                _G.pop(key)
                ex = exits(days, dr)
                row = dict(product=prod, entry=ent, rule=rule, k_abs=kk, exits=ex,
                           **{era: {k: v for k, v in cell[era].items()} for era in cell})
                grid.append(row)
                print(f"[{time.time() - t0:5.0f}s] {prod} {ent} {rule:8s}",
                      {e: round(cell[e]['boot']['ev'], 1) for e in ("pooled",) + ERAS}, flush=True)
    res["grid"] = grid
    res["runtime_s"] = round(time.time() - t0, 1)
    (OUT / "results").mkdir(exist_ok=True)
    name = a.plan_id + (f"_{a.tag}" if a.tag else "")
    (OUT / "results" / f"{name}.json").write_text(json.dumps(res, indent=1, default=float))
    print("wrote", name, res["runtime_s"], "s")


if __name__ == "__main__":
    main()
