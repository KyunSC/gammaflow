"""Synthetic-only tests for choch_futures_lucid (no real bar is read)."""
import json

import numpy as np
import pandas as pd
import pytest

import choch_futures_lucid as c

ET = "America/New_York"
F = (100.0, 98.0, 99.0)                       # flat filler 15m bar (h, l, c)
P = [(100, 98, 99), (104, 101, 103), (99, 95, 96), (102, 97, 101), (96, 92, 93), (100, 94, 99), (104, 99, 103.5)]
G = (104.0, 103.0, 103.5)                     # flat filler after the break
# k=1 on P: swing highs 104 (P1), 102 (P3); swing lows 95 (P2), 92 (P4) -> downtrend; P6 closes 103.5 > 102 -> long,
# extreme = min(92, lows from P3 through P6) = 92.


def session_df(d, bins, iid=1, tf=15):
    """One RTH session of 1m bars from 09:30 ET; every 1m bar of a tf bin has the bin's (h, l) and o = c = close."""
    t0 = pd.Timestamp(f"{d} 09:30", tz=ET)
    rows, idx = [], []
    for b, (h, l, cl) in enumerate(bins):
        for j in range(tf):
            idx.append(t0 + pd.Timedelta(minutes=b * tf + j))
            rows.append((cl, h, l, cl, iid))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "instrument_id"],
                        index=pd.DatetimeIndex(idx).tz_convert("UTC"))


def tape_of(*sessions):
    return c.make_tape(pd.concat(sessions))


def bins_with_break_at(b):
    """26 bins with P6 (the break) at bin b."""
    return [F] * (b - 6) + P + [G] * (26 - b - 1)


def days(n, start="2021-03-01"):
    return [d.date() for d in pd.bdate_range(start, periods=n)]


# ---------------------------------------------------------------- bars

@pytest.mark.parametrize("d", ["2021-03-12", "2021-03-15", "2021-11-05", "2021-11-08", "2021-07-01", "2021-01-04"])
def test_15m_bins_anchored_at_0930_et_across_dst(d):
    df = session_df(d, [F] * 26)
    extra = df.iloc[[0, -1]].copy()
    extra.index = extra.index + pd.to_timedelta([-1, 1], unit="min")   # 09:29 and 16:00 ET must be dropped
    t = c.make_tape(pd.concat([df, extra]))
    assert len(t.m) == 390 and t.m[0] == 570 and t.m[-1] == 959
    b = c.tf_bars(t, 15)
    assert list(b.start_m) == [570 + 15 * i for i in range(26)] and b.close_m[-1] == 960
    assert len(c.tf_bars(t, 5).h) == 78 and len(c.tf_bars(t, 30).h) == 13 and c.tf_bars(t, 30).close_m[-1] == 960


def test_bin_values_and_missing_minute():
    bins = [(100 + i, 90 + i, 95 + i) for i in range(26)]
    df = session_df("2021-06-01", bins).drop(pd.Timestamp("2021-06-01 09:44", tz=ET).tz_convert("UTC"))
    t = c.make_tape(df, min_bars=1)
    b = c.tf_bars(t, 15)
    assert len(b.h) == 26 and b.h[3] == 103 and b.l[3] == 93 and b.c[3] == 98
    assert b.c[0] == 95 and t.m[b.last[0]] == 583  # 09:44 missing: the first bin ends at 09:43


def test_early_close_and_mixed_sessions_dropped_and_segments():
    ds = days(4)
    s = [session_df(ds[0], [F] * 26, 1), session_df(ds[1], [F] * 14, 1), session_df(ds[2], [F] * 26, 1),
         session_df(ds[3], [F] * 26, 2)]  # ds[1] closes at 13:00 ET (scheduled early close)
    mixed = session_df(days(5)[4], [F] * 26, 2)
    mixed.iloc[200:, mixed.columns.get_loc("instrument_id")] = 3
    t = tape_of(*s, mixed)
    assert list(t.d) == [ds[0], ds[2], ds[3]] and list(t.seg) == [1, 1, 2] and list(t.first) == [True, False, True]


def test_halted_session_with_full_close_is_kept():
    # a 15-minute market-wide halt (e.g. 2020-03-09) leaves ~375 RTH bars but the session still runs to 15:59
    ds = days(2)
    halted = session_df(ds[1], [F] * 26)
    halted = halted.drop(halted.index[60:75])
    t = tape_of(session_df(ds[0], [F] * 26), halted)
    assert list(t.d) == ds and len(t.m) == 390 + 375


# ---------------------------------------------------------------- rule plumbing

def test_swings_carry_across_sessions_but_not_rolls():
    ds = days(3)
    s0 = session_df(ds[0], [F] * 26)
    s1 = session_df(ds[1], [F] * 21 + P[:5])          # swings form at the end of yesterday's RTH
    s2 = [P[5], P[6]] + [G] * 24                       # the break comes at today's 09:45 bar
    t = tape_of(s0, s1, session_df(ds[2], s2))
    sig = c.signals(t, c.tf_bars(t, 15), 1)
    assert len(sig) == 1 and sig[0].side == 1 and sig[0].sess == 2 and sig[0].close_m == 600
    assert t.m[sig[0].e] == 600
    t2 = tape_of(s0, s1, session_df(ds[2], s2, iid=2))  # a roll overnight: swings restart
    assert c.raw_events(c.tf_bars(t2, 15), 1) == [] and c.signals(t2, c.tf_bars(t2, 15), 1) == []


def test_no_trade_on_first_session_of_contract():
    ds = days(2)
    one = tape_of(session_df(ds[0], bins_with_break_at(16)))
    assert len(c.raw_events(c.tf_bars(one, 15), 1)) == 1 and c.signals(one, c.tf_bars(one, 15), 1) == []
    two = tape_of(session_df(ds[0], [F] * 26), session_df(ds[1], bins_with_break_at(16)))
    assert len(c.signals(two, c.tf_bars(two, 15), 1)) == 1
    # a roll makes the second session a contract's first session again
    rolled = tape_of(session_df(ds[0], [F] * 26), session_df(ds[1], bins_with_break_at(16), iid=2))
    assert len(c.raw_events(c.tf_bars(rolled, 15), 1)) == 1 and c.signals(rolled, c.tf_bars(rolled, 15), 1) == []


@pytest.mark.parametrize("b,ok", [(20, True), (21, True), (22, False), (25, False)])
def test_last_signal_cutoff_1500(b, ok):
    ds = days(2)
    t = tape_of(session_df(ds[0], [F] * 26), session_df(ds[1], bins_with_break_at(b)))
    sig = c.signals(t, c.tf_bars(t, 15), 1)
    assert len(c.raw_events(c.tf_bars(t, 15), 1)) == 1 and (len(sig) == 1) == ok
    if ok:
        assert sig[0].close_m == 570 + 15 * (b + 1) <= 900


def test_entry_next_1m_open_and_stop_distance():
    ds = days(2)
    df1 = session_df(ds[1], bins_with_break_at(16))
    pos = df1.index.get_loc(pd.Timestamp(f"{ds[1]} 13:45", tz=ET).tz_convert("UTC"))
    df1.iloc[pos, df1.columns.get_loc("open")] = 103.0
    t = tape_of(session_df(ds[0], [F] * 26), df1)
    bars = c.tf_bars(t, 15)
    (sg,) = c.signals(t, bars, 1)
    assert t.m[sg.e] == 825 and sg.close_m == 825
    atr = c.atr_simple(bars.h, bars.l, bars.c)[sg.bar]
    assert sg.dist == round((103.5 - 92 + 0.1 * atr) / 0.25) * 0.25
    (tr,) = c.run_book(t, [sg], c.PT_USD["NQ"])
    assert tr.legs[1]["entry"] == 103.25 and tr.legs[-1]["entry"] == 102.75


def test_atr_restarts_per_segment_and_needs_14_bars():
    a = c.atr_simple(np.arange(20.0) + 2, np.arange(20.0), np.arange(20.0) + 1)
    assert np.isnan(a[12]) and np.isfinite(a[13])
    ds = days(2)
    t = tape_of(session_df(ds[0], [F] * 26), session_df(ds[1], [F] * 5 + P + [G] * 14, iid=2))
    ev = c.raw_events(c.tf_bars(t, 15), 1)
    assert len(ev) == 1 and np.isnan(ev[0][3])  # break at the new segment's 12th bar: no ATR14 yet


def random_walk_df(n_sessions, seed, roll_at=None, start="2020-01-02", px=5000.0, scale=1.0):
    rng = np.random.default_rng(seed)
    out = []
    for i, d in enumerate(days(n_sessions, start)):
        n = 390
        steps = np.round(rng.normal(0, scale, n) / 0.25) * 0.25
        cl = px + np.cumsum(steps)
        op = np.r_[px, cl[:-1]]
        hi = np.maximum(op, cl) + np.round(np.abs(rng.normal(0, scale / 2, n)) / 0.25) * 0.25
        lo = np.minimum(op, cl) - np.round(np.abs(rng.normal(0, scale / 2, n)) / 0.25) * 0.25
        px = cl[-1] + np.round(rng.normal(0, 4 * scale) / 0.25) * 0.25   # overnight gap
        iid = 1 if roll_at is None or i < roll_at else 2
        idx = pd.Timestamp(f"{d} 09:30", tz=ET) + pd.to_timedelta(np.arange(n), unit="min")
        out.append(pd.DataFrame(dict(open=op, high=hi, low=lo, close=cl, instrument_id=iid),
                                index=idx.tz_convert("UTC")))
    return pd.concat(out)


def test_prefix_invariance():
    df = random_walk_df(30, 3, roll_at=12)
    cut = pd.Timestamp(f"{days(30, '2020-01-02')[20]} 12:07", tz=ET).tz_convert("UTC")
    full, part = c.make_tape(df, min_bars=1), c.make_tape(df[df.index < cut], min_bars=1)
    cut_sess, cut_m = 20, 12 * 60 + 7
    for k, tf in ((1, 5), (2, 15), (3, 30)):
        def key(t, sigs):
            return [(t.d[s.sess], s.close_m, s.side, s.dist, t.m[s.e]) for s in sigs
                    if s.sess < cut_sess or (s.sess == cut_sess and s.close_m < cut_m)]
        a = key(full, c.signals(full, c.tf_bars(full, tf), k))
        b = key(part, c.signals(part, c.tf_bars(part, tf), k))
        assert a == b and len(a) > 0


# ---------------------------------------------------------------- execution

def one_session(path, d="2021-06-01"):
    """Tape of one session from a list of (o, h, l, c) 1m bars, padded flat to 15:59."""
    last = path[-1][3]
    rows = list(path) + [(last, last, last, last)] * (390 - len(path))
    idx = pd.Timestamp(f"{d} 09:30", tz=ET) + pd.to_timedelta(np.arange(390), unit="min")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx.tz_convert("UTC")).assign(instrument_id=1)
    return c.make_tape(df)


E0 = (100, 100.5, 99.5, 100)   # entry bar: long entry 100.25, stop 96.25, target 104.25 (fills on 104.5)


@pytest.mark.parametrize("bar1,why,pts,x", [
    ((100, 104.5, 99, 104), "target", 4.0, 1),
    ((100, 104.25, 99, 104), "time", 104 - 0.25 - 100.25, 389),    # touching the target is not a fill
    ((100, 101, 96, 97), "stop", 96.0 - 100.25, 1),               # stop - 1 tick
    ((95, 95.5, 94, 95), "stop", 94.75 - 100.25, 1),               # gap through the stop: open - 1 tick
    ((100, 105, 96, 100), "stop", 96.0 - 100.25, 1),               # both on one bar: stop first
])
def test_long_leg(bar1, why, pts, x):
    t = one_session([E0, bar1])
    lg = c.leg(t, 0, 1, 4.0)
    assert lg["why"] == why and abs(lg["pts"] - pts) < 1e-9 and lg["exit"] == x and lg["entry"] == 100.25


@pytest.mark.parametrize("bar1,why,pts", [
    ((100, 101, 95.5, 96), "target", 4.0),                         # short entry 99.75, target 95.75 (fills 95.5)
    ((100, 104, 99, 103), "stop", 99.75 - 104.0),                  # stop 103.75 + 1 tick
    ((105, 105.5, 104, 105), "stop", 99.75 - 105.25),              # gap: open + 1 tick
    ((100, 104, 95, 100), "stop", 99.75 - 104.0),
    ((100, 100.5, 99, 99), "time", 99.75 - 99.25),                 # flat at 15:59 close + 1 tick
])
def test_short_leg(bar1, why, pts):
    t = one_session([E0, bar1])
    lg = c.leg(t, 0, -1, 4.0)
    assert lg["why"] == why and abs(lg["pts"] - pts) < 1e-9 and lg["entry"] == 99.75


def test_stop_on_entry_bar_fills_at_stop_not_open():
    t = one_session([(100, 100.5, 90, 91)])
    lg = c.leg(t, 0, 1, 4.0)
    assert lg["why"] == "stop" and lg["exit"] == 0 and abs(lg["pts"] + 4.25) < 1e-9 and lg["mae"] == -4.25


def test_time_exit_is_last_bar_and_mae_mfe():
    t = one_session([E0, (100, 103, 97, 101)])
    lg = c.leg(t, 0, 1, 4.0)
    assert lg["why"] == "time" and lg["exit"] == 389 and abs(lg["pts"] - 0.5) < 1e-9
    assert lg["mae"] == 97 - 100.25 and lg["mfe"] == 103 - 100.25


# ---------------------------------------------------------------- sizing and book

def test_sizing_and_cap():
    assert c.contracts(20, 2.0, 1050) == 25                 # 1050 / (40 + 1)
    assert c.contracts(2, 5.0, 1050) == 40 and c.uncapped(2, 5.0, 1050) == 95
    assert c.contracts(600, 2.0, 1050) == 0
    assert c.contracts(20, 2.0, 1550) == 37
    sg = c.Signal(e=1, side=1, dist=600.0, sess=0, bar=0, close_m=571)
    assert c.run_book(one_session([E0, E0]), [sg], 2.0) == []   # sized 0 -> skipped


def test_net_r_matches_dollars_at_stake():
    t = one_session([E0, (100, 101, 96, 97)])
    sg = c.Signal(e=0, side=1, dist=4.0, sess=0, bar=0, close_m=570)
    (tr,) = c.run_book(t, [sg], 2.0)
    n = c.contracts(4.0, 2.0, 1050)
    d = c.lucid_days(t, [tr], np.array([1]), 2.0, 1050)
    assert n == 40 and abs(d["pnl"][0] / (n * 4.0 * 2.0) - c.net_r(tr.legs[1], 4.0, 2.0)) < 1e-12
    assert abs(c.net_r(tr.legs[1], 4.0, 2.0) - (-4.25 * 2 - 1) / 8) < 1e-12
    assert d["lo"][0] <= d["pnl"][0] < 0 and d["trades"][0] == 1


def test_book_drops_signals_while_either_mirror_is_open():
    t = one_session([E0, (100, 101, 96, 97)])
    sigs = [c.Signal(0, 1, 4.0, 0, 0, 570), c.Signal(2, -1, 4.0, 0, 0, 572), c.Signal(389, 1, 4.0, 0, 0, 959)]
    # the long stops out at bar 1 (low 96 <= 96.25) but its short mirror (target fills at 95.5) runs to 15:59
    (tr,) = c.run_book(t, sigs, 2.0)
    assert tr.legs[1]["exit"] == 1 and tr.legs[-1]["exit"] == 389 and tr.legs[-1]["why"] == "time"
    t2 = one_session([E0, (100, 101, 95, 96)])   # both mirrors done at bar 1 -> the next signal is taken
    assert [x.sig.e for x in c.run_book(t2, sigs, 2.0)] == [0, 2]


def test_lucid_days_stack_trades():
    t = one_session([E0, (100, 104.5, 99, 104), (104, 104.5, 103.5, 104), (104, 104.5, 99.5, 100)])
    s1, s2 = c.Signal(0, 1, 4.0, 0, 0, 570), c.Signal(2, -1, 4.0, 0, 0, 572)
    trades = [c.Trade(s, c.contracts(4.0, 2.0, 1050), {d: c.leg(t, s.e, d, 4.0) for d in (1, -1)}) for s in (s1, s2)]
    d = c.lucid_days(t, trades, np.array([1, -1]), 2.0, 1050)
    p1 = trades[0].legs[1]["pts"] * 2 * 40 - 40
    p2 = trades[1].legs[-1]["pts"] * 2 * 40 - 40
    assert abs(d["pnl"][0] - (p1 + p2)) < 1e-9 and d["trades"][0] == 2 and d["hi"][0] >= p1


# ---------------------------------------------------------------- statistics

def test_twin_p_calibrated_on_random_walk():
    t = c.make_tape(random_walk_df(250, 11))
    trades = c.run_book(t, c.signals(t, c.tf_bars(t, 5), 1), 2.0)
    a = c.book_arrays(t, trades, 2.0)
    assert len(trades) > 300
    rng = np.random.default_rng(5)
    ps, cover = [], []
    for i in range(300):
        pl = rng.uniform(0.3, 0.7)
        dirs = np.where(rng.random(len(trades)) < pl, 1, -1)     # directions independent of price
        r = c.r_test(a["rl"], a["rs"], dirs, a["rank"], a["n_sess"], n_twins=200, seed=i)
        ps.append(r["p"])
        cover.append(r["excess_ci"][0] <= 0 <= r["excess_ci"][1])
    ps = np.array(ps)
    assert 0.01 <= (ps < 0.05).mean() <= 0.11 and 0.38 <= (ps < 0.5).mean() <= 0.62
    assert np.mean(cover) >= 0.85


def test_r_test_detects_a_planted_edge():
    rng = np.random.default_rng(0)
    rl = rng.normal(0, 1, 2000)
    rs = -rl - 0.1
    dirs = np.where(rl > 0, 1, -1)                              # look-ahead: always the winning side
    r = c.r_test(rl, rs, dirs, np.arange(2000) // 2, 1000, n_twins=500)
    assert r["p"] < 0.01 and r["excess_ci"][0] > 0 and c.passes(r)


def test_evaluate_smoke_on_random_walk(monkeypatch):
    tapes = {"NQ": c.make_tape(random_walk_df(60, 1, roll_at=30, px=8000.0, scale=2.0)),
             "ES": c.make_tape(random_walk_df(60, 2, roll_at=30, px=3000.0, scale=0.5))}
    res = c.evaluate(tapes, n_twins=100, lucid_paths=30, lucid_twins=2, lucid_twin_paths=10, grid=[c.SPEC["primary"]])
    assert res["verdict"] in ("PASS", "STRUCTURE-ONLY", "FAIL") and res["primary"] == "k2/15m"
    s = res["configs"]["k2/15m"]["NQ"]
    if s["trades"]:
        assert set(s["exits"]) <= {"stop", "target", "time"} and 0 <= s["twins"]["p"] <= 1
    assert set(res["lucid"]["NQ"]) == {"1050", "1550", "1050_noDLL", "1550_noDLL"}


# ---------------------------------------------------------------- one look

def test_lock_written_before_bars_and_refuses_second_run(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "OUT", tmp_path)
    monkeypatch.setattr(c, "missing_months", lambda p: [])
    calls = []

    def loader(p):
        calls.append(p)
        assert (tmp_path / "lucid.lock").exists() and (tmp_path / "lucid_prereg.json").exists()
        raise RuntimeError("stop before any computation")

    monkeypatch.setattr(c, "load_tape", loader)
    with pytest.raises(RuntimeError):
        c.confirm()
    pre = json.loads((tmp_path / "lucid_prereg.json").read_text())
    assert pre["spec"]["id"] == "C6L" and len(pre["spec_hash"]) == 16 and len(pre["choch_rule_sha256"]) == 64
    assert c.confirm() == 1 and calls == ["NQ"]


def test_missing_month_refuses_without_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "OUT", tmp_path)
    monkeypatch.setattr(c, "missing_months", lambda p: ["2015-07"] if p == "ES" else [])
    monkeypatch.setattr(c, "load_tape", lambda p: pytest.fail("bars loaded"))
    assert c.confirm() == 2 and not (tmp_path / "lucid.lock").exists()


def test_spec_frozen_values():
    assert c.SPEC["primary"] == dict(k=2, tf=15) and len(c.configs()) == 12
    assert c.RISKS == (1050, 1550) and c.ALPHA == 0.025 and c.N_TWINS == 2000 and c.LUCID_PATHS == 20000
    assert c.MAX_MICROS == 40 and c.COMM_SIDE == 0.5 and c.PT_USD == {"NQ": 2.0, "ES": 5.0} and c.TICK == 0.25
    assert c.SPEC["window"] == ["2011-01-03", "2021-12-31"]
