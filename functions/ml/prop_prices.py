"""Prop-firm prices on the Python side: one source, no hard-coded numbers.

Every price comes from frontend/lib/backtest/prop/firms.js (FIRMS and APEX_PRICES), through the fixture
flybrain/fixtures/lucid_plans.json. After editing a price there, re-export and reprice:

    cd frontend && node ../functions/ml/flybrain/tools/export_fixtures.mjs
    cd ../functions/ml && ../../.venv/bin/python prop_prices.py reprice --write

Schemes: 'list' is the firms.js price; 'promo' is price x (1 - the firm's promo.pct). Activation fees are not
discounted.

Repricing is exact, with no re-run. An attempt costs price x billing cycles + activation (when owed), so a stored mean
cost is linear in price: fee = price x cycles + activation x owed, where owed is the pass rate when activation is
charged only on pass, else 1. reprice() recovers the cycles from the stored fee at the price the row was run at
(data/prop_prices/prices_at_run.json for results made before 2026-11-04) and charges the new price. The best risk of a
monthly-billed plan can move slightly with its price; repricing keeps the risk it was chosen at.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = Path(os.environ.get("PROP_PRICES_FIXTURE") or HERE / "flybrain" / "fixtures" / "lucid_plans.json")  # env: dry runs
AT_RUN = HERE / "data" / "prop_prices" / "prices_at_run.json"
SCHEMES = ("list", "promo")
APEX_SIZE = {"25k": 0, "50k": 1}


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def table(path: Path | str = FIXTURE) -> dict:
    return _load(str(path))


def plans(path: Path | str = FIXTURE) -> list[dict]:
    return table(path)["plans"]


def plan_name(plan: dict) -> str:
    """Same label as lucid_structure.plan_name: 'LucidFlex 50K', 'Cons no-fee 50K noDLL'."""
    return f"{plan['planLabel']} {plan['sizeLabel']}{'' if plan['dailyLossLimit'] else ' noDLL'}"


def find(firm: str, name: str, path: Path | str = FIXTURE) -> dict:
    """A plan by firm and display name. Names collide across firms ('Standard 50K'), so the firm is required."""
    hits = {plan_name(p): p for p in plans(path) if p["firm"] == firm}
    if name not in hits:
        raise KeyError(f"{firm}: no plan named {name!r}")
    return hits[name]


def price(plan: dict, scheme: str = "list") -> float:
    if scheme not in SCHEMES:
        raise ValueError(f"scheme must be one of {SCHEMES}")
    p = float(plan["price"])
    return round(p * (1 - float(plan.get("promoPct") or 0)), 2) if scheme == "promo" else p


def priced(plan: dict, scheme: str = "list") -> dict:
    """The plan with its price set for `scheme`, for the account engine (attempt_cost reads plan['price'])."""
    return dict(plan, price=price(plan, scheme))


def fee(plan: dict, scheme: str = "list") -> float:
    """Flat up-front cost, as lucid_structure.fee_of: price + activation."""
    return price(plan, scheme) + float(plan.get("activationFee") or 0)


def terms(plan: dict, scheme: str = "list") -> dict:
    return dict(price=price(plan, scheme), activation=float(plan.get("activationFee") or 0),
                on_pass=bool(plan.get("activationOnPass")), rebill=bool(plan.get("rebillDays")))


# ---- Apex (prices only; rules provisional in data/prop_structure/apex/apex_study.py) ----

def _apex_kind(setup: str) -> tuple[str, int]:
    size = setup.split()[0].lower()
    if size not in APEX_SIZE:
        raise KeyError(setup)
    return ("eod" if " EOD" in setup else "intraday"), APEX_SIZE[size]


def apex_fees(setup: str, path: Path | str = FIXTURE) -> dict[str, tuple[float, float]]:
    """{fee scheme: (evaluation price, activation on pass)} for an apex_study setup name, scheme names as before:
    'Standard coupon' / 'Standard regular', '(3rd-party)' where the price source is third-party, and the 50K
    Tradovate no-activation pair."""
    ap = table(path)["apex"]
    pct = float(ap["promo"]["pct"])
    kind, si = _apex_kind(setup)
    out = {}
    blocks = [("Standard", ap[kind])]
    if kind == "intraday" and "Tradovate" in setup and ap["intradayNoActivation"]["price"][si] is not None:
        blocks.append(("No-activation", ap["intradayNoActivation"]))
    for label, b in blocks:
        src = b.get("source")
        src = src[si] if isinstance(src, list) else src
        tag = f" ({src})" if src else ""
        lst, act = float(b["price"][si]), float(b["activationFee"][si])
        out[f"{label} coupon{tag}"] = (round(lst * (1 - pct), 2), act)
        out[f"{label} regular{tag}"] = (lst, act)
    return out


def apex_terms(setup: str, scheme: str, path: Path | str = FIXTURE) -> dict:
    p, a = apex_fees(setup, path)[scheme]
    return dict(price=p, activation=a, on_pass=True, rebill=False)


# ---- repricing stored results ----

def reprice(row: dict, old: dict, new: dict, fee_key: str = "fee") -> dict:
    """Row re-priced from `old` terms (what it was run at) to `new`. Keeps every other field."""
    fee0, pr = float(row[fee_key]), float(row["pass_rate"])
    act0 = old["activation"] * (pr if old["on_pass"] else 1.0)
    cycles = (fee0 - act0) / old["price"] if old["price"] else 1.0
    if not old["rebill"] and abs(cycles - 1) > 1e-6:
        raise ValueError(f"stored fee {fee0} does not match its run price {old} (cycles {cycles:.4f})")
    fee1 = new["price"] * cycles + new["activation"] * (pr if new["on_pass"] else 1.0)
    d = fee0 - fee1
    out = dict(row)
    out[fee_key] = fee1
    out["ev"] = float(row["ev"]) + d
    if "ev_ci" in row:
        out["ev_ci"] = [float(x) + d for x in row["ev_ci"]]
    days = row.get("days_used", row.get("days"))
    if "ev_per_day" in row and days:
        out["ev_per_day"] = out["ev"] / float(days)
    if "breakeven_price" in row:        # apex_study: take - activation x pass, depends on activation only
        out["breakeven_price"] = float(row["breakeven_price"]) + (old["activation"] - new["activation"]) * pr
    return out


def at_run_terms(firm: str, name: str) -> dict:
    """Terms a pre-2026-11-04 result was run at (the fixture before the Lucid repricing, plus FLEX50_FEE $90.20)."""
    snap = table(AT_RUN)
    cur = find(firm, name)                       # display names did not change; the snapshot is keyed by plan id
    key = (cur["firm"], cur["plan"], cur["size"], cur["dll"])
    p = next(r for r in snap["plans"] if (r["firm"], r["plan"], r["size"], r["dll"]) == key)
    for o in snap["overrides"]:
        if (o["firm"], o["plan"], o["size"]) == key[:3]:
            p = dict(p, price=o["price"])
    return dict(price=float(p["price"]), activation=float(p["activationFee"] or 0),
                on_pass=bool(p["activationOnPass"]), rebill=bool(p["rebillDays"]))


def at_run_apex(setup: str, scheme: str) -> dict:
    f = table(AT_RUN)["apex"][setup][scheme]
    return dict(price=float(f["price"]), activation=float(f["activation"]), on_pass=True, rebill=False)


def _priced_row(row: dict, old: dict, list_t: dict, promo_t: dict | None, promo_pct: float, fee_key="fee") -> dict:
    base = row.get("at_run") and dict(row, **row["at_run"]) or row
    base = {k: v for k, v in base.items() if k not in ("at_run", "promo")}
    out = reprice(base, old, list_t, fee_key)
    out["at_run"] = {k: base[k] for k in (fee_key, "ev", "ev_ci", "ev_per_day", "breakeven_price") if k in base}
    if promo_t is not None:
        pr = reprice(base, old, promo_t, fee_key)
        out["promo"] = dict(pct=promo_pct, **{k: pr[k] for k in (fee_key, "ev", "ev_ci", "ev_per_day") if k in pr})
    return out


def _walk(obj, fn):
    """Apply fn to every dict holding a priced result (ev, fee, pass_rate)."""
    if isinstance(obj, dict):
        if "ev" in obj and "fee" in obj and "pass_rate" in obj:
            return fn(obj)
        return {k: (_walk(v, fn) if k not in ("at_run", "promo") else v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, fn) for v in obj]
    return obj


def _structure_files():
    root = HERE / "data" / "prop_structure"
    files = [(root / "lucid_headline.json", "lucid"), (root / "lucid_daily_fixed.json", "lucid")]
    for firm in ("topstep", "alpha", "mff"):
        for name in ("headline.json", "confirm.json", "sweep.json"):
            files.append((root / firm / name, firm))
    return [(p, f) for p, f in files if p.exists()]


def reprice_all(write: bool = False) -> dict:
    """Reprice every stored result at current list (main fields) and promo (`promo`), keeping `at_run`."""
    summary = dict(fixture=str(FIXTURE), fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                   files=[], headline=[])
    out_files = {}
    for path, firm in _structure_files():
        rows = json.loads(path.read_text())

        def one(r, firm=firm):
            cur = find(firm, r["plan"])
            pct = float(cur.get("promoPct") or 0)
            return _priced_row(r, at_run_terms(firm, r["plan"]), terms(cur, "list"),
                               terms(cur, "promo") if pct else None, pct)
        new = [one(r) for r in rows]
        out_files[path] = new
        if path.name in ("headline.json", "lucid_headline.json"):
            for r in new:
                summary["headline"].append(dict(firm=firm, plan=r["plan"], source=str(path.relative_to(HERE)), fee=r["fee"],
                                                ev=r["ev"], ev_ci=r.get("ev_ci"), ev_at_run=r["at_run"]["ev"],
                                                promo=r.get("promo")))
    apex = HERE / "data" / "prop_structure" / "apex" / "study.json"
    rows = json.loads(apex.read_text())
    out_files[apex] = [_priced_row(r, at_run_apex(r["setup"], r["scheme"]), apex_terms(r["setup"], r["scheme"]), None, 0.0,
                                   fee_key="cost") for r in rows]
    for r in out_files[apex]:
        summary["headline"].append(dict(firm="apex", plan=f"{r['setup']} / {r['scheme']}", source=str(apex.relative_to(HERE)),
                                        fee=r["cost"], ev=r["ev"], ev_ci=r.get("ev_ci"), ev_at_run=r["at_run"]["ev"],
                                        provisional=True))

    state = json.loads((HERE / "data" / "prop_realtape" / "state.json").read_text())
    queue = {e["id"]: e for e in state["plans_queue"]}
    rt = HERE / "data" / "prop_realtape"
    for path in sorted(rt.glob("results/*.json")) + sorted(rt.glob("hist_fix/*.json")):
        res = json.loads(path.read_text())
        if not isinstance(res, dict) or "plan_id" not in res:
            continue                                    # derived side files (e.g. lucid_discounts.json)
        e = queue[res["plan_id"]]
        mult = float(res.get("fee_mult") or 1.0)
        if e["firm"] == "apex":
            old = at_run_apex(e["plan"], e["scheme"])
            new_l, new_p, pct = apex_terms(e["plan"], e["scheme"]), None, 0.0
        else:
            old = at_run_terms(e["firm"], e["plan"])
            old = dict(old, price=old["price"] * mult)
            cur = find(e["firm"], e["plan"])
            pct = float(cur.get("promoPct") or 0)
            new_l = terms(cur, "promo" if mult != 1.0 else "list")   # a --fee-mult run stands for the promo price
            new_p = terms(cur, "promo") if pct and mult == 1.0 else None
        new = _walk(res, lambda r: _priced_row(r, old, new_l, new_p, pct))
        new["fee_flat_at_run"] = res.get("fee_flat_at_run", res["fee_flat"])
        new["fee_flat"] = new_l["price"] + (0 if new_l["on_pass"] else new_l["activation"])
        out_files[path] = new
    summary["files"] = [str(p.relative_to(HERE)) for p in out_files]
    if write:
        for p, v in out_files.items():
            p.write_text(json.dumps(v, indent=1) + "\n")
        (HERE / "data" / "prop_prices" / "priced.json").write_text(json.dumps(summary, indent=1) + "\n")
    return dict(summary=summary, files=out_files)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reprice", help="reprice stored results at current firms.js prices")
    r.add_argument("--write", action="store_true", help="write in place (default: dry run, print the headline table)")
    a = ap.parse_args()
    if a.cmd == "reprice":
        res = reprice_all(write=a.write)
        for h in res["summary"]["headline"]:
            pr = h.get("promo") or {}
            print(f"{h['firm']:8s} {h['plan']:42s} fee {h['fee']:8.2f} EV {h['ev']:+8.1f} (at run {h['ev_at_run']:+8.1f})"
                  + (f"  promo {pr['pct']:.0%}: fee {pr['fee']:7.2f} EV {pr['ev']:+8.1f}" if pr else ""))
        print(("wrote " if a.write else "dry run, would write ") + f"{len(res['files'])} files")


if __name__ == "__main__":
    main()
