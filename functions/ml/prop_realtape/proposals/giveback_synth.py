"""PROPOSAL: a synthetic day generator whose trades carry their whole excursion structure, so a winner can give
back gains from an intra-trade peak (see PROPOSAL.md for the math). Standalone; lucid_structure is imported
read-only and nothing is monkeypatched.

The law is the driftless walk's own, written in excursion theory (Brownian motion; regime-free, no market data):
  * Below its running maximum m, a driftless walk makes excursions whose depths g form a Poisson point process
    in (level m, depth g) with intensity dm dg / g^2 (Ito / Levy; this is what makes the running max at the
    first drawdown of size G exponential with mean G, Lehoczky 1977).
  * Bracket: stop S below, target T above. An excursion from level m kills the trade when g >= m + S.
    - winner: no killing excursion for m in [0, T]: P = exp(-int_0^T dm/(m+S)) = S/(S+T)  (the usual value);
      given a win the excursions are the same Poisson process restricted to g < m + S.
    - loser with best excursion M: the pre-max part is the process on [0, M] restricted to g < m + S, then a
      final excursion from M down to the stop.
  * make_days' existing draws are kept bit-for-bit: the win flags, the uniform u, the stop slip, and from u the
    winner's worst excursion D and the loser's best excursion M (the same conditional laws). Conditional on the
    global minimum D, a winner's deepest-below-start excursion sits at level m* with density ~ 1/(m*+D)^2 on [0, T]
    and has depth m* + D; every other excursion is the Poisson process restricted to g - m < D. So the dip
    marginal is exactly the old one and EOD-drawdown plans replay identically; what is new is that the dip can
    come after a rise (drawdown m* + D from a peak) and that deep excursions from high levels (give-backs) occur.
  * Excursions shallower than `g_min` ticks are dropped (sampled by thinning a homogeneous process). They cannot
    change a breach / DLL decision while g_min is below the trail and the DLL in ticks (see `table`).

$ convention = make_days': a bar's hi is the gross level x tick$ x n, its lo is net of the round-trip fees
(`fees`), the final bar closes at the trade's net pnl. Bars of a day are in path order and relative to the day
start; trades of a multi-trade day are chained at the running net pnl.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ML = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML))
import lucid_structure as L  # noqa: E402
from flybrain.prop import attempt_cost, simulate_account  # noqa: E402

G_MIN = 1.0          # excursion resolution, ticks
PATH_SALT = 0x6B1C   # second RNG stream, so make_days' stream is untouched


# ----------------------------------------------------------------------------------------------------------- laws
def p_mdd_win(G, S, T):
    """P(max drawdown from the running max >= G | win), driftless walk, stop S below, target T above.
    Excursions of depth >= G that do not kill the trade (G <= g < m + S) are Poisson with mean
    I = int_{max(0,G-S)}^{T} (1/G - 1/(m+S)) dm, independent of the killing ones, so P = 1 - exp(-I).
    (For G <= S this equals Lehoczky's (1/S) int_0^T e^{-m/G}/G (m - G + S) dm.)"""
    lo = max(0.0, G - S)
    if lo >= T:
        return 0.0
    return 1.0 - math.exp(-((T - lo) / G - math.log((T + S) / (lo + S))))


def p_dip_win(d, S, T):
    """P(worst excursion >= d | win) = T (S - d) / ((T + d) S) (lucid_structure's mirrored law)."""
    return 0.0 if d >= S else T * (S - d) / ((T + d) * S)


def p_runup_lose(m, S, T):
    """P(best excursion >= m | lose) = S (T - m) / ((S + m) T)."""
    return 0.0 if m >= T else S * (T - m) / ((S + m) * T)


def _ppp(rng, owner, top, cap, g_min):
    """Poisson process of excursions on levels [0, top[i]] with intensity dm dg / g^2, g in [g_min, cap_i(m)),
    by thinning: N ~ Poisson(top/g_min), m ~ U(0, top), g = g_min / v. `cap(i, m)` gives the depth bound."""
    lam = np.maximum(top, 0.0) / g_min
    cnt = rng.poisson(lam)
    t = np.repeat(owner, cnt)
    m = rng.random(t.size) * np.repeat(top, cnt)
    g = g_min / (1.0 - rng.random(t.size))           # 1 - U in (0, 1]: g in [g_min, inf)
    keep = g < cap(np.repeat(np.arange(len(owner)), cnt), m)
    return t[keep], m[keep], g[keep]


def excursions(rng, win, S, T, D, M, g_min=G_MIN):
    """All excursions (trade, level m, depth g) in ticks; winners include their argmax-dip excursion."""
    wi = np.flatnonzero(win)
    li = np.flatnonzero(~win)
    Dw = D[wi]
    # winner: the excursion attaining the global min D, at level m* ~ 1/(m+D)^2 on [0, T]
    v = rng.random(wi.size)
    with np.errstate(divide="ignore"):
        inv = 1.0 / np.maximum(Dw, 1e-12)
        ms = 1.0 / (inv - v * (inv - 1.0 / (T + Dw))) - Dw
    ms = np.clip(ms, 0.0, T)
    t1, m1, g1 = _ppp(rng, wi, np.full(wi.size, float(T)), lambda j, m: m + Dw[j], g_min)
    # loser: pre-max excursions on [0, M] that do not reach the stop
    t2, m2, g2 = _ppp(rng, li, M[li], lambda j, m: m + S, g_min)
    t = np.r_[wi, t1, t2]
    m = np.r_[ms, m1, m2]
    g = np.r_[ms + Dw, g1, g2]
    return t, m, g


# ------------------------------------------------------------------------------------------------------ day tables
def make_days_giveback(n_days, risk, stop_ticks, rr, k=1, mode="fixed", edge=0.0, seed=0, comm=L.COMM_SIDE,
                       g_min=G_MIN, path_seed=None):
    """lucid_structure.make_days with the same signature and the same returned arrays (bit-identical: same RNG
    stream, same draws), plus the path of every live trade as bars in `bars` (see module doc)."""
    rng = np.random.default_rng(seed)
    S = stop_ticks
    T = max(1, round(rr * S))
    n = int(min(L.MAX_CONTRACTS, max(1, math.floor(risk / (S * L.TICK_USD)))))
    p = S / (S + T + 1) + edge * S / (S + T)
    m_ = n_days * k
    win = rng.random(m_) < p
    u = rng.random(m_)
    slip = rng.choice(L.SLIP_T, size=m_, p=L.SLIP_P)
    fees = 2 * comm * n + L.ENTRY_SLIP_TICKS * L.TICK_USD * n
    usd = L.TICK_USD * n
    pnl = np.where(win, T, -S - slip) * usd - fees
    best_loser = S * T * (1 - u) / (u * T + S)
    worst_winner = T * S * (1 - u) / (u * S + T)
    lo = np.where(win, -worst_winner * usd - fees, pnl)
    hi = np.where(win, pnl + fees, best_loser * usd)
    W, P_, LO, HI = (a.reshape(n_days, k) for a in (win, pnl, lo, hi))
    if mode == "until_win":
        first = np.where(W.any(1), W.argmax(1), k - 1)
        live = np.arange(k)[None, :] <= first[:, None]
    else:
        live = np.ones((n_days, k), bool)
    P_, LO, HI = P_ * live, np.where(live, LO, 0.0), np.where(live, HI, 0.0)
    before = np.c_[np.zeros(n_days), np.cumsum(P_, 1)[:, :-1]]
    day_lo = np.minimum(0.0, (before + LO).min(1))
    day_hi = np.maximum(0.0, (before + HI).max(1))
    out = dict(pnl=P_.sum(1), lo=day_lo, hi=day_hi, trades=live.sum(1), contracts=n, risk=n * S * L.TICK_USD,
               p=p, target_ticks=T, won=W[:, 0] if k == 1 else None)

    # ---- new: excursion paths (separate stream)
    prng = np.random.default_rng([seed, PATH_SALT] if path_seed is None else path_seed)
    t, lev, dep = excursions(prng, win, S, T, worst_winner, best_loser, g_min)
    livef = live.ravel()
    keep = livef[t]
    t, lev, dep = t[keep], lev[keep], dep[keep]
    bf = before.ravel()
    lt = np.flatnonzero(livef)
    final_hi = np.where(win, T * usd, best_loser * usd)
    # bars: excursions (sorted by level within trade), then each trade's final bar
    tt = np.r_[t, lt]
    key = np.r_[lev, np.full(lt.size, np.inf)]
    bhi = np.r_[bf[t] + lev * usd, bf[lt] + final_hi[lt]]
    blo = np.r_[bf[t] + (lev - dep) * usd - fees, bf[lt] + pnl[lt]]
    bcl = np.r_[bf[t] + lev * usd, bf[lt] + pnl[lt]]
    order = np.lexsort((key, tt))
    out["bars"] = dict(day=(tt[order] // k), hi=bhi[order], lo=blo[order], close=bcl[order],
                       final=np.r_[np.zeros(t.size, bool), np.ones(lt.size, bool)][order])
    out["fees"] = fees
    out["usd_per_tick"] = usd
    return out


def table_mode(plan):
    """'eod' when no stage trails intraday (one bar a day, = the old table's decisions), else 'path'."""
    return "path" if "intraday" in (plan.get("evalDrawdown"), plan.get("fundedDrawdown")) else "eod"


def table(d, mode="path", dll=None):
    """flybrain.prop.build_day_table layout from make_days_giveback output.

    mode 'eod': one bar per day (open 0, day max, day min, pnl): every decision of an EOD-drawdown plan only reads
    the day's minimum, as in lucid_structure.day_table.
    mode 'path': the bars in path order, compressed exactly for run_stage (hi credited before lo):
      bar p merges into the next bar s when p.lo >= s.lo and p.lo > -dll (p does not cross the DLL level).
      Without a DLL this is replay.compress's 'merge'; with one, a bar that crosses the DLL level is never merged
      into a later one, so a freeze sees the peak of its own time (replay's 'records' concern), and every bar
      after it is irrelevant (the day ends at its first DLL crossing: freeze or breach).
      Vectorised: a bar is kept iff it crosses the DLL, or no crossing bar follows it in its day and its lo is
      below every later lo of the day. A kept bar takes the max hi and first open of the bars merged into it.
    Opens are set to the bar's hi (a continuous path has no gaps; a breach / freeze then fills at the level)."""
    n = len(d["pnl"])
    if mode == "eod":
        idx = list(range(n))
        return dict(n=n, start=idx, end=idx, active=[1] * n, time=[0.0] * n, lo=d["lo"].tolist(), hi=d["hi"].tolist(),
                    open=[0.0] * n, close=d["pnl"].tolist(), min_lo=d["lo"].tolist())
    b = d["bars"]
    day, hi, lo, cl = b["day"], b["hi"], b["lo"], b["close"]
    lvl = -float(dll) if dll else -np.inf
    cross = lo <= lvl
    nb = len(day)
    # reverse segmented cumulative min of lo per day (strictly later bars)
    rank = np.r_[0, np.cumsum(day[1:] != day[:-1])]
    BIG = 4.0 * float(np.abs(lo).max()) + 1.0        # later days must sit higher so a reversed cummin restarts
    sufmin_incl = np.minimum.accumulate((lo + rank * BIG)[::-1])[::-1] - rank * BIG
    later = np.r_[sufmin_incl[1:], np.inf]
    last_in_day = np.r_[day[1:] != day[:-1], True]
    later[last_in_day] = np.inf
    # any crossing strictly later in the same day
    cr_ext = np.append(np.cumsum(cross[::-1].astype(np.int64))[::-1], 0)   # crossings at or after i (global)
    after_day = cr_ext[np.flatnonzero(last_in_day) + 1]                     # crossings after each day's last bar
    later_cross = (cr_ext[1:nb + 1] - after_day[rank]) > 0
    kept = cross | ((~later_cross) & (lo < later))
    K = np.flatnonzero(kept)
    run_start = np.r_[0, K[:-1] + 1]
    # a run never spans days: each day's last bar is kept
    khi = np.maximum.reduceat(hi, run_start)
    kop = hi[run_start]
    klo, kcl, kday = lo[K], cl[K], day[K]
    starts = np.r_[0, np.flatnonzero(kday[1:] != kday[:-1]) + 1]
    ends = np.r_[starts[1:], len(K)] - 1
    assert len(starts) == n and (kday[starts] == np.arange(n)).all()
    return dict(n=n, start=starts.tolist(), end=ends.tolist(), active=[1] * n, time=[0.0] * n, lo=klo.tolist(),
                hi=khi.tolist(), open=kop.tolist(), close=kcl.tolist(), min_lo=np.minimum.reduceat(klo, starts).tolist())


def plan_table(d, plan):
    return table(d, table_mode(plan), plan.get("dailyLossLimit") or None)


# ------------------------------------------------------------------------------------- scoring (mirrors lucid_structure)
def attempts(days, plan, paths=4000, horizon=250, seed=1):
    """lucid_structure.attempts on a prebuilt table (same draws)."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(paths):
        draws = rng.integers(0, days["n"], horizon)
        a = simulate_account(days, lambda k: int(draws[k]) if k < horizon else -1, plan)
        if a["outcome"] != "eval-open":
            out.append(a)
    return out


def score(plan, fee, risk, stop_ticks, rr=1.0, paths=4000, n_days=40000, seed=0, rseed=1, giveback=True, g_min=G_MIN):
    """lucid_structure.score's EV (k=1, no edge). giveback=False uses lucid_structure's own make_days/day_table."""
    comm = plan.get("commissionPerSide", L.COMM_SIDE)
    if giveback:
        d = make_days_giveback(n_days, risk, stop_ticks, rr, seed=seed, comm=comm, g_min=g_min)
        done = attempts(plan_table(d, plan), plan, paths, seed=rseed)
    else:
        d = L.make_days(n_days, risk, stop_ticks, rr, seed=seed, comm=comm)
        done = L.attempts(d, plan, paths, seed=rseed)
    takes = np.array([a["take"] for a in done])
    used = np.array([a["daysUsed"] for a in done])
    paid = np.array([bool(a["payouts"]) for a in done])
    passed = np.array([a["outcome"] != "failed" for a in done])
    costs = np.full(len(done), float(fee))
    if plan.get("rebillDays") or plan.get("activationOnPass"):
        costs = np.array([attempt_cost(a, plan) for a in done], float)
        fee = float(costs.mean())
    return dict(ev=float(takes.mean() - fee), fee=fee, pass_rate=float(passed.mean()), p_paid=float(paid.mean()),
                mean_take=float(takes.mean()), days_used=float(used.mean()), contracts=d["contracts"])


def apex_run(p, risk, st, seed, rseed, paths, giveback=True, eval_limit=21, g_min=G_MIN):
    """apex_study.run (late evaluations count as failed)."""
    comm = p["commissionPerSide"]
    if giveback:
        d = make_days_giveback(40000, risk, st, 1.0, seed=seed, comm=comm, g_min=g_min)
        done = attempts(plan_table(d, p), p, paths, seed=rseed)
    else:
        d = L.make_days(40000, risk, st, 1.0, seed=seed, comm=comm)
        done = L.attempts(d, p, paths, seed=rseed)
    late = np.array([a["evalDays"] > eval_limit for a in done])
    passed = np.array([a["outcome"] != "failed" for a in done]) & ~late
    take = np.where(late, 0.0, [a["take"] for a in done])
    paid = np.array([bool(a["payouts"]) for a in done]) & ~late
    return dict(take=float(take.mean()), pass_rate=float(passed.mean()), p_paid=float(paid.mean()), late=float(late.mean()),
                days=float(np.mean([min(a["daysUsed"], eval_limit) if x else a["daysUsed"] for a, x in zip(done, late)])))


# ------------------------------------------------------------------------------------------- path statistics
def trade_stats(d):
    """Per day (k=1): max drawdown from the running max (ticks, gross of fees) and worst dip, from the bars."""
    b, usd, fees = d["bars"], d["usd_per_tick"], d["fees"]
    day = b["day"]
    hi = b["hi"] / usd
    lo = (b["lo"] + fees) / usd
    rank = np.r_[0, np.cumsum(day[1:] != day[:-1])]
    BIG = 4.0 * float(max(np.abs(hi).max(), np.abs(lo).max())) + 1.0
    runmax = np.maximum.accumulate(np.maximum(hi, 0.0) + rank * BIG) - rank * BIG
    starts = np.r_[0, np.flatnonzero(day[1:] != day[:-1]) + 1]
    mdd = np.maximum.reduceat(runmax - lo, starts)
    dip = -np.minimum(0.0, np.minimum.reduceat(lo, starts))
    return mdd, dip
