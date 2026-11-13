"""Regime-aware bracket for the coin-flip prop replay (question #1 after the prop_realtape loop).

Preregistration (written before any result): data/prop_realtape/regime_bracket/prereg.json.

  (a) per era, which fixed stop (multiple of the plan's headline stop st0, contracts re-sized from the plan's $ risk
      per step4_rules, plan cap respected) maximises real-tape bootstrap EV; plus reduced $ risk at st0;
  (b) does a prior-close-vol stop rule, stop = clip(k x vol_ticks, 0.1 st0, 1.6 st0), fitted leave-one-era-out,
      beat the fixed headline bracket pooled 2011-26?
  (c) Lucid plans at list and coupon prices (EV = take - one-off fee; argmax unchanged).

Stages (each resumable; results in data/prop_realtape/regime_bracket/):
  python prop_realtape/regime_bracket.py grid       # (a) + (b) grid cells, 16 coins x 1000 paths -> grid.jsonl
  python prop_realtape/regime_bracket.py fit        # leave-one-era-out selection (training eras only) -> folds.json
  python prop_realtape/regime_bracket.py composite  # fixed / R1 / R2 / C1 composites, 64 x 2000 -> composite.jsonl
  python prop_realtape/regime_bracket.py longblock  # fixed / R1 / C1 composites at block 125 and 250 -> longblock.jsonl
  python prop_realtape/regime_bracket.py report     # -> results.json

Strategy-free: direction is replay.coin_sides (date-keyed coin). realdays / replay / run_plan are imported read-only.
"""
from __future__ import annotations

import argparse
import hashlib
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
import run_plan as RN  # noqa: E402

HERE = PKG.parent
OUT = HERE / "data" / "prop_realtape" / "regime_bracket"
STATE = HERE / "data" / "prop_realtape" / "state.json"
PREREG = OUT / "prereg.json"
GRID = OUT / "grid.jsonl"
FOLDS = OUT / "folds.json"
COMP = OUT / "composite.jsonl"

ERAS = ("2011-18", "2019-21", "2022-26")
PRODUCTS = ("NQ", "ES")
ENTRIES = ("0935", "1100")
MULTS = (0.10, 0.15, 0.20, 0.25, 0.33, 0.40, 0.50, 0.65, 0.80, 1.00, 1.30, 1.60)
KS = (0.05, 0.065, 0.08, 0.10, 0.13, 0.16, 0.20, 0.25, 0.32, 0.40, 0.50, 0.65, 0.80, 1.00)
MEASURES = {"atr": "atr_ticks", "vix": "vixsd_ticks"}
CLIP = (0.10, 1.60)
P_STAR = 0.90
N_COIN, PATHS = 16, 1000
N_COIN_F, PATHS_F = 64, 2000
WORKERS = 2
LUCID_PRICES = {"lucidflex_50k": {"list": 115.0, "coupon": 80.50},          # coordinator, 2026-11-04
                "luciddirect_150k": {"list": 836.0, "coupon": 585.20}}

_G: dict = {}           # filled in the parent before fork: plans, paths


# ---------------------------------------------------------------- setup

def plan_ctx(pid: str) -> dict:
    state = json.loads(STATE.read_text())
    entry = next(e for e in state["plans_queue"] if e["id"] == pid)
    plan, h = RN.resolve(entry)
    fee = plan["_apex"]["price"] if "_apex" in plan else L.fee_of(plan)
    return dict(id=pid, plan=plan, risk=float(h["risk"]), n0=int(h["contracts"]), fee=float(fee),
                comm=plan.get("commissionPerSide", L.COMM_SIDE), flat=plan.get("flatByEt") or RP.DEFAULT_FLAT,
                cap=RP.plan_cap(plan), mode=RP.compress_mode(plan), provisional=bool(entry.get("provisional")),
                firm=entry["firm"], name=entry["plan"])


def plan_ids() -> list:
    return [e["id"] for e in json.loads(STATE.read_text())["plans_queue"]]


def load_paths(product: str, entry: str) -> dict:
    P = R.load_day_paths(product, entry, "fixed")
    d = P["days"]
    P["mask"] = (np.isfinite(d["atr_ticks"].to_numpy(float)) & np.isfinite(d["vixsd_ticks"].to_numpy(float)))
    return P


def reduced_ns(n0: int) -> list:
    return sorted({max(1, n0 // 2), int(round(0.75 * n0))} - {n0})


# ---------------------------------------------------------------- per-day stops

def stops_for(spec, days, st0: int) -> np.ndarray:
    """Wanted stop (ticks, float) per day. spec: ('fx', mult) | ('vol', measure, k) | ('comp', {era: spec})."""
    kind = spec[0]
    if kind == "fx":
        return np.full(len(days), spec[1] * st0, float)
    if kind == "vol":
        v = days[MEASURES[spec[1]]].to_numpy(float)
        return np.clip(spec[2] * v, CLIP[0] * st0, CLIP[1] * st0)
    if kind == "comp":
        out = np.full(len(days), np.nan)
        era = days["era"].to_numpy()
        for e, sub in spec[1].items():
            m = era == e
            out[m] = stops_for(sub, days[m], st0)
        return out
    raise ValueError(spec)


def cell_results(ctx: dict, P: dict, product: str, spec) -> dict:
    """replay.day_results for one spec. Full-risk specs go through rule='abs' with k_abs=1 and vol_ticks = the
    wanted stop (step4_rules re-rounding + cap); ('rr', n) keeps the stop at st0 exactly with n contracts."""
    tick = RP.TICK_USD[product]
    st0 = RP.base_bracket(ctx["risk"], ctx["n0"], product)
    kw = dict(product=product, comm=ctx["comm"], flat_mod=ctx["flat"], cap=ctx["cap"], mode=ctx["mode"])
    if spec[0] == "rr":
        n = int(spec[1])
        return RP.day_results(P, st0 * n * tick, n, rule="fixed", **kw)
    days = P["days"].copy()
    want = stops_for(spec, days, st0)
    days["vol_ticks"] = np.where(np.isfinite(want), want, np.nan)
    return RP.day_results(dict(P, days=days), ctx["risk"], ctx["n0"], rule="abs", k_abs=1.0, **kw)


def summarize(done, ctx):
    return RN.apex_summarize(done, ctx["plan"]) if "_apex" in ctx["plan"] else RP.summarize(done, ctx["plan"], ctx["fee"])


def boot_eras(table, days, mask, ctx, n_coin, paths, eras=("pooled",) + ERAS, block: int = RP.BLOCK) -> dict:
    dates = days["date"].tolist()
    sides = [RP.coin_sides(dates, s) for s in range(n_coin)]
    out = {}
    for era in eras:
        idx = RN.era_idx(days, era)
        idx = idx[mask[idx]]
        rows = []
        for s in range(n_coin):
            done = RP.run(table, RP.block_seqs(idx, sides[s], paths, block=block, seed=1000 + s), ctx["plan"])
            rows.append(summarize(done, ctx))
        m = lambda k: float(np.mean([r[k] for r in rows]))
        out[era] = dict(ev_coins=[round(float(r["ev"]), 3) for r in rows], ev=m("ev"), pass_rate=m("pass_rate"),
                        p_paid=m("p_paid"), days_used=m("days_used"), fee=m("fee"), n_days=int(len(idx)),
                        **({"late": m("late")} if "late" in rows[0] else {}))
    return out


def exit_stats(days, mask, dr) -> dict:
    o = {}
    for era in ERAS:
        m = (days["era"] == era).to_numpy() & mask
        c = dr["code"][m]
        sh = np.bincount(c.ravel(), minlength=3) / c.size
        o[era] = dict(stop=float(sh[0]), target=float(sh[1]), flat=float(sh[2]), resolve=float(sh[0] + sh[1]),
                      capped=float(dr["capped"][m].mean()), mean_risk=float(dr["risk"][m].mean()),
                      mean_stop=float(dr["st"][m].mean()), median_stop=float(np.median(dr["st"][m])),
                      mean_n=float(dr["n"][m].mean()))
    return o


def spec_key(pid, product, entry, spec) -> str:
    if spec[0] == "comp":
        return f"{pid}|{product}|{entry}|comp|{spec[2]}"
    return "|".join([pid, product, entry] + [str(x) for x in spec])


def _job(args):
    pid, product, entry, spec, n_coin, paths = args[:6]
    block = args[6] if len(args) > 6 else RP.BLOCK
    ctx, P = _G["plans"][pid], _G["paths"][(product, entry)]
    sp = spec[:2] if spec[0] == "comp" else spec
    t0 = time.time()
    dr = cell_results(ctx, P, product, sp)
    table = RP.table_from_bars(dr["bars"])
    res = boot_eras(table, P["days"], P["mask"], ctx, n_coin, paths, block=block)
    key = spec_key(pid, product, entry, spec) + (f"|block{block}" if block != RP.BLOCK else "")
    return dict(key=key, block=block, plan=pid, product=product, entry=entry,
                spec=list(spec[:1]) + ([spec[2]] if spec[0] == "comp" else list(spec[1:])),
                st0=RP.base_bracket(ctx["risk"], ctx["n0"], product), n_coin=n_coin, paths=paths,
                exits=exit_stats(P["days"], P["mask"], dr), eras=res, secs=round(time.time() - t0, 2))


def _setup(pids, products, entries):
    _G["plans"] = {p: plan_ctx(p) for p in pids}
    _G["paths"] = {(pr, e): load_paths(pr, e) for pr in products for e in entries}


def _done_keys(path: Path) -> set:
    if not path.exists():
        return set()
    return {json.loads(line)["key"] for line in path.read_text().splitlines() if line.strip()}


def _run_jobs(jobs, path: Path, workers: int):
    done = _done_keys(path)
    jobs = [j for j in jobs if spec_key(*j[:4]) + (f"|block{j[6]}" if len(j) > 6 else "") not in done]
    print(f"{len(jobs)} jobs to run ({len(done)} already in {path.name})", flush=True)
    t0 = time.time()
    with mp.get_context("fork").Pool(workers) as pool, path.open("a") as f:
        for i, r in enumerate(pool.imap_unordered(_job, jobs, chunksize=1)):
            f.write(json.dumps(r) + "\n")
            f.flush()
            if i % 25 == 0 or i == len(jobs) - 1:
                print(f"[{time.time() - t0:6.0f}s] {i + 1}/{len(jobs)} {r['key']} ({r['secs']}s)", flush=True)


def check_frozen():
    st = json.loads(STATE.read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(PKG / "realdays.py") == st["frozen"]["realdays_sha256"], "realdays.py changed since the freeze"
    pre = json.loads(PREREG.read_text())
    assert pre["frozen_inputs"]["realdays_sha256"] == st["frozen"]["realdays_sha256"]
    return sha(PREREG)


# ---------------------------------------------------------------- stage 1: grid

def grid_specs(n0: int) -> list:
    return ([("fx", m) for m in MULTS] + [("rr", n) for n in reduced_ns(n0)]
            + [("vol", meas, k) for meas in MEASURES for k in KS])


def cmd_grid(a):
    pids = a.plans or plan_ids()
    _setup(pids, a.products, a.entries)
    jobs = [(pid, pr, e, sp, N_COIN, PATHS) for pr in a.products for e in a.entries for pid in pids
            for sp in grid_specs(_G["plans"][pid]["n0"])]
    _run_jobs(jobs, GRID, a.workers)


# ---------------------------------------------------------------- stage 2: leave-one-era-out fit

def load_grid(path: Path = GRID) -> dict:
    rows = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["key"]] = r
    return rows


def _train_obj(row, train) -> float:
    w = np.array([row["eras"][e]["n_days"] for e in train], float)
    ev = np.array([row["eras"][e]["ev"] for e in train], float)
    return float((w * ev).sum() / w.sum())


def fit_fold(cells: list, held: str) -> dict:
    """cells: grid rows of one plan x product x entry. Selection reads ONLY the two training eras."""
    train = [e for e in ERAS if e != held]
    vol = [c for c in cells if c["spec"][0] == "vol"]
    fx = [c for c in cells if c["spec"][0] == "fx"]
    r1 = max(vol, key=lambda c: _train_obj(c, train))
    c1 = max(fx, key=lambda c: _train_obj(c, train))

    def resolve(c):
        w = np.array([c["eras"][e]["n_days"] for e in train], float)
        x = np.array([c["exits"][e]["resolve"] for e in train], float)
        return float((w * x).sum() / w.sum())
    atr = [c for c in vol if c["spec"][1] == "atr"]
    r2 = min(atr, key=lambda c: (abs(resolve(c) - P_STAR), c["spec"][2]))
    return dict(train=train,
                R1=dict(spec=r1["spec"], train_obj=_train_obj(r1, train)),
                R2=dict(spec=r2["spec"], train_resolve=resolve(r2)),
                C1=dict(spec=c1["spec"], train_obj=_train_obj(c1, train)))


def cmd_fit(a):
    G = load_grid()
    groups = {}
    for r in G.values():
        groups.setdefault((r["plan"], r["product"], r["entry"]), []).append(r)
    out = {}
    for (pid, pr, e), cells in sorted(groups.items()):
        out[f"{pid}|{pr}|{e}"] = {held: fit_fold(cells, held) for held in ERAS}
    FOLDS.write_text(json.dumps(dict(prereg_sha256=check_frozen(), folds=out), indent=1))
    print("wrote", FOLDS, len(out), "groups")


# ---------------------------------------------------------------- stage 3: composites (64 x 2000)

def comp_spec(fold: dict, rule: str):
    per = {}
    for held, f in fold.items():
        s = f[rule]["spec"]
        per[held] = ("fx", s[1]) if s[0] == "fx" else ("vol", s[1], s[2])
    return ("comp", per, rule)


def cmd_composite(a):
    pids = a.plans or plan_ids()
    folds = json.loads(FOLDS.read_text())["folds"]
    _setup(pids, a.products, a.entries)
    jobs = []
    for pr in a.products:
        for e in a.entries:
            for pid in pids:
                fold = folds[f"{pid}|{pr}|{e}"]
                jobs.append((pid, pr, e, ("comp", {h: ("fx", 1.0) for h in ERAS}, "fixed"), N_COIN_F, PATHS_F))
                for rule in ("R1", "C1", "R2"):
                    jobs.append((pid, pr, e, comp_spec(fold, rule), N_COIN_F, PATHS_F))
    _run_jobs(jobs, COMP, a.workers)


LONG = OUT / "longblock.jsonl"
LONG_BLOCKS = (125, 250)


def cmd_longblock(a):
    """Added after the coordinator's note (hist_fix: 20-day blocks splice vol regimes into one account, optimistic
    for slow plans). Same composites (folds unchanged, not re-fitted), 64 coins x 1000 paths, blocks 125 / 250."""
    pids = a.plans or plan_ids()
    folds = json.loads(FOLDS.read_text())["folds"]
    _setup(pids, a.products, a.entries)
    jobs = []
    for blk in LONG_BLOCKS:
        for pr in a.products:
            for e in a.entries:
                for pid in pids:
                    fold = folds[f"{pid}|{pr}|{e}"]
                    jobs.append((pid, pr, e, ("comp", {h: ("fx", 1.0) for h in ERAS}, "fixed"), N_COIN_F, 1000, blk))
                    for rule in ("R1", "C1"):
                        jobs.append((pid, pr, e, comp_spec(fold, rule), N_COIN_F, 1000, blk))
    _run_jobs(jobs, LONG, a.workers)


# ---------------------------------------------------------------- stage 4: report

def ci(x, t=None):
    x = np.asarray(x, float)
    n = len(x)
    t = t or (1.998 if n == 64 else 2.131 if n == 16 else 1.96)
    se = x.std(ddof=1) / math.sqrt(n)
    return [float(x.mean() - t * se), float(x.mean() + t * se)]


def surface(cells: list, era: str) -> dict:
    """(a): full-risk fixed-stop surface for one era, argmax and the stops tied with it (paired CI over coins)."""
    fx = sorted([c for c in cells if c["spec"][0] == "fx"], key=lambda c: c["spec"][1])
    ev = np.array([c["eras"][era]["ev"] for c in fx])
    j = int(np.argmax(ev))
    best = np.array(fx[j]["eras"][era]["ev_coins"])
    tied = []
    for i, c in enumerate(fx):
        if i == j:
            continue
        lo, hi = ci(best - np.array(c["eras"][era]["ev_coins"]))
        if lo <= 0:
            tied.append(c["spec"][1])
    nb = [fx[i]["spec"][1] for i in (j - 1, j + 1) if 0 <= i < len(fx)]
    rr = [dict(n=c["spec"][1], ev=c["eras"][era]["ev"], ev_ci=ci(c["eras"][era]["ev_coins"]),
               p_paid=c["eras"][era]["p_paid"]) for c in cells if c["spec"][0] == "rr"]
    head = next(c for c in fx if c["spec"][1] == 1.0)
    return dict(mults=[c["spec"][1] for c in fx], ev=ev.round(2).tolist(),
                stop_ticks=[round(c["exits"][era]["mean_stop"], 1) if era != "pooled" else None for c in fx],
                mean_risk=[round(c["exits"][era]["mean_risk"], 1) if era != "pooled" else None for c in fx],
                resolve=[round(c["exits"][era]["resolve"], 3) if era != "pooled" else None for c in fx],
                argmax_mult=fx[j]["spec"][1], argmax_ev=float(ev[j]), argmax_ci=ci(best),
                argmax_stop_ticks=(fx[j]["exits"][era]["mean_stop"] if era != "pooled" else None),
                argmax_minus_headline_ci=ci(best - np.array(head["eras"][era]["ev_coins"])),
                headline_ev=float(head["eras"][era]["ev"]), tied_mults=tied,
                not_separable=any(m in tied for m in nb), reduced_risk_at_st0=rr)


def cmd_report(a):
    G = load_grid()
    folds = json.loads(FOLDS.read_text())["folds"] if FOLDS.exists() else {}
    C = load_grid(COMP) if COMP.exists() else {}
    LB = load_grid(LONG) if LONG.exists() else {}
    pids = plan_ids()
    ctxs = {p: plan_ctx(p) for p in pids}
    groups = {}
    for r in G.values():
        groups.setdefault((r["plan"], r["product"], r["entry"]), []).append(r)
    res = dict(prereg_sha256=check_frozen(), surface={}, b={}, lucid_prices={})
    for (pid, pr, e), cells in sorted(groups.items()):
        g = f"{pid}|{pr}|{e}"
        res["surface"][g] = {era: surface(cells, era) for era in ("pooled",) + ERAS}
        comp = {rule: C.get(f"{g}|comp|{rule}") for rule in ("fixed", "R1", "C1", "R2")}
        if comp["fixed"] is None:
            continue
        fx = comp["fixed"]["eras"]
        b = dict(folds=folds.get(g), fixed={k: dict(ev=fx[k]["ev"], ci=ci(fx[k]["ev_coins"]), p_paid=fx[k]["p_paid"],
                                                     days_used=fx[k]["days_used"]) for k in fx})
        for rule in ("R1", "C1", "R2"):
            if comp[rule] is None:
                continue
            ce = comp[rule]["eras"]
            b[rule] = {k: dict(ev=ce[k]["ev"], ci=ci(ce[k]["ev_coins"]),
                               diff=float(np.mean(np.subtract(ce[k]["ev_coins"], fx[k]["ev_coins"]))),
                               diff_ci=ci(np.subtract(ce[k]["ev_coins"], fx[k]["ev_coins"])),
                               p_paid=ce[k]["p_paid"], days_used=ce[k]["days_used"],
                               mean_stop=(comp[rule]["exits"][k]["mean_stop"] if k != "pooled" else None),
                               mean_risk=(comp[rule]["exits"][k]["mean_risk"] if k != "pooled" else None),
                               capped=(comp[rule]["exits"][k]["capped"] if k != "pooled" else None))
                       for k in ce}
            b[rule]["beats_pooled"] = b[rule]["pooled"]["diff_ci"][0] > 0
            b[rule]["beats_all_eras"] = all(b[rule][k]["diff"] > 0 for k in ERAS)
            b[rule]["eras_beaten"] = int(sum(b[rule][k]["diff"] > 0 for k in ERAS))
        if comp["R1"] is not None and comp["C1"] is not None:
            d = np.subtract(comp["R1"]["eras"]["pooled"]["ev_coins"], comp["C1"]["eras"]["pooled"]["ev_coins"])
            b["R1_minus_C1"] = dict(diff=float(d.mean()), diff_ci=ci(d))
        lb = {}
        for blk in LONG_BLOCKS:
            rows = {rule: LB.get(f"{g}|comp|{rule}|block{blk}") for rule in ("fixed", "R1", "C1")}
            if rows["fixed"] is None:
                continue
            lb[blk] = {}
            for era in ("pooled",) + ERAS:
                fxc = rows["fixed"]["eras"][era]["ev_coins"]
                lb[blk][era] = dict(fixed=float(np.mean(fxc)), fixed_ci=ci(fxc))
                for rule in ("R1", "C1"):
                    if rows[rule] is not None:
                        d = np.subtract(rows[rule]["eras"][era]["ev_coins"], fxc)
                        lb[blk][era][rule] = float(np.mean(rows[rule]["eras"][era]["ev_coins"]))
                        lb[blk][era][f"{rule}_diff"] = float(d.mean())
                        lb[blk][era][f"{rule}_diff_ci"] = ci(d)
        if lb:
            b["long_block"] = lb
        res["b"][g] = b
    # verdict on the primary cell (NQ 09:35, R1)
    prim = [res["b"].get(f"{p}|NQ|0935", {}).get("R1") for p in pids]
    if all(prim):
        nb = sum(x["beats_pooled"] for x in prim)
        na = sum(x["beats_pooled"] and x["beats_all_eras"] for x in prim)
        res["verdict"] = dict(beats_pooled=nb, beats_pooled_and_all_eras=na,
                              all_eras_any=sum(x["beats_all_eras"] for x in prim),
                              verdict="YES" if na >= 7 else "PARTIAL" if nb >= 5 else "NO")
    # (c) Lucid at list and coupon. Prices from the coordinator (user screenshots of lucidtrading.com, 2026-11-04):
    # runs used the run-time fee (Flex $90.20, Direct $836); the fee is one-off, so EV(price) = EV_run + fee_run - price
    # on the identical accounts and the argmax is unchanged.
    for pid in ("lucidflex_50k", "luciddirect_150k"):
        fee_run, prices = ctxs[pid]["fee"], LUCID_PRICES[pid]
        adj = lambda ev: {k: ev + fee_run - v for k, v in prices.items()}
        out = {}
        for g in [k for k in res["surface"] if k.startswith(pid + "|")]:
            row = {}
            for era in ("pooled",) + ERAS:
                s_ = res["surface"][g][era]
                row[era] = dict(best_mult=s_["argmax_mult"], headline_16=adj(s_["headline_ev"]), best_fixed_16=adj(s_["argmax_ev"]))
                if g in res["b"] and "R1" in res["b"][g]:
                    row[era]["fixed_64"] = adj(res["b"][g]["fixed"][era]["ev"])
                    row[era]["R1_heldout_64"] = adj(res["b"][g]["R1"][era]["ev"])
                    row[era]["C1_heldout_64"] = adj(res["b"][g]["C1"][era]["ev"])
                lb = res["b"].get(g, {}).get("long_block", {}).get(250, {}).get(era)
                if lb:
                    row[era]["block250_fixed"] = adj(lb["fixed"])
                    row[era]["block250_R1"] = adj(lb["R1"])
            out[g] = row
        res["lucid_prices"][pid] = dict(fee_run=fee_run, prices=prices, rows=out)
    res["plans"] = {p: dict(name=ctxs[p]["name"], firm=ctxs[p]["firm"], risk=ctxs[p]["risk"], n0=ctxs[p]["n0"],
                            cap=ctxs[p]["cap"], fee=ctxs[p]["fee"], provisional=ctxs[p]["provisional"],
                            st0_NQ=RP.base_bracket(ctxs[p]["risk"], ctxs[p]["n0"], "NQ"),
                            st0_ES=RP.base_bracket(ctxs[p]["risk"], ctxs[p]["n0"], "ES")) for p in pids}
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    print("wrote results.json; verdict", res.get("verdict"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("grid", "fit", "composite", "longblock", "report"))
    ap.add_argument("--plans", nargs="*")
    ap.add_argument("--products", nargs="*", default=list(PRODUCTS))
    ap.add_argument("--entries", nargs="*", default=list(ENTRIES))
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args()
    a.workers = min(a.workers, WORKERS)
    OUT.mkdir(parents=True, exist_ok=True)
    check_frozen()
    {"grid": cmd_grid, "fit": cmd_fit, "composite": cmd_composite, "longblock": cmd_longblock,
     "report": cmd_report}[a.stage](a)


if __name__ == "__main__":
    main()
