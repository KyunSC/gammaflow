"""Per-plan sizing-policy search. One variant per process: `capped` (every level <= 0.5x max loss) or `uncapped`.

  python3 -m prop_policy.search --plan "LucidFlex 50K" --variant capped
  python3 -m prop_policy.search --plan "LucidFlex 50K" --merge

Selection (seeds 0-7, SEL_PATHS paths each, path seeds 50+seed, the same for every candidate so comparisons share
draws) uses the stage decomposition: run_stage restarts the funded stage at the start balance and days are iid, so
  EV = P(pass) x V_funded - E[evaluation cost]   (cost: billing cycles used, activation when owed)
The funded policy is chosen by V_funded alone, then the evaluation policy by P(pass) x V_funded - cost. The one thing
the decomposition ignores is the horizon (the funded stage gets 250 - evalDays days); scoring uses the full simulator.

Scoring (seeds 100-115 x 25k paths, path seeds 200+i, as lucid_structure.multi_seed): the winner, the best two-stage
fixed policy, the best one-risk fixed policy and the fixed-risk headline bracket, all on the same draws. Gains are
paired per seed (winner minus headline), with a 95% CI of +/- 2.13 x the standard error over the 16 seeds.
Unresolved evaluations at the horizon count as failures (sim.summarize).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
from prop_policy import outcomes as O  # noqa: E402
from prop_policy import policies as P  # noqa: E402
from prop_policy import sim  # noqa: E402

RES = ML / "data" / "prop_policy" / "results"
STATE = ML / "data" / "prop_policy" / "state.json"
SEL_PATHS = 3000
SCORE_PATHS = 25000
HORIZON = 250
CAP_FRAC, CAP_TOL = 0.5, 1.005  # tick rounding: the $1,000 grid level realises $1,001
N_COARSE = 18
T_16 = 2.13


def slug(name):
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


class LazyTables:
    """Day tables for one seed, built per level on first use (numpy-backed)."""

    def __init__(self, menu, seed):
        self.menu, self.seed, self.c = menu, seed, {}

    def __getitem__(self, i):
        t = self.c.get(i)
        if t is None:
            t = self.c[i] = O.day_table(self.menu[i], self.seed, as_list=False)
        return t


def setup(name):
    e = O.plans()[name]
    p = e["plan"]
    h = json.loads(STATE.read_text())["fixed_risk_headlines"][name]
    hn = int(round(h["risk"] / (h["stop_ticks"] * 0.5)))
    menu = O.plan_levels(p, extra=[(hn, h["stop_ticks"])])
    head = next(i for i, l in enumerate(menu) if (l.n, l.S) == (hn, h["stop_ticks"]))
    return e, p, menu, head, h


def full_run(policy, p, tabs, paths, rseed):
    """sim.attempts with lazy tables, keeping unresolved evaluations; each attempt carries its levels."""
    rng = np.random.default_rng(rseed)
    out = []
    for _ in range(paths):
        draws = rng.integers(0, O.N_DAYS, HORIZON)
        lv = []
        a = sim.simulate_account(tabs, lambda k: int(draws[k]) if k < HORIZON else -1, p, policy, lv)
        a["levels"] = lv
        out.append(a)
    return out


class Selector:
    def __init__(self, e, p, menu, allowed):
        self.e, self.p, self.menu = e, p, menu
        self.tabs = {s: LazyTables(menu, s) for s in O.SELECT_SEEDS}
        self.eval_h = e.get("eval_limit_days") or HORIZON
        self.calls = 0
        self.allowed = allowed

    def stage(self, policy, stage):
        policy.bind(self.menu, self.allowed)
        self.calls += 1
        horizon = self.eval_h if stage == "eval" else HORIZON
        out = []
        for s in O.SELECT_SEEDS:
            tabs = self.tabs[s]
            rng = np.random.default_rng(50 + s)
            for _ in range(SEL_PATHS):
                draws = rng.integers(0, O.N_DAYS, horizon)
                out.append(sim.run_stage(tabs, lambda k: int(draws[k]) if k < horizon else -1, 0, self.p, stage, policy))
        return out

    def funded_value(self, policy):
        r = self.stage(policy, "funded")
        return self.p["split"] * float(np.mean([sum(a["payouts"]) for a in r]))

    def eval_stats(self, policy):
        """(P(pass), mean cost per attempt). Unresolved or late evaluations are failures."""
        if not self.p["hasEval"]:
            return 1.0, float(sim.attempt_cost(dict(evalDays=0, outcome="graduated"), self.p))
        r = self.stage(policy, "eval")
        passed = np.array([a["status"] == "passed" for a in r])
        cost = [sim.attempt_cost(dict(evalDays=a["days"], outcome="passed" if a["status"] == "passed" else "failed"), self.p)
                for a in r]
        return float(passed.mean()), float(np.mean(cost))


def coordinate(start, cells, cands, score, sweeps=2):
    """Coordinate ascent over a Grid table; keeps a change only if it improves the (common-draw) score."""
    best = dict(start)
    cur = score(best)
    for _ in range(sweeps):
        moved = False
        for c in cells:
            for v in cands:
                if v == best[c]:
                    continue
                trial = {**best, c: v}
                sc = score(trial)
                if sc > cur + 1e-9:
                    best, cur, moved = trial, sc, True
        if not moved:
            break
    return best, cur


def search(name, variant):
    t0 = time.time()
    e, p, menu, head, h = setup(name)
    cap = CAP_FRAC * p["maxLoss"] * CAP_TOL if variant == "capped" else math.inf
    allowed = [i for i, l in enumerate(menu) if l.risk <= cap]
    step = max(1, len(allowed) // N_COARSE)
    coarse = sorted(set(allowed[::step]) | {allowed[-1]} | ({head} if head in allowed else set()))
    S = Selector(e, p, menu, allowed)
    log = lambda *a: print(f"[{variant} {time.time() - t0:6.0f}s]", *a, flush=True)
    log(f"{name}: {len(menu)} levels, {len(allowed)} allowed (cap {cap:.0f}), {len(coarse)} coarse, headline level {head} "
        f"${menu[head].risk:.0f}{'' if head in allowed else ' (over the cap)'}")

    # ---- funded stage
    F1 = {i: S.funded_value(P.Fixed(i, i)) for i in coarse}
    f1 = max(F1, key=F1.get)
    log("F1 fixed", {f"{menu[i].risk:.0f}": round(v, 1) for i, v in F1.items()})
    F2 = {}
    for kf in (1, 2, 3, 4):
        for hold in coarse[::2] + [f1]:
            F2[(kf, hold)] = S.funded_value(P.Ladder(1, kf, hold))
    f2 = max(F2, key=F2.get)
    log("F2 ladder best", f2, round(F2[f2], 1))
    fcells = [c for c in P.Grid.CELLS if c[0] == "funded"]
    base = {c: f1 for c in P.Grid.CELLS}
    f3, F3v = coordinate(base, fcells, coarse, lambda t: S.funded_value(P.Grid(t)))
    log("F3 grid", round(F3v, 1))
    fund = {"fixed": (P.Fixed(f1, f1), F1[f1]), "ladder": (P.Ladder(1, f2[0], f2[1]), F2[f2]), "grid": (P.Grid(f3), F3v)}
    fbest = max(fund, key=lambda k: fund[k][1])
    Vstar = fund[fbest][1]

    # ---- evaluation stage
    E1 = {i: S.eval_stats(P.Fixed(i, i)) for i in coarse}
    obj = lambda st, V: st[0] * V - st[1]
    E2 = {k: S.eval_stats(P.Ladder(k, 1, allowed[0])) for k in (1, 2, 3, 4)} if p["hasEval"] else {}
    if p["hasEval"]:
        e1 = max(E1, key=lambda i: obj(E1[i], Vstar))
        ecells = [c for c in P.Grid.CELLS if c[0] == "eval"]
        gbase = {**f3, **{c: e1 for c in ecells}}
        e3, _ = coordinate(gbase, ecells, coarse, lambda t: obj(S.eval_stats(P.Grid(t)), Vstar))
        E3 = S.eval_stats(P.Grid(e3))
        log("E1 fixed", {f"{menu[i].risk:.0f}": [round(a, 3), round(b, 1)] for i, (a, b) in E1.items()})
        log("E2 ladder", {k: [round(a, 3), round(b, 1)] for k, (a, b) in E2.items()}, "E3 grid", [round(x, 3) for x in E3])
    else:
        e3, E3 = dict(f3), E1[coarse[0]]

    # ---- candidates (selection estimate = P(pass) x V - cost)
    cands = {}
    i1 = max(coarse, key=lambda i: obj(E1[i], F1[f1]))
    cands["1 two-stage fixed"] = (P.Fixed(i1, f1), obj(E1[i1], F1[f1]))
    one = max(coarse, key=lambda i: obj(E1[i], F1[i]))
    cands["0 one-risk fixed"] = (P.Fixed(one, one), obj(E1[one], F1[one]))
    if p["hasEval"]:
        k2 = max(E2, key=lambda k: obj(E2[k], F2[f2]))
        cands["2 ladder"] = (P.Staged(P.Ladder(k2, 1, allowed[0]), P.Ladder(1, f2[0], f2[1])), obj(E2[k2], F2[f2]))
        cands["3 grid"] = (P.Grid({**e3, **{c: f3[c] for c in fcells}}), obj(E3, F3v))
        ie = max(coarse, key=lambda i: obj(E1[i], Vstar))
        evs = {"fixed": (P.Fixed(ie, ie), obj(E1[ie], Vstar)),
               "ladder": (P.Ladder(max(E2, key=lambda k: obj(E2[k], Vstar)), 1, allowed[0]), max(obj(E2[k], Vstar) for k in E2)),
               "grid": (P.Grid(e3), obj(E3, Vstar))}
        ebest = max(evs, key=lambda k: evs[k][1])
        cands[f"mix {ebest} eval + {fbest} funded"] = (P.Staged(evs[ebest][0], fund[fbest][0]), evs[ebest][1])
    else:
        cands["2 ladder"] = (P.Ladder(1, f2[0], f2[1]), obj(E1[coarse[0]], F2[f2]))
        cands["3 grid"] = (P.Grid(f3), obj(E1[coarse[0]], F3v))
    for k, (pol, v) in cands.items():
        pol.bind(menu, allowed)
        log(f"select {k:<34} {v:+8.1f}  {pol.describe()}")
    win = max((k for k in cands if not k.startswith("0")), key=lambda k: cands[k][1])
    log("winner", win, round(cands[win][1], 1), "selection calls", S.calls)
    del S

    # ---- score on fresh seeds
    allm = list(range(len(menu)))
    score_set = {"winner": cands[win][0], "two-stage fixed": cands["1 two-stage fixed"][0], "one-risk fixed": cands["0 one-risk fixed"][0],
                 "headline": P.Fixed(head, head).bind(menu, allm)}
    rows = {k: [] for k in score_set}
    risks = {k: [] for k in score_set}
    for i, s in enumerate(O.SCORE_SEEDS):
        tabs = LazyTables(menu, s)
        for k, pol in score_set.items():
            done = full_run(pol, p, tabs, SCORE_PATHS, 200 + i)
            rows[k].append(sim.summarize(done, p, fee=e["fee"], eval_limit=e.get("eval_limit_days")))
            if i < 4:
                risks[k].extend(menu[l].risk for a in done for l in a["levels"])
        log(f"score seed {s}: " + " ".join(f"{k} {rows[k][-1]['ev']:+.1f}" for k in rows))

    def agg(k):
        ev = np.array([r["ev"] for r in rows[k]])
        se = ev.std(ddof=1) / math.sqrt(len(ev))
        m = lambda f: float(np.mean([r[f] for r in rows[k]]))
        rk = np.array(risks[k])
        return dict(ev=float(ev.mean()), ev_ci=[float(ev.mean() - T_16 * se), float(ev.mean() + T_16 * se)], pass_rate=m("pass_rate"),
                    p_paid=m("p_paid"), days_used=m("days_used"), censored=m("censored"), cost=m("cost"), mean_take=m("mean_take"),
                    risk_p50=float(np.percentile(rk, 50)), risk_p95=float(np.percentile(rk, 95)), risk_max=float(rk.max()),
                    per_seed=ev.tolist())

    def paired(a, b):
        d = np.array([r["ev"] for r in rows[a]]) - np.array([r["ev"] for r in rows[b]])
        se = d.std(ddof=1) / math.sqrt(len(d))
        return dict(diff=float(d.mean()), ci=[float(d.mean() - T_16 * se), float(d.mean() + T_16 * se)],
                    excludes_0=bool(d.mean() - T_16 * se > 0 or d.mean() + T_16 * se < 0))

    out = dict(plan=name, variant=variant, cap=None if math.isinf(cap) else cap, fee=e["fee"], allowed=[menu[allowed[0]].risk, menu[allowed[-1]].risk],
               headline_bracket=dict(n=menu[head].n, stop=menu[head].S, risk=menu[head].risk, within_cap=head in allowed),
               headline_reported=h,
               selection={k: dict(estimate=v, params=pol.params(), describe=pol.describe()) for k, (pol, v) in cands.items()},
               selection_detail=dict(F1={f"{menu[i].risk:.1f}": v for i, v in F1.items()},
                                     F2={f"k{k}|hold{menu[hd].risk:.0f}": v for (k, hd), v in F2.items()},
                                     E1={f"{menu[i].risk:.1f}": list(v) for i, v in E1.items()}, E2={str(k): list(v) for k, v in E2.items()},
                                     V_funded=dict((k, v[1]) for k, v in fund.items())),
               winner=win, winner_describe=cands[win][0].describe(), winner_params=cands[win][0].params(),
               score={k: agg(k) for k in score_set},
               gain_vs_headline=paired("winner", "headline"), gain_vs_one_risk_fixed=paired("winner", "one-risk fixed"),
               one_risk_vs_headline=paired("one-risk fixed", "headline"),
               score_setup=dict(seeds=list(O.SCORE_SEEDS), paths=SCORE_PATHS, path_seeds="200+i", risk_quantiles_from="first 4 seeds, per trading day"),
               selection_setup=dict(seeds=list(O.SELECT_SEEDS), paths=SEL_PATHS, path_seeds="50+seed", coarse_levels=[menu[i].risk for i in coarse]),
               seconds=time.time() - t0)
    RES.mkdir(parents=True, exist_ok=True)
    (RES / f"{slug(name)}.{variant}.json").write_text(json.dumps(out, indent=1))
    sc = out["score"]
    for k in sc:
        log(f"SCORE {k:<16} EV {sc[k]['ev']:+7.1f} [{sc[k]['ev_ci'][0]:+.1f},{sc[k]['ev_ci'][1]:+.1f}] pass {sc[k]['pass_rate']:.3f} "
            f"paid {sc[k]['p_paid']:.3f} days {sc[k]['days_used']:.1f} cens {sc[k]['censored']:.4f} risk p50/p95 {sc[k]['risk_p50']:.0f}/{sc[k]['risk_p95']:.0f}")
    log("gain vs headline", out["gain_vs_headline"], "vs one-risk fixed", out["gain_vs_one_risk_fixed"])
    return out


def merge(name):
    parts = {v: json.loads((RES / f"{slug(name)}.{v}.json").read_text()) for v in ("capped", "uncapped")}
    c, u = parts["capped"], parts["uncapped"]
    best = lambda r: r["score"]["winner"]
    out = dict(plan=name, fee=c["fee"], headline_reported=c["headline_reported"],
               headline_rescored=c["score"]["headline"], headline_within_cap=c["headline_bracket"]["within_cap"],
               capped=dict(winner=c["winner"], describe=c["winner_describe"], score=best(c), gain_vs_headline=c["gain_vs_headline"],
                           gain_vs_capped_one_risk=c["gain_vs_one_risk_fixed"], capped_one_risk=c["score"]["one-risk fixed"],
                           capped_one_risk_vs_headline=c["one_risk_vs_headline"]),
               uncapped=dict(winner=u["winner"], describe=u["winner_describe"], score=best(u), gain_vs_headline=u["gain_vs_headline"],
                             gain_vs_one_risk=u["gain_vs_one_risk_fixed"]),
               realtape="pending: prop_realtape/realdays.py does not exist",
               parts=[f"{slug(name)}.capped.json", f"{slug(name)}.uncapped.json"])
    cg, ug = c["gain_vs_headline"], u["gain_vs_headline"]
    out["verdict"] = dict(capped_beats_headline=cg["excludes_0"] and cg["diff"] > 0,
                          uncapped_beats_headline=ug["excludes_0"] and ug["diff"] > 0,
                          executable_gain=cg["excludes_0"] and cg["diff"] > 0)
    (RES / f"{slug(name)}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("capped", "uncapped", "verdict", "headline_rescored")}, indent=1)[:6000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--variant", choices=["capped", "uncapped"])
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    merge(a.plan) if a.merge else search(a.plan, a.variant)
