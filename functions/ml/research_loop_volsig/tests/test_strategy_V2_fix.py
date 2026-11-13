"""V2_skew_shock_fix rules on synthetic bars and one engine run (not frozen); same cases as V2 plus history independence."""
import json
import math
import os
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("VOLSIG_PRODUCT", "NQ")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from research_loop_volsig.eval import config as C, data, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "V2_skew_shock_fix.py"
ORIG = C.LOOP_DIR / "strategies" / "V2_skew_shock.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "V2_skew_shock_fix.json").read_text())
PARAMS = {**SPEC["grid"]["base"], "k": 2.5}
BETA = -0.4


def day_bars(d, n=78, half=False, exdiv=False, news=(), shock=None, price_path=None, noise=0, base=5000.0):
    """Price follows price_path(k) (default flat-ish wiggle); skew25 = 0.05 + BETA * ln(c/base) + noise term,
    so a pure price move gives a skew move fully explained by the fit. shock=(slot, size) adds to skew from slot on."""
    out = []
    for k in range(42 if half else n):
        px = price_path(k) if price_path else base * (1 + 0.0005 * math.sin(k + noise))
        sk = 0.05 + BETA * math.log(px / base) + 0.0004 * math.sin(3.7 * k + 1.3 * noise)
        if shock and k >= shock[0]:
            sk += shock[1]
        out.append({"day": d.isoformat(), "slot": k, "mod": 570 + 5 * k, "o": px, "h": px + 10, "l": px - 10, "c": px,
                    "half_day": half, "news": list(news), "opt": {"skew25": sk, "exdiv": exdiv}})
    return out


def history(n=20, start=date(2017, 1, 2)):
    days, d = [], start
    for i in range(n):
        days.append(day_bars(d, noise=i))
        d += timedelta(days=1)
    return days, d


def run_days(days, params=PARAMS):
    st = engine.load_strategy_class(PATH)(params)
    acts = []
    for bars in days:
        for b in bars:
            a = st.on_bar(b, None)
            if a is not None:
                acts.append((b["day"], b["slot"], a))
    return st, acts


def test_sandbox_and_grid():
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["grid"]["axes"] == {"k": [2.5]} and SPEC["dev_split"] == "dev_opt"
    orig = json.loads((C.LOOP_DIR / "prereg" / "V2_skew_shock.json").read_text())
    assert {k: v for k, v in SPEC["rules"].items() if k != "history_independence"} == orig["rules"]
    assert SPEC["grid"]["base"] == orig["grid"]["base"] and SPEC["family"] == orig["family"]


def test_beta_learned_and_shock_side_is_fade():
    h, d = history()
    st, acts = run_days(h + [day_bars(d, shock=(20, +0.02), noise=99)])
    assert st.cur["beta"] == pytest.approx(BETA, abs=0.05)
    assert len(acts) == 1 and acts[0][1] == 20 and acts[0][2]["side"] == 1        # puts bid -> long (fade)
    _, acts = run_days(h + [day_bars(d, shock=(20, -0.02), noise=99)])
    assert acts[0][2]["side"] == -1


def test_pure_price_move_explained_by_beta_does_not_trigger():
    h, d = history()
    crash = lambda k: 5000.0 * math.exp(-0.002 * max(0, k - 15))                  # -1%/30 min for hours
    _, acts = run_days(h + [day_bars(d, price_path=crash, noise=99)])
    assert acts == []


def test_needs_20_sessions_and_one_trade_per_session():
    h, d = history(19)
    _, acts = run_days(h + [day_bars(d, shock=(20, 0.02))])
    assert acts == []
    h, d = history(20)
    bars = day_bars(d, shock=(20, 0.02))
    for b in bars[40:]:
        b["opt"]["skew25"] += 0.05                                                  # a second, later shock
    _, acts = run_days(h + [bars])
    assert len(acts) == 1


def test_news_window_skips_trigger_but_scan_continues():
    h, d = history()
    bars = day_bars(d, shock=(20, 0.02), news=[600])     # trigger bar (slot 20) closes 11:15; 10:00 is outside [10:45, 12:45]
    _, acts = run_days(h + [bars])
    assert len(acts) == 1
    bars = day_bars(d, shock=(20, 0.02), news=[700])     # 11:40 is inside [10:45, 12:45]: skipped
    _, acts = run_days(h + [bars])
    assert acts == []
    bars = day_bars(d, shock=(20, 0.02), news=[700])
    for b in bars[50:]:
        b["opt"]["skew25"] += 0.05                       # later shock: slot 50 closes 13:45, window [13:15, 15:15] excludes 11:40
    _, acts = run_days(h + [bars])
    assert len(acts) == 1 and acts[0][1] == 50


def test_exdiv_and_half_days_skip_and_stay_out_of_history():
    h, d = history()
    st, acts = run_days(h + [day_bars(d, shock=(20, 0.02), exdiv=True),
                             day_bars(d + timedelta(days=1), shock=(20, 0.02), half=True),
                             day_bars(d + timedelta(days=2))])
    assert acts == [] and len(st.hist) == 20             # exdiv + half day never stored; the last day is still open


def test_time_exit_after_18_bars_held():
    st = engine.load_strategy_class(PATH)(PARAMS)
    b = day_bars(date(2017, 3, 1))[30]
    assert st.on_bar(b, {"side": 1, "bars_held": 16}) is None
    assert st.on_bar({**b, "slot": 31}, {"side": 1, "bars_held": 17}) == {"op": "exit"}


def test_engine_exit_fills_90_minutes_after_entry():
    """Through the real engine: entry at the open after the trigger bar, exit 18 bars (90 min) later."""
    h, d = history()
    st = engine.load_strategy_class(PATH)(PARAMS)
    for bars in h:
        for b in bars:
            st.on_bar(b, None)
    bars = day_bars(d, shock=(20, 0.02), noise=99)
    n = 390
    t0 = int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc).timestamp())
    px = np.array([bars[i // 5]["c"] for i in range(n)])
    s = data.Session(day=d, half=False, close_mod=960, inst=1, roll=False, prev_close=None, overnight=None, news=[],
                     news_day=None, t=t0 + 60 * np.arange(n), mod=(570 + np.arange(n)).astype(np.int32),
                     o=px, h=px + 0.5, l=px - 0.5, c=px, v=np.ones(n))
    s.b5 = data.five_minute(s)
    s.opt5 = {k: dict(bars[k]["opt"], **{f: None for f in C.OPT_FIELDS if f not in bars[k]["opt"]}) for k in range(78)}
    res = engine.run([], [s], st)
    tr = res["trades"]
    assert len(tr) == 1 and tr[0]["side"] == 1 and tr[0]["exit_kind"] == "market"
    assert tr[0]["entry_mod"] == 570 + 5 * 21 and tr[0]["exit_mod"] == tr[0]["entry_mod"] + 90


def _hist_after(path, hold):
    """Feed 21 days; when hold, pretend a position is open on slots 20..37 of every day (as after a trade)."""
    h, d = history(21)
    st = engine.load_strategy_class(path)(PARAMS)
    for bars in h:
        for b in bars:
            pos = {"side": 1, "bars_held": b["slot"] - 20} if hold and 20 <= b["slot"] <= 37 else None
            st.on_bar(b, pos)
    return st.hist


def test_history_is_independent_of_positions():
    assert _hist_after(PATH, hold=False) == _hist_after(PATH, hold=True)


def test_original_V2_had_the_bug():
    """Documents the defect that invalidated V2_skew_shock's dev run (LOG iteration 13)."""
    assert _hist_after(ORIG, hold=False) != _hist_after(ORIG, hold=True)
