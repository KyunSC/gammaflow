"""Controller logic (not frozen; the evaluator's tests are test_eval.py)."""
import json
import os
import subprocess
import sys

os.environ["VOLSIG_PRODUCT"] = "NQ"

import pytest  # noqa: E402

from research_loop_volsig import controller as K  # noqa: E402


def test_configs_and_neighbours():
    g = {"base": {"a": 1}, "axes": {"stop": [1, 2, 3]}}
    assert K.configs(g) == [{"a": 1, "stop": 1}, {"a": 1, "stop": 2}, {"a": 1, "stop": 3}]
    assert K.neighbours(g, 1) == [0, 2] and K.neighbours(g, 0) == [1]


def test_spent_families_refused_on_overlapping_windows():
    assert K.spent_conflicts(["orb"], "dev")            # orb15_2r one-look on ES 2011-21
    assert K.spent_conflicts(["orb"], "dev_opt")        # 2016-18 overlaps it too
    assert K.spent_conflicts(["choch"], "val2")
    assert not K.spent_conflicts(["brand_new_family"], "dev_opt")


def test_paths_and_shared_files():
    assert K.LEDGER == K.C.ML / "research_loop_volsig" / "ledger.jsonl"
    assert K.STATE == K.C.ML / "data" / "research_loop_volsig" / "state.json"
    assert K.SPEND.exists() and K.CLOSED.exists() and K.SPEND.parent.name == "research_loop"
    assert K.SHARED_LOCK == K.C.ML / "research_loop" / ".shared.lock"
    assert K.MARKETS == {"NQ", "ES"}


def test_run_key_changes_with_any_input():
    a = K.run_key("x", 0, "dev", "d", "s", "p")
    assert len({a, K.run_key("x", 1, "dev", "d", "s", "p"), K.run_key("x", 0, "val1", "d", "s", "p"),
                K.run_key("x", 0, "dev", "e", "s", "p"), K.run_key("x", 0, "dev", "d", "t", "p")}) == 5


def test_dev_split_rules():
    ok = {"product": "NQ", "dev_split": "dev_opt", "uses_opt": True}
    assert K.dev_split_of(ok) == "dev_opt"
    assert K.dev_split_of({"product": "NQ", "dev_split": "dev", "uses_opt": False}) == "dev"
    for bad in ({**ok, "dev_split": "dev"},                 # opt idea on the 2011 dev (38% opt coverage)
                {**ok, "uses_opt": False},                  # Cboe-only idea on the short split
                {**ok, "product": "ES"},                    # prereg product != VOLSIG_PRODUCT
                {**ok, "dev_split": "val1"},
                {"product": "NQ", "dev_split": "dev_opt"}):  # uses_opt not stated
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
    code = ("import sys, os; os.environ['VOLSIG_PRODUCT']='NQ'\n"
            "from pathlib import Path\nfrom research_loop_volsig import controller as K\n"
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


def test_es_opt_idea_refused_cleanly():
    code = ("import os; os.environ['VOLSIG_PRODUCT']='ES'\nfrom research_loop_volsig import controller as K\n"
            "try:\n    K.dev_split_of({'product': 'ES', 'dev_split': 'dev_opt', 'uses_opt': True})\n    print('accepted')\n"
            "except K.Refused as e:\n    print('refused', '2 calendar years' in str(e))\n"
            "print(K.dev_split_of({'product': 'ES', 'dev_split': 'dev', 'uses_opt': False}))\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=K.C.ML, capture_output=True, text=True)
    assert out.stdout.split() == ["refused", "True", "dev"], out.stderr[-1500:]


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
