"""Timing and accounting tests for the frozen evaluator. Run from functions/ml:
    ../../.venv/bin/python -m pytest -q research_loop_nq/tests
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pytest

from research_loop_nq.eval import config as C
from research_loop_nq.eval import costs, criteria, data, engine, manifest, sandbox, twins

TICK = C.TICK
PV = C.POINT_VALUE          # $ per point (MNQ $2)
TV = C.TICK * C.POINT_VALUE  # $ per tick (MNQ $0.50)


# --- synthetic sessions -----------------------------------------------------------------------------------------

def make_session(bars: dict[int, tuple] | None = None, day=date(2019, 6, 3), half=False, base=100.0) -> data.Session:
    """390 (or 210) flat 1m bars at `base`; `bars` overrides {minute index: (o, h, l, c)}."""
    close = C.HALF_CLOSE if half else C.RTH_CLOSE
    n = close - C.RTH_OPEN
    o = np.full(n, base); h = np.full(n, base); l = np.full(n, base); c = np.full(n, base)
    for i, (oo, hh, ll, cc) in (bars or {}).items():
        o[i], h[i], l[i], c[i] = oo, hh, ll, cc
    t0 = int(datetime(day.year, day.month, day.day, 13, 30, tzinfo=timezone.utc).timestamp())  # EDT
    s = data.Session(day=day, half=half, close_mod=close, inst=1, roll=False, prev_close=None, overnight=None,
                     news=[], news_day=None, t=t0 + 60 * np.arange(n), mod=(C.RTH_OPEN + np.arange(n)).astype(np.int32),
                     o=o, h=h, l=l, c=c, v=np.ones(n))
    s.b5 = data.five_minute(s)
    return s


class Script:
    """Strategy that returns scripted actions by (day, slot) and records what it saw."""

    def __init__(self, actions: dict):
        self.actions, self.seen = actions, []

    def on_bar(self, bar, pos):
        self.seen.append((bar, pos))
        return self.actions.get((bar["day"], bar["slot"]))


def m(slot: int, minute: int = 0) -> int:
    """1m index of minute `minute` inside 5m slot `slot`."""
    return slot * 5 + minute


def run1(s, actions, warm=()):
    st = Script({(s.day.isoformat(), k): v for k, v in actions.items()})
    return engine.run(list(warm), [s], st), st


def long_mkt(stop, target=None):
    return {"op": "enter", "side": 1, "type": "market", "stop": stop, "target": target}


# --- timing -----------------------------------------------------------------------------------------------------

def test_no_lookahead_future_changes_do_not_change_past_inputs_or_actions():
    rng = np.random.default_rng(0)
    px = 100 + np.cumsum(rng.normal(0, 0.25, 390))
    bars = {i: (px[i], px[i] + 0.5, px[i] - 0.5, px[i]) for i in range(390)}
    s1 = make_session(bars)
    bars2 = dict(bars)
    for i in range(m(40), 390):
        bars2[i] = (px[i] + 50, px[i] + 51, px[i] + 49, px[i] + 50)
    s2 = make_session(bars2)
    _, a = run1(s1, {})
    _, b = run1(s2, {})
    k = 40
    assert [x[0] for x in a.seen[:k]] == [x[0] for x in b.seen[:k]]
    # bar k delivered at step k holds only minutes of slot k
    for step, (bar, _) in enumerate(a.seen):
        assert bar["slot"] == step
        lo, hi = m(step), m(step) + 4
        assert bar["h"] == pytest.approx(max(px[lo:hi + 1] + 0.5))
        assert bar["c"] == pytest.approx(px[hi])


def test_market_entry_fills_at_next_bar_open_not_decision_close():
    s = make_session({m(0, 4): (100, 100, 100, 101.0), m(1, 0): (102.0, 102.0, 102.0, 102.0)})
    res, _ = run1(s, {0: long_mkt(stop=95)})
    t = res["trades"][0]
    assert t["entry_ref"] == 102.0 and t["j_entry"] == m(1, 0) and t["at_open"]
    assert t["exit_kind"] == "flat" and t["j_exit"] == m(s.flat_slot)


def test_exit_action_fills_at_next_open():
    s = make_session({m(3, 0): (104.0, 104, 104, 104)})
    res, _ = run1(s, {0: long_mkt(stop=95), 2: {"op": "exit"}})
    t = res["trades"][0]
    assert t["exit_kind"] == "market" and t["exit_ref"] == 104.0 and t["j_exit"] == m(3, 0)


def test_stop_wins_when_bar_touches_both():
    s = make_session({m(2, 1): (100, 103.0, 98.0, 100)})
    res, _ = run1(s, {0: long_mkt(stop=99.0, target=102.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "stop" and t["exit_ref"] == 99.0


def test_target_needs_tick_through():
    s = make_session({m(2, 1): (100, 102.0, 100, 100)})  # touch only
    res, _ = run1(s, {0: long_mkt(stop=99.0, target=102.0)})
    assert res["trades"][0]["exit_kind"] == "flat"
    s = make_session({m(2, 1): (100, 102.0 + TICK, 100, 100)})
    res, _ = run1(s, {0: long_mkt(stop=99.0, target=102.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "target" and t["exit_ref"] == 102.0


def test_limit_entry_needs_tick_through():
    lim = {"op": "enter", "side": 1, "type": "limit", "price": 99.0, "stop": 97.0, "ttl": 3}
    s = make_session({m(1, 2): (100, 100, 99.0, 100)})  # touch
    res, _ = run1(s, {0: lim})
    assert res["trades"] == []
    s = make_session({m(1, 2): (100, 100, 99.0 - TICK, 100)})
    res, _ = run1(s, {0: lim})
    t = res["trades"][0]
    assert t["entry_kind"] == "limit" and t["entry_ref"] == 99.0 and not t["at_open"]


def test_limit_entry_expires_after_ttl():
    lim = {"op": "enter", "side": 1, "type": "limit", "price": 99.0, "stop": 97.0, "ttl": 1}
    s = make_session({m(2, 2): (100, 100, 98.0, 100)})  # trades through in bar 2, ttl covered bar 1 only
    res, _ = run1(s, {0: lim})
    assert res["trades"] == []


def test_stop_entry_gap_fills_at_open_and_midbar_entry_checks_stop_not_target():
    st = {"op": "enter", "side": 1, "type": "stop", "price": 101.0, "stop": 100.0, "target": 103.0}
    s = make_session({m(1, 0): (101.5, 101.5, 101.5, 101.5)})
    res, _ = run1(s, {0: st})
    t = res["trades"][0]
    assert t["entry_ref"] == 101.5 and t["at_open"]
    # mid-bar trigger on a bar that also spans the stop and the target: stopped, target ignored
    s = make_session({m(1, 1): (100.5, 104.0, 99.5, 101)})
    res, _ = run1(s, {0: st})
    t = res["trades"][0]
    assert t["entry_ref"] == 101.0 and t["exit_kind"] == "stop" and t["exit_ref"] == 100.0 and t["j_exit"] == m(1, 1)
    # mid-bar trigger that spans the target only: target not taken on the entry bar, taken on the next bar
    s = make_session({m(1, 1): (100.5, 104.0, 100.5, 101), m(1, 2): (103.5, 103.5, 103.5, 103.5)})
    res, _ = run1(s, {0: st})
    t = res["trades"][0]
    assert t["exit_kind"] == "target" and t["j_exit"] == m(1, 2)


def test_gap_through_stop_fills_at_open():
    s = make_session({m(2, 0): (97.0, 97.0, 97.0, 97.0)})
    res, _ = run1(s, {0: long_mkt(stop=99.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "stop" and t["exit_ref"] == 97.0


def test_stop_move_applies_from_next_bar():
    s = make_session({m(3, 2): (100, 100, 99.75, 100), m(5, 2): (100, 100, 99.75, 100)})
    res, _ = run1(s, {0: long_mkt(stop=99.0), 3: {"op": "stop", "price": 99.75}})
    t = res["trades"][0]
    # the 99.75 dip inside bar 3 happened before the move took effect; the one in bar 5 stops it
    assert t["exit_kind"] == "stop" and t["j_exit"] == m(5, 2) and t["stop_init"] == 99.0


def test_flat_at_last_bar_and_no_entry_into_it():
    s = make_session()
    res, _ = run1(s, {s.flat_slot - 1: long_mkt(stop=99.0)})
    assert res["trades"] == []
    h = make_session(day=date(2019, 11, 29), half=True)
    assert h.flat_slot == (12 * 60 + 55 - C.RTH_OPEN) // 5
    res, _ = run1(h, {0: long_mkt(stop=99.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "flat" and t["exit_mod"] == 12 * 60 + 55


def test_one_position_at_a_time_and_warmup_ignored():
    s = make_session()
    res, _ = run1(s, {0: long_mkt(stop=99.0), 2: long_mkt(stop=99.0)})
    assert len(res["trades"]) == 1 and res["rejected"] == 1
    w = make_session(day=date(2019, 5, 31))
    st = Script({("2019-05-31", 0): long_mkt(stop=99.0)})
    res = engine.run([w], [s], st)
    assert res["trades"] == [] and st.seen[0][0]["warmup"] is True


def test_bad_orders_raise():
    s = make_session()
    with pytest.raises(engine.StrategyError):
        run1(s, {0: {"op": "enter", "side": 1, "type": "market", "stop": 101.0}})
    with pytest.raises(engine.StrategyError):
        run1(s, {0: {"op": "enter", "side": -1, "type": "market", "stop": 101.0, "target": 102.0}})


# --- costs ------------------------------------------------------------------------------------------------------

def test_tick_point_value_and_commissions():
    t = {"side": 1, "entry_kind": "market", "entry_ref": 100.0, "exit_kind": "market", "exit_ref": 101.0,
         "risk_pts": 2.0, "entry_mod": 600, "exit_mod": 700}
    assert (C.PRODUCT, PV, TV) == ("NQ", 2.0, 0.5)
    b = costs.apply([t], "base")
    # +1 pt = $2; 2 ticks slip = 0.5 pt = $1.00; $0.50/side x 2 = $1
    assert b["usd"][0] == pytest.approx(PV - 2 * TV - 1.0)
    assert b["r"][0] == pytest.approx((PV - 2 * TV - 1.0) / (2.0 * PV))
    s = costs.apply([t], "stress")
    assert s["usd"][0] == pytest.approx(PV - 4 * TV - 2.0)
    tg = {**t, "exit_kind": "target"}
    assert costs.apply([tg], "base")["usd"][0] == pytest.approx(PV - TV - 1.0)
    st = {**t, "exit_kind": "stop", "exit_ref": 98.0}
    ss = costs.apply([st] * 500, "stress")["usd"]
    assert ss.max() <= -2 * PV - 2 * TV - 2.0 + 1e-9  # at least 1 tick + 1 tick base slip, $2 commission
    assert ss.mean() < -2 * PV - 2 * TV - 2.0 - 0.4 * TV   # PMF adds ~1 tick on average


def test_short_sign():
    t = {"side": -1, "entry_kind": "limit", "entry_ref": 100.0, "exit_kind": "target", "exit_ref": 99.0,
         "risk_pts": 1.0, "entry_mod": 600, "exit_mod": 700}
    assert costs.apply([t], "base")["usd"][0] == pytest.approx(PV - 1.0)


# --- twins and criteria -----------------------------------------------------------------------------------------

def test_twins_long_short_outcomes():
    s = make_session({m(2, 0): (100, 102.5, 100, 102), m(3, 0): (102, 102, 102, 102)})
    res, _ = run1(s, {0: long_mkt(stop=99.0, target=102.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "target"
    rl, rs = twins.long_short_r([s], res["trades"])
    real = costs.apply(res["trades"], "base")["r"]
    assert rl[0] == pytest.approx(real[0])
    assert rs[0] < 0  # the short twin (stop = entry + same risk) is stopped on the same rally
    tw = twins.twin_test(np.repeat(rl, 50), np.repeat(rl, 50), np.repeat(rs, 50), sides=np.tile([1, -1], 25), n=2000)
    assert tw["p"] < 0.01 and tw["always_long"] == pytest.approx(rl[0])


def test_criteria_helpers():
    days = np.array(["2011-01-03", "2011-01-03", "2012-01-03", "2013-01-03"])
    usd = np.array([10.0, 10.0, 5.0, 5.0])
    assert criteria.year_share(usd, days) == pytest.approx(20 / 30)
    r = np.array([1.0, -0.5, 0.2, 0.3, 0.1, -0.1, 2.0])
    assert criteria.ex_top(r, 2) == pytest.approx(np.mean([-0.5, -0.1, 0.1, 0.2, 0.3]))
    sess = ["2011-01-03", "2012-01-03", "2013-01-03"]
    assert criteria.folds_positive(np.array([1.0, 1, -1, 1]), days, sess) == [1.0, -1.0, 1.0]
    lo, hi = criteria.session_bootstrap_ci(np.ones(10), np.array([f"d{i}" for i in range(10)]))
    assert lo == hi == 1.0


# --- real data: sessions, DST, holidays, rolls -------------------------------------------------------------------

@pytest.fixture(scope="module")
def nq2019():
    return data.load_window(date(2019, 1, 2), date(2019, 12, 31))


def test_dst_boundaries_keep_0930_et(nq2019):
    by = {s.day: s for s in nq2019}
    for d_before, d_after in ((date(2019, 3, 8), date(2019, 3, 11)), (date(2019, 11, 1), date(2019, 11, 4))):
        for d in (d_before, d_after):
            s = by[d]
            assert s.mod[0] == C.RTH_OPEN and s.mod[-1] == C.RTH_CLOSE - 1 and len(s.o) >= 385
            assert s.b5["slot"][0] == 0 and s.b5["slot"][-1] == 77
        utc_hour = lambda s: datetime.fromtimestamp(int(s.t[0]), timezone.utc).hour  # noqa: E731
        assert {utc_hour(by[d_before]), utc_hour(by[d_after])} == {13, 14}


def test_holidays_dropped_half_days_kept(nq2019):
    days = {s.day for s in nq2019}
    assert date(2019, 1, 21) not in days       # MLK: CME short session, NYSE closed
    assert date(2019, 7, 4) not in days
    s = next(s for s in nq2019 if s.day == date(2019, 11, 29))
    assert s.half and s.close_mod == C.HALF_CLOSE and s.mod[-1] == C.HALF_CLOSE - 1
    assert all(s.day.weekday() < 5 for s in nq2019)
    assert 248 <= len(nq2019) <= 252


def test_roll_day_gap(nq2019):
    rolls = [s for s in nq2019 if s.roll]
    assert 3 <= len(rolls) <= 4
    for s in rolls:
        assert s.prev_close is None  # never compare across contracts
        if s.overnight:               # overnight stats come from today's contract only
            assert abs(s.overnight["c"] - s.o[0]) < 0.002 * s.o[0]  # scale-free (NQ ~7,000 in 2019)
    assert all(len(np.unique([s.inst])) == 1 for s in nq2019)


def test_split_refusals():
    with pytest.raises(ValueError):
        data.load_split("holdout")
    assert max(hi for _, hi in C.SPLITS.values()) <= date(2026, 8, 15)


# --- sandbox, child process, manifest ----------------------------------------------------------------------------

GOOD = """
import math
class Strategy:
    def __init__(self, params):
        self.p = params
    def on_bar(self, bar, pos):
        if bar['slot'] == 0 and pos is None:
            return {'op': 'enter', 'side': 1, 'type': 'market', 'stop': bar['c'] - self.p['risk']}
        return None
"""


@pytest.mark.parametrize("bad", [
    "import os\nclass Strategy: pass",
    "class Strategy:\n    def on_bar(self, b, p):\n        return open('x')",
    "import numpy as np\nclass Strategy:\n    def f(self):\n        return np.load('x')",
    "from research_loop_nq.eval import data\nclass Strategy: pass",
    "from . import x\nclass Strategy: pass",
    "class Strategy:\n    def f(self):\n        return ().__class__.__subclasses__()",
    "def f(): pass",
])
def test_sandbox_rejects(bad):
    with pytest.raises(sandbox.SandboxError):
        sandbox.check_source(bad)


def test_child_process_matches_in_process(tmp_path):
    sandbox.check_source(GOOD)
    p = tmp_path / "good.py"
    p.write_text(GOOD)
    s = make_session({m(1, 0): (100.5, 100.5, 100.5, 100.5)})
    cls = engine.load_strategy_class(p)
    a = engine.run([], [s], cls({"risk": 2.0}))
    with engine.ChildStrategy(p, {"risk": 2.0}) as ch:
        b = engine.run([], [s], ch)
    assert a["trades"] == b["trades"] and len(a["trades"]) == 1


def test_manifest_refuses_on_any_change(tmp_path):
    f1, f2 = tmp_path / "a.py", tmp_path / "b.json"
    f1.write_text("x = 1\n"); f2.write_text("{}")
    mf = tmp_path / "MANIFEST.sha256"
    digest = manifest.write(mf, [f1, f2], tmp_path)
    assert manifest.verify(mf, [f1, f2], tmp_path, expect_digest=digest) == digest
    f1.write_text("x = 2\n")
    with pytest.raises(manifest.HashMismatch, match="changed"):
        manifest.verify(mf, [f1, f2], tmp_path)
    f1.write_text("x = 1\n")
    f3 = tmp_path / "c.py"; f3.write_text("")
    with pytest.raises(manifest.HashMismatch, match="unpinned"):
        manifest.verify(mf, [f1, f2, f3], tmp_path)
    with pytest.raises(manifest.HashMismatch, match="missing"):
        manifest.verify(mf, [f1], tmp_path)
    mf.write_text(mf.read_text() + "\n")
    with pytest.raises(manifest.HashMismatch, match="digest"):
        manifest.verify(mf, [f1, f2], tmp_path, expect_digest=digest)


def test_child_errors_surface_instead_of_hanging(tmp_path):
    p = tmp_path / "boom.py"
    p.write_text("class Strategy:\n    def __init__(self, params):\n        pass\n    def on_bar(self, bar, pos):\n        raise ValueError('boom')\n")
    with engine.ChildStrategy(p, {}) as ch:
        with pytest.raises(engine.StrategyError, match="boom"):
            engine.run([], [make_session()], ch)
    q = tmp_path / "bad_init.py"
    q.write_text("class Strategy:\n    def __init__(self, params):\n        raise KeyError('nope')\n")
    with pytest.raises(engine.StrategyError, match="load"):
        engine.ChildStrategy(q, {})


# --- review fixes (2b) --------------------------------------------------------------------------------------------

def test_marketable_limit_rejected_and_limit_never_fills_better():
    s = make_session()
    with pytest.raises(engine.StrategyError, match="marketable"):
        run1(s, {0: {"op": "enter", "side": 1, "type": "limit", "price": 150.0, "stop": 90.0}})
    lim = {"op": "enter", "side": 1, "type": "limit", "price": 99.0, "stop": 97.0, "ttl": 3}
    s = make_session({m(1, 2): (98.75, 98.75, 98.5, 98.75)})  # gapped below the limit
    res, _ = run1(s, {0: lim})
    t = res["trades"][0]
    assert t["entry_ref"] == 99.0 and not t["at_open"]


def test_prices_snap_to_equivalent_tick():
    s = make_session({m(2, 1): (100, 100, 99.0, 100)})
    res, _ = run1(s, {0: long_mkt(stop=99.24)})          # long stop 99.24 == 99.00
    t = res["trades"][0]
    assert t["stop_init"] == 99.0 and t["exit_ref"] == 99.0
    s = make_session({m(1, 1): (100, 101.25, 100, 101)})
    res, _ = run1(s, {0: {"op": "enter", "side": 1, "type": "stop", "price": 101.01, "stop": 99.0}})
    assert res["trades"][0]["entry_ref"] == 101.25       # buy stop 101.01 == 101.25
    s = make_session({m(2, 1): (100, 102.5, 100, 100)})
    res, _ = run1(s, {0: long_mkt(stop=99.0, target=102.1)})
    t = res["trades"][0]
    assert t["target"] == 102.25 and t["exit_kind"] == "target"
    assert engine.snap(99.24, up=True) == 99.25 and engine.snap(-0.1, up=False) == -0.25


def test_market_entry_through_target_exits_at_open():
    s = make_session({m(0, 4): (100, 100, 100, 100.0), m(1, 0): (102.0, 102, 102, 102)})
    res, _ = run1(s, {0: long_mkt(stop=99.0, target=101.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "target" and t["exit_ref"] == 102.0 and t["j_exit"] == m(1, 0)


def test_side_matched_twins_neutral_to_drift():
    rng = np.random.default_rng(1)
    n = 400
    r_long = 0.25 + rng.normal(0, 1, n)
    r_short = -r_long                     # same path taken short
    # long-only, zero timing skill: coin flips are fooled by the drift, side-matched twins are not
    tw = twins.twin_test(r_long, r_long, r_short, sides=np.ones(n), n=2000)
    assert tw["p_coin"] < 0.005 and tw["p"] > 0.5 and tw["long_share"] == 1.0
    # calibration: 70% long, sides independent of outcomes -> p roughly uniform
    ps = []
    for k in range(200):
        sides = np.where(rng.random(n) < 0.7, 1, -1)
        real = np.where(sides > 0, r_long, r_short)
        ps.append(twins.twin_test(real, r_long, r_short, sides=sides, n=500, seed=k)["p"])
    assert 0.01 <= np.mean(np.array(ps) < 0.05) <= 0.11


def test_action_validation():
    s = make_session()
    bad = [
        {1: {"op": "stop", "price": float("nan")}},
        {1: {"op": "stop"}},
        {0: {"op": "stop", "price": 99.0}},                                   # no position
        {1: {"op": "stop", "price": 101.0}},                                  # wrong side of close (long)
        {0: {"op": "enter", "side": 1, "type": "stop", "price": 101.0, "stop": 99.0, "ttl": 0}},
        {0: {"op": "enter", "side": 1, "type": "stop", "price": 101.0, "stop": 99.0, "ttl": None}},
        {0: {"op": "enter", "side": True, "type": "market", "stop": 99.0}},
        {s.flat_slot - 1: {"op": "bogus"}},                                   # checked even on the bar before the flat
    ]
    for acts in bad:
        if 1 in acts and acts[1].get("op") == "stop" and 0 not in acts:
            acts = {0: long_mkt(stop=99.0), **acts}
        with pytest.raises(engine.StrategyError):
            run1(s, acts)


def test_exit_cancels_pending_and_replace_counted():
    st = {"op": "enter", "side": 1, "type": "stop", "price": 101.0, "stop": 99.0, "ttl": 20}
    s = make_session({m(5, 1): (100, 101.5, 100, 101)})
    res, _ = run1(s, {0: st, 2: {"op": "exit"}})
    assert res["trades"] == []
    res, _ = run1(s, {0: st, 1: st})
    assert res["replaced"] == 1 and len(res["trades"]) == 1


def test_bar_dict_is_a_copy():
    s = make_session()
    s.news = [600]
    s.overnight = {"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10.0}

    class Mut:
        def on_bar(self, bar, pos):
            bar["news"].append(1)
            bar["overnight"]["h"] = 99
            return None

    engine.run([], [s], Mut())
    assert s.news == [600] and s.overnight["h"] == 2.0


def test_halt_missing_5m_bars_and_no_flat_bar():
    s = make_session({m(13, 0): (103.0, 103, 103, 103)})
    keep = np.ones(len(s.o), bool)
    keep[m(10):m(13)] = False                                  # slots 10-12 missing (halt)
    for k in ("t", "mod", "o", "h", "l", "c", "v"):
        setattr(s, k, getattr(s, k)[keep])
    s.b5 = data.five_minute(s)
    res, st = run1(s, {9: long_mkt(stop=99.0)})
    t = res["trades"][0]
    assert t["entry_ref"] == 103.0 and t["entry_mod"] == C.RTH_OPEN + 65
    s = make_session()
    cut = s.mod < 15 * 60 + 30
    for k in ("t", "mod", "o", "h", "l", "c", "v"):
        setattr(s, k, getattr(s, k)[cut])
    s.b5 = data.five_minute(s)
    res, _ = run1(s, {0: long_mkt(stop=99.0)})
    t = res["trades"][0]
    assert t["exit_kind"] == "flat" and t["j_exit"] == len(s.c) - 1


def test_pending_ttl_never_fills_in_flat_bar():
    st = {"op": "enter", "side": 1, "type": "stop", "price": 101.0, "stop": 99.0, "ttl": 5}
    s = make_session()
    s.h[m(s.flat_slot, 1)] = 102.0
    res, _ = run1(s, {s.flat_slot - 2: st})
    assert res["trades"] == []


def test_short_stress_costs_and_pmf_sampling():
    t = {"side": -1, "entry_kind": "market", "entry_ref": 100.0, "exit_kind": "stop", "exit_ref": 101.0,
         "risk_pts": 1.0, "entry_mod": 600, "exit_mod": 700}
    b = costs.apply([t] * 200, "base")["usd"]
    s = costs.apply([t] * 200, "stress")["usd"]
    assert b[0] == pytest.approx(-PV - 2 * TV - 1.0) and (s < b).all()
    draws = costs.stop_slip_draw(np.full(100_000, 9 * 60 + 40), np.random.default_rng(0))
    pm = costs._pmf()[0]
    assert (pm[0], pm[1]) == (570, 600)
    assert np.mean(draws == 0) == pytest.approx(pm[3][0], abs=0.01)
    assert np.mean(draws) == pytest.approx(float((pm[2] * pm[3]).sum()), abs=0.05)


def test_gate_nan_fails_and_good_passes():
    good = {"trades": 300, "twin": {"p": 0.001}, "mean_r_base": 0.1, "ci_base": [0.02, 0.2], "mean_r_stress": 0.05,
            "max_year_share": 0.3, "ex_top5_mean": 0.08, "folds": [0.1, 0.1, -0.1]}
    assert criteria.gate(good, "dev") == (True, [])
    for k, v in (("mean_r_base", float("nan")), ("ci_base", [float("nan"), 1]), ("ex_top5_mean", float("nan")),
                 ("folds", [float("nan"), float("nan"), 0.1]), ("max_year_share", float("inf"))):
        ok, why = criteria.gate({**good, k: v}, "dev")
        assert not ok and why
    assert not criteria.gate({**good, "twin": {"p": 0.01}}, "dev")[0]
    assert criteria.gate({**good, "twin": {"p": 0.01}, "trades": 150}, "val1")[0]


def test_news_snapshot_is_scheduled_only():
    import json
    n = json.loads((C.EVAL_DIR / "news.json").read_text())
    assert "2020-03-03" not in n["rth"]
    assert n["news_days_coverage"][1] <= "2026-12-31"
    assert all(C.RTH_OPEN <= x < C.RTH_CLOSE for v in n["rth"].values() for x in v)


def test_nyse_half_day_rule():
    yes = [date(2019, 11, 29), date(2019, 7, 3), date(2019, 12, 24), date(2012, 7, 3), date(2025, 7, 3), date(2024, 12, 24)]
    no = [date(2026, 7, 3), date(2021, 12, 24), date(2015, 7, 3), date(2020, 7, 3), date(2019, 11, 22), date(2016, 12, 23)]
    assert all(data.nyse_half_day(d) for d in yes) and not any(data.nyse_half_day(d) for d in no)


def test_2011_news_day_unknown_and_split_bounds():
    warm, trade = data.load_split("val1")
    assert warm[-1].day == date(2019, 1, 8) and trade[0].day == date(2019, 1, 9) and len(warm) == C.WARMUP_SESSIONS
    assert sum(1 for s in warm if s.day >= date(2019, 1, 1)) == C.GAP_SESSIONS
    ses = data.load_window(date(2011, 3, 1), date(2011, 4, 1))
    assert all(s.news_day is None for s in ses)


def test_manifest_tracks_init_files_env_and_excludes_later_data():
    files = manifest.tracked()
    names = {str(p.relative_to(C.ML)) for p in files}
    assert "research_loop_nq/__init__.py" in names and "research_loop_nq/tests/__init__.py" in names
    assert "research_loop_nq/eval/news.json" in names and "research_loop_nq/tests/test_eval.py" in names
    assert not any("MANIFEST" in n for n in names) and not any(n.startswith("research_loop/") for n in names)
    pq = [n for n in names if n.endswith(".parquet")]
    assert all(manifest.SPAN.search(n)[1] <= C.LAST_ON_DISK.isoformat() for n in pq)
    nq = [n for n in pq if f"/{C.PRODUCT}/" in n]
    es = [n for n in pq if f"/{C.COMPANION}/" in n]
    assert len(nq) >= 180 and len(es) >= 180 and len(nq) + len(es) == len(pq)
    assert any(k.startswith("env:python=") for k in manifest.compute(files[:1]))


@pytest.mark.parametrize("bad", [
    "from numpy import load\nclass Strategy: pass",
    "from numpy.lib import npyio\nclass Strategy: pass",
    "import typing\nclass Strategy: pass",
    "class Strategy:\n    def f(self):\n        return len.__self__.open('x')",
    "import numpy\nclass Strategy:\n    def f(self):\n        return numpy.lib.format",
    "class Strategy:\n    def f(self, o):\n        return type(o).__mro__",
])
def test_sandbox_rejects_review_bypasses(bad):
    with pytest.raises(sandbox.SandboxError):
        sandbox.check_source(bad)


# --- ES companion (NQ loop) ---------------------------------------------------------------------------------------

def _pair(es_bars=None, nq_bars=None, **kw):
    s = make_session(nq_bars, **kw)
    e = make_session(es_bars, base=40.0, **kw)
    e.prev_close = 39.5
    data.attach_companion([s], [e])
    return s, e


def test_companion_bar_k_is_es_slot_k_and_has_no_lookahead():
    rng = np.random.default_rng(1)
    px = 40 + np.cumsum(rng.normal(0, 0.25, 390))
    es = {i: (px[i], px[i] + 0.5, px[i] - 0.5, px[i]) for i in range(390)}
    s1, e1 = _pair(es)
    es2 = dict(es)
    for i in range(m(40), 390):
        es2[i] = (px[i] + 9, px[i] + 10, px[i] + 8, px[i] + 9)
    s2, _ = _pair(es2)
    _, a = run1(s1, {})
    _, b = run1(s2, {})
    assert [x[0]["es"] for x in a.seen[:40]] == [x[0]["es"] for x in b.seen[:40]]
    assert a.seen[40][0]["es"] != b.seen[40][0]["es"]
    for step, (bar, _) in enumerate(a.seen):
        lo, hi = m(step), m(step) + 4                      # ES minutes of slot k only: it closes with NQ slot k
        assert bar["es"]["o"] == pytest.approx(e1.o[lo]) and bar["es"]["c"] == pytest.approx(e1.c[hi])
        assert bar["es"]["h"] == pytest.approx(e1.h[lo:hi + 1].max()) and bar["es"]["l"] == pytest.approx(e1.l[lo:hi + 1].min())
        assert bar["es"]["v"] == pytest.approx(e1.v[lo:hi + 1].sum())
        assert bar["es_prev_close"] == 39.5 and bar["es_roll"] is False


def test_companion_missing_slot_session_or_close_gives_none():
    s = make_session()
    e = make_session(base=40.0)
    keep = np.ones(len(e.o), bool)
    keep[m(10):m(13)] = False                                  # ES slots 10-12 missing
    for k in ("t", "mod", "o", "h", "l", "c", "v"):
        setattr(e, k, getattr(e, k)[keep])
    e.b5 = data.five_minute(e)
    data.attach_companion([s], [e])
    _, st = run1(s, {})
    got = {bar["slot"]: bar["es"] for bar, _ in st.seen}
    assert all(got[k] is None for k in (10, 11, 12)) and got[9] is not None and got[13] is not None
    s = make_session()
    data.attach_companion([s], [make_session(day=date(2019, 6, 4), base=40.0)])   # no ES session that date
    _, st = run1(s, {})
    assert all(bar["es"] is None and bar["es_prev_close"] is None for bar, _ in st.seen)
    s = make_session()
    data.attach_companion([s], [make_session(half=True, base=40.0)])            # close mismatch
    assert s.es5 is None and s.es_prev_close is None


def test_companion_bar_dict_is_a_copy():
    s, _ = _pair()

    class Mut:
        def on_bar(self, bar, pos):
            bar["es"]["h"] = 999.0
            return None

    engine.run([], [s], Mut())
    assert all(v["h"] == 40.0 for v in s.es5.values())


def test_companion_real_data_matches_es_sessions(nq2019):
    lo, hi = date(2019, 1, 2), date(2019, 12, 31)
    es = {e.day: e for e in data.build_sessions(data._raw(lo, hi, C.COMPANION))}
    assert all(s.es5 is not None for s in nq2019)
    for s in nq2019:
        e = es[s.day]
        assert e.close_mod == s.close_mod and s.es_roll == e.roll
        assert sorted(s.es5) == [int(x) for x in e.b5["slot"]]
        for k, x in s.es5.items():
            j = int(np.flatnonzero(e.b5["slot"] == k)[0])
            assert x["c"] == e.b5["c"][j] and x["h"] == e.b5["h"][j]
            assert int(e.mod[e.b5["b"][j]]) // C.BAR_MINUTES == (C.RTH_OPEN + 5 * k) // C.BAR_MINUTES  # ES bar ends in slot k
        assert 1.5 < s.c[-1] / e.c[-1] < 5.0           # NQ/ES ratio: it is really ES, not NQ again
        assert set(s.es5) >= {int(x) for x in s.b5["slot"]}
    # es_prev_close checked from the raw ES session list, not the attach path: previous ES day's 15:59 (or 12:59) close
    ed = sorted(es)
    for s in nq2019:
        i = ed.index(s.day)
        if i == 0 or es[ed[i - 1]].inst != es[s.day].inst:
            assert s.es_prev_close is None and (i == 0 or s.es_roll)
        else:
            p = es[ed[i - 1]]
            assert ed[i - 1] < s.day and s.es_prev_close == p.c[-1] and int(p.mod[-1]) == p.close_mod - 1
    assert sum(s.es_roll for s in nq2019) >= 3


@pytest.mark.parametrize("split", sorted(C.SPLITS))
def test_companion_session_alignment_every_split(split):
    warm, trade = data.load_split(split)
    ses = warm + trade
    missing = [s.day for s in ses if s.es5 is None]
    assert missing == []
    short = [s.day for s in ses if not {int(x) for x in s.b5["slot"]} <= set(s.es5)]
    assert short == []                                  # measured: every NQ slot has an ES bar in every split
