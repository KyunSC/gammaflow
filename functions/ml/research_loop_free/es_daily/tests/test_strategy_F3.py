"""F3_yield_shock on a hand-built history: fires against a large yield move, never on the opposite cases.

    cd functions/ml && DAILY_PRODUCT=ES ../../.venv/bin/python -B -m pytest -q research_loop_free/es_daily/tests/test_strategy_F3.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from research_loop_free.es_daily.eval import sandbox

P = Path(__file__).resolve().parents[1] / "strategies" / "F3_yield_shock.py"
spec = importlib.util.spec_from_file_location("f3", P)
f3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3)

PARAMS = {"k": 0.5, "atr_def": "tr", "min_deltas": 40, "Z": 1.5}


def hist(last_move, n=60, none_at=None):
    """Yields alternate +/-0.05 (sd ~0.05), then a final move of last_move. tr = 10 throughout."""
    y, out = 2.0, []
    for i in range(n - 1):
        y += 0.05 if i % 2 else -0.05
        out.append({"day": f"d{i}", "ust10y": y, "tr": 10.0, "h": 105.0, "l": 95.0})
    out.append({"day": "last", "ust10y": y + last_move, "tr": 10.0, "h": 105.0, "l": 95.0})
    if none_at is not None:
        out[none_at]["ust10y"] = None
    return out


def bar(h, slot=0):
    return {"slot": slot, "c": 100.0, "hist": h}


def test_sandbox_ok():
    sandbox.check_source(P.read_text(), str(P))


def test_yields_up_shorts_es():
    act = f3.Strategy(PARAMS).on_bar(bar(hist(+0.15)), None)       # z ~ +3
    assert act["side"] == -1 and act["stop"] == pytest.approx(105.0) and act["target"] == pytest.approx(95.0)


def test_yields_down_longs_es():
    assert f3.Strategy(PARAMS).on_bar(bar(hist(-0.15)), None)["side"] == 1


@pytest.mark.parametrize("h,slot", [
    (hist(+0.05), 0),                 # z ~ +1 < 1.5
    (hist(+0.15), 1),                 # not the 09:30 bar
    (hist(+0.15, none_at=-2), 0),     # bond holiday the day before: no prior-day delta
    (hist(+0.15, none_at=-1), 0),     # no yield yesterday
    (hist(+0.15, n=30), 0),           # under 40 deltas
])
def test_never_on_opposite_cases(h, slot):
    assert f3.Strategy(PARAMS).on_bar(bar(h, slot), None) is None


def test_no_trade_when_in_position():
    assert f3.Strategy(PARAMS).on_bar(bar(hist(+0.15)), {"side": 1}) is None
