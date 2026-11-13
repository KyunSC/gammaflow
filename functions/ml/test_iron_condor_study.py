import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

import iron_condor_study as ic


def quote(K: float, call: bool, bid: float, ask: float) -> dict:
    return dict(strike=K, call=call, bid=bid, ask=ask)


def legs(sc=(101, 0.50, 0.60), sp=(99, 0.50, 0.60), lc=(102, 0.10, 0.20), lp=(98, 0.10, 0.20)) -> dict:
    return {k: dict(K=v[0], bid=v[1], ask=v[2]) for k, v in dict(sc=sc, sp=sp, lc=lc, lp=lp).items()}


def norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1 + np.vectorize(math.erf)(x / math.sqrt(2)))


def bs(S: float, K: np.ndarray, v: float, call: bool) -> np.ndarray:
    """Black-Scholes at r=0 with v = sigma*sqrt(T) in log terms."""
    d1 = (np.log(S / K) + v * v / 2) / v
    d2 = d1 - v
    c = S * norm_cdf(d1) - K * norm_cdf(d2)
    return c if call else c - S + K


def test_full_fill_sells_bid_buys_ask():
    x = ic.condor(legs(), 100.0, 1.0)
    assert x["credit"] == pytest.approx(0.50 + 0.50 - 0.20 - 0.20)


def test_mid_fill_is_the_midpoint_and_half_sits_between():
    mid = ic.condor(legs(), 100.0, 0.0)["credit"]
    half = ic.condor(legs(), 100.0, 0.5)["credit"]
    full = ic.condor(legs(), 100.0, 1.0)["credit"]
    assert mid == pytest.approx(0.55 + 0.55 - 0.15 - 0.15)
    assert full < half < mid
    assert half == pytest.approx((full + mid) / 2)


def test_expiring_inside_keeps_the_credit_less_fees():
    x = ic.condor(legs(), 100.0, 1.0)
    assert x["pnl"] == pytest.approx(60.0 - 4 * ic.COMMISSION_LEG)


@pytest.mark.parametrize("close", [90.0, 110.0])
def test_expiring_past_a_wing_loses_exactly_the_risk(close):
    x = ic.condor(legs(), close, 1.0)
    assert x["pnl"] == pytest.approx(-x["risk"])
    assert x["r"] == pytest.approx(-1.0)


def test_expiring_between_short_and_wing_is_partial():
    x = ic.condor(legs(), 101.5, 1.0)
    assert x["pnl"] == pytest.approx(100 * (0.6 - 0.5) - 4 * ic.COMMISSION_LEG)


def test_no_credit_is_not_a_trade():
    assert ic.condor(legs(sc=(101, 0.10, 0.60), sp=(99, 0.10, 0.60)), 100.0, 1.0) is None


def test_commission_scales_the_loss():
    assert ic.condor(legs(), 100.0, 1.0, 2 * ic.COMMISSION_LEG)["pnl"] == pytest.approx(60.0 - 8 * ic.COMMISSION_LEG)


def test_pick_needs_a_bid_on_shorts_but_not_on_wings():
    chain = pd.DataFrame([quote(100.0, True, 0.0, 0.05)])
    assert ic.pick(chain, 100.0, True, 1.0, True) is None
    assert ic.pick(chain, 100.0, True, 1.0, False)["K"] == 100.0


def test_pick_rejects_a_strike_far_from_target():
    chain = pd.DataFrame([quote(100.0, True, 0.1, 0.2)])
    assert ic.pick(chain, 102.0, True, 1.0, False) is None
    assert ic.pick(chain, 100.2, True, 1.0, False)["K"] == 100.0


def test_build_needs_wings_outside_the_shorts():
    chain = pd.DataFrame([quote(100.0, c, 0.1, 0.2) for c in (True, False)])
    assert ic.build_legs(chain, 100.0, 1.0, 0.0, 0.1) is None


def test_fly_shorts_the_same_strike_on_both_sides():
    chain = pd.DataFrame([quote(float(k), c, 0.5, 0.6) for k in (99, 100, 101) for c in (True, False)])
    b = ic.build_legs(chain, 100.0, 1.0, 0.0, 1.0)
    assert b["sc"]["K"] == b["sp"]["K"] == 100.0
    assert (b["lc"]["K"], b["lp"]["K"]) == (101.0, 99.0)


def test_fair_priced_condor_has_zero_edge_at_mid():
    """Calibration: on a driftless walk priced by its own vol, the mid-filled condor earns nothing."""
    S, v = 100.0, 0.01
    K = np.arange(90.0, 110.5, 0.5)
    chain = pd.concat([pd.DataFrame(dict(strike=K, call=c, bid=p, ask=p)) for c, p in ((True, bs(S, K, v, True)), (False, bs(S, K, v, False)))])
    atm = float(bs(S, np.array([S]), v, True)[0] + bs(S, np.array([S]), v, False)[0])
    sigma = atm * ic.ATM_TO_SIGMA
    assert sigma == pytest.approx(S * v, rel=0.01)
    b = ic.build_legs(chain, S, sigma, 1.0, 2.0)
    close = S * np.exp(np.random.default_rng(1).normal(-v * v / 2, v, 400_000))
    pnl = np.array([ic.condor(b, float(c), 0.0, 0.0)["pnl"] for c in close])
    assert abs(pnl.mean()) < 3 * pnl.std() / math.sqrt(len(pnl))


def test_fair_priced_condor_loses_the_spread_at_full_fill():
    S, v = 100.0, 0.01
    K = np.arange(90.0, 110.5, 0.5)
    chain = pd.concat([pd.DataFrame(dict(strike=K, call=c, bid=p - 0.01, ask=p + 0.01))
                       for c, p in ((True, np.maximum(bs(S, K, v, True), 0.02)), (False, np.maximum(bs(S, K, v, False), 0.02)))])
    b = ic.build_legs(chain, S, S * v, 1.0, 2.0)
    assert ic.condor(b, S, 1.0, 0.0)["credit"] == pytest.approx(ic.condor(b, S, 0.0, 0.0)["credit"] - 0.04)


def test_discovery_window_stops_at_end():
    assert ic.END == date(2025, 3, 26)
    assert all(ic.START <= d <= ic.END for d in ic.days_for("QQQ"))


def test_pooled_counts_one_row_per_day():
    df = pd.DataFrame(dict(day=["a", "a", "b"], r=[1.0, 3.0, 5.0], pnl=[1.0, 1.0, 1.0], credit=[1.0] * 3, width=[1.0] * 3, in_band=[1.0] * 3))
    assert ic.pooled(df)["r"].tolist() == [2.0, 5.0]


def test_worst_streak_finds_the_longest_loss_run():
    assert ic.worst_streak(np.array([0.1, -1.0, -0.5, 0.2, -0.2])) == (2, -1.5)


def test_gate_fails_when_one_symbol_loses():
    days = [f"{y}-01-{d:02d}" for y in (2022, 2023, 2024, 2025) for d in range(1, 26)]
    rows = [dict(symbol=s, cell=ic.PRIMARY, fill="full", day=d, r=(0.2 if s == "QQQ" else -0.1), r_2x=0.0, pnl=1.0, credit=1.0, width=2.0, in_band=True)
            for s in ic.SYMBOLS for d in days]
    g = ic.gate(pd.DataFrame(rows))
    assert not g["items"]["net_r_positive_both"]
    assert not g["passed"]
