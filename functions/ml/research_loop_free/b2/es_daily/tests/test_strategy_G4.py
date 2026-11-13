"""G4_vrp_direction on hand-built sessions.

    cd functions/ml && DAILY_PRODUCT=ES ../../.venv/bin/python -B -m pytest -q research_loop_free/b2/es_daily/tests/test_strategy_G4.py
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from research_loop_free.b2.es_daily.eval import sandbox

P = Path(__file__).resolve().parents[1] / "strategies" / "G4_vrp_direction.py"
spec = importlib.util.spec_from_file_location("g4", P)
g4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g4)

PARAMS = {"k": 0.5, "atr_def": "tr", "max_hist": 250, "min_hist": 120, "rv_n": 20, "q": 0.9}


def hist(daily_sd=0.01, skipped_last=False):
    """20 alternating +/- daily_sd returns: sample sd ~ daily_sd*sqrt(20/19)."""
    h = [{"ret": daily_sd if i % 2 else -daily_sd, "nyse_skipped": 0, "tr": 10.0, "h": 105.0, "l": 95.0}
         for i in range(20)]
    if skipped_last:
        h[-1] = {**h[-1], "nyse_skipped": 1}
    return h


def bar(i, vix, h=None, slot=0):
    return {"day": f"d{i:04d}", "slot": slot, "c": 100.0, "hist": h or hist(), "daily": {"VIX": vix}}


def rv_pts():
    return g4.rv(hist(), 20)


def warmed(n=150, **kw):
    s = g4.Strategy({**PARAMS, **kw})
    for i in range(n):
        s.on_bar(bar(i, rv_pts() + (i % 5) - 2), None)      # VRP cycles -2..+2
    return s


def test_sandbox_ok():
    sandbox.check_source(P.read_text(), str(P))


def test_rv_units():
    assert rv_pts() == pytest.approx(0.01 * math.sqrt(20 / 19) * math.sqrt(252) * 100)


def test_long_high_vrp_short_low_vrp():
    s = warmed()
    a = s.on_bar(bar(1000, rv_pts() + 10), None)
    assert a["side"] == 1 and a["stop"] == pytest.approx(95.0)
    s = warmed()
    assert s.on_bar(bar(1000, rv_pts() - 10), None)["side"] == -1


def test_nothing_mid_or_missing():
    s = warmed()
    assert s.on_bar(bar(1000, rv_pts()), None) is None
    assert warmed(n=100).on_bar(bar(1000, rv_pts() + 10), None) is None
    assert warmed().on_bar(bar(1000, None), None) is None
    assert warmed().on_bar(bar(1000, rv_pts() + 10, h=hist(skipped_last=True)), None) is None   # 19 usable rets
    assert warmed().on_bar(bar(1000, rv_pts() + 10, slot=1), None) is None


def test_controls():
    s = warmed(series="vix_level")
    assert s.on_bar(bar(1000, 99.0), None)["side"] == 1
    s = g4.Strategy({**PARAMS, "series": "neg_rv"})
    for i in range(150):
        s.on_bar(bar(i, 20.0, h=hist(0.008 + 0.001 * (i % 5))), None)
    assert s.on_bar(bar(1000, 20.0, h=hist(0.003)), None)["side"] == 1          # very low RV -> long
