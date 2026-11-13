"""Tests for the cross-era historical replay (prop_realtape/hist_fix.py).

run: ../../.venv/bin/python -m pytest prop_realtape/tests -q
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PKG = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PKG), str(PKG.parent)]
import hist_fix as HF  # noqa: E402
import lucid_structure as L  # noqa: E402
import replay as RP  # noqa: E402

PLAN = next(p for p in L.all_plans("lucid") if L.plan_name(p) == "LucidFlex 50K")
FEE = L.fee_of(PLAN)
ERAS2 = ("2011-18", "2019-21")


def toy(pnl_long, pnl_short=None, eras=None, seed=0, start=date(2018, 11, 1)):
    """A day table from daily close pnl per side (one bar per day: open 0, hi max(0, c), lo min(0, c)) and a
    days frame with consecutive dates and the given era labels."""
    pnl_long = np.asarray(pnl_long, float)
    pnl_short = -pnl_long if pnl_short is None else np.asarray(pnl_short, float)
    bars = []
    for a, b in zip(pnl_long, pnl_short):
        for c in (a, b):
            bars.append(np.array([[0.0, max(0.0, c), min(0.0, c), c]]))
    n = len(pnl_long)
    dates = [start + timedelta(days=i) for i in range(n)]
    era = eras if eras is not None else ["2011-18"] * n
    return RP.table_from_bars(bars), pd.DataFrame(dict(date=dates, era=era))


def random_tape(n, seed, sd=700.0):
    rng = np.random.default_rng(seed)
    return np.round(rng.normal(60.0, sd, n), 2)


# ---- sequences --------------------------------------------------------------------------------------------------
def test_cont_seq_crosses_the_era_boundary_and_era_seq_does_not():
    order = np.arange(100, 130)                              # 30 pooled days; era boundary at position 20
    s = HF.cont_seq(order, 15, horizon=10)
    assert s.tolist() == list(range(115, 125))               # runs into the next era
    assert HF.era_seq(order, 15, 20, horizon=10).tolist() == list(range(115, 120))
    assert HF.cont_seq(order, 25, horizon=10).tolist() == list(range(125, 130))    # only the data end truncates
    assert HF.era_seq(order, 5, 20, horizon=10).tolist() == HF.cont_seq(order, 5, horizon=10).tolist()


def test_hybrid_seq_is_real_then_same_era_blocks():
    order = np.arange(40)
    era_pos = np.arange(25, 40)
    rng = np.random.default_rng(3)
    d, n_real = HF.hybrid_seq(order, 33, era_pos, rng, horizon=20, block=4)
    assert n_real == 7 and len(d) == 20
    assert d[:7].tolist() == list(range(33, 40))
    assert set(d[7:].tolist()) <= set(range(25, 40))
    full, k = HF.hybrid_seq(order, 2, era_pos, rng, horizon=20)
    assert k == 20 and full.tolist() == list(range(2, 22))   # enough real days: no completion


# ---- replay -----------------------------------------------------------------------------------------------------
def test_single_era_fixed_replay_equals_old_replay_exactly():
    """No era boundary to cross: every variant that keeps all starts equals replay.hist_seqs + replay.run."""
    n = 220
    table, days = toy(random_tape(n, 1))
    for coin in (0, 5):
        sides = RP.coin_sides(days["date"].tolist(), coin)
        idx = np.arange(n)
        ref = RP.summarize(RP.run(table, RP.hist_seqs(idx, sides, horizon=60), PLAN), PLAN, FEE)
        r = HF.hist_coin(table, PLAN, FEE, days, coin, horizon=60, eras=("2011-18",))
        for var in ("old", "cont"):
            for view in ("pooled", "2011-18"):
                got = r[view][var]
                assert {k: got[k] for k in ref} == ref, (coin, var, view)


def test_two_eras_without_truncation_equal_old():
    """Every account resolves on its first day (both sides lose more than the max loss): nothing is truncated,
    so the fixed replay equals the old one in every view."""
    plan = dict(PLAN, dailyLossLimit=0)                      # no DLL freeze: a -2,500 day breaches at once
    table, days = toy(np.full(40, -2500.0), np.full(40, -2500.0), eras=["2011-18"] * 25 + ["2019-21"] * 15)
    r = HF.hist_coin(table, plan, FEE, days, 0, horizon=30, eras=ERAS2)
    for view in ("pooled",) + ERAS2:
        assert r[view]["old"]["trunc_share"] == 0.0
        for k in ("ev", "n", "pass_rate", "days_used", "trunc_share"):
            assert r[view]["cont"][k] == r[view]["old"][k] == r[view]["hybrid"][k]
    assert r["2011-18"]["n_starts"] == 25 and r["2019-21"]["n_starts"] == 15


def test_late_era_starts_continue_and_keep_their_start_era_label():
    """Era 1 is flat (accounts stay open), era 2 wins every day on both sides. The old replay drops late era-1
    accounts as eval-open at the era end; the fix carries them into era 2, where they pass, and still counts them
    in era 1. Era 2 (the last era) is unchanged: only the data end truncates it."""
    n1, n2, H = 30, 30, 12
    pl = np.r_[np.zeros(n1), np.full(n2, 800.0)]
    table, days = toy(pl, pl, eras=["2011-18"] * n1 + ["2019-21"] * n2)
    r = HF.hist_coin(table, PLAN, FEE, days, 0, horizon=H, eras=ERAS2)
    old, new = r["2011-18"]["old"], r["2011-18"]["cont"]
    assert r["2011-18"]["n_starts"] == n1                     # era label = start day
    assert old["trunc_eval_open"] > 0 and old["n"] < old["n_all"]
    assert new["trunc_share"] == 0.0                          # era-1 starts all have H real days after them
    assert new["n"] > old["n"] and new["pass_rate"] > 0 and old["n"] == 0
    for k in ("ev", "n", "trunc_share"):
        assert r["2019-21"]["old"][k] == r["2019-21"]["cont"][k]
    # an era-1 start 3 days before the boundary trades era-2 days
    order, era, b = HF.pool_layout(days, ERAS2)
    a = HF.sim(table, HF.ids(HF.cont_seq(order, n1 - 3, H), np.zeros(len(days), int)), PLAN)
    assert a["outcome"] != "eval-open" and a["evalDays"] > 3


def test_drop_is_by_start_date_and_hybrid_completes_late_starts():
    n, H = 90, 30
    table, days = toy(random_tape(n, 2), eras=["2011-18"] * 50 + ["2019-21"] * 40)
    r = HF.hist_coin(table, PLAN, FEE, days, 1, horizon=H, eras=ERAS2)
    assert r["pooled"]["n_starts_drop"] == n - H + 1          # starts p with p + H <= n
    assert r["2011-18"]["n_starts_drop"] == 50 and r["2019-21"]["n_starts_drop"] == 40 - H + 1
    assert r["pooled"]["drop"]["trunc_share"] == 0.0
    assert r["pooled"]["hybrid"]["trunc_share"] == 0.0        # completed to the full horizon
    again = HF.hist_coin(table, PLAN, FEE, days, 1, horizon=H, eras=ERAS2)
    assert again["pooled"]["hybrid"] == r["pooled"]["hybrid"]  # seeded


def test_summ_truncation_fields():
    acc = lambda o, take, L_: dict(outcome=o, take=take, daysUsed=L_, payouts=[take] if take else [], evalDays=1,
                                   seq_len=L_)
    accs = [acc("failed", 0, 5), acc("funded-open", 500, 3), acc("eval-open", 0, 2), acc("graduated", 1000, 10),
            acc("funded-open", 200, 10)]
    s = HF.summ(accs, PLAN, 100.0, horizon=10)
    assert s["n_all"] == 5 and s["n"] == 4
    assert s["trunc_share"] == pytest.approx(0.4)             # funded-open(3) + eval-open(2) are short and open
    assert s["trunc_eval_open"] == pytest.approx(0.2) and s["trunc_funded_open"] == pytest.approx(0.2)
    assert s["horizon_open"] == pytest.approx(0.2)            # funded-open after the full horizon
    assert s["ev"] == pytest.approx((0 + 500 + 1000 + 200) / 4 - 100)
    assert s["ev_wo_trunc"] == pytest.approx((0 + 1000 + 200) / 3 - 100)


def test_boot_horizons_are_paired_prefixes():
    """The h250 run of boot_coin is the prefix of the h500 sequence: accounts closed by 250 are identical, so the
    longer horizon only changes accounts that were open at 250."""
    n = 300
    table, days = toy(random_tape(n, 4, sd=300.0), eras=["2011-18"] * n)
    b = HF.boot_coin(table, PLAN, FEE, days, 0, paths=40, horizons=(30, 60), eras=("2011-18",))["2011-18"]
    h30, h60 = b["h30"], b["h60"]
    assert h60["n_all"] == h30["n_all"] == 40
    open30 = h30["eval_open_at_h"] + h30["funded_open_at_h"]
    assert open30 > 0
    assert h60["eval_open_at_h"] + h60["funded_open_at_h"] <= open30
