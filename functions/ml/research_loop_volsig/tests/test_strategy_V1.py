"""V1_flow_divergence rules on synthetic bars (not frozen)."""
import json
import math
import os
from datetime import date, timedelta

os.environ.setdefault("VOLSIG_PRODUCT", "NQ")

import pytest  # noqa: E402

from research_loop_volsig.eval import config as C, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "V1_flow_divergence.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "V1_flow_divergence.json").read_text())
PARAMS = {**SPEC["grid"]["base"], "z": 0.5}


def day_bars(d, sp_open, sp_noon, r=0.0, half=False, exdiv=False, news=(), base=5000.0, rng_pts=40.0, opt=True):
    """78 (or 42) bars; price rises linearly so that ln(c29/o0) == r; spread windows set as given."""
    n = 42 if half else 78
    c29 = base * math.exp(r)
    out = []
    for k in range(n):
        px = base + (c29 - base) * min(k, 29) / 29
        o = base if k == 0 else px
        bar = {"day": d.isoformat(), "slot": k, "o": o, "h": px + rng_pts / 2, "l": px - rng_pts / 2, "c": px,
               "half_day": half, "news": list(news), "opt": None}
        if opt:
            sp = sp_open if k <= 4 else (sp_noon if 25 <= k <= 29 else 0.0)
            bar["opt"] = {"iv_spread": sp, "exdiv": exdiv, "atm_iv": 0.2}
        out.append(bar)
    return out


def run_days(days):
    st = engine.load_strategy_class(PATH)(PARAMS)
    acts = []
    for bars in days:
        for b in bars:
            a = st.on_bar(b, None)
            if a is not None:
                acts.append((b["day"], b["slot"], a))
    return st, acts


def history(n=20, start=date(2017, 1, 2)):
    """n ordinary sessions: dS = 0.002*r + small alternating noise, so the residual sd is ~1e-4."""
    days, d = [], start
    for i in range(n):
        r = 0.004 * ((i % 5) - 2)
        days.append(day_bars(d, 0.0, 0.002 * r + (1e-4 if i % 2 else -1e-4), r=r))
        d += timedelta(days=1)
    return days, d


def test_passes_sandbox_and_prereg_grid():
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["grid"]["axes"] == {"z": [0.25, 0.5, 0.75]} and SPEC["dev_split"] == "dev_opt"


def test_needs_20_sessions_then_trades_sign_of_residual():
    h, d = history(19)
    _, acts = run_days(h + [day_bars(d, 0.0, 0.01)])
    assert acts == []                                   # only 19 sessions of history
    h, d = history(20)
    st, acts = run_days(h + [day_bars(d, 0.0, 0.01)])   # calls much richer -> long
    assert len(acts) == 1 and acts[0][1] == 29 and acts[0][2]["side"] == 1
    _, acts = run_days(h + [day_bars(d, 0.0, -0.01)])   # puts richer -> short
    assert acts[0][2]["side"] == -1


def test_residual_removes_the_spot_part():
    h, d = history(20)
    r = 0.01
    _, acts = run_days(h + [day_bars(d, 0.0, 0.002 * r, r=r)])   # dS exactly what the fit implies -> z ~ 0
    assert acts == []


def test_stop_is_half_adr20_and_no_target():
    h, d = history(20)
    _, acts = run_days(h + [day_bars(d, 0.0, 0.01)])
    a = acts[0][2]
    assert a["type"] == "market" and a["target"] is None
    adr = sum(max(b["h"] for b in bars) - min(b["l"] for b in bars) for bars in h) / 20
    assert adr > 40.0                                     # drifting history days: range > the 40-pt bar range
    assert a["stop"] == pytest.approx(5000.0 - 0.5 * adr)


def test_exdiv_and_half_days_neither_trade_nor_enter_history():
    h, d = history(20)
    st, acts = run_days(h + [day_bars(d, 0.0, 0.01, exdiv=True), day_bars(d + timedelta(days=1), 0.0, 0.01, half=True)])
    assert acts == [] and len(st.hist) == 20


def test_news_afternoon_skips_trade_but_stores_history():
    h, d = history(20)
    st, acts = run_days(h + [day_bars(d, 0.0, 0.01, news=[840])])
    assert acts == [] and len(st.hist) == 21
    st, acts = run_days(h + [day_bars(d, 0.0, 0.01, news=[600])])   # morning release: allowed
    assert len(acts) == 1


def test_missing_spread_snapshots():
    h, d = history(20)
    bars = day_bars(d, 0.0, 0.01)
    for k in (25, 26, 27):
        bars[k]["opt"]["iv_spread"] = None                # only 2 of 5 noon snapshots left
    st, acts = run_days(h + [bars])
    assert acts == [] and len(st.hist) == 20
    bars = day_bars(d, 0.0, 0.01)
    bars[0]["opt"] = None                                 # no opt row on slot 0
    st, acts = run_days(h + [bars])
    assert acts == [] and len(st.hist) == 20


def test_no_reentry_when_already_in_position():
    h, d = history(20)
    st = engine.load_strategy_class(PATH)(PARAMS)
    for bars in h:
        for b in bars:
            st.on_bar(b, None)
    out = [st.on_bar(b, {"side": 1}) for b in day_bars(d, 0.0, 0.01)]
    assert all(a is None for a in out)
