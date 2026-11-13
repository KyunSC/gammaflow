"""D1_daily_reversal rules on synthetic bars + the real engine/controller shape (not frozen)."""
import json
import math
import os
from datetime import date

os.environ.setdefault("DAILY_PRODUCT", "ES")

import pytest  # noqa: E402

from research_loop_daily import controller as K  # noqa: E402
from research_loop_daily.eval import config as C, data, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "D1_daily_reversal.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "D1_daily_reversal.json").read_text())
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


def base_rets():
    return [0.01 if i % 2 else -0.01 for i in range(19)]      # sd ~ 0.01026


def test_grid_is_the_plan_three_configs_and_sandbox_ok():
    assert [c["cfg"] for c in CFGS] == [{"L": 1, "Z": 1.5}, {"L": 1, "Z": 1.0}, {"L": 5, "Z": 1.0}]
    assert all(c["k"] == 0.5 and c["atr_def"] == "tr" and c["n_sd"] == 20 and c["min_sd"] == 18 for c in CFGS)
    assert K.neighbours(SPEC["grid"], 0) == [1] and K.neighbours(SPEC["grid"], 1) == [0, 2]
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["product"] == "ES" and SPEC["dev_split"] == "dev" and SPEC["uses_opt"] is False
    if C.PRODUCT == "ES":                      # the suite may run as NQ (test_eval sets it first): then it must refuse
        assert K.dev_split_of(SPEC) == "dev"
    else:
        with pytest.raises(K.Refused):
            K.dev_split_of(SPEC)


def test_zscore_matches_definition_and_window():
    ns = load()
    rets = base_rets() + [0.03]
    sd = ns["_sd"](rets)
    assert ns["zscore"](hist(rets), 1, 20, 18) == pytest.approx(0.03 / sd)
    r5 = math.prod(1 + x for x in rets[-5:]) - 1
    assert ns["zscore"](hist(rets), 5, 20, 18) == pytest.approx(r5 / (sd * math.sqrt(5)))
    # only hist[-20:] counts: prepending wild returns changes nothing
    assert ns["zscore"](hist([0.5, -0.5] + rets), 1, 20, 18) == pytest.approx(0.03 / sd)


def test_none_and_skipped_rules():
    ns = load()
    rets = base_rets() + [0.03]
    assert ns["zscore"](hist(rets[:-1] + [None]), 1, 20, 18) is None                 # signal return missing
    assert ns["zscore"](hist(rets, skipped={19: 3}), 1, 20, 18) is None               # stale (gap) return
    assert ns["zscore"](hist(rets, skipped={17: 1}), 5, 20, 18) is None               # inside the L5 window
    h = hist(rets, skipped={2: 1, 3: 1})                                              # 18 usable left -> ok
    win = [r for i, r in enumerate(rets) if i not in (2, 3)]
    assert ns["zscore"](h, 1, 20, 18) == pytest.approx(0.03 / ns["_sd"](win))
    assert ns["zscore"](hist(rets, skipped={2: 1, 3: 1, 4: 1}), 1, 20, 18) is None    # 17 usable -> none
    assert ns["zscore"](hist(rets[-19:]), 5, 20, 18) is not None                      # 19 entries >= 18 usable
    assert ns["zscore"](hist(rets[-17:]), 1, 20, 18) is None


def test_side_bracket_half_day_and_slot():
    ns = load()
    S = ns["Strategy"]({**CFGS[1]})                                                   # L1 Z1
    up = hist(base_rets() + [0.03])
    a = S.on_bar(bar(up), None)
    assert a["side"] == -1 and a["type"] == "market"
    assert a["stop"] == pytest.approx(100 + 0.5 * 4.0) and a["target"] == pytest.approx(100 - 0.5 * 4.0)
    dn = hist(base_rets() + [-0.03])
    a = S.on_bar(bar(dn), None)
    assert a["side"] == 1 and a["stop"] == pytest.approx(98.0) and a["target"] == pytest.approx(102.0)
    assert S.on_bar(bar(up, half=True), None) is None
    assert S.on_bar(bar(up, slot=1), None) is None
    assert S.on_bar(bar(up), {"side": 1}) is None
    small = hist(base_rets() + [0.005])
    assert S.on_bar(bar(small), None) is None
    assert ns["Strategy"]({**CFGS[0]}).on_bar(bar(hist(base_rets() + [0.012])), None) is None   # |z| ~1.17 < 1.5
    assert S.on_bar(bar(hist(base_rets() + [0.012])), None) is not None
    h = hist(base_rets() + [0.03])
    h[-3]["tr"] = None
    assert S.on_bar(bar(h), None) is None                                             # no ATR20 -> no trade


def test_real_engine_window_passes_controller_shape():
    warm, trade = data.load_window(date(2014, 8, 1), date(2014, 11, 1)), None
    ses = [s for s in warm if s.day >= date(2014, 9, 1)]
    for cfg in CFGS:
        with engine.ChildStrategy(PATH, cfg) as st:
            res = engine.run([], ses, st)
        assert K.shape_violations(res["trades"], ses, cfg) == []
        assert len({t["day"] for t in res["trades"]}) == len(res["trades"])
    # 2014-09-26 follows the 09-23..25 Databento gap: hist[-1] is 09-22 and nothing in hist flags the gap (today's own
    # row is not in hist), so R_1 there is the stale 09-22 return -- the case the prereg accepts explicitly and reports.
    s = next(x for x in ses if x.day == date(2014, 9, 26))
    assert s.hist[-1]["day"] == "2014-09-22" and s.hist[-1]["nyse_skipped"] == 0
