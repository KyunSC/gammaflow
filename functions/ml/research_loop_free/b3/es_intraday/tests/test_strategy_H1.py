"""H1_es_hour_periodicity on hand-built 5m sessions.

    cd functions/ml && ../../.venv/bin/python -B -m pytest -q research_loop_free/b3/es_intraday/tests/test_strategy_H1.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from research_loop_free.b3.es_intraday.eval import sandbox

P = Path(__file__).resolve().parents[1] / "strategies" / "H1_es_hour_periodicity.py"
spec = importlib.util.spec_from_file_location("h1", P)
h1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h1)

PARAMS = {"series": "periodicity", "range_n": 20, "valid_frac": 0.8, "N": 5}


def session(i, up_hour=660, half=False, roll=False, skip=()):
    """09:30-16:00 5m bars, flat at 100 except +2 points during the hour starting at up_hour; range 1 pt per bar."""
    out, px = [], 100.0
    for m in range(570, 960, 5):
        o = px
        if up_hour <= m < up_hour + 60:
            px += 2 / 12
        if m in skip:
            continue
        out.append({"day": f"2015-01-{i:04d}", "mod": m, "o": o, "h": max(o, px) + 0.5, "l": min(o, px) - 0.5, "c": px,
                    "half_day": half, "roll": roll, "warmup": False})
    return out


def feed(s, sessions, pos_fn=lambda b: None):
    acts = []
    for sess in sessions:
        for b in sess:
            a = s.on_bar(b, pos_fn(b))
            if a:
                acts.append((b["day"], b["mod"], a))
    return acts


def test_sandbox_ok():
    sandbox.check_source(P.read_text(), str(P))


def test_follows_same_hour_with_range_bracket():
    s = h1.Strategy(PARAMS)
    feed(s, [session(i) for i in range(25)])
    acts = feed(s, [session(99)])
    ent = [(m, a) for _, m, a in acts if a["op"] == "enter"]
    assert [m for m, _ in ent] == [655]                       # only hour 11:00 has a nonzero history mean
    a = ent[0][1]
    rng = 2 + 1.0                                            # +2 drift over the hour plus the 1-pt bar range
    assert a["side"] == 1 and a["stop"] == pytest.approx(a["target"] - 2 * rng) and a["target"] - 100 == pytest.approx(rng)


def test_down_hour_shorts_and_exit_at_h50():
    s = h1.Strategy(PARAMS)
    sess = [session(i) for i in range(25)]
    for x in sess:
        for b in x:
            if 660 <= b["mod"] < 720:
                b["c"] = 200 - b["c"]; b["o"] = 200 - b["o"]; b["h"], b["l"] = 200 - b["l"], 200 - b["h"]
    feed(s, sess)
    assert s._mean(s.ret[660], 4) < 0
    assert s.on_bar({**session(99)[0], "mod": 655, "c": 100.0}, None)["side"] == -1
    assert s.on_bar({**session(99)[0], "mod": 710, "c": 100.0}, {"side": -1}) == {"op": "exit"}


def test_needs_history_and_skips_half_roll():
    s = h1.Strategy(PARAMS)
    feed(s, [session(i) for i in range(10)])                 # < 20 ranges
    assert not [a for *_, a in feed(s, [session(99)]) if a["op"] == "enter"]
    s = h1.Strategy(PARAMS)
    feed(s, [session(i) for i in range(25)])
    assert not [a for *_, a in feed(s, [session(98, half=True)]) if a["op"] == "enter"]
    s = h1.Strategy(PARAMS)
    feed(s, [session(i) for i in range(25)])
    assert not [a for *_, a in feed(s, [session(97, roll=True)]) if a["op"] == "enter"]


def test_missing_bars_invalidate_history():
    s = h1.Strategy(PARAMS)
    feed(s, [session(i, skip=(715,)) for i in range(25)])    # hour-11 end bar always missing
    assert all(x is None for x in s.ret[660])
    assert not [a for *_, a in feed(s, [session(99)]) if a["op"] == "enter"]


def test_prev_hour_control():
    s = h1.Strategy({**PARAMS, "series": "prev_hour"})
    feed(s, [session(i) for i in range(25)])
    ent = [m for _, m, a in feed(s, [session(99)]) if a["op"] == "enter"]
    assert ent == [715]                                      # decided at 12:00 after the up hour 11:00
