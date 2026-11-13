"""prop_prices: one price source, exact repricing."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import lucid_structure as L
import prop_prices as P

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent.parent / "frontend"


def _row(plan, price):
    """A small synthetic score at `price` (same seeds every call), as the stored rows look."""
    pl = dict(plan, price=price)
    return L.score(pl, L.fee_of(pl) if not (pl.get("rebillDays") or pl.get("activationOnPass")) else 0.0,
                   1550, 310, 1.0, paths=400, n_days=6000, seed=3, rseed=5)


@pytest.mark.parametrize("firm,name", [("topstep", "Cons no-fee 50K noDLL"),   # monthly rebill
                                       ("topstep", "Consistency 50K noDLL"),   # rebill + activation on pass
                                       ("mff", "Builder 50K")])                # one-off
def test_reprice_matches_a_rerun(firm, name):
    plan = P.find(firm, name)
    a, b = _row(plan, plan["price"]), _row(plan, plan["price"] * 0.6)
    old, new = P.terms(plan), dict(P.terms(plan), price=plan["price"] * 0.6)
    r = P.reprice(a, old, new)
    assert r["fee"] == pytest.approx(b["fee"], abs=1e-9)
    assert r["ev"] == pytest.approx(b["ev"], abs=1e-9)
    assert r["ev_ci"][0] - r["ev"] == pytest.approx(a["ev_ci"][0] - a["ev"], abs=1e-9)


def test_reprice_identity_and_bad_fee():
    plan = P.find("mff", "Builder 50K")
    row = dict(ev=10.0, ev_ci=[5.0, 15.0], fee=float(plan["price"]), pass_rate=0.3, days_used=5.0, ev_per_day=2.0)
    assert P.reprice(row, P.terms(plan), P.terms(plan)) == row
    with pytest.raises(ValueError):
        P.reprice(dict(row, fee=999.0), P.terms(plan), P.terms(plan))


def test_promo_prices():
    assert P.price(P.find("mff", "Builder 50K"), "promo") == pytest.approx(91.80)
    flex = P.find("lucid", "LucidFlex 50K")
    assert P.price(flex, "promo") == pytest.approx(round(flex["price"] * (1 - flex["promoPct"]), 2))
    assert P.price(P.find("topstep", "Cons no-fee 50K noDLL"), "promo") == P.find("topstep", "Cons no-fee 50K noDLL")["price"]


def test_apex_fees_reproduce_the_study_schemes():
    """Every scheme apex_study priced before centralising is still produced, at the same numbers."""
    snap = P.table(P.AT_RUN)["apex"]
    for setup, schemes in snap.items():
        fees = P.apex_fees(setup)
        for scheme, f in schemes.items():
            assert fees[scheme] == pytest.approx((f["price"], f["activation"])), (setup, scheme)


def test_at_run_terms_keep_the_flex_override():
    assert P.at_run_terms("lucid", "LucidFlex 50K")["price"] == pytest.approx(90.20)
    assert P.at_run_terms("lucid", "LucidDirect 150K")["price"] == pytest.approx(836.0)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_fixture_is_current_with_firms_js(tmp_path):
    """The fixture is the only way prices reach Python: it must match firms.js. If this fails, re-export
    (cd frontend && node ../functions/ml/flybrain/tools/export_fixtures.mjs) and run prop_prices.py reprice --write."""
    script = tmp_path / "dump.mjs"
    script.write_text(f"""
import {{ createRequire }} from 'node:module'
import path from 'node:path'
const frontend = {json.dumps(str(FRONTEND))}
const require = createRequire(path.join(frontend, 'package.json'))
const jiti = require('jiti').createJiti(import.meta.url)
const {{ resolvePlan, FIRM_LIST, sizesFor, APEX_PRICES }} = jiti(path.join(frontend, 'lib/backtest/prop/firms.js'))
const plans = []
for (const f of FIRM_LIST) for (const p of Object.keys(f.plans)) for (const s of sizesFor(f, f.plans[p])) for (const dll of [true, false]) plans.push(resolvePlan({{ firm: f.id, plan: p, size: s.id, dll }}))
console.log(JSON.stringify({{ plans, apex: APEX_PRICES }}))
""")
    live = json.loads(subprocess.run(["node", str(script)], cwd=FRONTEND, capture_output=True, text=True, check=True).stdout)
    fx = json.loads(P.FIXTURE.read_text())
    key = lambda p: (p["firm"], p["plan"], p["size"], p["dll"])
    cols = ("price", "promoPct", "activationFee", "rebillDays", "activationOnPass")
    assert {key(p): [p.get(c) for c in cols] for p in fx["plans"]} == {key(p): [p.get(c) for c in cols] for p in live["plans"]}
    assert fx.get("apex") == live["apex"]
