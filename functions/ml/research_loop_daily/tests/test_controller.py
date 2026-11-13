"""Controller logic (not frozen; the evaluator's tests are test_eval.py)."""
import json
import os
import subprocess
import sys

os.environ["DAILY_PRODUCT"] = "NQ"

import pytest  # noqa: E402

from research_loop_daily import controller as K  # noqa: E402


def test_configs_and_neighbours():
    g = {"base": {"a": 1}, "axes": {"stop": [1, 2, 3]}}
    assert K.configs(g) == [{"a": 1, "stop": 1}, {"a": 1, "stop": 2}, {"a": 1, "stop": 3}]
    assert K.neighbours(g, 1) == [0, 2] and K.neighbours(g, 0) == [1]


def test_spent_families_refused_on_overlapping_windows():
    assert K.spent_conflicts(["orb"], "dev")            # orb15_2r one-look on ES 2011-21
    assert K.spent_conflicts(["vwap_cross_ema_exit"], "val2")   # one-look on ES/NQ 2022-26
    assert K.spent_conflicts(["choch"], "val2")
    assert not K.spent_conflicts(["brand_new_family"], "dev")
    assert not K.spent_conflicts(["short_term_reversal"], "dev")   # shock_fade spent it as DISCOVERY, not one_look


def test_paths_and_shared_files():
    assert K.LEDGER == K.C.ML / "research_loop_daily" / "ledger.jsonl"
    assert K.STATE == K.C.ML / "data" / "research_loop_daily" / "state.json"
    assert K.SPEND.exists() and K.CLOSED.exists() and K.SPEND.parent.name == "research_loop"
    assert K.SHARED_LOCK == K.C.ML / "research_loop" / ".shared.lock"
    assert K.MARKETS == {"NQ", "ES"}


def test_run_key_changes_with_any_input():
    a = K.run_key("x", 0, "dev", "d", "s", "p")
    assert len({a, K.run_key("x", 1, "dev", "d", "s", "p"), K.run_key("x", 0, "val1", "d", "s", "p"),
                K.run_key("x", 0, "dev", "e", "s", "p"), K.run_key("x", 0, "dev", "d", "t", "p")}) == 5


def test_dev_split_rules():
    ok = {"product": "NQ", "dev_split": "dev", "uses_opt": False}
    assert K.dev_split_of(ok) == "dev"
    for bad in ({**ok, "dev_split": "dev_opt"}, {**ok, "uses_opt": True}, {**ok, "product": "ES"},
                {**ok, "dev_split": "val1"}, {"product": "NQ", "dev_split": "dev"}):
        with pytest.raises(K.Refused):
            K.dev_split_of(bad)


def test_shared_append_keeps_other_rows_and_order(tmp_path):
    spend, md, lock = tmp_path / "spend.json", tmp_path / "CLOSED.md", tmp_path / ".lock"
    spend.write_text(json.dumps({"_doc": "x", "rows": [{"study": "a"}, {"study": "b"}], "tail": 1}))
    md.write_text("# Closed\n\nold\n")
    K.shared_append_spend([{"study": "c"}], spend, lock)
    d = json.loads(spend.read_text())
    assert [r["study"] for r in d["rows"]] == ["a", "b", "c"] and d["_doc"] == "x" and d["tail"] == 1
    K.shared_append_md("## new\nline", md, lock)
    assert md.read_text() == "# Closed\n\nold\n\n## new\nline\n"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_shared_append_is_safe_under_concurrent_writers(tmp_path):
    spend, lock = tmp_path / "spend.json", tmp_path / ".lock"
    spend.write_text(json.dumps({"rows": []}))
    code = ("import sys, os; os.environ['DAILY_PRODUCT']='NQ'\n"
            "from pathlib import Path\nfrom research_loop_daily import controller as K\n"
            "for i in range(25): K.shared_append_spend([{'w': sys.argv[1], 'i': i}], Path(sys.argv[2]), Path(sys.argv[3]))\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w), str(spend), str(lock)], cwd=K.C.ML) for w in range(3)]
    assert all(p.wait(120) == 0 for p in procs)
    rows = json.loads(spend.read_text())["rows"]
    assert len(rows) == 75 and len({(r["w"], r["i"]) for r in rows}) == 75
    for w in ("0", "1", "2"):
        assert [r["i"] for r in rows if r["w"] == w] == list(range(25))


def test_real_spend_ledger_round_trips_byte_identical(tmp_path):
    """Appending must not reformat other loops' rows: an empty append on a copy of the real file changes 0 bytes."""
    cp, lock = tmp_path / "spend.json", tmp_path / ".lock"
    cp.write_text(K.SPEND.read_text())
    K.shared_append_spend([], cp, lock)
    assert cp.read_text() == K.SPEND.read_text()


def test_es_product_runs_the_controller():
    code = ("import os; os.environ['DAILY_PRODUCT']='ES'\nfrom research_loop_daily import controller as K\n"
            "print(K.C.PRODUCT, ' '.join(sorted(K.MARKETS)), K.dev_split_of({'product': 'ES', 'dev_split': 'dev', 'uses_opt': False}))\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=K.C.ML, capture_output=True, text=True)
    assert out.stdout.split() == ["ES", "ES", "NQ", "dev"], out.stderr[-1500:]


def test_table_row_append_keeps_table_contiguous(tmp_path):
    md, lock = tmp_path / "CLOSED.md", tmp_path / ".lock"
    md.write_text("# x\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    K.shared_append_table_row("| 3 | 4 |", md, lock)
    assert md.read_text().endswith("| 1 | 2 |\n| 3 | 4 |\n")
    with pytest.raises(K.Refused):
        K.shared_append_table_row("| 5 | 6 | 7 |", md, lock)          # wrong column count
    md.write_text(md.read_text() + "\nsome paragraph another loop wrote\n")
    with pytest.raises(K.Refused):
        K.shared_append_table_row("| 5 | 6 |", md, lock)              # table no longer last: refuse
    with pytest.raises(ValueError):
        K.shared_append_table_row("not a row", md, lock)


# --- trade shape (plan: one 1:1 trade at the 09:35 open, stop = k x ATR20 of the prior close) -----------------

from datetime import date  # noqa: E402

import numpy as np  # noqa: E402

from research_loop_daily.eval import data  # noqa: E402


def _session(c0=100.0, tr=2.0, n_hist=20):
    n = 390
    px = np.full(n, c0)
    t0 = 1_559_568_600
    s = data.Session(day=date(2019, 6, 3), half=False, close_mod=960, inst=1, roll=False, prev_close=None, overnight=None,
                     news=[], news_day=None, t=t0 + 60 * np.arange(n), mod=(570 + np.arange(n)).astype(np.int32),
                     o=px, h=px, l=px, c=px, v=np.ones(n))
    s.b5 = data.five_minute(s)
    s.hist = [{"day": f"h{i}", "o": c0, "h": c0 + 1.5, "l": c0 - 1.5, "c": c0, "tr": tr, "ret": 0.0} for i in range(n_hist)]
    return s


def _trade(side=1, stop=99.0, target=101.0, mod=575, kind="market", at_open=True, day="2019-06-03"):
    return {"day": day, "side": side, "entry_kind": kind, "at_open": at_open, "entry_mod": mod, "entry_ref": 100.0,
            "stop_init": stop, "target": target}


def test_shape_ok_and_each_violation():
    s, prm = _session(), {"k": 0.5, "atr_def": "tr"}           # ATR20 = 2.0 -> risk 1.0 around the 09:30 close 100
    assert K.shape_violations([_trade()], [s], prm) == []
    assert K.shape_violations([_trade(-1, 101.0, 99.0)], [s], prm) == []
    assert K.shape_violations([_trade(stop=99.25, target=100.75)], [s], {"k": 0.375, "atr_def": "tr"}) == []
    bad = {
        "two trades": [_trade(), _trade()],
        "09:40 entry": [_trade(mod=580)],
        "limit entry": [_trade(kind="limit")],
        "no target": [_trade(target=None)],
        "2:1": [_trade(target=102.0)],
        "wrong k": [_trade(stop=98.0, target=102.0)],
    }
    for name, tr in bad.items():
        assert K.shape_violations(tr, [s], prm), name
    assert K.shape_violations([_trade(stop=98.5, target=101.5)], [s], {"k": 0.5, "atr_def": "range"}) == []   # h-l = 3
    assert K.shape_violations([_trade()], [_session(n_hist=19)], prm)          # < 20 sessions of history


def test_shape_params_required():
    for bad in ({}, {"k": 0}, {"k": 0.5}, {"k": 0.5, "atr_def": "atr"}, {"k": True, "atr_def": "tr"}):
        with pytest.raises(K.Refused):
            K.shape_params(bad)
    assert K.shape_params({"k": 0.5, "atr_def": "range"}) == (0.5, "range")


def test_atr20_uses_last_20_and_none_on_missing():
    h = [{"tr": float(i), "h": 2.0, "l": 1.0} for i in range(30)]
    assert K.atr20(h, "tr") == pytest.approx(np.mean(range(10, 30))) and K.atr20(h, "range") == 1.0
    h[-1]["tr"] = None
    assert K.atr20(h, "tr") is None and K.atr20(h[:19], "range") is None
