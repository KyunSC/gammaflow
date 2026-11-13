"""One-day outcome tables per risk level, for the sizing-policy search. No market data.

A day in `lucid_structure.make_days` (one 1:1 bracket, rr = 1) is fixed by three draws that do not depend on risk:
the win uniform r, the excursion uniform u and the stop slip in ticks, drawn in that order from
`default_rng(seed)`. So instead of storing 40,000-day tables for every level, this stores:

  data/prop_policy/outcomes/draws.npz       r, u, slip per seed (seeds 0-7 select, 100-115 re-score), 40,000 days
  data/prop_policy/outcomes/c<comm>.npz     per commission (all plans trade MNQ, $0.50/tick): the bracket of every
                                            $25 grid level, its win net, its loss net per slip value, and p(win)

`day_table(level, seed)` rebuilds `lucid_structure.day_table(make_days(...))` exactly (tests/test_outcomes.py). All
levels built from one seed share the same draws, so a policy that switches levels sees common random numbers.

Brackets follow `lucid_structure.sweep`: n = min(cap, max(1, round(risk / 150))) contracts with
cap = (fundedStartMinis or maxMinis) x 10, stop = max(40, round(risk / (n x $0.50))) ticks, target = stop (1:1).
Not modelled, as in every headline: flat-by time, news, timeouts (every trade reaches its stop or target), so there
are no flat-by partials to record.
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
import lucid_structure as L  # noqa: E402

OUT = ML / "data" / "prop_policy" / "outcomes"
PLANS_JSON = ML / "data" / "prop_policy" / "plans.json"
N_DAYS = 40000
SELECT_SEEDS = tuple(range(8))
SCORE_SEEDS = tuple(range(100, 116))
STEP = 25.0


def plans():
    return json.loads(PLANS_JSON.read_text())


def cap_of(plan):
    return (plan.get("fundedStartMinis") or plan["maxMinis"]) * 10


def bracket(plan, risk):
    """(contracts, stop ticks, realised risk) for a nominal $ risk, by the sweep rule."""
    n = int(min(cap_of(plan), max(1, round(risk / 150))))
    st = max(40, round(risk / (n * L.TICK_USD)))
    return n, st, n * st * L.TICK_USD


def grid(plan):
    """Nominal $ risks from 0.2x to 1.0x the max loss on a $25 grid."""
    lo, hi = 0.2 * plan["maxLoss"], plan["maxLoss"]
    return np.arange(math.ceil(lo / STEP) * STEP, hi + 1e-9, STEP)


class Level:
    """One bracket: n contracts, S-tick stop, S-tick target, at a commission."""
    __slots__ = ("n", "S", "T", "comm", "risk", "p", "fees", "win_net", "loss_net")

    def __init__(self, n, S, comm):
        self.n, self.S, self.T, self.comm = int(n), int(S), int(S), float(comm)
        self.risk = self.n * self.S * L.TICK_USD
        assert int(min(L.MAX_CONTRACTS, max(1, math.floor(self.risk / (self.S * L.TICK_USD))))) == self.n
        self.p = self.S / (self.S + self.T + 1)
        self.fees = 2 * self.comm * self.n + L.ENTRY_SLIP_TICKS * L.TICK_USD * self.n
        self.win_net = self.T * L.TICK_USD * self.n - self.fees
        self.loss_net = (-self.S - L.SLIP_T) * L.TICK_USD * self.n - self.fees  # one per slip value

    def __repr__(self):
        return f"Level(n={self.n}, S={self.S}, risk={self.risk:.1f}, comm={self.comm})"

    def key(self):
        return (self.n, self.S, self.comm)


def plan_levels(plan, extra=()):
    """The plan's distinct brackets on its grid (sorted by realised risk), plus any extra (n, S) pairs, e.g. the
    fixed-risk headline bracket."""
    seen = {}
    for r in grid(plan):
        n, st, _ = bracket(plan, r)
        seen[(n, st)] = None
    for n, st in extra:
        seen[(int(n), int(st))] = None
    lv = [Level(n, st, plan["commissionPerSide"]) for n, st in seen]
    return sorted(lv, key=lambda x: (x.risk, x.n))


@lru_cache(maxsize=64)
def draws(seed, n_days=N_DAYS):
    """make_days' three draws for one seed (k = 1): r (win uniform), u (excursion uniform), slip ticks."""
    path = OUT / "draws.npz"
    if n_days == N_DAYS and path.exists():
        z = np.load(path)
        if f"r{seed}" in z:
            return z[f"r{seed}"], z[f"u{seed}"], z[f"slip{seed}"].astype(np.int64)
    rng = np.random.default_rng(seed)
    r = rng.random(n_days)
    u = rng.random(n_days)
    slip = rng.choice(L.SLIP_T, size=n_days, p=L.SLIP_P)
    return r, u, slip


def day_arrays(lv, seed, n_days=N_DAYS):
    """Exactly make_days(n_days, lv.risk, lv.S, 1.0, seed=seed, comm=lv.comm) for k = 1: pnl, lo, hi, won."""
    r, u, slip = draws(seed, n_days)
    S, T, n, fees = lv.S, lv.T, lv.n, lv.fees
    win = r < lv.p
    pnl = np.where(win, T, -S - slip) * L.TICK_USD * n - fees
    best_loser = S * T * (1 - u) / (u * T + S)
    worst_winner = T * S * (1 - u) / (u * S + T)
    lo = np.where(win, -worst_winner * L.TICK_USD * n - fees, pnl)
    hi = np.where(win, pnl + fees, best_loser * L.TICK_USD * n)
    day_lo = np.minimum(0.0, lo)
    day_hi = np.maximum(0.0, hi)
    return pnl, day_lo, day_hi, win


def day_table(lv, seed, n_days=N_DAYS, as_list=True):
    """lucid_structure.day_table(make_days(...)) for this level and seed (two bars a day, in path order)."""
    pnl, lo, hi, won = day_arrays(lv, seed, n_days)
    t = L.day_table(dict(pnl=pnl, lo=lo, hi=hi, won=won))
    if not as_list:
        t = {k: (np.asarray(v) if isinstance(v, list) else v) for k, v in t.items()}
    return t


def build():
    """Write draws.npz and one c<comm>.npz per commission (the union of that commission's plans' grids)."""
    OUT.mkdir(parents=True, exist_ok=True)
    arrs = {}
    for s in SELECT_SEEDS + SCORE_SEEDS:
        r, u, slip = draws(s)
        arrs[f"r{s}"], arrs[f"u{s}"], arrs[f"slip{s}"] = r, u, slip.astype(np.int16)
    np.savez_compressed(OUT / "draws.npz", **arrs)
    st = json.loads((ML / "data" / "prop_policy" / "state.json").read_text())
    heads = st["fixed_risk_headlines"]
    by_comm, summary = {}, {}
    for name, e in plans().items():
        p = e["plan"]
        h = heads[name]
        hn = int(round(h["risk"] / (h["stop_ticks"] * L.TICK_USD)))
        lv = plan_levels(p, extra=[(hn, h["stop_ticks"])])
        by_comm.setdefault(p["commissionPerSide"], {}).update({x.key(): x for x in lv})
        summary[name] = dict(comm=p["commissionPerSide"], cap=cap_of(p), levels=len(lv), risk_min=lv[0].risk, risk_max=lv[-1].risk,
                             headline=[hn, h["stop_ticks"], hn * h["stop_ticks"] * L.TICK_USD],
                             cap_binds=any(bracket(p, r)[0] == cap_of(p) and round(r / 150) > cap_of(p) for r in grid(p)))
    for comm, lvs in by_comm.items():
        lv = sorted(lvs.values(), key=lambda x: (x.risk, x.n))
        np.savez_compressed(OUT / f"c{comm:.2f}.npz", comm=comm, tick_usd=L.TICK_USD, n=[x.n for x in lv], S=[x.S for x in lv],
                            risk=[x.risk for x in lv], p=[x.p for x in lv], fees=[x.fees for x in lv],
                            win_net=[x.win_net for x in lv], loss_net=np.array([x.loss_net for x in lv]),
                            slip_ticks=L.SLIP_T, slip_p=L.SLIP_P)
    (OUT / "levels.json").write_text(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    for k, v in build().items():
        print(f"{k:<36} {v}")
