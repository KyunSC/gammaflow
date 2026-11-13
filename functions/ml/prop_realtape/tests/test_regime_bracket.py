"""Tests for prop_realtape/regime_bracket.py (run: ../../.venv/bin/python -m pytest prop_realtape/tests -q)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent))
import regime_bracket as RB  # noqa: E402
import replay as RP  # noqa: E402


@pytest.fixture(scope="module")
def nq():
    P = RB.load_paths("NQ", "0935")
    d = P["days"]
    keep = np.flatnonzero(d["era"].isin(RB.ERAS).to_numpy())[::40]          # small sample of days, all eras
    days = d.iloc[keep].reset_index(drop=True)
    return dict(P, days=days, mask=P["mask"][keep])


@pytest.fixture(scope="module")
def flex():
    return RB.plan_ctx("lucidflex_50k")


def test_fx_1_equals_frozen_fixed_rule(nq, flex):
    """fx 1.0 through rule='abs' must reproduce replay's own 'fixed' rule bar for bar."""
    a = RB.cell_results(flex, nq, "NQ", ("fx", 1.0))
    b = RP.day_results(nq, flex["risk"], flex["n0"], "NQ", flex["comm"], flex["flat"], rule="fixed",
                       cap=flex["cap"], mode=flex["mode"])
    assert (a["st"] == b["st"]).all() and (a["n"] == b["n"]).all()
    assert np.allclose(a["pnl"], b["pnl"])
    assert all(np.array_equal(x, y) for x, y in zip(a["bars"], b["bars"]))


def test_reduced_risk_keeps_st0(nq, flex):
    st0 = RP.base_bracket(flex["risk"], flex["n0"], "NQ")
    for n in RB.reduced_ns(flex["n0"]):
        r = RB.cell_results(flex, nq, "NQ", ("rr", n))
        assert (r["st"] == st0).all() and (r["n"] == n).all()
    assert RB.reduced_ns(3) == [1, 2] and RB.reduced_ns(7) == [3, 5] and RB.reduced_ns(20) == [10, 15]


def test_vol_stop_clip_and_cap(nq, flex):
    st0 = RP.base_bracket(flex["risk"], flex["n0"], "NQ")
    w = RB.stops_for(("vol", "atr", 0.05), nq["days"], st0)
    assert np.nanmin(w) >= 0.1 * st0 - 1e-9 and np.nanmax(w) <= 1.6 * st0 + 1e-9
    r = RB.cell_results(flex, nq, "NQ", ("fx", 0.10))
    assert r["n"].max() <= flex["cap"]
    capped = r["capped"]
    assert (r["risk"][~capped] > 0.9 * flex["risk"]).all()                 # uncapped days keep ~full $ risk
    assert (r["risk"][capped] < flex["risk"]).all()


def test_comp_uses_each_eras_rule(nq):
    spec = ("comp", {"2011-18": ("fx", 0.25), "2019-21": ("fx", 0.5), "2022-26": ("fx", 1.0)})
    w = RB.stops_for(spec, nq["days"], 300)
    era = nq["days"]["era"].to_numpy()
    assert np.allclose(w[era == "2011-18"], 75) and np.allclose(w[era == "2019-21"], 150)
    assert np.allclose(w[era == "2022-26"], 300)


def _row(spec, evs, res=None):
    return dict(spec=list(spec), eras={e: dict(ev=v, n_days=100) for e, v in zip(RB.ERAS, evs)},
                exits={e: dict(resolve=r) for e, r in zip(RB.ERAS, res or (0.5, 0.5, 0.5))})


def test_fit_never_reads_held_out_era():
    cells = [_row(("vol", "atr", 0.1), (10, 10, 10)), _row(("vol", "atr", 0.2), (5, 5, 1e6)),
             _row(("vol", "vix", 0.1), (0, 0, 0)), _row(("fx", 1.0), (1, 2, 3)), _row(("fx", 0.5), (2, 3, -1e6))]
    f = RB.fit_fold(cells, "2022-26")
    assert f["R1"]["spec"] == ["vol", "atr", 0.1]                           # 0.2 only wins on the held-out era
    assert f["C1"]["spec"] == ["fx", 0.5]                                   # held-out -1e6 ignored
    assert RB.fit_fold(cells, "2011-18")["R1"]["spec"] == ["vol", "atr", 0.2]


def test_r2_targets_resolve_share():
    cells = [_row(("vol", "atr", 0.1), (0, 0, 0), (0.95, 0.97, 0.2)), _row(("vol", "atr", 0.3), (9, 9, 9), (0.88, 0.91, 0.99)),
             _row(("vol", "vix", 0.1), (0, 0, 0), (0.9, 0.9, 0.9)), _row(("fx", 1.0), (0, 0, 0))]
    f = RB.fit_fold(cells, "2022-26")
    assert f["R2"]["spec"] == ["vol", "atr", 0.3]                            # atr only; |0.895-0.9| < |0.96-0.9|
