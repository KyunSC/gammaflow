"""F1_news_gap on hand-built sessions: fires on a pre-RTH-release gap day, never on the opposite cases.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/es_intraday/tests/test_strategy_F1.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from research_loop_free.es_intraday.eval import sandbox

P = Path(__file__).resolve().parents[1] / "strategies" / "F1_news_gap.py"
spec = importlib.util.spec_from_file_location("f1", P)
f1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f1)

PARAMS = {"day_filter": "pre_rth_news", "atr_n": 20, "stop_pad_atr": 0.1, "g": 0.30}


def bar(day, slot, o, h, l, c, prev_close, news_day=True, news=()):
    return {"day": day, "slot": slot, "o": o, "h": h, "l": l, "c": c, "prev_close": prev_close,
            "news_day": news_day, "news": list(news)}


def warm(s, n=20):
    """n flat sessions around 100: RTH range 10 (TR 10), each closing at 100."""
    for i in range(n):
        d = f"2015-01-{i + 1:02d}"
        assert s.on_bar(bar(d, 0, 100, 104, 96, 100, 100.0), None) is None or i == n  # no gap -> no trade
        s.on_bar(bar(d, 1, 100, 105, 95, 100, 100.0), None)


def first_bar(s, **kw):
    a = dict(day="2015-02-01", slot=0, o=104, h=106, l=103, c=105, prev_close=100.0)
    a.update(kw)
    return s.on_bar(bar(**a), None)


def test_sandbox_ok():
    sandbox.check_source(P.read_text(), str(P))


def test_fires_long_on_up_gap_news_day():
    s = f1.Strategy(PARAMS)
    warm(s)
    act = first_bar(s)                       # gap +4 = 0.4 ATR >= 0.30 ATR
    assert act["op"] == "enter" and act["side"] == 1 and act["type"] == "market"
    assert act["stop"] == pytest.approx(103 - 0.1 * 10)
    assert act["target"] == pytest.approx(105 + (105 - 102))


def test_fires_short_on_down_gap():
    s = f1.Strategy(PARAMS)
    warm(s)
    act = first_bar(s, o=96, h=97, l=94, c=95)
    assert act["side"] == -1 and act["stop"] == pytest.approx(97 + 1.0) and act["target"] == pytest.approx(95 - 3.0)


@pytest.mark.parametrize("kw", [
    {"news_day": False},                     # quiet day
    {"news_day": None},                      # calendar not covered (2011)
    {"news": [600]},                         # ISM 10:00 day
    {"news": [840]},                         # FOMC-only day
    {"o": 102},                              # gap 0.2 ATR < 0.30
    {"prev_close": None},                    # roll day
    {"slot": 1},                             # not the 09:30 bar
])
def test_never_on_opposite_cases(kw):
    s = f1.Strategy(PARAMS)
    warm(s)
    assert first_bar(s, **kw) is None


def test_needs_full_atr_history():
    s = f1.Strategy(PARAMS)
    warm(s, n=19)
    assert first_bar(s) is None


def test_one_trade_per_session_and_quiet_filter():
    s = f1.Strategy({**PARAMS, "day_filter": "quiet"})
    warm(s)
    assert first_bar(s) is None                          # news day is excluded under the quiet control
    s2 = f1.Strategy({**PARAMS, "day_filter": "quiet"})
    warm(s2)
    assert first_bar(s2, news_day=False)["side"] == 1
    assert s2.on_bar(bar("2015-02-01", 1, 105, 106, 104, 105, 100.0, news_day=False), None) is None
