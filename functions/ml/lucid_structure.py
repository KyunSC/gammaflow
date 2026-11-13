"""Prop account structure under a coin flip: what a zero-edge (or +e edge) bracket trader earns per account.
Built for Lucid; `firm --firm <id>` runs any firm in firms.js, at that firm's commission and billing, into
data/prop_structure/<id>/.

No market data is read, so running this spends no test window. Every trade is an independent bracket:
  - stop S ticks, target T = rr x S ticks, MNQ ($0.50/tick/contract), n = floor(risk / (S x $0.50)) <= 40.
  - win probability under no edge is the driftless-walk value with the target needing a tick THROUGH it:
    p0 = S / (S + T + 1). An edge of e R per trade (gross) adds e x S / (S + T) to p.
  - costs: $0.50/side/contract commission; entry ENTRY_SLIP_TICKS adverse; stop exits resample the measured
    stop-slippage PMF (fill_study results.json, all clock buckets pooled by count); targets fill at the price.
  - intraday path: a loser's best excursion and a winner's worst are drawn from the driftless-walk
    conditional laws (P(M >= m | lose) = S(T-m) / ((S+m)T), mirrored for winners), so the intraday
    drawdown checks, the soft daily loss limit and LucidDaily's intraday trail see a plausible path.
  - per day: `k` trades in sequence ('fixed'), or up to k stopping after the first winner ('until_win').
  - timeouts, news days and the flat-by time are not modelled: every trade reaches its stop or target.
Accounts are replayed by flybrain.prop.simulate_account (the faithful port of prop/account.js) on iid days,
fee = plan list price from firms.js via prop_prices (no price is hard-coded here). EV per account = 90% of payouts - fee.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from flybrain.prop import _plans, attempt_cost, resolve_plan, simulate_account  # noqa: E402
import prop_prices  # noqa: E402

TICK_USD = 0.50
COMM_SIDE = 0.50
MAX_CONTRACTS = 40
ENTRY_SLIP_TICKS = 0.4
FLEX50_FEE = prop_prices.fee(prop_prices.find("lucid", "LucidFlex 50K"))   # list price; was $90.20 (paid) before 2026-11-04
FILL = HERE / "data" / "fill_study" / "results.json"


def stop_pmf():
    res = json.loads(FILL.read_text())
    w = {k: v["n"] for k, v in res["stop_by_clock"].items()}
    acc = {}
    for bucket, pmf in res["stop_slip_pmf"].items():
        for t, p in pmf.items():
            acc[int(t)] = acc.get(int(t), 0.0) + w[bucket] * p
    ticks = np.array(sorted(acc))
    p = np.array([acc[t] for t in ticks])
    return ticks, p / p.sum()


SLIP_T, SLIP_P = stop_pmf()


def make_days(n_days, risk, stop_ticks, rr, k=1, mode="fixed", edge=0.0, seed=0, comm=COMM_SIDE):
    """iid day table (one replay bar per day): pnl, lo, hi in dollars."""
    rng = np.random.default_rng(seed)
    S = stop_ticks
    T = max(1, round(rr * S))
    n = int(min(MAX_CONTRACTS, max(1, math.floor(risk / (S * TICK_USD)))))
    p = S / (S + T + 1) + edge * S / (S + T)
    m = n_days * k
    win = rng.random(m) < p
    u = rng.random(m)
    slip = rng.choice(SLIP_T, size=m, p=SLIP_P)
    fees = 2 * comm * n + ENTRY_SLIP_TICKS * TICK_USD * n
    pnl = np.where(win, T, -S - slip) * TICK_USD * n - fees
    # Intraday excursions under the driftless walk, conditional on the outcome.
    best_loser = S * T * (1 - u) / (u * T + S)
    worst_winner = T * S * (1 - u) / (u * S + T)
    lo = np.where(win, -worst_winner * TICK_USD * n - fees, pnl)
    hi = np.where(win, pnl + fees, best_loser * TICK_USD * n)
    pnl, lo, hi, win = (a.reshape(n_days, k) for a in (pnl, lo, hi, win))
    if mode == "until_win":
        first = np.where(win.any(1), win.argmax(1), k - 1)
        live = np.arange(k)[None, :] <= first[:, None]
    else:
        live = np.ones((n_days, k), bool)
    pnl, lo, hi = pnl * live, np.where(live, lo, 0.0), np.where(live, hi, 0.0)
    before = np.c_[np.zeros(n_days), np.cumsum(pnl, 1)[:, :-1]]
    day_lo = np.minimum(0.0, (before + lo).min(1))
    day_hi = np.maximum(0.0, (before + hi).max(1))
    trades = live.sum(1)
    return dict(pnl=pnl.sum(1), lo=day_lo, hi=day_hi, trades=trades, contracts=n, risk=n * S * TICK_USD,
                p=p, target_ticks=T, won=win[:, 0] if k == 1 else None)


def day_table(d):
    """build_day_table's layout, values relative to the day's start.

    The engine credits a bar's high before checking its low, which is right for a short bar and wrong for a whole
    day: a winner's dip comes before its high, so one bar would breach an intraday-trailing account on a day it won.
    One trade a day therefore gets two bars in path order: a winner dips then runs, a loser runs then falls. Multi-trade
    days have no single order and stay one bar. EOD plans only read the day's minimum, so the split cannot change them.
    """
    n = len(d["pnl"])
    idx = list(range(n))
    won = d.get("won")
    if won is None:
        return dict(n=n, start=idx, end=idx, active=[1] * n, time=[0.0] * n, lo=d["lo"].tolist(), hi=d["hi"].tolist(),
                    open=[0.0] * n, close=d["pnl"].tolist(), min_lo=d["lo"].tolist())
    lo, hi, pnl = d["lo"], d["hi"], d["pnl"]
    first_lo, first_hi = np.where(won, lo, 0.0), np.where(won, 0.0, hi)
    first_close = np.where(won, lo, hi)
    bars = lambda a, b: np.stack((a, b), 1).ravel().tolist()
    return dict(n=n, start=list(range(0, 2 * n, 2)), end=list(range(1, 2 * n, 2)), active=[1] * n, time=[0.0] * n,
                lo=bars(first_lo, pnl), hi=bars(first_hi, hi), open=bars(np.zeros(n), first_close),
                close=bars(first_close, pnl), min_lo=np.minimum(first_lo, pnl).tolist())


def attempts(d, plan, paths=4000, horizon=250, seed=1):
    days = day_table(d)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(paths):
        draws = rng.integers(0, days["n"], horizon)
        a = simulate_account(days, lambda k: int(draws[k]) if k < horizon else -1, plan)
        if a["outcome"] != "eval-open":
            out.append(a)
    return out


def replay(d, plan, paths=4000, horizon=250, seed=1):
    done = attempts(d, plan, paths, horizon, seed)
    return (np.array([a["take"] for a in done]), np.array([a["daysUsed"] for a in done]),
            np.array([bool(a["payouts"]) for a in done]), np.array([a["outcome"] != "failed" for a in done]),
            [a["outcome"] for a in done])


def spend_to_break_even(takes, costs, seqs=4000, cap=300, seed=2):
    """Median fees paid buying accounts one after another until cumulative take >= cumulative fees."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(seqs):
        pick = rng.choice(len(takes), cap)
        net = np.cumsum(takes[pick] - costs[pick])
        hit = np.flatnonzero(net >= 0)
        out.append(float(costs[pick[:hit[0] + 1]].sum()) if len(hit) else math.inf)
    return float(np.median(out)), float(np.mean(np.isinf(out)))


def plan_name(plan):
    return f"{plan['planLabel']} {plan['sizeLabel']}{'' if plan['dailyLossLimit'] else ' noDLL'}"


def score(plan, fee, risk, stop_ticks, rr, k=1, mode="fixed", edge=0.0, paths=4000, n_days=40000, seed=0, be=False, rseed=1):
    """`fee` is the flat price; monthly billing and pass-only activation are charged per attempt instead."""
    d = make_days(n_days, risk, stop_ticks, rr, k, mode, edge, seed, plan.get("commissionPerSide", COMM_SIDE))
    done = attempts(d, plan, paths, seed=rseed)
    takes = np.array([a["take"] for a in done])
    used = np.array([a["daysUsed"] for a in done])
    paid = np.array([bool(a["payouts"]) for a in done])
    passed = np.array([a["outcome"] != "failed" for a in done])
    costs = np.full(len(done), float(fee))
    if plan.get("rebillDays") or plan.get("activationOnPass"):
        costs = np.array([attempt_cost(a, plan) for a in done], float)
        fee = float(costs.mean())
    ev = takes.mean() - fee
    se = (takes - costs).std(ddof=1) / math.sqrt(len(takes))
    out = dict(plan=plan_name(plan), fee=fee,
               risk=d["risk"], contracts=d["contracts"], stop_ticks=stop_ticks, rr=rr, k=k, mode=mode, edge=edge,
               p_win=d["p"], trades_per_day=float(d["trades"].mean()), pass_rate=float(passed.mean()),
               p_paid=float(paid.mean()), mean_take=float(takes.mean()), ev=float(ev), ev_ci=[float(ev - 1.96 * se), float(ev + 1.96 * se)],
               days_used=float(used.mean()), ev_per_day=float(ev / used.mean()), breakeven_fee=float(takes.mean()))
    if be:
        out["median_spend_to_breakeven"], out["never_breakeven_share"] = spend_to_break_even(takes, costs)
    return out


def calibrate():
    """Reproduce the established LucidFlex 50K coin-flip figures."""
    plan = resolve_plan("flex", "50k", True)
    base = score(plan, FLEX50_FEE, 750, 375, 1.0, be=True, paths=8000)
    print(json.dumps(base, indent=1))
    for e in (-0.04, -0.02, 0.02, 0.04):
        s = score(plan, FLEX50_FEE, 750, 375, 1.0, edge=e, paths=8000)
        print(f"edge {e:+.2f}R (win {s['p_win']:.3f}): EV {s['ev']:+7.1f} {s['ev_ci']}")


def flex_grid(paths=20000):
    """Risk x R:R x trades/day x stop-after-win on LucidFlex 50K, at no edge and at +0.02R."""
    plan = resolve_plan("flex", "50k", True)
    rows = []
    for n in (1, 2, 3, 4, 6, 8, 10):
        for rr in (0.5, 1.0, 2.0, 3.0):
            for k in (1, 2, 3):
                for mode in (("fixed",) if k == 1 else ("fixed", "until_win")):
                    r0 = score(plan, FLEX50_FEE, n * 187.5, 375, rr, k, mode, 0.0, paths)
                    r1 = score(plan, FLEX50_FEE, n * 187.5, 375, rr, k, mode, 0.02, paths)
                    r0["ev_edge02"] = r1["ev"]; r0["slope_per_002R"] = r1["ev"] - r0["ev"]
                    rows.append(r0)
    return rows


def show(rows, key="ev", top=25):
    print(f"{'plan':<20}{'risk':>7}{'rr':>5}{'k':>3}{'mode':>10}{'tpd':>5} | {'pass':>6}{'paid':>6}{'take':>7}{'EV':>8}{'EV 95% CI':>18}"
          f"{'days':>6}{'EV/day':>7} | {'EV+.02R':>8}{'slope':>7}")
    for r in sorted(rows, key=lambda r: -r[key])[:top]:
        print(f"{r['plan']:<20}{r['risk']:>7.0f}{r['rr']:>5.1f}{r['k']:>3}{r['mode']:>10}{r['trades_per_day']:>5.2f} | {r['pass_rate']:>6.1%}"
              f"{r['p_paid']:>6.1%}{r['mean_take']:>7.0f}{r['ev']:>+8.1f}  [{r['ev_ci'][0]:+6.1f},{r['ev_ci'][1]:+6.1f}]{r['days_used']:>6.1f}"
              f"{r['ev_per_day']:>+7.2f} | {r.get('ev_edge02', float('nan')):>+8.1f}{r.get('slope_per_002R', float('nan')):>+7.1f}")


SHORTLIST = [  # (risk, stop ticks, rr, k, mode): the flex-grid leaders plus the established baseline
    (750, 375, 1.0, 1, "fixed"), (1125, 375, 1.0, 1, "fixed"), (1125, 375, 1.0, 2, "until_win"),
    (562.5, 375, 1.0, 2, "fixed"), (1875, 375, 0.5, 2, "until_win"), (375, 375, 3.0, 2, "until_win"),
    (750, 375, 1.0, 2, "until_win"), (875, 250, 1.0, 1, "fixed"), (1000, 250, 1.0, 1, "fixed"),
    (1250, 250, 1.0, 1, "fixed"),
    (1125, 40, 1.0, 1, "fixed"), (1125, 80, 1.0, 1, "fixed"), (1125, 160, 1.0, 1, "fixed"),
]


def confirm(paths=100000):
    plan = resolve_plan("flex", "50k", True)
    rows = []
    for risk, st, rr, k, mode in SHORTLIST:
        r0 = score(plan, FLEX50_FEE, risk, st, rr, k, mode, 0.0, paths, seed=7, rseed=11, be=True)
        r1 = score(plan, FLEX50_FEE, risk, st, rr, k, mode, 0.02, paths, seed=7, rseed=11)
        rm = score(plan, FLEX50_FEE, risk, st, rr, k, mode, -0.02, paths, seed=7, rseed=11)
        r0.update(ev_edge02=r1["ev"], ev_edge_m02=rm["ev"], slope_per_002R=(r1["ev"] - rm["ev"]) / 2)
        rows.append(r0)
        print(f"{risk:>7.0f} {st:>4}t rr{rr:<4} k{k} {mode:<9} n={r0['contracts']:>2} | pass {r0['pass_rate']:.1%} paid {r0['p_paid']:.1%} "
              f"take {r0['mean_take']:6.1f} EV {r0['ev']:+6.1f} [{r0['ev_ci'][0]:+.1f},{r0['ev_ci'][1]:+.1f}] days {r0['days_used']:5.1f} "
              f"EV/day {r0['ev_per_day']:+5.2f} | -0.02R {rm['ev']:+6.1f} +0.02R {r1['ev']:+6.1f} | spend-to-BE {r0['median_spend_to_breakeven']:.0f}", flush=True)
    return rows


def all_plans(firm="lucid"):
    """Every plan/size of `firm` with the daily loss limit on where the plan has one (None otherwise),
    plus the limit-off variant where the firm makes it the trader's choice."""
    seen, out = set(), []
    for p in _plans():
        key = (p["plan"], p["size"], p["dll"])
        if p["firm"] != firm or key in seen or not (p["dll"] or p.get("dllOptional")):
            continue
        seen.add(key)
        out.append(dict(p))
    return out


def fee_of(plan, scheme="list"):
    return prop_prices.fee(plan, scheme)


def sweep(paths=20000, steps=46, plans=None):
    """Per plan: risk from 0.25x to 1.375x the max loss at 1:1, one trade a day, ~300-tick bracket.
    The contract cap is the funded account's opening tier where it scales up from one."""
    rows = []
    for plan in plans or all_plans():
        fee = fee_of(plan)
        cap = (plan.get("fundedStartMinis") or plan["maxMinis"]) * 10
        for f in np.linspace(0.25, 1.375, steps):
            risk = f * plan["maxLoss"]
            n = int(min(cap, max(1, round(risk / 150))))
            st = max(40, round(risk / (n * TICK_USD)))
            r = score(plan, fee, n * st * TICK_USD, st, 1.0, paths=paths)
            r["risk_frac"] = r["risk"] / plan["maxLoss"]
            rows.append(r)
        best = max((r for r in rows if r["plan"] == rows[-1]["plan"]), key=lambda r: r["ev"])
        print(f"{best['plan']:<20} fee {fee:6.1f} best risk {best['risk']:7.1f} ({best['risk_frac']:.2f}x maxLoss) EV {best['ev']:+7.1f} "
              f"[{best['ev_ci'][0]:+.1f},{best['ev_ci'][1]:+.1f}] EV/day {best['ev_per_day']:+.2f}", flush=True)
    return rows


def aligned(win_net, rr, cushion=0.0):
    """(risk, stop ticks, exact rr) so a target fill nets >= win_net + cushion after commission and entry slip."""
    n = max(1, round(win_net / rr / 150))
    T = math.ceil((win_net + cushion + n * (2 * COMM_SIDE + ENTRY_SLIP_TICKS * TICK_USD)) / (n * TICK_USD))
    S = max(1, round(T / rr))
    return n * S * TICK_USD, S, T / S


def refine(paths=100000):
    """Flex 50K: target sized to clear the $3,000 eval in 4 / 3 / 2 wins, across R:R and a second trade after a loss."""
    plan = resolve_plan("flex", "50k", True)
    rows = []
    for w in (750, 1000, 1500):
        for rr in (0.5, 0.75, 1.0, 1.5, 2.0):
            for k, mode in ((1, "fixed"), (2, "until_win")):
                risk, st, rre = aligned(w, rr)
                r = {e: score(plan, FLEX50_FEE, risk, st, rre, k, mode, e, paths, seed=21, rseed=23, be=(e == 0))
                     for e in (-0.02, 0.0, 0.02)}
                r0 = r[0.0]
                r0.update(win_net=w, ev_edge_m02=r[-0.02]["ev"], ev_edge02=r[0.02]["ev"], slope_per_002R=(r[0.02]["ev"] - r[-0.02]["ev"]) / 2)
                rows.append(r0)
                print(f"win>={w:<5} rr {rr:<4} k{k} {mode:<9} risk {risk:7.1f} ({st}t, n={r0['contracts']}) | pass {r0['pass_rate']:.1%} "
                      f"paid {r0['p_paid']:.1%} take {r0['mean_take']:6.1f} EV {r0['ev']:+6.1f} [{r0['ev_ci'][0]:+.1f},{r0['ev_ci'][1]:+.1f}] "
                      f"days {r0['days_used']:4.1f} EV/day {r0['ev_per_day']:+5.2f} | -.02R {r[-0.02]['ev']:+6.1f} +.02R {r[0.02]['ev']:+6.1f} "
                      f"| BE spend {r0['median_spend_to_breakeven']:.0f}", flush=True)
    return rows


def plan_confirm(paths=100000, top=3, plans=None, sw=None):
    """Fresh seeds for each plan's top `top` sweep risks (removes the sweep's selection bias from the estimate)."""
    sw = sw or json.loads((OUT / "plan_sweep.json").read_text())
    rows = []
    for plan in plans or all_plans():
        name = plan_name(plan)
        cand = sorted((r for r in sw if r["plan"] == name), key=lambda r: -r["ev"])[:top]
        for c in cand:
            r = score(plan, fee_of(plan), c["risk"], c["stop_ticks"], 1.0, paths=paths, seed=31, rseed=37, be=True)
            r1 = score(plan, fee_of(plan), c["risk"], c["stop_ticks"], 1.0, edge=0.02, paths=paths, seed=31, rseed=37)
            r.update(ev_edge02=r1["ev"], risk_frac=c["risk_frac"])
            rows.append(r)
            print(f"{name:<22} fee {r['fee']:6.1f} risk {r['risk']:7.1f} | pass {r['pass_rate']:.1%} paid {r['p_paid']:.1%} take {r['mean_take']:6.1f} "
                  f"EV {r['ev']:+7.1f} [{r['ev_ci'][0]:+.1f},{r['ev_ci'][1]:+.1f}] days {r['days_used']:5.1f} EV/day {r['ev_per_day']:+6.2f} "
                  f"| +.02R {r1['ev']:+7.1f} | BE spend {r['median_spend_to_breakeven']:.0f} never {r['never_breakeven_share']:.1%}", flush=True)
    return rows


OUT = HERE / "data" / "lucid_structure"
FIRM_OUT = HERE / "data" / "prop_structure"


def multi_seed(plan, risk, stop_ticks, rr=1.0, seeds=16, paths=25000):
    """EV across independent day tables. One 40,000-day table has a mean of about +/-0.005R by chance, which is
    a phantom edge that score()'s CI cannot see: its paths all share the table. The spread across tables can."""
    rows = [score(plan, fee_of(plan), risk, stop_ticks, rr, paths=paths, seed=100 + i, rseed=200 + i) for i in range(seeds)]
    evs = np.array([r["ev"] for r in rows])
    se = evs.std(ddof=1) / math.sqrt(seeds)
    mean = lambda k: float(np.mean([r[k] for r in rows]))
    return dict(plan=rows[0]["plan"], risk=rows[0]["risk"], stop_ticks=stop_ticks, contracts=rows[0]["contracts"], fee=mean("fee"),
                pass_rate=mean("pass_rate"), p_paid=mean("p_paid"), mean_take=mean("mean_take"), days_used=mean("days_used"),
                ev=float(evs.mean()), ev_se=float(se), ev_ci=[float(evs.mean() - 2.13 * se), float(evs.mean() + 2.13 * se)],
                ev_per_day=float(evs.mean() / mean("days_used")), seeds=seeds, paths=paths)


def headline(firm, top=6):
    """Best risk per plan from the confirm run, under the max loss, with the leaders re-estimated across day tables."""
    src = OUT / "plan_confirm.json" if firm == "lucid" else FIRM_OUT / firm / "confirm.json"
    plans = {plan_name(p): p for p in all_plans(firm)}
    best = {}
    for r in json.loads(src.read_text()):
        if r["risk"] < plans[r["plan"]]["maxLoss"] and (r["plan"] not in best or r["ev"] > best[r["plan"]]["ev"]):
            best[r["plan"]] = r
    rows = []
    for r in sorted(best.values(), key=lambda r: -r["ev"])[:top]:
        h = multi_seed(plans[r["plan"]], r["risk"], r["stop_ticks"])
        rows.append(h)
        print(f"{h['plan']:<24} risk {h['risk']:7.0f} fee {h['fee']:6.1f} pass {h['pass_rate']:.1%} paid {h['p_paid']:.1%} EV {h['ev']:+7.1f} "
              f"[{h['ev_ci'][0]:+.1f},{h['ev_ci'][1]:+.1f}] days {h['days_used']:.1f} EV/day {h['ev_per_day']:+.2f}", flush=True)
    return sorted(rows, key=lambda r: -r["ev"])


def firm_study(firm):
    """One firm end to end: every plan swept, then re-scored on fresh seeds."""
    plans = all_plans(firm)
    if not plans:
        raise SystemExit(f"no plans for firm {firm!r}; re-run flybrain/tools/export_fixtures.mjs")
    out = FIRM_OUT / firm
    out.mkdir(parents=True, exist_ok=True)
    sw = sweep(plans=plans)
    (out / "sweep.json").write_text(json.dumps(sw, indent=1))
    rows = plan_confirm(plans=plans, sw=sw)
    (out / "confirm.json").write_text(json.dumps(rows, indent=1))
    (out / "headline.json").write_text(json.dumps(headline(firm), indent=1))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["calibrate", "flex", "confirm", "sweep", "refine", "plans", "firm", "headline"])
    ap.add_argument("--firm", default="lucid")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.cmd == "firm":
        firm_study(a.firm)
    elif a.cmd == "headline":
        out = OUT if a.firm == "lucid" else FIRM_OUT / a.firm
        name = "plan_headline.json" if a.firm == "lucid" else "headline.json"
        (out / name).write_text(json.dumps(headline(a.firm), indent=1))
    elif a.cmd == "calibrate":
        calibrate()
    elif a.cmd == "flex":
        rows = flex_grid()
        (OUT / "flex_grid.json").write_text(json.dumps(rows, indent=1))
        print("== by EV per account"); show(rows, "ev")
        print("\n== by EV per trading day"); show(rows, "ev_per_day", 15)
    elif a.cmd == "confirm":
        (OUT / "flex_confirm.json").write_text(json.dumps(confirm(), indent=1))
    elif a.cmd == "sweep":
        (OUT / "plan_sweep.json").write_text(json.dumps(sweep(), indent=1))
    elif a.cmd == "refine":
        (OUT / "flex_refine.json").write_text(json.dumps(refine(), indent=1))
    elif a.cmd == "plans":
        (OUT / "plan_confirm.json").write_text(json.dumps(plan_confirm(), indent=1))
