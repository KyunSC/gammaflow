"""Tests for the PROPOSAL generator prop_realtape/proposals/giveback_synth.py (lucid_structure untouched)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

PKG = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PKG / "proposals"), str(PKG), str(PKG.parent)]
import giveback_synth as G  # noqa: E402
import lucid_structure as L  # noqa: E402


def plan(firm, name):
    return next(p for p in L.all_plans(firm) if L.plan_name(p) == name)


def apex_plan(name="50K Intraday, Tradovate"):
    import importlib.util
    spec = importlib.util.spec_from_file_location("apex_study", PKG.parent / "data/prop_structure/apex/apex_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SETUPS[name][0]


def outcomes(table, p, paths=1500, seed=3):
    return [(a["outcome"], a["take"], a["daysUsed"], a["evalDays"]) for a in G.attempts(table, p, paths, seed=seed)]


def raw_table(d):
    """Every bar of the path, uncompressed (open = hi, as giveback_synth.table)."""
    b = d["bars"]
    day = b["day"]
    starts = np.r_[0, np.flatnonzero(day[1:] != day[:-1]) + 1]
    ends = np.r_[starts[1:], len(day)] - 1
    n = len(starts)
    return dict(n=n, start=starts.tolist(), end=ends.tolist(), active=[1] * n, time=[0.0] * n, lo=b["lo"].tolist(),
                hi=b["hi"].tolist(), open=b["hi"].tolist(), close=b["close"].tolist(),
                min_lo=np.minimum.reduceat(b["lo"], starts).tolist())


# ------------------------------------------------------------------------------- reduces to make_days exactly
@pytest.mark.parametrize("k,mode", [(1, "fixed"), (2, "fixed"), (3, "until_win")])
def test_day_arrays_bit_identical_to_make_days(k, mode):
    kw = dict(n_days=3000, risk=1550, stop_ticks=310, rr=1.0, k=k, mode=mode, seed=5, comm=0.51)
    new, old = G.make_days_giveback(**kw), L.make_days(**kw)
    for key in ("pnl", "lo", "hi", "trades"):
        assert np.array_equal(new[key], old[key]), key
    assert new["contracts"] == old["contracts"] and new["p"] == old["p"] and new["target_ticks"] == old["target_ticks"]
    if k == 1:
        assert np.array_equal(new["won"], old["won"])
    tb = G.table(new, "path")
    assert np.allclose(tb["min_lo"], old["lo"])                              # the dip marginal is the old one
    assert np.allclose([tb["close"][e] for e in tb["end"]], old["pnl"])
    assert np.allclose(np.maximum.reduceat(np.array(tb["hi"]), tb["start"]), old["hi"])


def test_loser_runup_and_winner_dip_are_the_old_laws():
    d = G.make_days_giveback(20000, 1550, 310, 1.0, seed=2)
    stats_mdd, dip = G.trade_stats(d)
    usd, fees = d["usd_per_tick"], d["fees"]
    w = d["won"]
    assert np.allclose(dip[w], -(d["lo"][w] + fees) / usd)                   # winner dip = old worst excursion
    assert np.allclose(np.maximum.reduceat(d["bars"]["hi"], np.r_[0, np.flatnonzero(np.diff(d["bars"]["day"])) + 1])[~w] / usd,
                       d["hi"][~w] / usd)                                     # loser best = old law
    # the excursion process never kills a winner, and a winner's drawdown is at least its dip
    assert (dip[w] < 310).all() and (stats_mdd[w] >= dip[w] - 1e-9).all()


@pytest.mark.parametrize("firm,name,risk,st", [("topstep", "Cons no-fee 50K noDLL", 1550, 310),
                                               ("alpha", "Standard 50K", 1550, 310), ("lucid", "LucidFlex 50K", 1050, 300),
                                               ("mff", "Builder 50K", 1050, 300)])
def test_eod_plans_replay_identically(firm, name, risk, st):
    """EOD-drawdown plans read only the day's minimum: old table, new 'eod' table and the full new path table give
    the same account for every path."""
    p = plan(firm, name)
    assert G.table_mode(p) == "eod"
    d_old = L.make_days(4000, risk, st, 1.0, seed=9, comm=p.get("commissionPerSide", L.COMM_SIDE))
    d_new = G.make_days_giveback(4000, risk, st, 1.0, seed=9, comm=p.get("commissionPerSide", L.COMM_SIDE))
    ref = outcomes(L.day_table(d_old), p)
    assert outcomes(G.plan_table(d_new, p), p) == ref
    assert outcomes(G.table(d_new, "path", p.get("dailyLossLimit")), p) == ref
    assert outcomes(raw_table(d_new), p) == ref


def test_score_mirror_matches_lucid_structure():
    p = plan("lucid", "LucidFlex 50K")
    a = G.score(p, L.fee_of(p), 1050, 300, 1.0, paths=800, n_days=4000, seed=4, rseed=6, giveback=False)
    b = L.score(p, L.fee_of(p), 1050, 300, 1.0, paths=800, n_days=4000, seed=4, rseed=6)
    assert a["ev"] == pytest.approx(b["ev"], abs=1e-9) and a["pass_rate"] == b["pass_rate"]


# ------------------------------------------------------------------------------- compression is exact
@pytest.mark.parametrize("which", ["apex50", "luciddaily50", "rapid50", "luciddaily25"])
def test_path_compression_exact(which):
    p, risk, st = {"apex50": (apex_plan(), 1550, 310), "luciddaily50": (plan("lucid", "LucidDaily 50K"), 2499, 294),
                   "rapid50": (plan("mff", "Rapid 50K noDLL"), 1950, 300),
                   "luciddaily25": (plan("lucid", "LucidDaily 25K"), 650, 325)}[which]
    d = G.make_days_giveback(3000, risk, st, 1.0, seed=11, comm=p.get("commissionPerSide", L.COMM_SIDE), g_min=2.0)
    assert G.table_mode(p) == "path"
    ref = outcomes(raw_table(d), p)
    tb = G.plan_table(d, p)
    assert len(tb["lo"]) < 0.2 * len(d["bars"]["lo"])
    assert outcomes(tb, p) == ref


def test_dll_crossing_bar_is_never_merged():
    """With a DLL, plain merging is not exact (an early DLL freeze would see a later, higher peak)."""
    p = plan("lucid", "LucidDaily 50K")
    d = G.make_days_giveback(3000, 2499, 294, 1.0, seed=12, comm=p.get("commissionPerSide", L.COMM_SIDE), g_min=2.0)
    safe, plain = G.plan_table(d, p), G.table(d, "path", None)
    assert len(safe["lo"]) >= len(plain["lo"])
    assert outcomes(safe, p, 3000) == outcomes(raw_table(d), p, 3000)


def test_small_excursions_cannot_change_decisions():
    """Dropping every excursion shallower than 16 ticks (but keeping each day's deepest dip) changes nothing."""
    p = apex_plan()
    d = G.make_days_giveback(3000, 1550, 310, 1.0, seed=13, comm=0.51, g_min=1.0)
    b = d["bars"]
    depth = (b["hi"] - b["lo"] - d["fees"]) / d["usd_per_tick"]
    starts = np.r_[0, np.flatnonzero(np.diff(b["day"])) + 1]
    is_min = b["lo"] == np.repeat(np.minimum.reduceat(b["lo"], starts), np.diff(np.r_[starts, len(b["lo"])]))
    keep = b["final"] | is_min | (depth >= 16)
    thin = dict(d, bars={k: v[keep] for k, v in b.items()})
    assert keep.mean() < 0.3
    assert outcomes(G.plan_table(thin, p), p) == outcomes(G.plan_table(d, p), p)


# ------------------------------------------------------------------------------- the law
def test_p_mdd_win_formula():
    S = T = 310
    # G <= S: equals Lehoczky's integral (1/S) int_0^T e^{-m/G}/G (m - G + S) dm
    for g in (50, 150, 300):
        m = np.linspace(0, T, 200001)
        f = np.exp(-m / g) / g * (m - g + S)
        lehoczky = float(np.sum((f[1:] + f[:-1]) / 2 * np.diff(m))) / S
        assert G.p_mdd_win(g, S, T) == pytest.approx(lehoczky, rel=1e-6)
    assert G.p_mdd_win(S + T, S, T) == 0.0
    assert G.p_mdd_win(1e-6, S, T) == pytest.approx(1.0)
    # the old generator's winners: drawdown = dip, so P(MDD >= 400) = 0; the new law gives ~10.6%
    assert G.p_dip_win(400, S, T) == 0.0 and 0.10 < G.p_mdd_win(400, S, T) < 0.11


def test_generator_matches_analytic_law():
    d = G.make_days_giveback(60000, 1550, 310, 1.0, seed=21, g_min=20.0)
    mdd, dip = G.trade_stats(d)
    w = d["won"]
    nw = w.sum()
    for g in (150, 250, 350, 450):
        p = G.p_mdd_win(g, 310, 310)
        assert abs((mdd[w] >= g).mean() - p) < 4 * math.sqrt(p * (1 - p) / nw), g
    for x in (50, 150, 250):
        p = G.p_dip_win(x, 310, 310)
        assert abs((dip[w] >= x).mean() - p) < 4 * math.sqrt(p * (1 - p) / nw), x


def _brute_walk(S, T, sigma, n, seed):
    """Gaussian random walk from 0 until <= -S or >= T: (won, max drawdown, dip, best run-up)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n); mx = np.zeros(n); mdd = np.zeros(n); mn = np.zeros(n)
    alive = np.ones(n, bool); won = np.zeros(n, bool)
    while alive.any():
        i = np.flatnonzero(alive)
        x[i] += sigma * rng.standard_normal(i.size)
        mx[i] = np.maximum(mx[i], x[i]); mn[i] = np.minimum(mn[i], x[i])
        mdd[i] = np.maximum(mdd[i], mx[i] - x[i])
        hit_t, hit_s = x[i] >= T, x[i] <= -S
        won[i[hit_t]] = True
        alive[i[hit_t | hit_s]] = False
    return won, mdd, -mn, mx


def test_conditional_laws_match_brute_force_random_walk():
    """P(drawdown >= G | win), P(dip >= d | win), P(run-up >= m | lose) from the excursion generator against a
    brute-force driftless walk with small steps (sigma = S/50; overshoot ~0.6 sigma is inside the tolerance)."""
    S = T = 100.0
    won, mdd, dip, run = _brute_walk(S, T, 2.0, 6000, 0)
    rng = np.random.default_rng(1)
    m = 40000
    u = rng.random(m)
    win = rng.random(m) < S / (S + T)
    D = T * S * (1 - u) / (u * S + T)
    M = S * T * (1 - u) / (u * T + S)
    t, lev, dep = G.excursions(rng, win, S, T, D, M, g_min=0.5)
    gmax = np.zeros(m)
    np.maximum.at(gmax, t, dep)
    gdip = np.zeros(m)
    np.maximum.at(gdip, t, dep - lev)
    tol = lambda p, k: 4 * math.sqrt(p * (1 - p) / k) + 0.02
    wb = won.sum()
    assert abs(won.mean() - 0.5) < 0.03
    for g in (40, 80, 120, 160):
        pb, pg, pa = (mdd[won] >= g).mean(), (gmax[win] >= g).mean(), G.p_mdd_win(g, S, T)
        assert abs(pb - pa) < tol(pa, wb), (g, pb, pa)
        assert abs(pg - pa) < tol(pa, win.sum()) - 0.015, (g, pg, pa)
    for x in (20, 50, 80):
        pb, pg = (dip[won] >= x).mean(), (gdip[win] >= x).mean()
        assert abs(pb - G.p_dip_win(x, S, T)) < tol(pb, wb) and abs(pg - G.p_dip_win(x, S, T)) < 0.01
    lb = ~won
    for x in (20, 50, 80):
        assert abs((run[lb] >= x).mean() - G.p_runup_lose(x, S, T)) < tol(0.3, lb.sum())
    # losers' pre-max excursions never reach the stop and sit below the run-up
    lose_t = ~win[t]
    assert (dep[lose_t] < lev[lose_t] + S).all() and (lev[lose_t] <= M[t[lose_t]] + 1e-9).all()


def test_giveback_lowers_intraday_trail_ev_only():
    """Intraday-trail plan: the new law can only add drawdown, so fewer accounts survive; an EOD plan is unchanged."""
    p = apex_plan()
    a = G.apex_run(p, 1550, 310, 1, 2, 3000, giveback=False)
    b = G.apex_run(p, 1550, 310, 1, 2, 3000, giveback=True)
    assert b["take"] < a["take"]
    q = apex_plan("50K EOD, DLL $1,000")
    assert G.apex_run(q, 1050, 300, 1, 2, 3000, giveback=False) == G.apex_run(q, 1050, 300, 1, 2, 3000, giveback=True)
