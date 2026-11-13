"""G1_vix9d_inversion on hand-built sessions: long in the panic tail, short in the complacency tail, nothing between.

    cd functions/ml && DAILY_PRODUCT=ES ../../.venv/bin/python -B -m pytest -q research_loop_free/b2/es_daily/tests/test_strategy_G1.py
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from research_loop_free.b2.es_daily.eval import sandbox

P = Path(__file__).resolve().parents[1] / "strategies" / "G1_vix9d_inversion.py"
spec = importlib.util.spec_from_file_location("g1", P)
g1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g1)

PARAMS = {"k": 0.5, "atr_def": "tr", "max_hist": 250, "min_hist": 120, "q": 0.9}
HIST = [{"tr": 10.0, "h": 105.0, "l": 95.0}] * 20


def bar(i, vix9d, vix=20.0, slot=0):
    return {"day": f"d{i:04d}", "slot": slot, "c": 100.0, "hist": HIST, "daily": {"VIX": vix, "VIX9D": vix9d}}


def warmed(n=150):
    s = g1.Strategy(PARAMS)
    for i in range(n):   # VIX9D cycles 18..22 around VIX 20: ln ratio in [-0.105, +0.095]
        a = s.on_bar(bar(i, 18.0 + (i % 5)), None)
        assert a is None or i >= 120
    return s


def test_sandbox_ok():
    sandbox.check_source(P.read_text(), str(P))


def test_long_on_panic_short_on_complacency():
    s = warmed()
    a = s.on_bar(bar(1000, 26.0), None)            # ln(26/20)=+0.26 far above the 90th pct
    assert a["side"] == 1 and a["stop"] == pytest.approx(95.0) and a["target"] == pytest.approx(105.0)
    s = warmed()
    assert s.on_bar(bar(1000, 15.0), None)["side"] == -1


def test_nothing_in_the_middle_or_without_history_or_data():
    s = warmed()
    assert s.on_bar(bar(1000, 20.0), None) is None
    s = warmed(n=100)                               # < 120 prior values
    assert s.on_bar(bar(1000, 26.0), None) is None
    s = warmed()
    assert s.on_bar({**bar(1000, 26.0), "daily": {"VIX": 20.0, "VIX9D": None}}, None) is None
    s = warmed()
    assert s.on_bar(bar(1000, 26.0, slot=1), None) is None
    s = warmed()
    assert s.on_bar(bar(1000, 26.0), {"side": 1}) is None


def test_history_is_causal():
    s = warmed()
    n0 = len(s.xs)
    s.on_bar(bar(1000, 26.0), None)
    assert len(s.xs) == n0 + 1 and s.xs[-1] == pytest.approx(math.log(26 / 20))


def test_vix_level_control():
    s = g1.Strategy({**PARAMS, "series": "vix_level"})
    for i in range(150):
        s.on_bar(bar(i, 20.0, vix=15.0 + (i % 10)), None)
    assert s.on_bar(bar(1000, 20.0, vix=40.0), None)["side"] == 1
