"""Apex 50K plans with the rules checked on Apex's own pages (2026-11-04), real tape plus synthetic.

  ../../.venv/bin/python prop_realtape/apex_verified.py [--sweep]

The rules, sources and read date are in data/prop_realtape/apex_verified/rules.json. Two Intraday PA rules differ
from apex_study.SETUPS: the PA has a tiered DLL, $1,000 at L1-L2, and its payouts use a $200 qualifying day and
caps 1500/2000/2500/2500/3000/3000. The EOD plan matches at L1-L2. At L3+ (profit >= $3,000) the DLL is $2,000 or
$3,000. flybrain.prop has one constant DLL, so L3+ is bracketed by a variant with a $2,000 PA DLL.

Read-only reuse. Plans come from run_plan.resolve (apex_study.SETUPS) and day tables from run_plan.cell_table
(realdays.load_day_paths, replay.day_results). EV uses run_plan.apex_summarize / agg (21-day eval limit, activation
on pass), and synthetic days come from lucid_structure.make_days / day_table. The only new glue is `sim_split`,
which is flybrain.prop.simulate_account with separate plan dicts for the eval and funded stages (needed for the
EOD bound, where the eval DLL stays $1,000). With one plan dict it is simulate_account line for line, and the
as_run parity checks below confirm it reproduces results/apex_*.json and apex/study.json exactly.

Strategy-free: date-keyed coin-flip direction, as in run_plan. No validation window is spent. At most 2 workers.
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
import replay as RP  # noqa: E402
import run_plan as RPL  # noqa: E402
from flybrain.prop import run_stage  # noqa: E402

HERE = PKG.parent
OUT = HERE / "data" / "prop_realtape" / "apex_verified"
WORKERS = 2
ERAS = ("pooled",) + RPL.ERAS

INTRADAY_PA = dict(minDayProfit=200, payoutCap=[1500, 2000, 2500, 2500, 3000, 3000])   # intraday_payouts page


def sim_split(days, next_day, plan, funded=None):
    """flybrain.prop.simulate_account, with an optional separate plan dict for the funded stage."""
    fplan = funded or plan
    out = dict(outcome=None, reason=None, evalDays=0, fundedDays=0, payouts=[], take=0, daysUsed=0, dllHits=0)
    k = 0
    if plan['hasEval']:
        ev = run_stage(days, next_day, 0, plan, 'eval'); out['evalDays'] = ev['days']; out['dllHits'] += ev['dllHits']; k = ev['days']
        if ev['status'] != 'passed':
            out.update(outcome='failed' if ev['status'] == 'breached' else 'eval-open', reason=ev['reason'], daysUsed=k)
            return out
    fu = run_stage(days, next_day, k, fplan, 'funded')
    out.update(fundedDays=fu['days'], dllHits=out['dllHits'] + fu['dllHits'], payouts=fu['payouts'],
               outcome='funded-breached' if fu['status'] == 'breached' else 'graduated' if fu['status'] == 'graduated' else 'funded-open',
               reason=fu['reason'], take=fplan['split'] * sum(fu['payouts']), daysUsed=k + fu['days'])
    return out


def run_accounts(table, seqs, plan, funded=None):
    """replay.run with sim_split."""
    done = []
    for seq in seqs:
        m = len(seq)
        a = sim_split(table, lambda k, s=seq, m=m: int(s[k]) if k < m else -1, plan, funded)
        if a["outcome"] != "eval-open":
            done.append(a)
    return done


def variants():
    state = json.loads((HERE / "data" / "prop_realtape" / "state.json").read_text())
    q = {e["id"]: e for e in state["plans_queue"]}
    eod, h_eod = RPL.resolve(q["apex_50k_eod_standard"])
    itd, h_itd = RPL.resolve(q["apex_50k_intraday_standard"])
    itd_pay = dict(itd, **INTRADAY_PA)
    return {
        "apex_50k_eod_standard": dict(h=h_eod, base_id="apex_50k_eod_standard", v={
            "as_run": (eod, None),                                             # = verified at L1-L2 (no rule differs)
            "bound_pa_dll_2000": (eod, dict(eod, dailyLossLimit=2000)),         # L3 DLL everywhere in the PA
        }),
        "apex_50k_intraday_standard": dict(h=h_itd, base_id="apex_50k_intraday_standard", v={
            "as_run": (itd, None),
            "payout_fix_only": (itd_pay, None),                                 # $200 day, verified caps, still no DLL
            "verified": (dict(itd_pay, dailyLossLimit=1000, dllFundedOnly=True), None),      # PA DLL L1-L2
            "bound_pa_dll_2000": (dict(itd_pay, dailyLossLimit=2000, dllFundedOnly=True), None),
        }),
    }


_G: dict = {}


def _job(args):
    key, kind, idx, seq, paths, seed = args
    days, table, plan, funded = _G[key]
    dates = days["date"].tolist()
    sides = np.zeros(len(dates), int) if seq < 0 else RP.coin_sides(dates, seq)
    gen = RP.block_seqs(idx, sides, paths, seed=seed) if kind == "boot" else RP.hist_seqs(idx, sides)
    return RPL.apex_summarize(run_accounts(table, gen, plan, funded), plan)


def headline(pool, key, days):
    """run_plan.run_cell for the headline cell (64 coins x 2000 paths, bootstrap + historical + always-long)."""
    out = {}
    for era in ERAS:
        idx = RPL.era_idx(days, era)
        res = dict(boot=RPL.agg(pool.map(_job, [(key, "boot", idx, s, RPL.PATHS, 1000 + s) for s in range(RPL.N_COIN)]), RPL.T63))
        res["hist"] = RPL.agg(pool.map(_job, [(key, "hist", idx, s, 0, 0) for s in range(RPL.N_COIN)]), RPL.T63)
        res["always_long_boot"] = _job((key, "boot", idx, -1, RPL.PATHS * 4, 999))
        res["always_long_hist"] = _job((key, "hist", idx, -1, 0, 0))
        out[era] = res
    return out


def _synth(args):
    """apex_study.run on one synthetic table (seed i), with sim_split."""
    plan, funded, risk, st, seed, rseed, paths = args
    d = L.make_days(40000, risk, st, 1.0, seed=seed, comm=plan["commissionPerSide"])
    days = L.day_table(d)
    rng = np.random.default_rng(rseed)
    done = []
    for _ in range(paths):
        draws = rng.integers(0, days["n"], 250)
        a = sim_split(days, lambda k: int(draws[k]) if k < 250 else -1, plan, funded)
        if a["outcome"] != "eval-open":
            done.append(a)
    s = RPL.apex_summarize(done, plan)
    return dict(take=s["mean_take"], pass_rate=s["pass_rate"], p_paid=s["p_paid"], late=s["late"], days=s["days_used"], ev=s["ev"])


def synthetic(pool, plan, funded, risk, st, n_tab=16, paths=25000):
    rows = pool.map(_synth, [(plan, funded, risk, st, 100 + i, 200 + i, paths) for i in range(n_tab)])
    e = np.array([r["ev"] for r in rows]); se = e.std(ddof=1) / math.sqrt(n_tab)
    m = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
    return dict(m, ev_ci=[float(e.mean() - 2.13 * se), float(e.mean() + 2.13 * se)], risk=risk, stop_ticks=st, tables=n_tab, paths=paths)


def sweep(pool, plan, funded):
    """apex_study's risk sweep (0.25-1.0x max loss, 20k paths, top 3 confirmed on 16 x 25k) for one plan."""
    def bracket(f):
        risk = f * plan["maxLoss"]
        n = int(min(plan["fundedStartMinis"] * 10, max(1, round(risk / 150))))
        st = max(40, round(risk / (n * L.TICK_USD)))
        return n * st * L.TICK_USD, st
    cands = sorted({bracket(f) for f in np.linspace(0.25, 1.0, 31)})
    sw = pool.map(_synth, [(plan, funded, r, s, 0, 1, 20000) for r, s in cands])
    top = sorted(zip(cands, sw), key=lambda x: -x[1]["ev"])[:3]
    conf = [synthetic(pool, plan, funded, r, s) for (r, s), _ in top]
    return dict(sweep=[dict(risk=r, stop_ticks=s, **x) for (r, s), x in zip(cands, sw)], confirmed=conf,
                best=max(conf, key=lambda c: c["ev"]))


def brief(cell):
    b = cell["boot"]
    return dict(ev=round(b["ev"], 1), ci=[round(x, 1) for x in b["ev_ci"]], pass_rate=round(b["pass_rate"], 4),
                p_paid=round(b["p_paid"], 4), late=round(b.get("late", 0), 4), days=round(b["days_used"], 2),
                fee=round(b["fee"], 2), hist=round(cell["hist"]["ev"], 1), long=round(cell["always_long_boot"]["ev"], 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="also re-optimise the synthetic risk for the corrected intraday plan")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ctx = mp.get_context("fork")
    res = dict(read_date="2026-11-04", rules="data/prop_realtape/apex_verified/rules.json", plans={})
    for pid, spec in variants().items():
        h = spec["h"]
        before = json.loads((HERE / "data" / "prop_realtape" / "results" / f"{spec['base_id']}.json").read_text())
        st = h["stop_ticks"]
        assert st == RP.base_bracket(h["risk"], h["contracts"], "NQ")
        pr = dict(risk=h["risk"], contracts=h["contracts"], stop_ticks_nq=st, variants={})
        for vname, (plan, funded) in spec["v"].items():
            vr = dict(compress_mode=RP.compress_mode(plan), funded_dll=(funded or plan)["dailyLossLimit"],
                      eval_dll=0 if plan.get("dllFundedOnly") else plan["dailyLossLimit"],
                      minDayProfit=(funded or plan)["minDayProfit"], payoutCap=(funded or plan)["payoutCap"])
            for prod in ("NQ", "ES"):
                days, dr, table = RPL.cell_table(plan, h, prod, "0935", "fixed")
                key = (pid, vname, prod)
                _G[key] = (days, table, plan, funded)
                with ctx.Pool(WORKERS) as pool:
                    vr[f"headline_{prod}"] = headline(pool, key, days)
                _G.pop(key)
                if vname == "as_run":                       # parity with run_plan's own result file
                    for era in ERAS:
                        for line in ("boot", "hist"):
                            x, y = vr[f"headline_{prod}"][era][line]["ev"], before[f"headline_{prod}"][era][line]["ev"]
                            assert abs(x - y) < 1e-6, (pid, prod, era, line, x, y)
                    vr.setdefault("parity", []).append(f"{prod}: boot+hist EV equal to results/{spec['base_id']}.json in all eras")
                print(f"[{time.time() - t0:5.0f}s] {pid} {vname:18s} {prod}",
                      {e: brief(vr[f'headline_{prod}'][e])["ev"] for e in ERAS}, flush=True)
            with ctx.Pool(WORKERS) as pool:
                vr["synthetic"] = synthetic(pool, plan, funded, h["risk"], st)
            if vname == "as_run":
                assert abs(vr["synthetic"]["ev"] - h["ev"]) < 1e-6, (pid, vr["synthetic"]["ev"], h["ev"])
                vr.setdefault("parity", []).append("synthetic EV equal to apex/study.json at the headline risk")
            print(f"[{time.time() - t0:5.0f}s] {pid} {vname:18s} synthetic {vr['synthetic']['ev']:+.1f} "
                  f"[{vr['synthetic']['ev_ci'][0]:+.1f}, {vr['synthetic']['ev_ci'][1]:+.1f}] pass {vr['synthetic']['pass_rate']:.3f} "
                  f"paid {vr['synthetic']['p_paid']:.3f}", flush=True)
            pr["variants"][vname] = vr
        res["plans"][pid] = pr
        (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    if a.sweep:
        spec = variants()["apex_50k_intraday_standard"]
        plan, funded = spec["v"]["verified"]
        with ctx.Pool(WORKERS) as pool:
            sw = sweep(pool, plan, funded)
        res["intraday_verified_sweep"] = sw
        b = sw["best"]
        print(f"[{time.time() - t0:5.0f}s] intraday verified sweep best risk {b['risk']} / {b['stop_ticks']}t EV {b['ev']:+.1f}", flush=True)
        h = spec["h"]
        if b["risk"] != h["risk"]:                          # real tape at the re-optimised risk too
            n = int(min(plan["fundedStartMinis"] * 10, max(1, round(b["risk"] / 150))))
            h2 = dict(h, risk=b["risk"], contracts=n)
            out = {}
            for prod in ("NQ", "ES"):
                days, dr, table = RPL.cell_table(plan, h2, prod, "0935", "fixed")
                key = ("itd_resized", prod)
                _G[key] = (days, table, plan, funded)
                with ctx.Pool(WORKERS) as pool:
                    out[f"headline_{prod}"] = headline(pool, key, days)
                _G.pop(key)
                print(f"[{time.time() - t0:5.0f}s] intraday verified @ {b['risk']} {prod}",
                      {e: brief(out[f'headline_{prod}'][e])["ev"] for e in ERAS}, flush=True)
            res["intraday_verified_resized"] = dict(risk=b["risk"], contracts=n, stop_ticks_nq=b["stop_ticks"], **out)
    res["runtime_s"] = round(time.time() - t0, 1)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    summary = {pid: {v: {p: {e: brief(x[f"headline_{p}"][e]) for e in ERAS} for p in ("NQ", "ES")} | {"synthetic": {k: round(x["synthetic"][k], 3) if isinstance(x["synthetic"][k], float) else x["synthetic"][k] for k in ("ev", "ev_ci", "pass_rate", "p_paid", "days")}}
                     for v, x in pr["variants"].items()} for pid, pr in res["plans"].items()}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print("wrote", OUT / "results.json", res["runtime_s"], "s")


if __name__ == "__main__":
    main()
