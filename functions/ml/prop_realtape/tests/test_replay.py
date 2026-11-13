"""Step-3 tests for the real-tape prop loop (run: ../../.venv/bin/python -m pytest prop_realtape/tests -q)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent))
import lucid_structure as L  # noqa: E402
import realdays as R  # noqa: E402
import replay as RP  # noqa: E402
from flybrain.prop import simulate_account  # noqa: E402

B = RP.Bracket(st=4, n=1, tick_usd=0.5, comm=0.5, flat_mod=16 * 60 + 10)
CIN = 0.5 + L.ENTRY_SLIP_TICKS * 0.5          # entry commission + entry slip, $ per contract
ET0 = 9 * 60 + 35


def bars(rows, et=None):
    a = np.array(rows, dtype=np.int32)
    e = np.arange(ET0, ET0 + len(a), dtype=np.int16) if et is None else np.array(et, np.int16)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], e


def plan(firm, name):
    return next(p for p in L.all_plans(firm) if L.plan_name(p) == name)


# ---- 1. toy tape: hand-computed fills -------------------------------------------------------------------------
def test_same_bar_stop_first_with_slip():
    o, h, l, c, e = bars([[0, 2, -2, 1], [1, 5, -4, 0], [0, 9, 0, 9]])
    code, k, fill, _ = RP.trade(o, h, l, c, e, B, slip=1.0)
    assert (code, k, fill) == (RP.EXIT["stop"], 1, -5.0)                # stop -4, then 1 tick slip
    eb = RP.equity_bars(o, h, l, c, code, k, fill, False, B)
    assert eb[-1, 3] == pytest.approx(-5 * 0.5 - CIN - 0.5)            # -3.70


def test_target_needs_tick_through():
    o, h, l, c, e = bars([[0, 3, -1, 2], [2, 4, 1, 3], [3, 5, 2, 5]])
    code, k, fill, _ = RP.trade(o, h, l, c, e, B, slip=1.0)
    assert (code, k, fill) == (RP.EXIT["target"], 2, 4.0)               # touch of +4 on bar 1 does not fill
    eb = RP.equity_bars(o, h, l, c, code, k, fill, False, B)
    assert eb[-1, 3] == pytest.approx(4 * 0.5 - CIN - 0.5)             # +0.80
    # short side of the same tape: mirror, stop at +4 for the short -> bar 2 high 5 is a stop
    code, k, fill, _ = RP.trade(-o, -l, -h, -c, e, B, slip=2.0)
    assert (code, k, fill) == (RP.EXIT["stop"], 1, -6.0)                # bar 1 high 4 = -4 for the short


def test_gap_through_stop_fills_at_open():
    o, h, l, c, e = bars([[0, 1, -1, 0], [-7, -6, -8, -7]])
    code, k, fill, _ = RP.trade(o, h, l, c, e, B, slip=1.0)
    assert (code, k, fill) == (RP.EXIT["stop"], 1, -8.0)


def test_flat_by_exits_at_bar_open():
    et = [ET0, ET0 + 1, 16 * 60 + 9, 16 * 60 + 10, 16 * 60 + 11]
    o, h, l, c, e = bars([[0, 1, -1, 1], [1, 2, 0, 2], [2, 3, 1, 2], [2, 9, -9, 0], [0, 0, 0, 0]], et)
    code, k, fill, at_close = RP.trade(o, h, l, c, e, B, slip=1.0)
    assert (code, k, fill, at_close) == (RP.EXIT["flat"], 3, 2 - L.ENTRY_SLIP_TICKS, False)   # bar 3 never trades
    eb = RP.equity_bars(o, h, l, c, code, k, fill, at_close, B)
    assert eb[-1, 3] == pytest.approx(1.6 * 0.5 - CIN - 0.5)
    assert eb[:, 2].min() == pytest.approx(-1 * 0.5 - CIN)               # bar 3's -9 is never seen


def test_half_day_flat_and_tape_end():
    et = [12 * 60 + 30, 13 * 60 + 9, 13 * 60 + 10]
    o, h, l, c, e = bars([[0, 1, -1, 1], [1, 2, 0, 2], [3, 3, 3, 3]], et)
    assert RP.trade(o, h, l, c, e, B, 1.0, half=True)[:2] == (RP.EXIT["flat"], 2)
    code, k, fill, at_close = RP.trade(o[:2], h[:2], l[:2], c[:2], e[:2], B, 1.0)   # tape ends before 16:10
    assert (code, k, fill, at_close) == (RP.EXIT["flat"], 1, 2 - L.ENTRY_SLIP_TICKS, True)


# ---- 2. synthetic days through the replay reproduce lucid_structure.score to the cent ---------------------------
@pytest.mark.parametrize("firm,name,risk,st", [("topstep", "Cons no-fee 50K noDLL", 1550, 310),
                                               ("lucid", "LucidFlex 50K", 1050, 300),
                                               ("topstep", "Cons no-fee 150K", 3040, 304)])
def test_synthetic_matches_score(firm, name, risk, st):
    p = plan(firm, name)
    fee = L.fee_of(p)
    ref = L.score(p, fee, risk, st, 1.0, paths=1500, n_days=40000, seed=3, rseed=4)
    d = L.make_days(40000, risk, st, 1.0, seed=3, comm=p.get("commissionPerSide", L.COMM_SIDE))
    table = L.day_table(d)
    got = RP.summarize(RP.run(table, RP.iid_seqs(table["n"], 1500, seed=4), p), p, fee)
    assert round(got["ev"], 2) == round(ref["ev"], 2)
    assert got["pass_rate"] == ref["pass_rate"] and got["p_paid"] == ref["p_paid"]
    # the same days rebuilt per day and compressed give the same accounts
    lo, hi, op, cl = (np.array(table[k]) for k in ("lo", "hi", "open", "close"))
    per_day = [RP.compress(np.stack([op[s:e + 1], hi[s:e + 1], lo[s:e + 1], cl[s:e + 1]], 1), "merge")
               for s, e in zip(table["start"], table["end"])]
    t2 = RP.table_from_bars(per_day)
    got2 = RP.summarize(RP.run(t2, RP.iid_seqs(t2["n"], 1500, seed=4), p), p, fee)
    assert round(got2["ev"], 2) == round(ref["ev"], 2)


# ---- compression is exact for the account engine ---------------------------------------------------------------
@pytest.mark.parametrize("intraday", [False, True])
@pytest.mark.parametrize("vol", [60, 120])
@pytest.mark.parametrize("firm,name", [("topstep", "Cons no-fee 50K noDLL"), ("topstep", "Cons no-fee 150K"),
                                       ("lucid", "LucidFlex 50K"), ("lucid", "LucidDirect 150K"),
                                       ("alpha", "Standard 50K")])
def test_compression_exact(firm, name, vol, intraday):
    p = dict(plan(firm, name))
    if intraday:                                           # Apex-style intraday trailing drawdown in both stages
        p.update(evalDrawdown="intraday", fundedDrawdown="intraday")
    rng = np.random.default_rng(11)
    raw, comp = [], []
    for _ in range(300):                                   # 1m random-walk trades, 1..400 bars, $ equity
        m = int(rng.integers(1, 400))
        step = rng.normal(0, vol, m).cumsum()
        o = np.r_[0, step[:-1]]
        hi = np.maximum(o, step) + rng.exponential(30, m)
        lo = np.minimum(o, step) - rng.exponential(30, m)
        b = np.stack([o, hi, lo, step], 1)
        raw.append(b)
        comp.append(RP.compress(b, RP.compress_mode(p)))
    assert sum(len(c) for c in comp) < sum(len(r) for r in raw) / 3
    t_raw, t_cmp = RP.table_from_bars(raw), RP.table_from_bars(comp)
    hits = 0
    for s in range(300):
        seq = np.random.default_rng(100 + s).integers(0, 300, 250)
        nd = lambda k, q=seq: int(q[k]) if k < 250 else -1
        a, b = simulate_account(t_raw, nd, p), simulate_account(t_cmp, nd, p)
        assert (a["outcome"], a["payouts"], a["daysUsed"], a["dllHits"]) == (b["outcome"], b["payouts"], b["daysUsed"], b["dllHits"])
        hits += a["dllHits"]
    if p["dailyLossLimit"] and vol == 120:
        assert hits > 0                                    # the DLL path is exercised


# ---- 3. no look-ahead in the ATR / VIX scaling ------------------------------------------------------------------
def _sessions(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n).date
    rngs = rng.uniform(10, 40, n)
    close = 2000 + rng.normal(0, 10, n).cumsum()
    return pd.DataFrame({"range": rngs, "close": close, "weekend": False}, index=pd.Index(idx))


def test_atr_scale_uses_prior_close_only():
    s = _sessions()
    base = R.atr_scale(s)
    cut = 300
    s2 = s.copy()
    s2.iloc[cut:, s2.columns.get_loc("range")] *= 7          # change day `cut` onward
    s2.iloc[cut:, s2.columns.get_loc("close")] += 999
    alt = R.atr_scale(s2)
    pd.testing.assert_frame_equal(base.iloc[:cut + 1], alt.iloc[:cut + 1])   # day `cut` still sees only cut-1
    assert not np.allclose(base["ticks"].iloc[cut + 1], alt["ticks"].iloc[cut + 1])


def test_vix_scale_uses_prior_cboe_date_only(tmp_path, monkeypatch):
    v = pd.read_csv(R.VIX_CSV)
    d = pd.to_datetime(v["DATE"], format="%m/%d/%Y").dt.date
    D = date(2020, 3, 16)
    v2 = v.copy()
    v2.loc[d >= D, "CLOSE"] = 99.0                           # tamper with D and after
    f = tmp_path / "vix.csv"
    v2.to_csv(f, index=False)
    dates = [x for x in d if date(2020, 1, 2) <= x <= D]
    base, _ = R.vix_scale(dates)
    monkeypatch.setattr(R, "VIX_CSV", f)
    alt, _ = R.vix_scale(dates)
    pd.testing.assert_frame_equal(base, alt)                 # D's scale uses D-1's close, untouched
    alt2, _ = R.vix_scale(dates + [date(2020, 3, 17)])
    assert alt2.loc[date(2020, 3, 17), "level"] == 99.0


def test_built_files_consistent():
    p = R.load_day_paths("NQ", "0935", "atr")
    D = p["days"]
    assert (p["o"][D["start"].to_numpy()] == 0).all()
    assert (p["et_min"][D["start"].to_numpy()] == ET0).all()
    assert D["date"].is_monotonic_increasing
    f = R.load_day_paths("NQ", "0935", "fixed")
    assert (f["days"]["scale"] == 1.0).all() and len(f["days"]) == len(D)


# ---- review follow-ups (finding 4) ------------------------------------------------------------------------------
def _toy_paths(day_moves, product_dates=None):
    """Each day: a clean 1-tick-per-bar walk to +/- `m` ticks from 09:35 (no gaps), then flat to 16:59."""
    rows, o, h, l, c, e, start = [], [], [], [], [], [], 0
    dates = product_dates or [date(2024, 1, 2 + i) for i in range(len(day_moves))]
    for d, m in zip(dates, day_moves):
        step = 1 if m > 0 else -1
        path = list(range(0, m + step, step)) + [m] * 5
        n = len(path)
        for k in range(n):
            prev = path[k - 1] if k else 0
            o.append(prev); c.append(path[k]); h.append(max(prev, path[k])); l.append(min(prev, path[k]))
            e.append(ET0 + k)
        rows.append(dict(date=d, era="2022-26", half=False, start=start, n_bars=n, scale=1.0, vol_ticks=np.nan))
        start += n
    arr = lambda x, t: np.array(x, dtype=t)
    return dict(days=pd.DataFrame(rows), o=arr(o, np.int32), h=arr(h, np.int32), l=arr(l, np.int32),
                c=arr(c, np.int32), et_min=arr(e, np.int16))


@pytest.mark.parametrize("product", ["NQ", "ES"])
def test_day_results_matches_make_days_formula(product):
    risk, n = 1550.0, 10
    st = RP.base_bracket(risk, n, product)
    assert abs(st * n * RP.TICK_USD[product] - risk) <= n * RP.TICK_USD[product] / 2   # ES no longer sized in MNQ ticks
    p = _toy_paths([st + 1, -(st + 3), st + 5])            # long: win, lose, win (target needs st+1)
    dr = RP.day_results(p, risk, n, product, 0.5, 970, mode="eod")
    u = n * RP.TICK_USD[product]
    fees = 2 * 0.5 * n + L.ENTRY_SLIP_TICKS * RP.TICK_USD[product] * n           # make_days' fee line
    win, lose = st * u - fees, lambda s: (-st - s) * u - fees
    np.testing.assert_allclose(dr["pnl"][:, 0], [win, lose(dr["slip"][1, 0]), win])
    np.testing.assert_allclose(dr["pnl"][:, 1], [lose(dr["slip"][0, 1]), win, lose(dr["slip"][2, 1])])
    assert (dr["code"][:, 0] == [1, 0, 1]).all()
    assert (dr["risk"] == st * u).all()


def test_abs_rule_caps_contracts_and_keeps_stop():
    p = _toy_paths([10])
    p["days"]["vol_ticks"] = 100.0
    dr = RP.day_results(p, 1550.0, 10, "NQ", 0.5, 970, rule="abs", k_abs=0.24, cap=40, mode="eod")
    assert dr["capped"][0] and dr["n"][0] == 40 and dr["st"][0] == 24           # wants 129 contracts
    assert dr["risk"][0] == pytest.approx(24 * 40 * 0.5)
    dr = RP.day_results(p, 1550.0, 10, "NQ", 0.5, 970, rule="abs", k_abs=6.2, cap=40, mode="eod")
    assert not dr["capped"][0] and dr["n"][0] == 5 and dr["st"][0] == 620


@pytest.mark.parametrize("mode", ["eod", "records", "merge"])
def test_compression_gap_open_exact_balance(mode):
    from flybrain.prop import run_stage
    p = dict(plan("lucid", "LucidFlex 50K"))
    if mode != "eod":
        p.update(evalDrawdown="intraday", fundedDrawdown="intraday")
    if mode == "merge":
        p["dailyLossLimit"] = 0
    # day: up to +300, drift down to -900, then a 1m bar opens at -1900 (gap) and trades -2100
    raw = np.array([[0, 300, -50, 250], [250, 260, -900, -880], [-880, -870, -950, -900],
                    [-1900, -1850, -2100, -2000], [-2000, -1500, -2050, -1600]], float)
    cmp_ = RP.compress(raw, mode)
    got = []
    assert any(r[0] == -1900 for r in cmp_)                 # the gap bar keeps its own open
    for tbl in (RP.table_from_bars([raw]), RP.table_from_bars([cmp_])):
        r = run_stage(tbl, lambda k: 0 if k == 0 else -1, 0, p, "eval")
        got.append((r["status"], r["balance"], r["dllHits"]))
    assert got[0] == got[1]
    assert got[0][0] == "breached" or got[0][2] == 1        # the gap bar decides the day


def test_sessions_labelling_roll_and_halt():
    idx = pd.date_range("2024-03-11 21:00", periods=3000, freq="1min", tz="UTC")   # Mon 17:00 ET onward
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "instrument_id": 1}, index=idx)
    df.loc[idx >= pd.Timestamp("2024-03-12 12:00", tz="UTC"), "instrument_id"] = 2   # contract change on 03-12
    s, mod = R.sessions(df)
    et = idx.tz_convert(R.TZ)
    assert mod[0] == 17 * 60 and mod[60] == 18 * 60
    assert date(2024, 3, 12) in s.index and date(2024, 3, 13) in s.index
    assert s.loc[date(2024, 3, 12), "i0"] == 60             # 18:00 ET Monday belongs to Tuesday's session
    assert bool(s.loc[date(2024, 3, 12), "roll"])           # two contracts inside
    assert bool(s.loc[date(2024, 3, 13), "roll"]) is False  # starts on the new contract, same as prior last
    assert et[s.loc[date(2024, 3, 12), "i1"]].hour == 17 and et[s.loc[date(2024, 3, 12), "i1"]].minute == 59


def test_coins_paired_by_date_and_balanced():
    a = R.load_day_paths("NQ", "0935", "fixed")["days"]["date"].tolist()
    b = R.load_day_paths("ES", "1300", "fixed")["days"]["date"].tolist()
    ca, cb = RP.coin_sides(a, 5), RP.coin_sides(b, 5)
    ma, mb = dict(zip(a, ca)), dict(zip(b, cb))
    common = set(a) & set(b)
    assert len(common) > 3500 and all(ma[d] == mb[d] for d in common)
    assert abs(ca.mean() - 0.5) < 0.03 and not np.array_equal(ca, RP.coin_sides(a, 6))
    sa, sb = RP.date_slips(a, 7), RP.date_slips(b, 7)
    assert all(sa[i, 1] == sb[b.index(d), 1] for i, d in enumerate(a[:200]) if d in mb)
    assert set(np.unique(sa)) <= set(L.SLIP_T.tolist())


def test_sequence_generators():
    idx = np.arange(100)
    sides = np.zeros(100, int)
    seqs = list(RP.block_seqs(idx, sides, 4000, block=20, horizon=250, seed=0))
    assert all(len(q) == 250 for q in seqs)
    seen = np.unique(np.concatenate(seqs) // 2)
    assert seen.min() == 0 and seen.max() == 99
    h = list(RP.hist_seqs(np.arange(400), np.ones(400, int), horizon=250))
    assert len(h) == 400 and len(h[0]) == 250 and len(h[-1]) == 1 and (h[0] % 2 == 1).all()
