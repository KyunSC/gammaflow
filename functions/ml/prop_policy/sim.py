"""Prop account replay with state-dependent risk.

The rules are a line-for-line port of `flybrain.prop.run_stage` / `simulate_account` (read, not imported, so the loop
can be changed without touching shared code). The only difference is that each day's bars come from one of several
day tables, one per risk level, chosen at the start of the day by `policy.level(state)`. All tables are indexed by the
same draw `d`, so when they are built from the same seed every level sees the same coin flips (common random numbers).

With one table and a constant policy this reproduces `flybrain.prop.simulate_account` to the cent (tests/test_sim.py).

Day tables use `flybrain.prop.build_day_table`'s layout: start/end bar index per day, per-bar lo/hi/open/close relative
to the day's opening balance, per-day active flag and min_lo.
"""
from __future__ import annotations

import math

import numpy as np

EPS = 1e-9


def nth(values, k):
    return values[min(k, len(values) - 1)] if values else None


class State:
    """What a policy may read at the start of a day. Updated in place; do not keep references to it."""
    __slots__ = ("plan", "stage", "k", "day", "start", "bal", "threshold", "lock_at", "locked", "dll", "target",
                 "active_days", "best_day", "payouts", "paid", "cycle_start", "cycle_active", "cycle_profit_days",
                 "cycle_best", "goal")

    @property
    def cushion(self):
        """Dollars above the floor (EOD threshold) at the start of the day."""
        return self.bal - self.threshold

    @property
    def profit(self):
        return self.bal - self.start

    @property
    def to_target(self):
        """Dollars of balance still needed. Evaluation: to the profit target. Funded: to the next payout's dollar gates:
        cycle profit > 0 and >= the cycle goal, balance above the buffer, and an amount >= minPayout. The day-count
        and consistency gates are not included (see cycle_active, cycle_profit_days, cycle_best)."""
        if self.stage == "eval":
            return max(0.0, self.target - (self.bal - self.start))
        p = self.plan
        need = self.cycle_start + max(self.goal or 0, 0.01)
        if p["buffer"]:
            need = max(need, p["buffer"] + 0.01)
        if p["payoutFraction"] is not None:
            need = max(need, self.start + p["minPayout"] / p["payoutFraction"])
        else:
            need = max(need, max(p["buffer"] or 0, self.start) + p["minPayout"])
        return max(0.0, need - self.bal)


class Constant:
    def __init__(self, level=0):
        self.lv = level

    def level(self, s):
        return self.lv


def run_stage(tables, next_day, k0, plan, stage, policy, st=None, levels=None):
    """`tables`: list of day tables (one per risk level). `levels`: optional list that receives each day's level."""
    start = plan["startBalance"]
    lock_offset = plan["evalLockOffset"] if stage == "eval" and "evalLockOffset" in plan else plan["lockOffset"]
    lock_at = math.inf if lock_offset is None else start + lock_offset
    intraday = (plan.get("evalDrawdown") if stage == "eval" else plan["fundedDrawdown"]) == "intraday"
    dll = 0 if plan.get("dllFundedOnly") and stage == "eval" else plan["dailyLossLimit"] or 0
    bal = peak = start
    locked = False
    threshold = min(peak - plan["maxLoss"], lock_at)
    active_days = best_day = dll_hits = cycle_active = cycle_profit_days = cycle_best = 0
    cycle_start = start
    payouts = []
    s = st or State()
    s.plan, s.best_day = plan, 0  # best_day only moves in the evaluation; it stays 0 when funded
    s.stage, s.start, s.lock_at, s.dll, s.target, s.payouts = stage, start, lock_at, dll, plan["profitTarget"], payouts

    def done(status, reason, k):
        return dict(status=status, reason=reason, days=k - k0, payouts=payouts, dllHits=dll_hits, balance=bal)

    k = k0
    while True:
        d = next_day(k)
        if d < 0:
            return done("open", "end-of-data", k)
        s.k, s.day, s.bal, s.threshold, s.locked = k, k - k0, bal, threshold, locked
        s.active_days, s.best_day, s.paid = active_days, best_day, len(payouts)
        s.cycle_start, s.cycle_active, s.cycle_profit_days, s.cycle_best = cycle_start, cycle_active, cycle_profit_days, cycle_best
        s.goal = nth(plan["profitGoal"], len(payouts)) or 0
        lv = policy.level(s)
        if levels is not None:
            levels.append(lv)
        days = tables[lv]
        st_i, e = days["start"][d], days["end"][d]
        lo, hi, op = days["lo"], days["hi"], days["open"]
        day_base = bal
        dll_level = day_base - dll if dll else -math.inf
        pnl = None
        safe = not intraday and day_base + days["min_lo"][d] > max(threshold, dll_level)
        for i in (() if safe else range(st_i, e + 1)):
            if intraday and not locked:
                peak = max(peak, day_base + hi[i])
                threshold = min(peak - plan["maxLoss"], lock_at)
            worst = day_base + lo[i]
            if dll and worst <= dll_level and dll_level > threshold:
                frozen = min(dll_level, day_base + op[i])
                dll_hits += 1
                if frozen <= threshold:
                    bal = frozen
                    return done("breached", "max-loss", k + 1)
                pnl = frozen - day_base
                break
            if worst <= threshold:
                bal = min(threshold, day_base + op[i])
                return done("breached", "max-loss", k + 1)
        if pnl is None:
            pnl = days["close"][e]
        bal = day_base + pnl
        act = days["active"][d] == 1
        if act:
            active_days += 1
        if not locked:
            peak = max(peak, bal)
            threshold = min(peak - plan["maxLoss"], lock_at)
        if stage == "eval":
            best_day = max(best_day, pnl)
            profit = bal - start
            if (active_days >= plan["evalMinDays"] and profit >= plan["profitTarget"]
                    and (not plan["evalConsistency"] or best_day <= plan["evalConsistency"] * profit + EPS)):
                return done("passed", "target", k + 1)
            k += 1
            continue
        if act:
            cycle_active += 1
        if act and pnl > 0 and pnl >= plan["minDayProfit"]:
            cycle_profit_days += 1
        cycle_best = max(cycle_best, pnl)
        cycle_profit = bal - cycle_start
        idx = len(payouts)
        goal = nth(plan["profitGoal"], idx) or 0
        c = plan["fundedConsistency"]
        consistent = not c or (cycle_best < c * cycle_profit - EPS if plan.get("fundedConsistencyStrict")
                               else cycle_best <= c * cycle_profit + EPS)
        eligible = (cycle_active >= plan["fundedMinDays"] and cycle_profit_days >= plan["minProfitDays"] and cycle_profit > 0
                    and cycle_profit >= goal and consistent and (not plan["buffer"] or bal > plan["buffer"]))
        if eligible:
            amount = (plan["payoutFraction"] * (bal - start) if plan["payoutFraction"] is not None
                      else bal - max(plan["buffer"] or 0, start))
            cap = nth(plan["payoutCap"], idx)
            if cap is not None and cap > 0:
                amount = min(amount, cap)
            amount = math.floor(amount)
            if amount >= plan["minPayout"]:
                payouts.append(amount)
                bal -= amount
                if not plan.get("payoutKeepsMll"):
                    locked = True
                    threshold = lock_at
                cycle_start = bal
                cycle_active = cycle_profit_days = cycle_best = 0
                if len(payouts) >= plan["maxPayouts"]:
                    return done("graduated", "max-payouts", k + 1)
        k += 1


def simulate_account(tables, next_day, plan, policy=None, levels=None):
    """Same output dict as flybrain.prop.simulate_account. `tables` may be a single day table (constant risk)."""
    if isinstance(tables, dict):
        tables = [tables]
    policy = policy or Constant(0)
    out = dict(outcome=None, reason=None, evalDays=0, fundedDays=0, payouts=[], take=0, daysUsed=0, dllHits=0)
    k = 0
    st = State()
    if plan["hasEval"]:
        ev = run_stage(tables, next_day, 0, plan, "eval", policy, st, levels)
        out["evalDays"] = ev["days"]
        out["dllHits"] += ev["dllHits"]
        k = ev["days"]
        if ev["status"] != "passed":
            out.update(outcome="failed" if ev["status"] == "breached" else "eval-open", reason=ev["reason"], daysUsed=k)
            return out
    fu = run_stage(tables, next_day, k, plan, "funded", policy, st, levels)
    out.update(fundedDays=fu["days"], dllHits=out["dllHits"] + fu["dllHits"], payouts=fu["payouts"],
               outcome="funded-breached" if fu["status"] == "breached" else "graduated" if fu["status"] == "graduated" else "funded-open",
               reason=fu["reason"], take=plan["split"] * sum(fu["payouts"]), daysUsed=k + fu["days"])
    return out


def attempt_cost(attempt, plan):
    """What one attempt paid the firm (port of flybrain.prop.attempt_cost)."""
    rebill = plan.get("rebillDays")
    cycles = max(1, math.ceil(attempt["evalDays"] / rebill)) if rebill else 1
    activation = 0 if plan.get("activationOnPass") and attempt["outcome"] == "failed" else plan["activationFee"] or 0
    return plan["price"] * cycles + activation


def attempts(tables, plan, policy=None, paths=4000, horizon=250, seed=1, levels=False, drop_open=False):
    """Port of lucid_structure.attempts: iid day draws, same RNG stream. With levels=True each attempt carries the
    list of levels it used.

    drop_open=True drops attempts still in evaluation at the horizon, as lucid_structure does (parity only). The
    default keeps them so `summarize` can charge them as failures: a policy that stalls near the target must not
    drop its unresolved attempts out of the denominator."""
    tl = tables if isinstance(tables, list) else [tables]
    n = len(tl[0]["start"])
    assert all(len(t["start"]) == n for t in tl), "all risk levels must share the same day draws"
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(paths):
        draws = rng.integers(0, n, horizon)
        lv = [] if levels else None
        a = simulate_account(tables, lambda k: int(draws[k]) if k < horizon else -1, plan, policy, lv)
        if a["outcome"] != "eval-open" or not drop_open:
            if levels:
                a["levels"] = lv
            out.append(a)
    return out


def summarize(done, plan, fee=None, eval_limit=None):
    """EV per attempt as lucid_structure.score / apex_study.run compute it.

    fee=None charges attempt_cost per attempt (rebill and pass-only activation); a number charges that flat price.
    eval_limit (Apex): an evaluation longer than this many days counts as failed, with no take and no activation.
    Attempts still in evaluation at the horizon ('eval-open') count as failed and pay what a failure pays (rebill
    cycles out to the horizon, no activation); `censored` reports their share."""
    if plan.get("firm") == "apex":
        assert eval_limit is not None, "Apex plans need eval_limit (the 21-day evaluation rule)"
    open_ = np.array([a["outcome"] == "eval-open" for a in done])
    done = [dict(a, outcome="failed") if o else a for a, o in zip(done, open_)]
    take = np.array([a["take"] for a in done], float)
    used = np.array([a["daysUsed"] for a in done], float)
    passed = np.array([a["outcome"] != "failed" for a in done])
    paid = np.array([bool(a["payouts"]) for a in done])
    if eval_limit is not None:
        late = np.array([a["evalDays"] > eval_limit for a in done])
        take = np.where(late, 0.0, take)
        passed &= ~late
        paid &= ~late
        used = np.where(late, np.minimum(used, eval_limit), used)
        costs = np.array([plan["price"] + (0 if (a["outcome"] == "failed" or l) and plan.get("activationOnPass") else plan["activationFee"] or 0)
                          for a, l in zip(done, late)], float)
    elif fee is None or plan.get("rebillDays") or plan.get("activationOnPass"):
        costs = np.array([attempt_cost(a, plan) for a in done], float)
    else:
        costs = np.full(len(done), float(fee))
    net = take - costs
    return dict(n=len(done), censored=float(open_.mean()), ev=float(net.mean()), ev_se=float(net.std(ddof=1) / math.sqrt(len(net))), mean_take=float(take.mean()),
                cost=float(costs.mean()), pass_rate=float(passed.mean()), p_paid=float(paid.mean()), days_used=float(used.mean()))
