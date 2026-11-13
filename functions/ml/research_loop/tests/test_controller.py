"""Controller logic (not frozen; the evaluator's tests are test_eval.py)."""
from research_loop import controller as K


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


def test_run_key_changes_with_any_input():
    a = K.run_key("x", 0, "dev", "d", "s", "p")
    assert len({a, K.run_key("x", 1, "dev", "d", "s", "p"), K.run_key("x", 0, "val1", "d", "s", "p"),
                K.run_key("x", 0, "dev", "e", "s", "p"), K.run_key("x", 0, "dev", "d", "t", "p")}) == 5
