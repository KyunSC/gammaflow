"""Tests for vwap_ema_3m_study.py on synthetic bars only. Run from functions/ml:
    ../../.venv/bin/python -m pytest -q test_vwap_ema_3m_study.py
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

import vwap_ema_3m_study as V

T = V.TICK


def var(mode="none", ema=9, stop="vwap_close", warm=0):
    return dict(mode=mode, ema=ema, stop=stop, warm=warm, id=V.variant_id(mode, ema, stop, warm))


# --- hand-built Data (exact control of closes, VWAP and EMA) ----------------------------------------------------

def mk(c3, vw=100.0, ema=100.0, atr=1.0, start_sm=60, one_m=None, half=False, vwr=None):
    """3 x 1m bars per 3m bar. Default 1m: first = (prev close, max, min, close), then two flat bars at the close.
    `one_m` overrides 1m bars {j: (o, h, l, c)}; 3m OHLC are then rebuilt from the 1m bars."""
    n = len(c3)
    o1, h1, l1, c1 = [], [], [], []
    for k in range(n):
        o = c3[k - 1] if k else c3[k]
        c = c3[k]
        o1 += [o, c, c]
        h1 += [max(o, c), c, c]
        l1 += [min(o, c), c, c]
        c1 += [c, c, c]
    for j, (o, h, l, c) in (one_m or {}).items():
        o1[j], h1[j], l1[j], c1[j] = o, h, l, c
    o1, h1, l1, c1 = map(np.array, (o1, h1, l1, c1))
    a1 = np.arange(n) * 3
    b1 = a1 + 2
    sm3 = start_sm + np.arange(n) * 3
    sm1 = np.repeat(sm3, 3) + np.tile(np.arange(3), n)
    mod1 = (sm1 + V.SESSION_START_MOD) % 1440
    full = lambda x: np.full(n, x, float) if np.isscalar(x) else np.asarray(x, float)
    flat_sm = V.SM_FLAT_HALF if half else V.SM_FLAT
    hit = np.flatnonzero(sm1 >= flat_sm)
    rflat = V.SM_RTH_FLAT_HALF if half else V.SM_RTH_FLAT
    rhit = np.flatnonzero(sm1 >= rflat)
    s = {"day": date(2015, 6, 10), "k0": 0, "k1": n - 1, "j0": 0, "jl": 3 * n - 1,
         "j_flat": int(hit[0]) if len(hit) else 3 * n, "half": half, "flat_sm": flat_sm,
         "noentry_sm": V.SM_NOENTRY_HALF if half else V.SM_NOENTRY,
         "j_flat_rth": int(rhit[0]) if len(rhit) else 3 * n,
         "rth_noentry_sm": V.SM_RTH_NOENTRY_HALF if half else V.SM_RTH_NOENTRY}
    return V.Data(sym="ES", o1=o1, h1=h1, l1=l1, c1=c1, sm1=sm1, mod1=mod1, a1=a1, b1=b1, sm3=sm3,
                  o3=o1[a1], h3=np.maximum.reduceat(h1, a1), l3=np.minimum.reduceat(l1, a1), c3=c1[b1],
                  vw=full(vw), vwr=full(vw if vwr is None else vwr), ema={e: full(ema) for e in V.EMAS},
                  atr=full(atr), sessions=[s])


# --- DataFrame builder (exercises build(): sessions, 3m anchoring, VWAP, rolls) -----------------------------------

def session_df(d: date, price, inst=1, start_sm=0, end_sm=1380, switch_sm=None, inst2=2, vol=1.0):
    """1m bars of session d (18:00 ET d-1 -> end). price: scalar, array over session minutes, or callable(sm)."""
    t0 = pd.Timestamp(datetime.combine(d - timedelta(days=1), time(18, 0)), tz=V.TZ)
    sm = np.arange(start_sm, end_sm)
    p = price(sm) if callable(price) else (np.full(len(sm), price, float) if np.isscalar(price) else np.asarray(price))
    idx = (t0 + pd.to_timedelta(sm, unit="min")).tz_convert("UTC")
    ins = np.full(len(sm), inst)
    if switch_sm is not None:
        ins[sm >= switch_sm] = inst2
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "volume": vol, "instrument_id": ins}, index=idx)


def rw_df(days, seed=7):
    rng = np.random.default_rng(seed)
    parts = []
    px = 2000.0
    for d in days:
        n = 1380
        steps = rng.choice([-1, 0, 1], size=n, p=[0.35, 0.3, 0.35]) * T * rng.integers(1, 5, size=n)
        c = px + np.cumsum(steps)
        o = np.r_[px, c[:-1]]
        h = np.maximum(o, c) + T * rng.integers(0, 3, size=n)
        l = np.minimum(o, c) - T * rng.integers(0, 3, size=n)
        px = c[-1]
        f = session_df(d, c)
        f["open"], f["high"], f["low"] = o, h, l
        f["volume"] = rng.integers(1, 50, size=n).astype(float)
        parts.append(f)
    return pd.concat(parts)


DAYS = [date(2015, 6, 8), date(2015, 6, 9), date(2015, 6, 10), date(2015, 6, 11), date(2015, 6, 12)]


# --- grid / spec ------------------------------------------------------------------------------------------------

def test_grid_is_72_and_ids_unique():
    assert len(V.GRID) == 72 and len({v["id"] for v in V.GRID}) == 72


def test_stop_slip_means_match_frozen_pmf():
    pm = json.loads((V.HERE / "research_loop" / "eval" / "stop_slip_pmf.json").read_text())["buckets"]
    means = [sum(int(k) * p for k, p in b.items()) / sum(b.values()) for b in pm.values()]
    assert [round(m, 4) for m in means] == [b[2] for b in V.STOP_SLIP_BUCKETS]
    assert V.stop_slip_mean(3 * 60) == V.STOP_SLIP_BUCKETS[-1][2]      # overnight: last bucket (evaluator rule)
    assert V.stop_slip_mean(12 * 60) == pytest.approx(1.1888)


def test_costs():
    # ES (MES) long +1 pt, market exit: 5 - 2 ticks x $1.25 - $1 commission
    assert V.trade_usd("ES", 1, 100.0, 101.0, "ema", 600)[0] == pytest.approx(1.5)
    # NQ (MNQ) round trip at the same price: -$2 (spec: ~$2 RT)
    assert V.trade_usd("NQ", -1, 100.0, 100.0, "flip", 600)[0] == pytest.approx(-2.0)
    # stop at 12:00 ET: 1 tick in + 1.1888 ticks out
    assert V.trade_usd("ES", 1, 100.0, 100.0, "stop", 720)[0] == pytest.approx(-(1 + 1.1888) * T * 5 - 1)
    # stress: 2 ticks in, 1 + mean on the stop, $1/side
    assert V.trade_usd("ES", 1, 100.0, 100.0, "stop", 720, "stress")[0] == pytest.approx(-(2 + 2.1888) * T * 5 - 2)
    # stress market/flat fills: 2 ticks each way on MNQ, $1/side
    assert V.trade_usd("NQ", 1, 100.0, 100.0, "flip", 600, "stress")[0] == pytest.approx(-4 * T * 2 - 2)
    assert V.trade_usd("NQ", 1, 100.0, 100.0, "flat", 1015, "stress")[0] == pytest.approx(-4 * T * 2 - 2)


# --- guard ------------------------------------------------------------------------------------------------------

def test_guard_refuses_2022_without_confirm():
    with pytest.raises(PermissionError):
        V.assert_window(date(2022, 1, 3), date(2022, 2, 1))
    with pytest.raises(PermissionError):
        V.assert_window(date(2018, 1, 2), date(2023, 1, 1))
    with pytest.raises(PermissionError):
        V.load_1m("ES", date(2024, 1, 2), date(2024, 1, 5))   # raises before any file is read


def test_guard_discovery_bounds():
    V.assert_window(V.DISC_LO, V.DISC_HI)
    with pytest.raises(PermissionError):                 # 2019-21 is newer data too: prereg path only
        V.assert_window(date(2019, 1, 2), date(2019, 6, 1))
    with pytest.raises(ValueError):
        V.assert_window(date(2010, 12, 1), date(2011, 6, 1))


def test_guard_confirm_needs_prereg(tmp_path):
    missing = tmp_path / "none.json"
    with pytest.raises(PermissionError):
        V.assert_window(V.CONF_LO, V.CONF_HI, confirm=True, prereg=missing)
    pr = tmp_path / "pr.json"
    pr.write_text("{}")
    V.assert_window(V.CONF_LO, V.CONF_HI, confirm=True, prereg=pr)
    V.assert_window(V.VAL1_LO, V.VAL1_HI, confirm=True, prereg=pr)
    with pytest.raises(ValueError):
        V.assert_window(date(2022, 1, 3), date(2023, 1, 1), confirm=True, prereg=pr)


def test_cli_refuses_2022_and_confirm_without_prereg(monkeypatch, tmp_path):
    with pytest.raises(PermissionError):
        V.main(["--start", "2022-01-03", "--end", "2022-03-01"])
    monkeypatch.setattr(V, "PREREG", tmp_path / "absent.json")
    with pytest.raises(PermissionError):          # assert_window resolves PREREG at call time
        V.main(["--confirm"])


def _no_reads(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("bars were read")
    monkeypatch.setattr(V.pd, "read_parquet", boom)


def test_confirm_loader_needs_run_confirm(monkeypatch, tmp_path):
    pr = tmp_path / "pr.json"
    pr.write_text("{}")
    monkeypatch.setattr(V, "PREREG", pr)
    monkeypatch.setattr(V, "LOCK", tmp_path / "confirm.lock")
    _no_reads(monkeypatch)
    with pytest.raises(PermissionError):          # prereg exists, but not armed by run_confirm
        V.load_1m("ES", V.CONF_LO, V.CONF_HI, confirm=True)
    with pytest.raises(PermissionError):
        V.run_symbol("ES", V.CONF_LO, V.CONF_HI, V.GRID[:1], confirm=True)


def test_run_confirm_refuses_hash_mismatch_and_second_look(monkeypatch, tmp_path):
    _no_reads(monkeypatch)
    pr = tmp_path / "pr.json"
    monkeypatch.setattr(V, "PREREG", pr)
    monkeypatch.setattr(V, "OUT", tmp_path)
    monkeypatch.setattr(V, "LOCK", tmp_path / "confirm.lock")
    pr.write_text(json.dumps({"spec_sha256": "x", "study_sha256": V.sha(V.Path(V.__file__)), "variants": []}))
    with pytest.raises(SystemExit, match="changed"):
        V.run_confirm(1)
    assert not (tmp_path / "confirm.lock").exists()
    pr.write_text(json.dumps({"spec_sha256": V.sha(V.SPEC), "study_sha256": V.sha(V.Path(V.__file__)),
                              "variants": []}))
    (tmp_path / "confirm.lock").write_text("2026-11-03")
    with pytest.raises(SystemExit, match="spent"):
        V.run_confirm(1)


def test_draft_prereg_only_freezes_passing_variants(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "PREREG", tmp_path / "pr.json")
    disc = tmp_path / "discovery.json"
    ok = V.GRID[0]["id"]
    good = {"spec_sha256": V.sha(V.SPEC), "study_sha256": V.sha(V.Path(V.__file__)), "passing": [ok]}
    disc.write_text(json.dumps(good | {"spec_sha256": "stale"}))
    with pytest.raises(SystemExit, match="different spec"):
        V.draft_prereg([ok], disc)
    disc.write_text(json.dumps(good))
    with pytest.raises(SystemExit, match="not gate-passing"):
        V.draft_prereg([V.GRID[1]["id"]], disc)
    with pytest.raises(SystemExit, match="1 or 2"):
        V.draft_prereg([ok, V.GRID[1]["id"], V.GRID[2]["id"]], disc)
    V.draft_prereg([ok], disc)
    pr = json.loads((tmp_path / "pr.json").read_text())
    assert pr["variants"] == [ok] and pr["spec_sha256"] == V.sha(V.SPEC)
    with pytest.raises(SystemExit, match="one-shot"):
        V.draft_prereg([ok], disc)


# --- build: sessions, 3m bars, VWAP, rolls ------------------------------------------------------------------------

def test_3m_bars_anchored_at_1800_and_vwap_resets():
    df = pd.concat([session_df(DAYS[0], 100.0), session_df(DAYS[1], lambda sm: 200.0 + (sm // 3) * 0.25)])
    D = V.build(df, "ES", DAYS[0], DAYS[1])
    assert [s["day"] for s in D.sessions] == DAYS[:2]
    s1 = D.sessions[1]
    k0 = s1["k0"]
    first = pd.Timestamp(df.index[D.a1[k0]]).tz_convert(V.TZ)
    assert (first.hour, first.minute) == (18, 0) and first.date() == DAYS[0]
    assert set(np.diff(D.sm3[k0:s1["k1"] + 1])) == {3} and D.sm3[k0] == 0
    assert np.all(D.b1[k0:s1["k1"] + 1] - D.a1[k0:s1["k1"] + 1] == 2)
    # VWAP of the new session starts from its own first bar: no carry of the 100.0 session
    assert D.vw[k0] == pytest.approx(200.0)
    assert D.vw[k0 + 1] == pytest.approx((200.0 + 200.25) / 2)
    assert D.vw[s1["k0"] - 1] == pytest.approx(100.0)


def test_bar_at_1800_belongs_to_next_session():
    df = pd.concat([session_df(DAYS[0], 100.0, end_sm=1380), session_df(DAYS[1], 101.0, end_sm=1380)])
    D = V.build(df, "ES", DAYS[0], DAYS[1])
    s0, s1 = D.sessions
    assert s0["jl"] + 1 == s1["j0"]
    assert D.sm1[s1["j0"]] == 0 and D.c1[s1["j0"]] == 101.0


def test_roll_session_skipped_and_ema_restarts():
    df = pd.concat([session_df(DAYS[0], 100.0, inst=1),
                    session_df(DAYS[1], 101.0, inst=1, switch_sm=60, inst2=2),   # .v.0 rolls at 00:00 UTC
                    session_df(DAYS[2], 102.0, inst=2)])
    D = V.build(df, "ES", DAYS[0], DAYS[2])
    assert [s["day"] for s in D.sessions] == [DAYS[0], DAYS[2]]
    assert D.skipped["roll"] == 1
    k_switch = int(np.flatnonzero((D.sm3 == 60) & (D.c3 == 101.0))[0])
    assert np.isnan(D.ema[9][k_switch]) and np.isnan(D.atr[k_switch])           # restarted on the new contract
    assert not np.isnan(D.ema[9][k_switch - 1])
    assert D.ema[9][k_switch + 8] == pytest.approx(101.0) and np.isnan(D.ema[9][k_switch + 7])
    assert not np.isnan(D.ema[9][D.sessions[1]["k0"]])                            # carried across sessions


def test_roll_with_decreasing_instrument_id_skips_only_the_roll_session():
    df = pd.concat([session_df(DAYS[0], 100.0, inst=9),
                    session_df(DAYS[1], 101.0, inst=9, switch_sm=60, inst2=3),
                    session_df(DAYS[2], 102.0, inst=3), session_df(DAYS[3], 102.0, inst=3)])
    D = V.build(df, "ES", DAYS[0], DAYS[3])
    assert [s["day"] for s in D.sessions] == [DAYS[0], DAYS[2], DAYS[3]] and D.skipped["roll"] == 1


def test_session_where_contract_differs_from_previous_is_a_roll():
    df = pd.concat([session_df(DAYS[0], 100.0, inst=1), session_df(DAYS[1], 101.0, inst=2),
                    session_df(DAYS[2], 101.0, inst=2)])
    D = V.build(df, "ES", DAYS[0], DAYS[2])
    assert [s["day"] for s in D.sessions] == [DAYS[0], DAYS[2]]


def test_holiday_session_skipped_and_half_day_flat_at_1310():
    hol = date(2015, 7, 3)        # Friday, NYSE closed (Jul 4 observed): CME halts 13:00 ET
    half = date(2015, 11, 27)     # day after Thanksgiving: CME halts 13:15 ET
    df = pd.concat([session_df(date(2015, 7, 2), 100.0), session_df(hol, 100.0, end_sm=1140)])
    D = V.build(df, "ES", date(2015, 7, 2), hol)
    assert [s["day"] for s in D.sessions] == [date(2015, 7, 2)] and D.skipped["early_halt"] == 1

    price = lambda sm: np.where(sm < 60, 100.0, np.where(sm < 63, 99.0, 101.0))
    D = V.build(session_df(half, price, end_sm=1155), "ES", half, half)
    s = D.sessions[0]
    assert s["half"] and s["flat_sm"] == 19 * 60 + 10
    tr = V.simulate(D, var())
    assert tr[-1]["exit_kind"] == "flat" and tr[-1]["exit_mod"] == 13 * 60 + 10


def test_friday_1615_close_flat_at_1610_no_entry_from_1545():
    fri = date(2011, 6, 10)
    price = lambda sm: np.where(sm < 63, 99.0, 101.0)
    D = V.build(session_df(fri, price, end_sm=1335), "ES", fri, fri)     # last bar 16:14 ET
    s = D.sessions[0]
    assert (s["flat_sm"], s["noentry_sm"]) == (22 * 60 + 10, 21 * 60 + 45)
    assert D.skipped["close_1615_by_weekday"] == {4: 1}
    tr = V.simulate(D, var())
    assert tr[-1]["exit_kind"] == "flat" and tr[-1]["exit_mod"] == 16 * 60 + 10
    # a cue whose fill would be at 15:45 is not taken
    late = lambda sm: np.where(sm < 1299, 99.0, 101.0)                   # cue bar 15:39-15:42: fill 15:42
    tr = V.simulate(V.build(session_df(fri, late, end_sm=1335), "ES", fri, fri), var())
    assert [(t["entry_sm"], t["exit_mod"]) for t in tr] == [(1302, 16 * 60 + 10)]
    late = lambda sm: np.where(sm < 1302, 99.0, 101.0)                   # cue bar 15:42-15:45: fill 15:45 -> none
    assert V.simulate(V.build(session_df(fri, late, end_sm=1335), "ES", fri, fri), var()) == []


# --- timing: no lookahead ---------------------------------------------------------------------------------------

def _cue_session():
    # flat at 99 (= VWAP, no cue) until the bar at sm 63 closes 101 (long cue); the bar at sm 66 opens 101.25
    def price(sm):
        return np.where(sm < 63, 99.0, 101.0)
    df = session_df(DAYS[2], price)
    df.loc[df.index[66], "open"] = 101.25
    df.loc[df.index[66], "high"] = 101.25
    return df


def test_signal_on_close_fill_at_next_open():
    D = V.build(_cue_session(), "ES", DAYS[2], DAYS[2])
    tr = V.simulate(D, var())
    t = tr[0]
    assert t["side"] == 1
    assert D.sm3[t["k_cue"]] == 63 and t["k_entry"] == t["k_cue"] + 1
    assert t["entry_sm"] == 66 and t["entry_ref"] == 101.25                    # next 3m bar's first 1m open
    # 16:55 flat at the 1m open, never at a close
    assert t["exit_kind"] == "flat" and t["exit_mod"] == 16 * 60 + 55 and t["exit_ref"] == 101.0


def test_future_bars_cannot_change_past_trades():
    days = DAYS[:4]
    base = rw_df(days)
    D0 = V.build(base, "ES", days[0], days[-1])
    cut = D0.sessions[2]["j0"] + 500
    pert = base.copy()
    rng = np.random.default_rng(1)
    shift = np.cumsum(rng.normal(0, 2.0, size=len(pert) - cut))
    for col in ("open", "high", "low", "close"):
        pert.iloc[cut:, pert.columns.get_loc(col)] += shift
    pert.iloc[cut:, pert.columns.get_loc("volume")] *= 3
    D1 = V.build(pert, "ES", days[0], days[-1])
    for v in V.GRID:
        a = [t for t in V.simulate(D0, v) if t["j_exit"] < cut]
        b = [t for t in V.simulate(D1, v) if t["j_exit"] < cut]
        key = lambda t: (t["side"], t["j_entry"], t["entry_ref"], t["exit_kind"], t["j_exit"], t["exit_ref"])
        assert [key(t) for t in a] == [key(t) for t in b], v["id"]
        assert len(a) > 0


def test_cue_needs_previous_close_on_other_side():
    # closes 101, 101, 101 above VWAP 100 the whole time: no cross, no trade
    assert V.simulate(mk([101.0] * 8), var()) == []


# --- flip logic -------------------------------------------------------------------------------------------------

def test_flip_reverses_at_the_same_open():
    D = mk([100.0, 99.0, 101.0, 101.0, 99.0, 99.0], ema=100.0)
    tr = V.simulate(D, var())
    assert [(t["side"], t["k_entry"], t["exit_kind"]) for t in tr] == [(-1, 2, "flip"), (1, 3, "flip"), (-1, 5, "end")]
    for a, b in zip(tr, tr[1:]):
        assert a["j_exit"] == b["j_entry"] and a["exit_ref"] == b["entry_ref"]


def test_filter_entry_blocks_cue_and_ema_exit_fires_instead_of_flip():
    # EMA 101 > VWAP 100: longs allowed, shorts blocked. Long cue at k=1; short cue at k=3 fails the filter,
    # but close 99.5 < EMA, so the EMA exit fires; no short is opened.
    D = mk([100.0, 101.5, 102.0, 99.5, 99.5, 99.5], ema=101.0)
    tr = V.simulate(D, var("filter_entry"))
    assert [(t["side"], t["k_entry"], t["exit_kind"], t["j_exit"]) for t in tr] == [(1, 2, "ema", D.a1[4])]
    # EMA below VWAP: the long cue fails the filter -> nothing
    assert V.simulate(mk([100.0, 101.5, 102.0, 102.0], ema=99.0), var("filter_entry")) == []
    # same data in mode none: the short cue flips
    tr = V.simulate(D, var("none"))
    assert [(t["side"], t["exit_kind"]) for t in tr] == [(1, "flip"), (-1, "end")]


def test_ema_exit_in_none_mode():
    # long cue at k=1 (EMA 102 above price); close 101 < EMA 102 at k=2 -> exit at k=3 open
    D = mk([100.0, 101.0, 101.0, 101.0], ema=102.0)
    tr = V.simulate(D, var("none"))
    assert [(t["side"], t["k_entry"], t["exit_kind"], t["j_exit"]) for t in tr] == [(1, 2, "ema", D.a1[3])]


# --- arm_exit ---------------------------------------------------------------------------------------------------

def test_arm_exit_arms_when_ema_crosses_vwap():
    # long cue at k=1 with EMA 99 < VWAP 100 (not armed). k=2: EMA 100.5 crosses above VWAP, close 101 above it
    # (arms, no exit). k=3: close 100.25 < EMA 100.5 -> exit at k=4 open.
    ema = [99.0, 99.0, 100.5, 100.5, 100.5, 100.5]
    D = mk([100.0, 101.0, 101.0, 100.25, 100.25, 100.25], ema=ema)
    tr = V.simulate(D, var("arm_exit"))
    assert [(t["side"], t["exit_kind"], t["j_exit"]) for t in tr] == [(1, "ema", D.a1[4])]


def test_arm_exit_armed_at_entry_when_ema_already_on_side():
    D = mk([100.0, 101.0, 101.0, 101.0], ema=102.0)   # EMA above VWAP at the cue: armed immediately
    tr = V.simulate(D, var("arm_exit"))
    assert [(t["exit_kind"], t["j_exit"]) for t in tr] == [("ema", D.a1[3])]


def test_arm_exit_equals_none_under_flips():
    """With every cue flipping, a close beyond the EMA while the EMA is on the wrong side of VWAP is already a
    VWAP cross, so arm_exit trades exactly like none (spec redundancy, recorded in LOG.md)."""
    D = V.build(rw_df(DAYS), "ES", DAYS[0], DAYS[-1])
    for e in V.EMAS:
        for s in V.STOPS:
            for w in V.WARMUPS:
                a = V.simulate(D, var("none", e, s, w))
                b = V.simulate(D, var("arm_exit", e, s, w))
                assert [(t["j_entry"], t["j_exit"], t["exit_kind"]) for t in a] == \
                       [(t["j_entry"], t["j_exit"], t["exit_kind"]) for t in b]


# --- stops ------------------------------------------------------------------------------------------------------

def test_atr_stop_first_then_fresh_cue():
    # long cue at k=2 (99 -> 101), fill 101 at k=3 open, ATR 1 -> stop 100. In bar k=3 the first 1m bar trades
    # 99.75 (stop hit) and the bar closes 99 (a short cue): the stop fills first at 100, then the close's cue
    # opens a short at the k=4 open.
    D = mk([99.0, 99.0, 101.0, 99.0, 99.0, 99.0], one_m={9: (101.0, 101.0, 99.75, 100.5)})
    tr = V.simulate(D, var("none", stop="atr1"))
    t0 = tr[0]
    assert (t0["side"], t0["stop_init"], t0["exit_kind"], t0["exit_ref"], t0["j_exit"]) == (1, 100.0, "stop", 100.0, 9)
    assert tr[1]["side"] == -1 and tr[1]["j_entry"] == D.a1[4]


def test_stop_gap_fills_at_open_and_atr_snaps_to_grid():
    D = mk([99.0, 99.0, 101.0, 99.0, 99.0], atr=0.9, one_m={9: (101.0, 101.0, 99.5, 99.5), 10: (99.5, 99.5, 99.5, 99.5),
                                                          11: (99.0, 99.0, 99.0, 99.0)})
    # fill at k=3 open = 101.0, stop = snap down(100.1) = 100.0; 1m bar 9 opens 101 then trades 99.5 -> stop at 100
    t = V.simulate(D, var("none", stop="atr1"))[0]
    assert t["stop_init"] == 100.0 and t["exit_ref"] == 100.0
    # fill 101 at 1m bar 9 (stop 100); 1m bar 10 gaps open at 99.5, below the stop -> fills at that open
    D = mk([99.0, 99.0, 101.0, 99.0, 99.0], one_m={9: (101.0, 101.0, 101.0, 101.0), 10: (99.5, 99.5, 99.0, 99.0)})
    t = V.simulate(D, var("none", stop="atr1"))[0]
    assert (t["exit_kind"], t["exit_ref"], t["j_exit"]) == ("stop", 99.5, 10)


def test_entry_bar_stop_one_tick_beyond_cue_candle():
    D = mk([99.0, 99.0, 101.0, 101.0, 101.0])
    t = V.simulate(D, var("none", stop="entry_bar"))[0]
    assert t["stop_init"] == D.l3[2] - T == 98.75 and t["risk_pts"] == pytest.approx(101.0 - 98.75)
    D = mk([101.0, 101.0, 99.0, 99.0, 99.0])
    t = V.simulate(D, var("none", stop="entry_bar"))[0]
    assert t["side"] == -1 and t["stop_init"] == D.h3[2] + T == 101.25


def test_entry_gapped_through_its_stop_is_skipped():
    # long cue at k=2, entry_bar stop 98.75; the k=3 open gaps to 98.0 (below the stop): no trade
    D = mk([99.0, 99.0, 101.0, 98.0, 98.0], one_m={9: (98.0, 98.0, 98.0, 98.0)})
    tr = V.simulate(D, var("none", stop="entry_bar"))
    # only the k=3 close's short cue trades (fills at k=4); the gapped long never opens
    assert [(t["side"], t["k_entry"]) for t in tr] == [(-1, 4)] and tr[0]["risk_pts"] > 0


def test_stop_beats_flip_on_the_same_bar():
    # with entry_bar stop 98.75: bar k=3 hits 98.5 intrabar and closes 99 (short cue): exit is the stop
    D = mk([99.0, 99.0, 101.0, 99.0, 99.0], one_m={9: (101.0, 101.0, 98.5, 99.0)})
    tr = V.simulate(D, var("none", stop="entry_bar"))
    assert tr[0]["exit_kind"] == "stop" and tr[0]["exit_ref"] == 98.75


# --- session clock ----------------------------------------------------------------------------------------------

def test_no_entry_at_or_after_1630():
    c = [99.0, 99.0, 101.0] + [101.0] * 10
    # cue bar starts 16:27 (sm 1347): next bar opens 16:30 -> no entry
    assert V.simulate(mk(c, start_sm=1341), var()) == []
    # one bar earlier: next bar opens 16:27 -> entry, then flat at 16:55
    tr = V.simulate(mk(c, start_sm=1338), var())
    assert len(tr) == 1 and tr[0]["entry_sm"] == 1347
    assert tr[0]["exit_kind"] == "flat" and tr[0]["exit_mod"] == 16 * 60 + 55


def test_flip_after_cutoff_only_exits():
    c = [99.0, 99.0, 101.0, 101.0, 99.0] + [99.0] * 10
    tr = V.simulate(mk(c, start_sm=1338), var())      # long fills 16:27; short cue closes 16:33 -> exit only
    assert [(t["side"], t["exit_kind"]) for t in tr] == [(1, "flip")]


def test_warmup30_blocks_fills_before_1830():
    c = [99.0, 99.0, 101.0] + [101.0] * 6
    assert V.simulate(mk(c, start_sm=0), var(warm=30)) == []     # fill at 18:09
    assert len(V.simulate(mk(c, start_sm=0), var(warm=0))) == 1
    assert V.simulate(mk(c, start_sm=21), var(warm=30))[0]["entry_sm"] == 30


def test_flat_when_1655_bar_is_missing():
    # long fills at 16:09 (sm 1329); the next bar in the data starts at 16:57 (bars 16:12..16:54 missing):
    # the position is closed flat at that bar's open, before any order there
    D = mk([99.0, 99.0, 101.0, 101.0, 101.5])
    D.sm3 = np.array([1320, 1323, 1326, 1329, 1377])
    D.sm1 = np.repeat(D.sm3, 3) + np.tile(np.arange(3), 5)
    D.mod1 = (D.sm1 + V.SESSION_START_MOD) % 1440
    D.sessions[0]["j_flat"] = 12
    D._lists.clear()
    tr = V.simulate(D, var())
    assert [(t["entry_sm"], t["exit_kind"], t["j_exit"], t["exit_ref"]) for t in tr] == [(1329, "flat", 12, 101.0)]


# --- twins ------------------------------------------------------------------------------------------------------

def test_same_side_twin_reproduces_the_real_trade():
    D = V.build(rw_df(DAYS), "ES", DAYS[0], DAYS[-1])
    n = 0
    for stop in V.STOPS:
        for t in V.simulate(D, var("none", 13, stop, 0)):
            assert V.twin_exit(D, t, t["side"]) == (t["exit_kind"], t["exit_ref"], t["j_exit"])
            k, px, j = V.twin_exit(D, t, -t["side"])
            assert j >= t["j_entry"]
            n += 1
    assert n > 100


def test_opposite_twin_uses_mirrored_stop():
    # long with entry_bar stop 98.75 (risk 2.25): the short twin's stop is 103.25; price rises to 104 -> stopped
    D = mk([99.0, 99.0, 101.0, 102.0, 104.0, 104.0], ema=95.0)
    t = V.simulate(D, var("none", stop="entry_bar"))[0]
    k, px, j = V.twin_exit(D, t, -1)
    assert (k, px) == ("stop", 103.25)


def test_twin_p_normal_matches_mc():
    rng = np.random.default_rng(3)
    n = 4000
    rl = rng.normal(0.2, 3, n)
    rs = -rl + rng.normal(-2, 0.5, n)
    sides = np.where(rng.random(n) < 0.6, 1, -1)
    real = np.where(sides > 0, rl, rs) + 0.05
    pn = V.twin_p_normal(real, rl, rs, sides)["p"]
    pm = V.twin_p_mc(real, rl, rs, sides, n_mc=4000)
    assert abs(pn - pm) < 0.03


def test_stats_and_gate_smoke():
    D = V.build(rw_df(DAYS), "ES", DAYS[0], DAYS[-1])
    years = sorted({s["day"].year for s in D.sessions})
    res = {}
    for sym in ("ES", "NQ"):
        D.sym = sym
        vs = {}
        for v in V.GRID:
            st = V.stats(D, v, V.simulate(D, v), years)
            st.pop("_arrays", None)
            vs[v["id"]] = st
        res[sym] = {"variants": vs}
    g = V.gate(res)
    assert len(g) == 72
    st = res["ES"]["variants"][V.GRID[0]["id"]]
    assert st["n"] > 0 and set(st["yearly"]) == {2015} and 0 <= st["win_rate"] <= 1


def _cell(net=1.0, p=0.001, years_pos=6, top5=0.2):
    return {"net_per_trade": net, "p": p, "years_pos": years_pos, "n_years": 8, "top5_share": top5}


def test_gate_rules():
    v = V.variant_id("filter_entry", 13, "atr1", 0)
    base = {s: {"variants": {x["id"]: _cell() for x in V.GRID}} for s in ("ES", "NQ")}
    assert V.gate(base)[v] == []
    for sym, field, val, msg in [("ES", "net_per_trade", -0.1, "net"), ("NQ", "p", 0.005, "p "),
                                 ("NQ", "years_pos", 4, "years"), ("ES", "top5_share", 0.5, "top-5"),
                                 ("ES", "top5_share", None, "top-5")]:
        res = json.loads(json.dumps(base))
        res[sym]["variants"][v][field] = val
        assert any(msg in f for f in V.gate(res)[v]), (field, val)
    res = json.loads(json.dumps(base))
    res["NQ"]["variants"][V.variant_id("filter_entry", 21, "atr1", 0)]["net_per_trade"] = 0.0
    assert any("neighbour" in f for f in V.gate(res)[v])
    # ema9's only neighbour is ema13; ema34's only neighbour is ema21
    assert V.neighbours({"mode": "none", "ema": 9, "stop": "atr1", "warm": 0}) == ["none|ema13|atr1|w0"]
    assert V.neighbours({"mode": "none", "ema": 34, "stop": "atr1", "warm": 30}) == ["none|ema21|atr1|w30"]


# --- v2 versions ------------------------------------------------------------------------------------------------

def v2(entry="price", flip=True, session="globex", ema=9, stop="none"):
    return next(v for v in V.GRID2 if v["id"] == V.v2_id(entry, flip, session, ema, stop))


def test_v2_grid_and_ids():
    assert len(V.GRID2) == 64 and len({v["id"] for v in V.GRID2}) == 64
    assert V.neighbours(v2("ema", False, "rth", 13, "atr1")) == ["v2|ema|noflip|rth|ema9|atr1",
                                                                  "v2|ema|noflip|rth|ema21|atr1"]


def test_v2_price_flip_globex_reproduces_v1():
    D = V.build(rw_df(DAYS), "ES", DAYS[0], DAYS[-1])
    key = lambda tr: [(t["side"], t["j_entry"], t["j_exit"], t["exit_kind"], t["exit_ref"]) for t in tr]
    for e in V.EMAS:
        assert key(V.simulate(D, v2(ema=e))) == key(V.simulate(D, var("none", e, "vwap_close", 0)))
        assert key(V.simulate(D, v2(ema=e, stop="atr1"))) == key(V.simulate(D, var("none", e, "atr1", 0)))


def test_ema_cross_entry_needs_ema_cross_and_close_on_same_side():
    # VWAP 100. EMA 99.5 -> 100.5 at k=2 (crosses up) with close 101 > VWAP: long fills at k=3 open
    ema = [99.5, 99.5, 100.5, 100.5, 100.5, 100.5]
    D = mk([101.0] * 6, ema=ema)
    tr = V.simulate(D, v2("ema"))
    assert [(t["side"], t["k_cue"], t["k_entry"]) for t in tr] == [(1, 2, 3)]
    # same EMA cross but the close is below VWAP: no entry
    assert V.simulate(mk([101.0, 101.0, 99.5, 99.5, 99.5, 99.5], ema=ema), v2("ema")) == []
    # price crosses VWAP but the EMA does not: the price entry trades, the EMA entry does not
    D = mk([99.0, 99.0, 101.0, 101.0, 101.0], ema=99.0)
    assert V.simulate(D, v2("ema")) == [] and len(V.simulate(D, v2("price"))) == 1


def test_noflip_opposite_signal_only_exits():
    D = mk([99.0, 99.0, 101.0, 101.0, 99.0, 99.0, 101.0, 101.0], ema=100.0)
    tr = V.simulate(D, v2(flip=False))
    # long at k=3; short cue at k=4 exits at k=5 (no short); fresh long cue at k=6 -> long at k=7
    assert [(t["side"], t["k_entry"], t["exit_kind"]) for t in tr] == [(1, 3, "signal"), (1, 7, "end")]
    tr = V.simulate(D, v2(flip=True))
    assert [(t["side"], t["exit_kind"]) for t in tr] == [(1, "flip"), (-1, "flip"), (1, "end")]


def test_rth_vwap_anchored_at_0930_and_session_clock():
    df = session_df(DAYS[2], lambda sm: np.where(sm < 930, 100.0, 200.0))
    D = V.build(df, "ES", DAYS[2], DAYS[2])
    k930 = int(np.flatnonzero(D.sm3 == 930)[0])
    assert np.isnan(D.vwr[k930 - 1]) and D.vwr[k930] == pytest.approx(200.0)     # no overnight volume in it
    assert D.vw[k930] < 200.0                                                     # Globex VWAP still includes it
    s = D.sessions[0]
    assert D.sm1[s["j_flat_rth"]] == V.SM_RTH_FLAT and s["rth_noentry_sm"] == V.SM_RTH_NOENTRY
    # RTH trade: flat at 15:55; a cue whose fill would be at 15:30 is not taken
    c = [99.0, 99.0, 101.0] + [101.0] * 10
    tr = V.simulate(mk(c, start_sm=1278, vwr=100.0), v2(session="rth"))     # fill 15:27
    assert [(t["entry_sm"], t["exit_mod"], t["exit_kind"]) for t in tr] == [(1287, 15 * 60 + 55, "flat")]
    assert V.simulate(mk(c, start_sm=1281, vwr=100.0), v2(session="rth")) == []     # fill 15:30
    # a cue whose fill would be before 09:30 (here 09:09) is dropped, not carried to the open
    assert V.simulate(mk(c, start_sm=900, vwr=100.0), v2(session="rth")) == []
    assert V.simulate(mk(c, start_sm=921, vwr=100.0), v2(session="rth"))[0]["entry_sm"] == V.SM_RTH_OPEN


def test_rth_uses_rth_vwap_not_globex():
    # Globex VWAP 100 (cross at k=2); RTH VWAP 105 (no cross): RTH variant does not trade
    c = [99.0, 99.0, 101.0, 101.0, 101.0]
    assert V.simulate(mk(c, start_sm=1000, vwr=105.0), v2(session="rth")) == []
    assert len(V.simulate(mk(c, start_sm=1000, vwr=105.0), v2(session="globex"))) == 1


def test_twin_uses_the_variants_flat():
    D = V.build(rw_df(DAYS), "ES", DAYS[0], DAYS[-1])
    n = 0
    for t in V.simulate(D, v2(session="rth", stop="atr1")):
        assert V.twin_exit(D, t, t["side"]) == (t["exit_kind"], t["exit_ref"], t["j_exit"])
        assert t["exit_mod"] <= 15 * 60 + 55
        n += 1
    assert n > 20


def test_prereg_user_freezes_everything_once(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "PREREG", tmp_path / "pr.json")
    V.draft_prereg_user("user asked in chat 2026-11-03")
    pr = json.loads((tmp_path / "pr.json").read_text())
    assert pr["n_variants"] == 136 and pr["alpha_per_variant"] == pytest.approx(0.05 / 136)
    assert pr["windows"] == [["2019-01-02", "2021-12-31"], ["2022-01-03", "2026-08-14"]]
    assert pr["spec2_sha256"] == V.sha(V.SPEC2)
    with pytest.raises(SystemExit, match="one-shot"):
        V.draft_prereg_user("again")
