"""Sizing policies: map the start-of-day account state (sim.State) to an index into a plan's level menu.

A menu is a list of outcomes.Level sorted by realised risk. Every policy only returns indices in `allowed` (the risk
cap), so a capped policy can never size above 0.5x the max loss.

  Fixed(e, f)        one level in the evaluation, another once funded (class 1; e == f is the one-risk headline)
  Ladder(...)        risk that clears what is still needed in k wins, re-chosen daily, capped by the floor cushion (class 2)
  Grid(table)        level per (stage, cushion tercile, remaining-need tercile) (class 3)
  Staged(ev, fu)     evaluation policy of one class, funded policy of another
  Lookup(...)        a dynamic-programming table over (cushion, need) on a $ grid (class 4)

`need(s)` is the profit still needed in the current stage, including the consistency rules, which `State.to_target`
leaves out: an evaluation with consistency c cannot pass until profit >= best_day / c; a funded cycle with consistency
c cannot pay until cycle profit >= cycle_best / c.
"""
from __future__ import annotations

import bisect

import numpy as np

EPS = 1e-6


def need(s):
    p = s.plan
    if s.stage == "eval":
        req = p["profitTarget"]
        c = p["evalConsistency"]
        if c and s.best_day > 0:
            req = max(req, s.best_day / c)
        return max(0.0, req - (s.bal - s.start))
    n = s.to_target
    c = p["fundedConsistency"]
    if c and s.cycle_best > 0:
        n = max(n, s.cycle_best / c - (s.bal - s.cycle_start) + 0.01)
    return max(0.0, n)


def loss95(lv):
    """Net loss (positive $) of a stop-out at the 95th percentile of the stop-slip PMF."""
    from lucid_structure import SLIP_P
    q = np.searchsorted(np.cumsum(SLIP_P), 0.95)
    return float(-lv.loss_net[min(q, len(lv.loss_net) - 1)])


class Policy:
    kind = "policy"

    def bind(self, menu, allowed):
        self.menu, self.allowed = menu, list(allowed)
        return self

    def params(self):
        return {}

    def risks(self):
        return {}


class Fixed(Policy):
    kind = "fixed"

    def __init__(self, e, f):
        self.e, self.f = e, f

    def level(self, s):
        return self.e if s.stage == "eval" else self.f

    def params(self):
        return dict(eval=self.e, funded=self.f)

    def describe(self):
        e, f = self.menu[self.e].risk, self.menu[self.f].risk
        if self.e == self.f:
            return f"risk ${e:,.0f} every day, evaluation and funded"
        return f"risk ${e:,.0f} a day in the evaluation, then ${f:,.0f} once funded"


class Ladder(Policy):
    """Smallest allowed level whose target fill nets >= need / k; if none, the largest allowed. Then capped so a
    95th-percentile stop-out stays above the floor (down to the smallest allowed level). When nothing is needed in
    dollars (waiting on day counts), trade `hold`."""
    kind = "ladder"

    def __init__(self, k_eval, k_funded, hold):
        self.ke, self.kf, self.hold = k_eval, k_funded, hold

    def bind(self, menu, allowed):
        super().bind(menu, allowed)
        self.win = [menu[i].win_net for i in self.allowed]
        self.l95 = [loss95(menu[i]) for i in self.allowed]
        return self

    def level(self, s):
        n = need(s)
        k = self.ke if s.stage == "eval" else self.kf
        if n <= 0:
            return self.hold
        j = bisect.bisect_left(self.win, n / k)
        j = min(j, len(self.allowed) - 1)
        cush = s.bal - s.threshold
        while j > 0 and self.l95[j] >= cush:
            j -= 1
        return self.allowed[j]

    def params(self):
        return dict(k_eval=self.ke, k_funded=self.kf, hold=self.hold)

    def describe(self):
        return (f"size so {self.ke} win(s) clear what the evaluation still needs and {self.kf} win(s) clear what the next "
                f"payout needs, never risking more than the cushion; ${self.menu[self.hold].risk:,.0f} while only waiting on days")


def tercile(x):
    return 0 if x < 1 / 3 else 1 if x < 2 / 3 else 2


class Grid(Policy):
    """table[(stage, cushion bin, need bin)] -> level. Cushion bins: (bal - floor) / maxLoss in [0,1/3), [1/3,2/3), >= 2/3.
    Need bins: need / profitTarget in the evaluation, need / maxLoss when funded, same cut points."""
    kind = "grid"
    CELLS = [(st, c, n) for st in ("eval", "funded") for c in range(3) for n in range(3)]

    def __init__(self, table):
        self.t = dict(table)

    def cell(self, s):
        p = s.plan
        c = tercile((s.bal - s.threshold) / p["maxLoss"])
        ref = p["profitTarget"] if s.stage == "eval" else p["maxLoss"]
        return (s.stage, c, tercile(need(s) / ref))

    def level(self, s):
        return self.t[self.cell(s)]

    def params(self):
        return {f"{a}|cushion{b}|need{c}": v for (a, b, c), v in self.t.items()}

    def describe(self):
        names = ("low", "mid", "high")
        out = []
        for st in ("eval", "funded"):
            rows = [f"cushion {names[c]}: " + "/".join(f"${self.menu[self.t[(st, c, n)]].risk:,.0f}" for n in range(3)) for c in range(3)]
            out.append(f"{st} (need low/mid/high) " + "; ".join(rows))
        return " | ".join(out)


class Staged(Policy):
    kind = "staged"

    def __init__(self, ev, fu):
        self.ev, self.fu = ev, fu

    def bind(self, menu, allowed):
        super().bind(menu, allowed)
        self.ev.bind(menu, allowed)
        self.fu.bind(menu, allowed)
        return self

    def level(self, s):
        return (self.ev if s.stage == "eval" else self.fu).level(s)

    def params(self):
        return dict(eval=dict(kind=self.ev.kind, **self.ev.params()), funded=dict(kind=self.fu.kind, **self.fu.params()))

    def describe(self):
        def part(p, st):
            if isinstance(p, Fixed):
                return f"${self.menu[p.e if st == 'eval' else p.f].risk:,.0f} a day"
            if isinstance(p, Ladder):
                k = p.ke if st == "eval" else p.kf
                return f"size so {k} win(s) clear what is still needed, cushion-capped" + \
                    ("" if st == "eval" else f", ${self.menu[p.hold].risk:,.0f} while waiting on days")
            if isinstance(p, Grid):
                return [x for x in p.describe().split(" | ") if x.startswith(st)][0]
            return p.describe()
        return f"evaluation: {part(self.ev, 'eval')}; funded: {part(self.fu, 'funded')}"


class Lookup(Policy):
    """Class 4: a DP policy over (cushion, need) on a $ grid, one table per stage; nearest grid cell, clipped."""
    kind = "dp"

    def __init__(self, tables, step, fallback):
        self.tables, self.step, self.fb = tables, step, fallback

    def level(self, s):
        t = self.tables.get(s.stage)
        if t is None:
            return self.fb.level(s)
        c = int(round((s.bal - s.threshold) / self.step))
        n = int(round(need(s) / self.step))
        c = min(max(c, 0), t.shape[0] - 1)
        n = min(max(n, 0), t.shape[1] - 1)
        return int(t[c, n])

    def describe(self):
        return "dynamic-programming table over (cushion, remaining target)"
