"""D2_monthend_rebalance rules on synthetic bars + real engine/controller shape (not frozen)."""
import json
import math
import os
from datetime import date

os.environ.setdefault("DAILY_PRODUCT", "ES")

import pytest  # noqa: E402

from research_loop_daily import controller as K  # noqa: E402
from research_loop_daily.eval import config as C, data, engine, sandbox  # noqa: E402

PATH = C.LOOP_DIR / "strategies" / "D2_monthend_rebalance.py"
SPEC = json.loads((C.LOOP_DIR / "prereg" / "D2_monthend_rebalance.json").read_text())
CFGS = K.configs(SPEC["grid"])


def load():
    ns = {}
    exec(compile(PATH.read_text(), str(PATH), "exec"), ns)
    return ns


def hist(n=20, tr=4.0):
    return [{"day": f"2019-05-{i + 1:02d}", "o": 100, "h": 102, "l": 98, "c": 100, "ret": 0.01 if i % 2 else -0.01,
             "tr": tr, "nyse_skipped": 0} for i in range(n)]


def bar(ret=0.02, dy10=0.0, left=0, base="2019-05-08", slot=0, half=False, h=None):
    return {"slot": slot, "c": 100.0, "half_day": half, "sessions_left_in_month": left, "hist": h or hist(),
            "mtd": None if ret is None else {"base_day": base, "ret": ret, "dy10": dy10, "rolled": False}}


def test_grid_sandbox_and_prereg_fields():
    assert [c["cfg"] for c in CFGS] == [{"N": 3, "zmin": 0.0}, {"N": 5, "zmin": 0.0}, {"N": 5, "zmin": 0.4307}]
    assert all(c["k"] == 0.5 and c["atr_def"] == "tr" and c["bond_duration"] == 8.0 for c in CFGS)
    assert K.neighbours(SPEC["grid"], 1) == [0, 2]
    sandbox.check_source(PATH.read_text(), str(PATH))
    assert SPEC["product"] == "ES" and SPEC["dev_split"] == "dev" and SPEC["uses_opt"] is False


def test_signal_x_and_side():
    ns = load()
    assert ns["signal_x"]({"ret": 0.02, "dy10": 0.25}, 8.0) == pytest.approx(0.02 + 0.02)   # yields up: bonds lost
    assert ns["signal_x"]({"ret": 0.02, "dy10": -0.5}, 8.0) == pytest.approx(0.02 - 0.04)
    assert ns["signal_x"]({"ret": 0.02, "dy10": None}, 8.0) is None and ns["signal_x"](None, 8.0) is None
    S = ns["Strategy"](CFGS[0])
    a = S.on_bar(bar(ret=0.02), None)
    assert a["side"] == -1 and a["stop"] == pytest.approx(102.0) and a["target"] == pytest.approx(98.0)
    a = S.on_bar(bar(ret=0.02, dy10=-0.5), None)              # equities +2% but bonds +4%: behind -> long
    assert a["side"] == 1 and a["stop"] == pytest.approx(98.0)


def test_calendar_window_and_skips():
    ns = load()
    S3, S5 = ns["Strategy"](CFGS[0]), ns["Strategy"](CFGS[1])
    assert S3.on_bar(bar(left=2), None) is not None and S3.on_bar(bar(left=3), None) is None
    assert S5.on_bar(bar(left=4), None) is not None and S5.on_bar(bar(left=5), None) is None
    for b in (bar(half=True), bar(slot=1), bar(ret=None), bar(ret=0.0), bar(dy10=None)):
        assert S5.on_bar(b, None) is None
    assert S5.on_bar(bar(), {"side": 1}) is None
    h = hist(); h[-1]["tr"] = None
    assert S5.on_bar(bar(h=h), None) is None


def test_z_cut():
    ns = load()
    Sz = ns["Strategy"](CFGS[2])
    h = hist()
    sd = ns["_sd"]([r["ret"] for r in h])
    n = sum(1 for r in h if r["day"] > "2019-05-08")             # 12 sessions in the MTD window
    assert n == 12
    thr = 0.4307 * sd * math.sqrt(n)
    assert ns["zscore"](thr * 1.01, {"base_day": "2019-05-08"}, h, 20, 18) == pytest.approx(0.4307 * 1.01)
    assert Sz.on_bar(bar(ret=thr * 1.01), None) is not None and Sz.on_bar(bar(ret=thr * 0.99), None) is None
    assert Sz.on_bar(bar(ret=-thr * 1.01), None)["side"] == 1
    assert ns["Strategy"](CFGS[1]).on_bar(bar(ret=thr * 0.99), None) is not None      # no cut on config 1
    h2 = hist(); [r.update(nyse_skipped=1) for r in h2[:3]]
    assert Sz.on_bar(bar(ret=thr * 2, h=h2), None) is None                             # 17 usable < 18


def test_real_engine_month_end_window_passes_shape():
    ses = [s for s in data.load_window(date(2016, 1, 1), date(2016, 5, 1)) if s.day >= date(2016, 2, 1)]
    for cfg in CFGS:
        with engine.ChildStrategy(PATH, cfg) as st:
            res = engine.run([], ses, st)
        assert K.shape_violations(res["trades"], ses, cfg) == []
        days = {t["day"] for t in res["trades"]}
        by = {s.day.isoformat(): s for s in ses}
        assert all(by[d].left_in_month <= cfg["cfg"]["N"] - 1 for d in days)
        if cfg["cfg"]["zmin"] == 0:
            assert len(days) == sum(1 for s in ses if s.left_in_month <= cfg["cfg"]["N"] - 1 and not s.half
                                    and s.mtd and s.mtd["dy10"] is not None)
