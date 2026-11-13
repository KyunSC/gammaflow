"""E1_tsmom_daily rules on synthetic bars + the real engine/controller shape (not frozen)."""
import json
import os
from datetime import date

os.environ.setdefault("DAILY_PRODUCT", "ES")

import pytest  # noqa: E402

from research_loop_daily import controller as K  # noqa: E402
from research_loop_daily.eval import config as C, data, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "E1_tsmom_daily.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "E1_tsmom_daily.json").read_text())
CFGS = K.configs(SPEC["grid"])


def load():
    ns = {}
    exec(compile(PATH.read_text(), str(PATH), "exec"), ns)
    return ns


def hist(rets, tr=4.0, skipped=None):
    skipped = skipped or {}
    return [{"day": f"d{i}", "o": 100, "h": 102, "l": 98, "c": 100, "inst": 1, "roll": False, "adj": 0.0,
             "ret": r, "tr": tr, "nyse_skipped": skipped.get(i, 0), "ust10y": None} for i, r in enumerate(rets)]


def bar(h, slot=0, c=100.0, half=False):
    return {"slot": slot, "c": c, "half_day": half, "hist": h}


def test_grid_is_the_two_approved_configs_and_sandbox_ok():
    assert [c["L"] for c in CFGS] == [20, 40]
    assert all(c["k"] == 0.5 and c["atr_def"] == "tr" for c in CFGS)
    assert K.neighbours(SPEC["grid"], 0) == [1] and K.neighbours(SPEC["grid"], 1) == [0]
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["product"] == "ES" and SPEC["dev_split"] == "dev" and SPEC["uses_opt"] is False
    if C.PRODUCT == "ES":
        assert K.dev_split_of(SPEC) == "dev"
    else:
        with pytest.raises(K.Refused):
            K.dev_split_of(SPEC)


def test_trend_sum_window_none_and_skipped():
    ns = load()
    f = ns["trend_sum"]
    rets = [0.001] * 15 + [-0.002] * 5                                     # sum over 20 = +0.005
    assert f(hist(rets), 20) == pytest.approx(0.005)
    assert f(hist([-0.5] * 10 + rets), 20) == pytest.approx(0.005)          # only hist[-L:] counts
    assert f(hist(rets[-19:]), 20) is None                                  # fewer than L entries
    assert f(hist(rets[:-1] + [None]), 20) is None                          # a ret is None
    assert f(hist([None] + rets), 20) == pytest.approx(0.005)               # None outside the window is ignored
    assert f(hist(rets, skipped={10: 3}), 20) == pytest.approx(0.005)       # gap entries count as recorded
    assert f(hist(rets * 2), 40) == pytest.approx(0.010)


def test_side_bracket_half_day_slot_and_zero():
    ns = load()
    S = ns["Strategy"]({**CFGS[0]})
    up = hist([0.002] * 20)
    a = S.on_bar(bar(up), None)
    assert a["side"] == 1 and a["type"] == "market"
    assert a["stop"] == pytest.approx(98.0) and a["target"] == pytest.approx(102.0)
    dn = hist([-0.002] * 20)
    a = S.on_bar(bar(dn), None)
    assert a["side"] == -1 and a["stop"] == pytest.approx(102.0) and a["target"] == pytest.approx(98.0)
    assert S.on_bar(bar(up, half=True), None) is None
    assert S.on_bar(bar(up, slot=1), None) is None
    assert S.on_bar(bar(up), {"side": 1}) is None
    assert S.on_bar(bar(hist([0.001, -0.001] * 10)), None) is None          # S_L == 0 -> no trade
    h = hist([0.002] * 20)
    h[-3]["tr"] = None
    assert S.on_bar(bar(h), None) is None                                   # no ATR20 -> no trade
    S40 = ns["Strategy"]({**CFGS[1]})
    assert S40.on_bar(bar(up), None) is None                                # L40 needs 40 entries
    assert S40.on_bar(bar(hist([0.003] * 20 + [-0.002] * 20)), None)["side"] == 1
    assert S.on_bar(bar(hist([0.003] * 20 + [-0.002] * 20)), None)["side"] == -1


def test_real_engine_window_passes_controller_shape():
    ses = data.load_window(date(2014, 6, 1), date(2014, 11, 1))
    ses = [s for s in ses if s.day >= date(2014, 9, 1)]
    for cfg in CFGS:
        with engine.ChildStrategy(PATH, cfg) as st:
            res = engine.run([], ses, st)
        assert K.shape_violations(res["trades"], ses, cfg) == []
        days = [t["day"] for t in res["trades"]]
        assert len(set(days)) == len(days)
        assert len(days) >= len([s for s in ses if not s.half]) - 2           # trades (almost) every session
