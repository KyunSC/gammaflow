"""build_features: synthetic-chain checks. Run from functions/ml:
    .venv/bin/python -m pytest -q research_loop_volsig/tests
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from research_loop_volsig import build_features as B


def _chain(S=100.0, t="2018-03-05 12:00", exp="2018-03-16", smile=lambda k: 0.20, strikes=None, extra=None):
    strikes = np.arange(70, 131, 1.0) if strikes is None else strikes
    rows = []
    for k in strikes:
        for r in ("CALL", "PUT"):
            rows.append(dict(expiration=exp, strike=k, right=r, timestamp=pd.Timestamp(t, tz=B.ET),
                             bid=1.0, ask=1.1, implied_vol=smile(k), underlying_price=S))
    df = pd.DataFrame(rows)
    return pd.concat([df, extra]) if extra is not None else df


def test_pick_expiry_nearest_ge_7():
    assert B.pick_expiry(["2018-03-09", "2018-03-12", "2018-03-16"], date(2018, 3, 5)) == "2018-03-12"
    assert B.pick_expiry(["2018-03-09"], date(2018, 3, 5)) is None


def test_atm_interpolates_in_strike_and_flat_smile_has_zero_skew():
    df = _chain(S=100.4, smile=lambda k: 0.20 + 0.001 * (100 - k))
    f, info = B.day_features(df, date(2018, 3, 5))
    r = f.iloc[0]
    assert r.atm_call_iv == pytest.approx(0.20 - 0.0004, abs=1e-9)
    assert r.iv_spread == pytest.approx(0.0, abs=1e-12)
    flat = B.day_features(_chain(), date(2018, 3, 5))[0].iloc[0]
    assert flat.skew25 == pytest.approx(0.0, abs=1e-12) and flat.atm_iv == pytest.approx(0.20)


def test_skew_reads_iv_at_25_delta():
    smile = lambda k: 0.20 + 0.004 * (100 - k)       # put wing richer
    f = B.day_features(_chain(smile=smile), date(2018, 3, 5))[0].iloc[0]
    tau = (pd.Timestamp("2018-03-16 16:00", tz=B.ET) - pd.Timestamp("2018-03-05 12:00", tz=B.ET)).total_seconds() / B.YEAR_S
    # brute force: find the strike where put delta = -0.25 under its own IV
    ks = np.linspace(80, 100, 200001)
    d = B.bs_delta(100.0, ks, smile(ks), tau, call=False)
    kp = ks[np.argmin(np.abs(d + 0.25))]
    assert f.put25_iv == pytest.approx(smile(kp), abs=2e-4)
    assert f.skew25 > 0


def test_unquoted_rows_ignored_and_no_extrapolation():
    df = _chain(strikes=np.arange(101, 131, 1.0))        # nothing below spot -> ATM not bracketed
    r = B.day_features(df, date(2018, 3, 5))[0].iloc[0]
    assert np.isnan(r.atm_iv) and np.isnan(r.put25_iv)
    df = _chain()
    df.loc[df.strike == 100, "bid"] = 0.0                 # unquoted ATM strike is skipped, neighbours bracket
    r = B.day_features(df, date(2018, 3, 5))[0].iloc[0]
    assert r.atm_iv == pytest.approx(0.20) and r.n_call == 60


def test_each_slot_uses_only_its_own_snapshot_and_skips_0930():
    a = _chain(t="2018-03-05 09:30", smile=lambda k: 0.90)
    b = _chain(t="2018-03-05 09:35", smile=lambda k: 0.20)
    c = _chain(t="2018-03-05 09:40", smile=lambda k: 0.30)
    f = B.day_features(pd.concat([a, b, c]), date(2018, 3, 5))[0]
    assert list(f.slot_end.dt.strftime("%H:%M")) == ["09:35", "09:40"]
    assert list(f.atm_iv.round(6)) == [0.2, 0.3]


def test_one_expiry_per_day():
    other = _chain(exp="2018-03-23", smile=lambda k: 0.5)
    f = B.day_features(_chain(extra=other), date(2018, 3, 5))[0]
    assert set(f.expiry) == {"2018-03-16"} and f.atm_iv.iloc[0] == pytest.approx(0.20)


def test_six_dte_expiry_is_skipped():
    six = _chain(exp="2018-03-11", smile=lambda k: 0.9)          # 6 calendar days from 2018-03-05
    f = B.day_features(_chain(extra=six), date(2018, 3, 5))[0]
    assert set(f.expiry) == {"2018-03-16"} and f.atm_iv.iloc[0] == pytest.approx(0.20)


def test_25_delta_uses_otm_options_only():
    df = _chain()
    itm_put = (df.right == "PUT") & (df.strike > 100)
    itm_call = (df.right == "CALL") & (df.strike < 100)
    df.loc[itm_call, "implied_vol"] = 0.9                         # ITM wings must not move the 25-delta reads
    # IV 8.0 puts an ITM put's own-IV delta near -0.25 (d1 ~ 0.69): mixing ITM puts in would read it
    df.loc[itm_put, "implied_vol"] = 8.0
    tau = (pd.Timestamp("2018-03-16 16:00", tz=B.ET) - pd.Timestamp("2018-03-05 12:00", tz=B.ET)).total_seconds() / B.YEAR_S
    d_itm = B.bs_delta(100.0, df[itm_put].strike.to_numpy(float), np.full(itm_put.sum(), 8.0), tau, call=False)
    assert (np.abs(d_itm + 0.25) < 0.03).any()
    r = B.day_features(df, date(2018, 3, 5))[0].iloc[0]
    assert r.put25_iv == pytest.approx(0.20) and r.call25_iv == pytest.approx(0.20)


def test_atm_bracket_wider_than_5pct_gives_nan():
    strikes = np.r_[np.arange(70, 95, 1.0), np.arange(106, 131, 1.0)]   # 94 -> 106 gap = 12% of S
    r = B.day_features(_chain(strikes=strikes), date(2018, 3, 5))[0].iloc[0]
    assert np.isnan(r.atm_iv)
    strikes = np.r_[np.arange(70, 98, 1.0), np.arange(102, 131, 1.0)]   # 97 -> 102 = 5%: allowed
    r = B.day_features(_chain(strikes=strikes), date(2018, 3, 5))[0].iloc[0]
    assert r.atm_iv == pytest.approx(0.20)
