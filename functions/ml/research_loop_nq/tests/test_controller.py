"""Controller logic (not frozen; the evaluator's tests are test_eval.py)."""
from research_loop_nq import controller as K


def test_configs_and_neighbours():
    g = {"base": {"a": 1}, "axes": {"stop": [1, 2, 3]}}
    assert K.configs(g) == [{"a": 1, "stop": 1}, {"a": 1, "stop": 2}, {"a": 1, "stop": 3}]
    assert K.neighbours(g, 1) == [0, 2] and K.neighbours(g, 0) == [1]
    assert K.configs({"base": {"a": 1}}) == [{"a": 1}] and K.neighbours({"base": {}}, 0) == []


def test_spent_families_refused_on_overlapping_es_windows():
    assert K.spent_conflicts(["orb"], "dev")            # orb15_2r one-look on ES 2011-21
    assert K.spent_conflicts(["choch"], "val2")         # choch_nq_confirm on ES 2022-26
    assert not K.spent_conflicts(["orb"], "val2")       # ORB 2022+ was ETF proxies, not ES
    assert not K.spent_conflicts(["brand_new_family"], "dev")
    assert K.spent_conflicts(["absorption"], "val2")     # ES-only one-look (2026-04..08) counts for NQ too
    assert not K.spent_conflicts(["absorption"], "dev")


def test_nq_paths_and_shared_files():
    assert K.LEDGER == K.C.ML / "research_loop_nq" / "ledger.jsonl"
    assert K.STATE == K.C.ML / "data" / "research_loop_nq" / "state.json"
    assert K.SPEND.exists() and K.CLOSED.exists() and K.SPEND.parent.name == "research_loop"
    assert K.MARKETS == {"NQ", "ES"}


def test_run_key_changes_with_any_input():
    a = K.run_key("x", 0, "dev", "d", "s", "p")
    assert len({a, K.run_key("x", 1, "dev", "d", "s", "p"), K.run_key("x", 0, "val1", "d", "s", "p"),
                K.run_key("x", 0, "dev", "e", "s", "p"), K.run_key("x", 0, "dev", "d", "t", "p")}) == 5
