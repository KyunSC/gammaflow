from datetime import date

import numpy as np
import pandas as pd

import overnight_nodes_study as on

T = on.TICK


def _day(o, h, l, e0=0, e1=None, fx=None):
    n = len(o)
    return {"o": np.array(o, float), "h": np.array(h, float), "l": np.array(l, float),
            "mod": np.arange(n, dtype=np.int32), "e0": e0, "e1": n if e1 is None else e1,
            "fx_open": n - 1 if fx is None else fx, "fx_close": n - 1 if fx is None else fx}


def test_et_ts_is_dst_aware():
    # 2026-03-08 is the spring-forward Sunday: 18:30 EDT = 22:30 UTC
    assert on.et_ts(date(2026, 3, 8), 18 * 60 + 30) == int(pd.Timestamp("2026-03-08 22:30", tz="UTC").value // 10**9)
    assert on.et_ts(date(2026, 1, 8), 18 * 60 + 30) == int(pd.Timestamp("2026-01-08 23:30", tz="UTC").value // 10**9)


def test_back_adjust_removes_roll_gap():
    df = pd.DataFrame({"inst": [1, 1, 2, 2], "o": [100., 101, 111, 112], "h": [101., 102, 112, 113],
                       "l": [99., 100, 110, 111], "c": [101., 101, 112, 112]})
    on.back_adjust(df)
    assert list(df["c"]) == [111., 111, 112, 112]  # gap = 111 - 101 added to the old contract
    assert list(df["o"][2:]) == [111., 112]         # newest contract unchanged


def test_tick_volume_conserves_volume_and_weights_body():
    # bar 100 -> 101 body, wicks to 99.5 / 101.5: range 8 ticks, body 4, wick ratio 0.5 -> body weight 0.7
    o, h, l, c, v = (np.array([x]) for x in (100.0, 101.5, 99.5, 101.0, 1000.0))
    idx, vol = on.tick_volume(o, h, l, c, v)
    assert abs(vol.sum() - 1000) < 1e-6
    body = vol[(idx >= 400) & (idx <= 404)].sum()
    assert abs(body - 700) < 1e-6
    assert abs(vol[idx == 406].sum() - 75) < 1e-6  # upper wick 2 ticks share 150 -> 75 each


def test_tick_volume_single_and_extreme_bars():
    o = np.array([100.0] * 20 + [100.0])
    h = np.array([100.25] * 20 + [110.0])
    l = np.array([100.0] * 20 + [100.0])
    c = np.array([100.25] * 20 + [110.0])
    v = np.array([10.0] * 20 + [41.0])
    idx, vol = on.tick_volume(o, h, l, c, v)
    assert abs(vol.sum() - 241) < 1e-6
    # the 10-pt bar is >3x ATR: spread uniformly over its 41 ticks
    assert abs(vol[idx == 430].sum() - 1.0) < 1e-6


def test_fade_from_above_hits_target_twin_stops():
    L, A, S = 100.0, 2.0, 2.0
    # bar0 armed above (low 102.5 >= 102), bar1 trades through 99.75 -> long limit at 100, then rally to 102.25
    d = _day(o=[103, 101, 100.5, 102, 102], h=[104, 101, 101, 102.5, 102], l=[102.5, 99.75, 100, 101.5, 101.5])
    tr = on.sim_level(L, d, "fade", d["fx_open"], A, S, 1.0)
    assert len(tr) == 1 and tr[0]["side"] == 1 and tr[0]["entry_ref"] == 100.0
    assert tr[0]["exit_kind"] == "target" and tr[0]["exit_ref"] == 102.0
    assert tr[0]["o_exit_kind"] == "stop" and tr[0]["o_exit_ref"] == 102.0  # short twin: stop 102 on bar 3


def test_break_from_above_shorts_one_tick_through():
    L, A, S = 100.0, 2.0, 2.0
    d = _day(o=[103, 100.5, 99.5, 98.5, 98], h=[104, 100.5, 99.5, 98.5, 98], l=[102.5, 99.5, 98.5, 97.5, 97.5])
    tr = on.sim_level(L, d, "break", d["fx_open"], A, S, 1.0)
    assert tr[0]["side"] == -1 and tr[0]["entry_kind"] == "stop" and tr[0]["entry_ref"] == 99.75
    # stop order at 99.75: stop 101.75, target 97.75 needs a print at 97.5 (bar 3)
    assert tr[0]["exit_kind"] == "target" and tr[0]["exit_ref"] == 97.75 and tr[0]["risk_pts"] == 2.0


def test_touch_before_entry_window_disarms_then_rearms():
    L, A, S = 100.0, 2.0, 2.0
    # touch on bar 1 (before e0=2) disarms; re-armed bar 2, touched bar 3 inside the window
    d = _day(o=[103, 100, 103, 100, 100, 100], h=[104, 100.5, 104, 100.5, 100.5, 100.5],
             l=[102.5, 99.5, 102.5, 99.5, 99.5, 99.5], e0=2)
    tr = on.sim_level(L, d, "fade", d["fx_open"], A, S, 1.0)
    assert len(tr) == 1 and tr[0]["entry_mod"] == 3 and tr[0]["exit_kind"] == "flat"


def test_stop_wins_inside_one_bar():
    L, A, S = 100.0, 2.0, 2.0
    d = _day(o=[103, 100, 100, 100], h=[104, 100.5, 102.5, 100], l=[102.5, 99.75, 97.5, 100])
    tr = on.sim_level(L, d, "fade", d["fx_open"], A, S, 1.0)
    assert tr[0]["exit_kind"] == "stop" and tr[0]["exit_ref"] == 98.0


def test_profiles_and_trading_window_have_no_lookahead():
    lo, hi = date(2015, 3, 2), date(2015, 4, 1)
    tasks, used = on.day_tasks("ES", lo, hi, on.P["stop_adr"], with_random=False)
    assert len(tasks) > 10
    df = on.load_bars("ES", date(2014, 12, 1), hi)
    days = on.trading_days(df)
    td = sorted(days)
    targets = [d for d in td if lo <= d < hi]
    prof = on.build_profiles(df, days, targets)
    t = df["t"].to_numpy()
    for d in targets:
        i = td.index(d)
        start = on.et_ts(date.fromordinal(d.toordinal() - 1), 18 * 60)
        assert t[days[td[i - 1]][1] - 1] < start  # previous trading day ends before this Globex open
        assert t[days[d][0]] >= start
    for (d, w), pr in prof.items():
        if pr is None:
            continue
        assert pr["lo"] <= pr["poc"][0] <= pr["hi"]
        assert all(pr["lo"] <= x <= pr["hi"] for x in pr["hvn"] + pr["lvn"])
    assert 3 <= np.median([tk["S"] for tk in tasks]) <= 20  # half an ES daily range in 2015


def test_excess_p_and_cell_pipeline_on_synthetic_trades():
    days = [f"2015-01-{d:02d}" for d in range(1, 29)]
    rng = np.random.default_rng(0)
    rows = []
    for d in days:
        for seed in range(-1, 3):
            win = rng.random() < (0.7 if seed == -1 else 0.45)
            rows.append({"cell": "week/hvn/fade/open", "seed": seed, "day": d, "side": 1, "entry_kind": "limit",
                         "entry_ref": 100.0, "risk_pts": 4.0, "entry_mod": 100, "exit_mod": 200,
                         "exit_kind": "target" if win else "stop", "exit_ref": 104.0 if win else 96.0,
                         "o_exit_kind": "stop" if win else "target", "o_exit_ref": 104.0 if win else 96.0,
                         "o_exit_mod": 200, "level": 100.0})
    tr = pd.DataFrame(rows)
    m = on.evaluate_cell("ES", tr, "week/hvn/fade/open", days, n_trials=96)
    assert m["trades"] == 28 and m["random_levels"]["excess"] > 0
    assert 0 < m["random_levels"]["p"] < 0.5
    fails = on.gate(m, "dev", 0.001)
    assert fails and fails[0].startswith("trades")  # 28 < 200
    m0 = on.evaluate_cell("ES", tr.iloc[:0], "week/hvn/fade/open", days, n_trials=96)
    assert m0["trades"] == 0 and on.gate(m0, "dev", 0.001)
