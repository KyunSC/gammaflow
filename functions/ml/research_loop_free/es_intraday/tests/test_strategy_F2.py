"""F2_friday_squaring on hand-built weeks: fades a large WTD move at Friday 14:00, never on the opposite cases.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/es_intraday/tests/test_strategy_F2.py
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from research_loop_free.es_intraday.eval import sandbox

P = Path(__file__).resolve().parents[1] / "strategies" / "F2_friday_squaring.py"
spec = importlib.util.spec_from_file_location("f2", P)
f2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f2)

PARAMS = {"day_filter": "friday", "atr_n": 20, "stop_atr": 0.5, "decide_mod": 835, "w": 1.0}
SLOT_1355 = (835 - 570) // 5


def session(s, d: date, open_, close_1355, roll=False, half=False, skip_1355=False):
    """Two bars: the 09:30 bar (range 10 around open) and the 13:55 bar closing at close_1355."""
    common = {"day": d.isoformat(), "dow": d.weekday(), "prev_close": None if roll else 100.0, "roll": roll,
              "half_day": half}
    acts = [s.on_bar({**common, "slot": 0, "mod": 570, "o": open_, "h": open_ + 5, "l": open_ - 5, "c": open_}, None)]
    if not skip_1355:
        acts.append(s.on_bar({**common, "slot": SLOT_1355, "mod": 835, "o": close_1355, "h": close_1355 + 1,
                              "l": close_1355 - 1, "c": close_1355}, None))
    return acts


def warmed():
    s = f2.Strategy(PARAMS)
    d = date(2015, 1, 5)   # a Monday; 4 weeks of flat sessions -> 20 TRs of 10 (prev_close 100 inside range)
    for i in range(28):
        day = d + timedelta(days=i)
        if day.weekday() < 5:
            assert session(s, day, 100, 100) == [None, None]
    return s


def week(s, monday: date, fri_close, **fri_kw):
    for i in range(4):
        assert session(s, monday + timedelta(days=i), 100 if i == 0 else 101, 101)[-1] is None
    return session(s, monday + timedelta(days=4), 101, fri_close, **fri_kw)[-1]


MON = date(2015, 2, 2)


def test_sandbox_ok():
    sandbox.check_source(P.read_text(), str(P))


def test_week_index_monday_start():
    assert f2.week_index("2015-02-02") == f2.week_index("2015-02-06") != f2.week_index("2015-02-09")
    assert f2.week_index("2015-02-01") != f2.week_index("2015-02-02")   # Sunday belongs to the previous week


def test_fades_up_week_on_friday():
    s = warmed()
    act = week(s, MON, 112)                  # WTD +12 >= 1.0 * ATR 10
    assert act["op"] == "enter" and act["side"] == -1
    assert act["stop"] == pytest.approx(112 + 5) and act["target"] == pytest.approx(112 - 5)


def test_fades_down_week():
    s = warmed()
    assert week(s, MON, 88)["side"] == 1


@pytest.mark.parametrize("kw", [{"half": True}, {"roll": True}, {"skip_1355": True}])
def test_never_on_excluded_fridays(kw):
    s = warmed()
    assert week(s, MON, 112, **kw) is None


def test_never_below_threshold_or_mid_week():
    s = warmed()
    assert week(s, MON, 108) is None         # WTD +8 < 10
    s = warmed()
    for i in range(4):                        # Mon-Thu with a big move: no trade under the Friday filter
        assert session(s, MON + timedelta(days=i), 100 if i == 0 else 101, 115)[-1] is None


def test_mid_week_roll_skips_the_week():
    s = warmed()
    session(s, MON, 100, 101)
    session(s, MON + timedelta(days=1), 101, 101, roll=True)
    for i in (2, 3):
        session(s, MON + timedelta(days=i), 101, 101)
    assert session(s, MON + timedelta(days=4), 101, 115)[-1] is None


def test_monday_holiday_uses_tuesday_open():
    s = warmed()
    tue = MON + timedelta(days=1)
    session(s, tue, 90, 95)                   # week open 90
    for i in (1, 2):
        session(s, tue + timedelta(days=i), 95, 95)
    assert session(s, tue + timedelta(days=3), 95, 101)[-1]["side"] == -1   # WTD +11 vs open 90


def test_mon_thu_control():
    s = f2.Strategy({**PARAMS, "day_filter": "mon_thu"})
    d = date(2015, 1, 5)
    for i in range(28):
        day = d + timedelta(days=i)
        if day.weekday() < 5:
            session(s, day, 100, 100)
    assert session(s, MON, 100, 112)[-1]["side"] == -1
    s2 = f2.Strategy({**PARAMS, "day_filter": "mon_thu"})
    for i in range(28):
        day = d + timedelta(days=i)
        if day.weekday() < 5:
            session(s2, day, 100, 100)
    for i in range(4):
        session(s2, MON + timedelta(days=i), 100, 100)
    assert session(s2, MON + timedelta(days=4), 100, 112)[-1] is None   # Friday excluded under the control
