"""PROPOSAL driver: synthetic EV under lucid_structure.make_days (old) and giveback_synth (new), and the real NQ tape
(coin flip, 09:35, fixed bracket) for the plans the change touches. Writes data/prop_realtape/giveback/*.json only.

  ../../.venv/bin/python prop_realtape/proposals/run_giveback.py synth     # old vs new, 16 seeds x 25,000 paths
  ../../.venv/bin/python prop_realtape/proposals/run_giveback.py real      # real tape, 64 coins x 2,000 paths
  ../../.venv/bin/python prop_realtape/proposals/run_giveback.py laws      # excursion laws: analytic vs real

Strategy-free: no entry rule, no validation window. Read-only imports of lucid_structure, replay, run_plan, realdays.
At most 2 worker processes.
"""
from __future__ import annotations

import importlib.util
import json
import math
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

PROP = Path(__file__).resolve().parent
PKG = PROP.parent
ML = PKG.parent
sys.path[:0] = [str(PROP), str(PKG), str(ML)]
import giveback_synth as G  # noqa: E402
import lucid_structure as L  # noqa: E402
import realdays as R  # noqa: E402
import replay as RP  # noqa: E402
import run_plan as RPL  # noqa: E402

OUT = ML / "data" / "prop_realtape" / "giveback"
WORKERS = 2
SEEDS, PATHS = 16, 25000


def apex_module():
    spec = importlib.util.spec_from_file_location("apex_study", ML / "data/prop_structure/apex/apex_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cases():
    """(id, kind, plan, fee info, risk, stop ticks, role). Brackets = each plan's published synthetic headline."""
    A = apex_module()
    study = json.loads((ML / "data/prop_structure/apex/study.json").read_text())
    out = []
    for name, scheme, role in (("50K Intraday, Tradovate", "Standard coupon", "affected"),
                               ("50K Intraday, Rithmic", "Standard coupon", "affected"),
                               ("25K Intraday, Tradovate", "Standard coupon", "affected"),
                               ("25K Intraday, Rithmic", "Standard coupon", "affected"),
                               ("50K EOD, DLL $1,000", "Standard coupon (3rd-party)", "control"),
                               ("25K EOD, DLL $500", "Standard coupon", "control")):
        base, fees = A.SETUPS[name]
        row = next(r for r in study if r["setup"] == name and r["scheme"] == scheme)
        price, act = fees[scheme]
        out.append(dict(id=f"apex {name} / {scheme}", kind="apex", firm="apex", name=name, plan=base, price=price,
                        activation=act, risk=row["risk"], st=row["stop_ticks"], role=role, stored_ev=row["ev"]))

    def firm_rows(path):
        return json.loads((ML / path).read_text())
    src = {"lucid": firm_rows("data/prop_structure/lucid_headline.json") + firm_rows("data/prop_structure/lucid_daily_fixed.json"),
           "mff": firm_rows("data/prop_structure/mff/headline.json"),
           "topstep": firm_rows("data/prop_structure/topstep/headline.json"),
           "alpha": firm_rows("data/prop_structure/alpha/headline.json")}
    mff_conf = firm_rows("data/prop_structure/mff/confirm.json")
    for firm, name, role in (("lucid", "LucidDaily 25K", "affected"), ("lucid", "LucidDaily 50K", "affected"),
                             ("lucid", "LucidDaily 100K", "affected"), ("lucid", "LucidDaily 150K", "affected"),
                             ("mff", "Rapid 25K noDLL", "affected"), ("mff", "Rapid 50K noDLL", "affected"),
                             ("mff", "Rapid 100K noDLL", "affected"), ("mff", "Rapid 150K noDLL", "affected"),
                             ("topstep", "Cons no-fee 50K noDLL", "control"), ("lucid", "LucidFlex 50K", "control"),
                             ("alpha", "Standard 50K", "control"), ("mff", "Builder 50K", "control")):
        plan = next(p for p in L.all_plans(firm) if L.plan_name(p) == name)
        row = next((r for r in src[firm] if r["plan"] == name), None)
        stored = row["ev"] if row else None
        if row is None:                     # not in a headline (no risk under maxLoss): best confirm row
            row = max((r for r in mff_conf if r["plan"] == name), key=lambda r: r["ev"])
        out.append(dict(id=f"{firm} {name}", kind="firm", firm=firm, name=name, plan=plan, fee=L.fee_of(plan),
                        risk=row["risk"], st=row["stop_ticks"], role=role, stored_ev=stored))
    return out


# ------------------------------------------------------------------------------------------------ synthetic
def _synth_job(args):
    c, i, giveback, g_min = args
    if c["kind"] == "apex":
        r = G.apex_run(c["plan"], c["risk"], c["st"], 100 + i, 200 + i, PATHS, giveback=giveback, g_min=g_min)
        return dict(ev=r["take"] - c["price"] - c["activation"] * r["pass_rate"], pass_rate=r["pass_rate"],
                    p_paid=r["p_paid"], days_used=r["days"])
    r = G.score(c["plan"], c["fee"], c["risk"], c["st"], 1.0, paths=PATHS, seed=100 + i, rseed=200 + i,
                giveback=giveback, g_min=g_min)
    return dict(ev=r["ev"], pass_rate=r["pass_rate"], p_paid=r["p_paid"], days_used=r["days_used"])


def agg(rows, t=2.13):
    ev = np.array([r["ev"] for r in rows])
    se = ev.std(ddof=1) / math.sqrt(len(ev))
    m = lambda k: float(np.mean([r[k] for r in rows]))
    return dict(ev=float(ev.mean()), ev_ci=[float(ev.mean() - t * se), float(ev.mean() + t * se)], pass_rate=m("pass_rate"),
                p_paid=m("p_paid"), days_used=m("days_used"), seeds=len(rows), evs=ev.tolist())


def synth(g_min=G.G_MIN, only=None, tag=""):
    res = []
    t0 = time.time()
    with mp.get_context("fork").Pool(WORKERS) as pool:
        for c in cases():
            if only and not any(o in c["id"] for o in only):
                continue
            old = agg(pool.map(_synth_job, [(c, i, False, g_min) for i in range(SEEDS)]))
            new = agg(pool.map(_synth_job, [(c, i, True, g_min) for i in range(SEEDS)]))
            diff = np.array(new["evs"]) - np.array(old["evs"])          # paired by seed (same win/loss draws)
            row = dict(id=c["id"], role=c["role"], risk=c["risk"], stop_ticks=c["st"], mode=G.table_mode(c["plan"]),
                       dll=c["plan"].get("dailyLossLimit"), max_loss=c["plan"]["maxLoss"], stored_ev=c["stored_ev"], old=old,
                       new=new, diff=float(diff.mean()), diff_ci=[float(diff.mean() - 2.13 * diff.std(ddof=1) / 4),
                                                                   float(diff.mean() + 2.13 * diff.std(ddof=1) / 4)])
            res.append(row)
            print(f"[{time.time() - t0:5.0f}s] {c['id']:<52} {row['mode']:<4} old {old['ev']:+7.1f} (stored "
                  f"{c['stored_ev'] if c['stored_ev'] is None else round(c['stored_ev'], 1)}) new {new['ev']:+7.1f} "
                  f"diff {row['diff']:+6.1f} [{row['diff_ci'][0]:+.1f},{row['diff_ci'][1]:+.1f}]", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"synthetic{tag}.json").write_text(json.dumps(dict(g_min=g_min, seeds=SEEDS, paths=PATHS, rows=res), indent=1))


# ------------------------------------------------------------------------------------------------ real tape
_G: dict = {}


def _real_job(args):
    key, idx, seq, paths, seed, fee = args
    days, table, plan = _G[key]
    sides = RP.coin_sides(days["date"].tolist(), seq)
    done = RP.run(table, RP.block_seqs(idx, sides, paths, seed=seed), plan)
    return RPL.apex_summarize(done, plan) if "_apex" in plan else RP.summarize(done, plan, fee)


def real(only=None, eras=("2022-26", "2019-21")):
    """Same cell as run_plan's headline (NQ 09:35 fixed, 64 coins x 2,000 paths, block 20, seeds 1000+s)."""
    res = []
    t0 = time.time()
    P = R.load_day_paths("NQ", "0935", "fixed")
    for c in cases():
        if only and not any(o in c["id"] for o in only):
            continue
        plan = c["plan"]
        if c["kind"] == "apex":
            plan = dict(plan, flatByEt=RPL.APEX_FLAT, _apex=dict(price=c["price"], activation=c["activation"]))
            fee = c["price"]
        else:
            fee = c["fee"]
        n = int(min(L.MAX_CONTRACTS, max(1, math.floor(c["risk"] / (c["st"] * L.TICK_USD)))))
        if c["kind"] == "apex":
            n = int(min(plan["fundedStartMinis"] * 10, max(1, round(c["risk"] / 150))))
        dr = RP.day_results(P, c["risk"], n, "NQ", plan.get("commissionPerSide", L.COMM_SIDE),
                            plan.get("flatByEt") or RP.DEFAULT_FLAT, cap=RP.plan_cap(plan), mode=RP.compress_mode(plan))
        table = RP.table_from_bars(dr["bars"])
        _G[c["id"]] = (P["days"], table, plan)
        row = dict(id=c["id"], role=c["role"], contracts=n, stop_ticks=int(dr["st0"]), compress=RP.compress_mode(plan))
        with mp.get_context("fork").Pool(WORKERS) as pool:
            for era in eras:
                idx = RPL.era_idx(P["days"], era)
                rows = pool.map(_real_job, [(c["id"], idx, s, 2000, 1000 + s, fee) for s in range(64)])
                row[era] = RPL.agg(rows, RPL.T63)
        _G.pop(c["id"])
        res.append(row)
        print(f"[{time.time() - t0:5.0f}s] {c['id']:<52} n={n} st={row['stop_ticks']} " +
              " ".join(f"{e} {row[e]['ev']:+7.1f} [{row[e]['ev_ci'][0]:+.0f},{row[e]['ev_ci'][1]:+.0f}]" for e in eras), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "real.json"
    old = json.loads(path.read_text())["rows"] if path.exists() else []
    keep = [r for r in old if r["id"] not in {x["id"] for x in res}]
    path.write_text(json.dumps(dict(cell="NQ 09:35 fixed, 64 coins x 2000 paths", rows=keep + res), indent=1, default=float))


# ------------------------------------------------------------------------------------------------ laws
def real_excursions(S=310, flat=RPL.APEX_FLAT):
    """Per (day, side): exit code, max drawdown from the running max, worst dip, best run-up (ticks, 1m bars, hi
    credited before lo within a bar as the engine does; the target bar is open -> low -> target)."""
    P = R.load_day_paths("NQ", "0935", "fixed")
    b = RP.Bracket(S, 10, 0.5, 0.51, flat)
    rows = []
    for r in P["days"].itertuples(index=False):
        a, z = r.start, r.start + r.n_bars
        O, H, Lo, C, E = (P[k][a:z] for k in ("o", "h", "l", "c", "et_min"))
        for side in (0, 1):
            o_, h_, l_, c_ = (O, H, Lo, C) if side == 0 else (-O, -Lo, -H, -C)
            code, k, fill, _ = RP.trade(o_, h_, l_, c_, E, b, 0.0, bool(r.half))
            hh, ll = h_[:k + 1].astype(float), l_[:k + 1].astype(float)
            if code == RP.EXIT["target"]:
                hh[-1], ll[-1] = o_[k], min(l_[k], o_[k])        # exit bar: open -> low, then the target fill
                hh = np.r_[hh, S]
                ll = np.r_[ll, S]
            elif code == RP.EXIT["stop"]:
                hh[-1], ll[-1] = o_[k], min(-S, o_[k])
            runmax = np.maximum.accumulate(np.r_[0.0, hh])[1:]
            rows.append((r.era, code, float((runmax - ll).max()), float(-min(0.0, ll.min())), float(max(0.0, hh.max()))))
    return rows


def laws():
    S = T = 310
    rows = real_excursions(S)
    out = dict(S=S, T=T, note="10 MNQ x 310t, NQ 09:35, flat 16:59; drawdown and dip in ticks", eras={})
    Gs, ds, ms = (150, 200, 250, 300, 350, 400, 450), (100, 150, 200, 250), (45, 90, 155, 200)
    out["analytic"] = dict(mdd={g: G.p_mdd_win(g, S, T) for g in Gs}, dip={d: G.p_dip_win(d, S, T) for d in ds},
                           runup_lose={m: G.p_runup_lose(m, S, T) for m in ms}, mdd_old={g: (G.p_dip_win(g, S, T)) for g in Gs})
    for era in ("2011-18", "2019-21", "2022-26"):
        v = np.array([x[1:] for x in rows if x[0] == era])
        w, lo = v[v[:, 0] == 1], v[v[:, 0] == 0]
        out["eras"][era] = dict(n=len(v), wins=len(w), losses=len(lo), flat_share=float((v[:, 0] == 2).mean()),
                                mdd={g: float((w[:, 1] >= g).mean()) for g in Gs},
                                dip={d: float((w[:, 2] >= d).mean()) for d in ds},
                                runup_lose={m: float((lo[:, 3] >= m).mean()) for m in ms})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "laws.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    only = sys.argv[2:] or None
    if cmd == "synth":
        synth(only=only)
    elif cmd == "synth_gmin":
        synth(g_min=8.0, only=only, tag="_gmin8")
    elif cmd == "real":
        real(only=only)
    elif cmd == "laws":
        laws()
