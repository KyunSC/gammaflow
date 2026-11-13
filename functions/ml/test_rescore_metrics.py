"""Synthetic known-answer tests for rescore_metrics.py."""

import math

import numpy as np
import pytest

import rescore_metrics as rm


# ---------------------------------------------------------------- Sharpe & moments

def test_daily_sharpe_known():
    # mean 2, sample sd of [1,2,3] = 1
    assert rm.daily_sharpe([1, 2, 3]) == pytest.approx(2.0)
    assert rm.daily_sharpe([5, 5, 5]) is None
    assert rm.daily_sharpe([1]) is None


def test_skew_kurtosis_symmetric_two_point():
    # +-1 equally often: skew 0, kurtosis 1 (non-excess)
    sk, ku = rm.skew_kurtosis([1, -1] * 50)
    assert sk == pytest.approx(0.0, abs=1e-12)
    assert ku == pytest.approx(1.0)


def test_skew_kurtosis_normal_large_sample():
    x = np.random.default_rng(0).normal(size=400_000)
    sk, ku = rm.skew_kurtosis(x)
    assert sk == pytest.approx(0.0, abs=0.02)
    assert ku == pytest.approx(3.0, abs=0.03)


# ---------------------------------------------------------------- Deflated Sharpe

@pytest.mark.parametrize("N, exact", [(10, 1.5388), (100, 2.5076)])
def test_expected_max_sharpe_close_to_true_max_of_normals(N, exact):
    # Bailey-LdP approximation to E[max of N iid N(0,1)]; true values from order-statistic tables
    assert rm.expected_max_sharpe(N, 1.0) == pytest.approx(exact, abs=0.05)


def test_expected_max_sharpe_single_trial_is_zero():
    assert rm.expected_max_sharpe(1, 0.3) == 0.0


def test_dsr_paper_example():
    # Bailey & Lopez de Prado (2014): annual SR 2.5, 5y daily (T=1250), skew -3, kurt 10,
    # N=100, annualized V[SR]=0.5  ->  DSR ~ 0.9004
    sr = 2.5 / math.sqrt(250)
    v = 0.5 / 250
    assert rm.deflated_sharpe_from_stats(sr, 1250, -3.0, 10.0, 100, v) == pytest.approx(0.9004, abs=0.002)


def test_dsr_half_when_sr_equals_benchmark():
    T, N = 500, 20
    sr0 = rm.expected_max_sharpe(N, 1.0 / T)
    assert rm.deflated_sharpe_from_stats(sr0, T, 0.0, 3.0, N) == pytest.approx(0.5)


def test_dsr_n1_equals_psr_against_zero():
    # N=1, normal moments: Phi(SR*sqrt(T-1)/sqrt(1+SR^2/2))
    sr, T = 0.1, 401
    want = 0.5 * (1 + math.erf(sr * math.sqrt(T - 1) / math.sqrt(1 + sr * sr / 2) / math.sqrt(2)))
    assert rm.deflated_sharpe_from_stats(sr, T, 0.0, 3.0, 1) == pytest.approx(want)


def test_dsr_from_series_default_v_and_monotone_in_n():
    x = np.random.default_rng(1).normal(0.2, 1.0, size=1000)
    d1 = rm.deflated_sharpe(x, 1)
    d100 = rm.deflated_sharpe(x, 100)
    assert 0.99 < d1 <= 1.0
    assert d100 < d1


def test_sharpe_variance_across_trials():
    assert rm.sharpe_variance_across_trials([0.0, 0.1, 0.2]) == pytest.approx(0.01)
    assert rm.sharpe_variance_across_trials([0.1]) is None


# ---------------------------------------------------------------- concentration, stress, years

def test_top5_share():
    pnl = [10, 10, 10, 10, 10, -5, -5, 0, 0, 0]  # total 40, best 5 = 50
    assert rm.top5_share(pnl) == pytest.approx(1.25)
    assert rm.top5_share([1] * 20) == pytest.approx(0.25)
    assert rm.top5_share([-1, -2, 1]) is None


def test_stress_net_fallbacks():
    assert rm.stress_net(100, slippage_total=30) == (70.0, "2x_slippage")
    assert rm.stress_net(100, noncommission_cost_total=40) == (60.0, "2x_noncommission_cost")
    assert rm.stress_net(100, total_cost=120) == (-20.0, "2x_total_cost")
    assert rm.stress_net(100) == (None, "unavailable")


def test_years_positive():
    dates = ["2020-01-02", "2020-06-01", "2021-03-01", "2022-05-05", "2023-01-03"]
    pnl = [5, -1, -3, 2, 0]   # 2020 +, 2021 -, 2022 +, 2023 has no activity
    assert rm.years_positive(dates, pnl) == pytest.approx(2 / 3)


# ---------------------------------------------------------------- verdicts

BASE = dict(oos=True, net_total=1000, gross_per_trade=10, cost_per_trade=4, dsr=0.97,
            twin_p=0.01, twin_kind="side_matched", top5=0.3, stress=500, years_pos=0.8)


def test_strong():
    assert rm.symbol_verdict(**BASE) == ("STRONG", None)


@pytest.mark.parametrize("change", [
    dict(dsr=0.9), dict(twin_p=0.06), dict(twin_kind="coin_flip"), dict(top5=0.5),
    dict(stress=-1), dict(years_pos=0.5), dict(stress=None)])
def test_strong_fails_one_test_becomes_promising(change):
    assert rm.symbol_verdict(**{**BASE, **change})[0] == "PROMISING"


def test_regime_rule_replaces_years():
    assert rm.symbol_verdict(**{**BASE, "years_pos": 0.2}, regime_rule_tested_oos=True)[0] == "STRONG"


def test_discovery_capped_at_promising():
    assert rm.symbol_verdict(**{**BASE, "oos": False}) == ("PROMISING", None)


def test_promising_via_twin_only():
    v = rm.symbol_verdict(**{**BASE, "dsr": 0.1, "twin_p": 0.08, "twin_kind": "coin_flip"})
    assert v == ("PROMISING", None)


def test_promising_needs_gross_above_cost():
    # not STRONG (dsr 0.9), so the PROMISING gross > cost test decides
    v = rm.symbol_verdict(**{**BASE, "dsr": 0.9, "gross_per_trade": 4, "cost_per_trade": 4})
    assert v == ("DEAD", "gross_le_costs")


def test_dead_reasons():
    sv = rm.symbol_verdict
    assert sv(**{**BASE, "net_total": -10, "twin_p": 0.7}) == ("DEAD", "worse_than_random")
    assert sv(**{**BASE, "net_total": -10, "twin_p": 0.3}, discovery_net=50) == ("DEAD", "oos_reversal")
    assert sv(**{**BASE, "net_total": -10, "twin_p": 0.3, "gross_per_trade": 2}) == ("DEAD", "gross_le_costs")
    assert sv(**{**BASE, "net_total": -10, "twin_p": 0.3, "gross_per_trade": -1}) == ("DEAD", "net_negative")
    assert sv(**{**BASE, "dsr": 0.2, "twin_p": 0.3, "top5": 0.9}) == ("DEAD", "few_days")
    assert sv(**{**BASE, "dsr": 0.2, "twin_p": 0.3}) == ("DEAD", "weak_stats")
    assert sv(**{**BASE, "dsr": 0.2, "twin_p": 0.6}) == ("DEAD", "worse_than_random")
    assert sv(**{**BASE, "dsr": None, "twin_p": None}) == ("DEAD", "weak_stats")


def test_study_verdict_best_symbol():
    assert rm.study_verdict(["DEAD", "PROMISING"]) == "PROMISING"
    assert rm.study_verdict(["DEAD", "STRONG", "PROMISING"]) == "STRONG"
    assert rm.study_verdict([]) == "DEAD"


def test_score_symbol_end_to_end():
    rng = np.random.default_rng(2)
    pnl = rng.normal(20, 50, size=600)
    dates = [f"{2020 + i // 200}-06-01" for i in range(600)]
    row = rm.score_symbol(pnl, N=1, oos=True, dates=dates, trades=600, gross_per_trade=25,
                          cost_per_trade=5, twin_p=0.001, twin_kind="side_matched",
                          slippage_total=600.0)
    assert row["verdict"] == "STRONG"
    assert row["net_per_trade"] == pytest.approx(pnl.mean())
    assert row["stress_method"] == "2x_slippage"
    loss = rm.score_symbol(-np.abs(pnl), N=5, oos=False, trades=600, gross_per_trade=-1, cost_per_trade=5)
    assert loss["verdict"] == "DEAD" and loss["dead_reason"] == "net_negative"


def test_missing_fields():
    assert "study" in rm.missing_fields({})
    js = {k: None for k in rm.REQUIRED_STUDY_FIELDS}
    js["per_symbol"] = {"NQ": {"window": "x"}}
    miss = rm.missing_fields(js)
    assert "NQ.dsr" in miss and "study" not in miss
