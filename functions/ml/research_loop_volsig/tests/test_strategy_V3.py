"""V3_term_slope rules on synthetic bars (not frozen)."""
import json
import os
from datetime import date, timedelta

os.environ.setdefault("VOLSIG_PRODUCT", "NQ")   # V3 trades ES, but the strategy itself is product-agnostic

import pytest  # noqa: E402

from research_loop_volsig.eval import config as C, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "V3_term_slope.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "V3_term_slope.json").read_text())
PARAMS = {**SPEC["grid"]["base"], "z": 0.5}


def day_bars(d, vix, vix3m, half=False, n=78, base=2000.0, rng=10.0):
    daily = None if vix is None else {"date": "x", "VIX": vix, "VIX3M": vix3m, "VIX9D": None, "VVIX": None, "SKEW": None}
    return [{"day": d.isoformat(), "dow": d.weekday(), "slot": k, "o": base, "h": base + rng / 2, "l": base - rng / 2,
             "c": base, "half_day": half, "daily": None if daily is None else dict(daily)} for k in range(42 if half else n)]


def weekdays(start, n):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def ratios_hist(n, mon_jump=0.0):
    """VIX3M fixed at 20; ratio wiggles +-0.01 day to day; optional extra jump on Mondays (weekend pattern)."""
    days = weekdays(date(2012, 1, 2), n)
    out, r = [], 0.85
    for i, d in enumerate(days):
        r += (0.01 if i % 2 else -0.01) + (mon_jump if d.weekday() == 0 else 0.0) - (mon_jump / 4 if d.weekday() else 0.0)
        out.append((d, r))
    return out


def run(seq, params=PARAMS, positions=None):
    st = engine.load_strategy_class(PATH)(params)
    acts = []
    for d, r in seq:
        for b in (day_bars(d, r * 20.0, 20.0) if r is not None else day_bars(d, None, None)):
            pos = positions.get((b["day"], b["slot"])) if positions else None
            a = st.on_bar(b, pos)
            if a is not None:
                acts.append((b["day"], b["slot"], a))
    return st, acts


def test_sandbox_and_grid():
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["grid"]["axes"] == {"z": [0.0, 0.5, 1.0]} and SPEC["product"] == "ES" and SPEC["dev_split"] == "dev"


def test_needs_weekday_and_sd_history_then_side_is_minus_sign_z():
    seq = ratios_hist(260)
    st, acts = run(seq)
    assert acts and all(a[1] == 0 for a in acts)
    first = acts[0][0]
    assert first >= seq[200][0].isoformat()                  # 40 same-weekday obs ~ 200 weekdays
    last_r = seq[-1][1]
    nxt = seq[-1][0] + timedelta(days=3 if seq[-1][0].weekday() == 4 else 1)
    _, a_up = run(seq + [(nxt, last_r + 0.08)])              # ratio jumps up -> short
    _, a_dn = run(seq + [(nxt, last_r - 0.08)])
    assert a_up[-1][0] == a_dn[-1][0] == nxt.isoformat()
    # the decision for day nxt uses D = ratio(nxt's daily) - ratio(previous); here daily is attached to nxt directly
    assert a_up[-1][2]["side"] == -1 and a_dn[-1][2]["side"] == 1


def test_weekday_pattern_is_removed():
    seq = ratios_hist(400, mon_jump=0.05)                    # big systematic Monday jump, others drift down
    st, acts = run(seq, {**PARAMS, "z": 0.0})
    mon = [a for a in acts if date.fromisoformat(a[0]).weekday() == 0]
    # raw D on Mondays is always large positive -> raw rule would short every Monday; adjusted: both sides appear
    assert {a[2]["side"] for a in mon} == {1, -1}


def test_stop_is_one_adr_and_no_target():
    st, acts = run(ratios_hist(260))
    a = acts[-1][2]
    assert a["type"] == "market" and a["target"] is None and a["stop"] == pytest.approx(2000.0 - a["side"] * 10.0)


def test_missing_daily_breaks_the_chain_and_half_days_do_not_trade():
    seq = ratios_hist(260)
    d0 = seq[-1][0]
    days = weekdays(d0 + timedelta(days=1), 3)
    st, acts = run(seq + [(days[0], None), (days[1], 0.95), (days[2], 1.10)])
    got = {a[0] for a in acts}
    assert days[0].isoformat() not in got and days[1].isoformat() not in got   # no D on the gap and right after it
    st = engine.load_strategy_class(PATH)({**PARAMS, "z": 0.0})
    for d, r in seq:
        for b in day_bars(d, r * 20, 20.0):
            st.on_bar(b, None)
    out = [st.on_bar(b, None) for b in day_bars(days[0], 25.0, 20.0, half=True)]
    assert all(x is None for x in out)


def test_history_is_independent_of_positions():
    seq = ratios_hist(300)
    st1, _ = run(seq)
    held = {(d.isoformat(), k): {"side": 1, "bars_held": k} for d, _ in seq[::3] for k in range(78)}
    st2, _ = run(seq, positions=held)
    assert st1.adj == st2.adj and st1.by_dow == st2.by_dow and st1.ranges == st2.ranges
