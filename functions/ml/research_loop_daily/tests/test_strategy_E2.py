"""E2_opex_week rules on synthetic bars + the real engine/controller shape (not frozen)."""
import json
import os
from datetime import date, timedelta

os.environ.setdefault("DAILY_PRODUCT", "ES")

import pytest  # noqa: E402

from research_loop_daily import controller as K  # noqa: E402
from research_loop_daily.eval import config as C, data, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "E2_opex_week.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "E2_opex_week.json").read_text())
CFGS = K.configs(SPEC["grid"])
EPOCH = date(1970, 1, 1)


def load():
    ns = {}
    exec(compile(PATH.read_text(), str(PATH), "exec"), ns)
    return ns


def hist(n=20, tr=4.0):
    return [{"day": f"d{i}", "o": 100, "h": 102, "l": 98, "c": 100, "inst": 1, "roll": False, "adj": 0.0,
             "ret": 0.0, "tr": tr, "nyse_skipped": 0, "ust10y": None} for i in range(n)]


def bar(day, slot=0, c=100.0, half=False, h=None):
    return {"slot": slot, "c": c, "half_day": half, "day": day, "hist": hist() if h is None else h}


def ref_side(d, window):
    """Independent datetime reference, same as the prereg's count-only scan."""
    F = date(d.year, d.month, 1)
    F += timedelta(days=(4 - F.weekday()) % 7 + 14)
    w0 = [F - timedelta(days=i) for i in range(4, -1, -1)]
    w1 = [F + timedelta(days=i) for i in range(3, 8)]
    if window == "full_weeks":
        return 1 if d in w0 else -1 if d in w1 else 0
    s0 = [x for x in w0 if data.nyse_scheduled(x)]
    s1 = [x for x in w1 if data.nyse_scheduled(x)]
    return 1 if d in s0[-3:] else -1 if d in s1[:3] else 0


def test_grid_is_the_two_approved_configs_and_sandbox_ok():
    assert [c["window"] for c in CFGS] == ["full_weeks", "3_sessions"]
    assert all(c["k"] == 0.5 and c["atr_def"] == "tr" for c in CFGS)
    assert K.neighbours(SPEC["grid"], 0) == [1] and K.neighbours(SPEC["grid"], 1) == [0]
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["product"] == "ES" and SPEC["dev_split"] == "dev" and SPEC["uses_opt"] is False
    if C.PRODUCT == "ES":
        assert K.dev_split_of(SPEC) == "dev"
    else:
        with pytest.raises(K.Refused):
            K.dev_split_of(SPEC)


def test_integer_calendar_matches_datetime_and_eval_holidays():
    ns = load()
    for y in range(2010, 2028):
        got = {EPOCH + timedelta(days=z) for z in ns["nyse_holidays"](y)}
        assert got == set(data.nyse_holidays(y)), y
    d = date(2010, 1, 1)
    while d < date(2028, 1, 1):
        z = ns["days_from_civil"](d.year, d.month, d.day)
        assert z == (d - EPOCH).days and ns["civil_from_days"](z) == (d.year, d.month, d.day)
        assert ns["weekday"](z) == d.weekday() and ns["scheduled"](z) == data.nyse_scheduled(d)
        for w in ("full_weeks", "3_sessions"):
            assert ns["side_for"](d.isoformat(), w) == ref_side(d, w), (d, w)
        d += timedelta(days=1)


def test_known_windows_and_holiday_expirations():
    f = load()["side_for"]
    # 2017-03: third Friday 03-17 (quarterly)
    assert [f(f"2017-03-{x:02d}", "full_weeks") for x in range(13, 18)] == [1] * 5
    assert [f(f"2017-03-{x:02d}", "full_weeks") for x in range(20, 25)] == [-1] * 5
    assert f("2017-03-10", "full_weeks") == 0 and f("2017-03-27", "full_weeks") == 0
    assert [f(f"2017-03-{x:02d}", "3_sessions") for x in (13, 14, 15, 16, 17)] == [0, 0, 1, 1, 1]
    assert [f(f"2017-03-{x:02d}", "3_sessions") for x in (20, 21, 22, 23, 24)] == [-1, -1, -1, 0, 0]
    # Good Friday expiration 2014-04-18: last 3 sessions of W0 are Tue-Thu
    assert [f(f"2014-04-{x:02d}", "3_sessions") for x in (14, 15, 16, 17)] == [0, 1, 1, 1]
    # MLK Monday 2016-01-18 sits in W1 (third Friday 01-15; W1 = 01-18..22): first 3 W1 sessions are Tue-Thu
    assert [f(f"2016-01-{x:02d}", "3_sessions") for x in (19, 20, 21, 22)] == [-1, -1, -1, 0]
    # Thanksgiving 2018-11-22 inside W1 (third Friday 11-16): W1 sessions 19, 20, 21, (23 half) -> first 3
    assert [f(f"2018-11-{x:02d}", "3_sessions") for x in (19, 20, 21, 23)] == [-1, -1, -1, 0]


def test_side_bracket_half_day_slot_and_atr():
    ns = load()
    S = ns["Strategy"]({**CFGS[0]})
    a = S.on_bar(bar("2017-03-15"), None)
    assert a["side"] == 1 and a["type"] == "market"
    assert a["stop"] == pytest.approx(98.0) and a["target"] == pytest.approx(102.0)
    a = S.on_bar(bar("2017-03-21"), None)
    assert a["side"] == -1 and a["stop"] == pytest.approx(102.0) and a["target"] == pytest.approx(98.0)
    assert S.on_bar(bar("2017-03-28"), None) is None
    assert S.on_bar(bar("2017-03-15", half=True), None) is None
    assert S.on_bar(bar("2017-03-15", slot=1), None) is None
    assert S.on_bar(bar("2017-03-15"), {"side": 1}) is None
    assert S.on_bar(bar("2017-03-15", h=hist(19)), None) is None
    h = hist()
    h[-1]["tr"] = None
    assert S.on_bar(bar("2017-03-15", h=h), None) is None


def test_real_engine_window_passes_controller_shape():
    ses = data.load_window(date(2017, 1, 15), date(2017, 5, 1))
    ses = [s for s in ses if s.day >= date(2017, 3, 1)]
    for cfg in CFGS:
        with engine.ChildStrategy(PATH, cfg) as st:
            res = engine.run([], ses, st)
        assert K.shape_violations(res["trades"], ses, cfg) == []
        want = sorted(s.day.isoformat() for s in ses if not s.half and ref_side(s.day, cfg["window"]))
        assert sorted(t["day"] for t in res["trades"]) == want
