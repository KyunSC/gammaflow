"""Research-loop controller: runs pre-registered candidates through the frozen evaluator and keeps the ledger.

    ../../.venv/bin/python -B -m research_loop_free.es_intraday.controller run <id> --split dev|val1|val2
    ../../.venv/bin/python -B -m research_loop_free.es_intraday.controller sanity [--seeds 3]
    ../../.venv/bin/python -B -m research_loop_free.es_intraday.controller status

Every run first verifies eval/MANIFEST.sha256 against the digest pinned in data/research_loop/state.json and
refuses on any mismatch. Each configuration's result is one append-only line in research_loop/ledger.jsonl,
written only once the run completed (fsync'd), so a killed run leaves no row and a rerun resumes without
duplicates. Refusals:
  * no prereg/<id>.json, a prereg or strategy that changed after its first dev run, or a grid of more than
    3 configurations;
  * the loop's configuration budget (config.ATTEMPT_LIMIT) would be exceeded;
  * a candidate family that data_spend_ledger.json marks as spent (one_look) on ES over the split's dates;
  * val1/val2 for a configuration that did not pass dev (gate + neighbour stability), or val2 before val1 passed.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

from .eval import config as C
from .eval import costs, criteria, data, engine, manifest, sandbox, twins

LOOP = C.LOOP_DIR
LEDGER = LOOP / "ledger.jsonl"
PREREG = LOOP / "prereg"
STRATS = LOOP / "strategies"
STATE = C.OUT_DIR / "state.json"
RUNS = C.OUT_DIR / "runs"
SPEND = C.ML / "research_loop" / "data_spend_ledger.json"   # shared with the other research loops
LOOP_NAME = "research_loop_free/es_intraday"
MAX_GRID = 3


class Refused(RuntimeError):
    pass


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(x) for x in LEDGER.read_text().splitlines() if x.strip()]


def append_row(row: dict) -> None:
    line = json.dumps(row, sort_keys=True, default=float) + "\n"
    with open(LEDGER, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


_append_local = append_row


def append_row(row: dict) -> None:
    """Local ledger (budget) first, then the shared research_loop/ledger.jsonl mirror (plan rule 3)."""
    _append_local(row)
    from research_loop_free.shared import mirror_run
    mirror_run(row, LOOP_NAME)


def verify_eval() -> str:
    pinned = json.loads(STATE.read_text()).get("eval_manifest_sha256")
    if not pinned:
        raise Refused("no pinned evaluator digest in state.json")
    try:
        return manifest.verify(expect_digest=pinned)
    except manifest.HashMismatch as e:
        raise Refused(f"evaluator hash mismatch: {e}") from e


def configs(grid: dict) -> list[dict]:
    base, axes = grid.get("base", {}), grid.get("axes", {})
    names = sorted(axes)
    out = [{**base, **dict(zip(names, vals))} for vals in itertools.product(*(axes[n] for n in names))] if names else [dict(base)]
    return out


def neighbours(grid: dict, i: int) -> list[int]:
    """Indices of configurations one grid step away on exactly one axis."""
    axes = grid.get("axes", {})
    names = sorted(axes)
    if not names:
        return []
    pos = list(itertools.product(*(range(len(axes[n])) for n in names)))
    me = pos[i]
    return [j for j, p in enumerate(pos) if sum(abs(a - b) for a, b in zip(p, me)) == 1]


def run_key(cid: str, k: int, split: str, digest: str, strat_sha: str, prereg_sha: str) -> str:
    return hashlib.sha256(f"{cid}|{k}|{split}|{digest}|{strat_sha}|{prereg_sha}".encode()).hexdigest()[:24]


def spent_conflicts(families: list[str], split: str) -> list[str]:
    lo, hi = C.SPLITS[split]
    out = []
    for r in json.loads(SPEND.read_text())["rows"]:
        if r["kind"] != "one_look" or C.PRODUCT not in r["market"]:
            continue
        if set(r["families"]) & set(families) and date.fromisoformat(r["start"]) < hi and date.fromisoformat(r["end"]) >= lo:
            out.append(f"{r['study']} ({r['start']}..{r['end']}, {sorted(set(r['families']) & set(families))})")
    return out


def evaluate(path: Path, params: dict, warm, trade, n_trials: int) -> tuple[dict, list[dict]]:
    t0 = time.time()
    with engine.ChildStrategy(path, params) as strat:
        res = engine.run(warm, trade, strat)
    tr = res["trades"]
    base, stress = costs.apply(tr, "base"), costs.apply(tr, "stress")
    rl, rs = twins.long_short_r(trade, tr)
    tw = twins.twin_test(base["r"], rl, rs, sides=[t["side"] for t in tr])
    days = np.array([t["day"] for t in tr], dtype=object).astype(str)
    sess = [s.day.isoformat() for s in trade]
    m = criteria.summarize(base["r"], base["usd"], stress["r"], days, sess, tw, n_trials)
    m.update({"rejected": res["rejected"], "replaced": res["replaced"], "seconds": round(time.time() - t0, 1),
              "gross_r_mean": float((base["gross_pts"] / np.array([t["risk_pts"] for t in tr])).mean()) if tr else float("nan"),
              "cost_r_mean": float((base["gross_pts"] / np.array([t["risk_pts"] for t in tr]) - base["r"]).mean()) if tr else float("nan"),
              "exit_kinds": {k: sum(t["exit_kind"] == k for t in tr) for k in ("stop", "target", "market", "flat")}})
    for t, rb, rsx in zip(tr, base["r"], stress["r"]):
        t["r_base"], t["r_stress"] = float(rb), float(rsx)
    return m, tr


def _load_candidate(cid: str) -> tuple[dict, Path, str, str]:
    pre = PREREG / f"{cid}.json"
    if not pre.exists():
        raise Refused(f"no pre-registration {pre.relative_to(C.ML)}")
    spec = json.loads(pre.read_text())
    path = STRATS / f"{cid}.py"
    if not path.exists():
        raise Refused(f"no strategy file {path.relative_to(C.ML)}")
    sandbox.check_source(path.read_text(), str(path))
    return spec, path, sha(path), sha(pre)


def cmd_run(cid: str, split: str) -> int:
    if split not in C.SPLITS:
        raise Refused(f"split {split!r} is not dev/val1/val2 (the holdout is never run inside the loop)")
    digest = verify_eval()
    spec, path, s_sha, p_sha = _load_candidate(cid)
    grid = spec["grid"]
    cfgs = configs(grid)
    if len(cfgs) > MAX_GRID:
        raise Refused(f"grid has {len(cfgs)} configurations (max {MAX_GRID})")
    rows = [r for r in ledger_rows() if r.get("kind") == "candidate"]
    mine = [r for r in rows if r["id"] == cid and r["status"] == "ok"]
    first_dev = [r for r in mine if r["split"] == "dev"]
    if first_dev and (first_dev[0]["strategy_sha256"] != s_sha or first_dev[0]["prereg_sha256"] != p_sha):
        raise Refused(f"{cid}: strategy or prereg changed after its dev run; a refinement needs a new id")
    conflicts = spent_conflicts(spec.get("family", []), split)
    if conflicts:
        raise Refused(f"{cid}: family already spent on {split}: " + "; ".join(conflicts))
    todo = list(range(len(cfgs)))
    if split == "dev":
        done = {r["k"] for r in first_dev}
        new = [k for k in todo if k not in done]
        used = len({(r["id"], r["k"]) for r in rows if r["split"] == "dev"})
        if used + len(new) > C.ATTEMPT_LIMIT:
            raise Refused(f"budget: {used} configurations used, {len(new)} more would exceed {C.ATTEMPT_LIMIT}")
    else:
        need = "dev" if split == "val1" else "val1"
        passed = {r["k"] for r in mine if r["split"] == need and r["pass"]}
        if not passed:
            raise Refused(f"{cid}: no configuration passed {need}; {split} not allowed")
        todo = sorted(passed)
    warm, trade = data.load_split(split)
    n_trials = max(1, len({(r["id"], r["k"]) for r in rows if r["split"] == "dev"}) + (len(todo) if split == "dev" else 0))
    results: dict[int, dict] = {r["k"]: r for r in mine if r["split"] == split}
    RUNS.mkdir(parents=True, exist_ok=True)
    for k in todo:
        key = run_key(cid, k, split, digest, s_sha, p_sha)
        if any(r.get("run_key") == key for r in mine):
            continue  # resumed: already recorded
        base = {"kind": "candidate", "id": cid, "k": k, "split": split, "params": cfgs[k], "run_key": key,
                "eval_digest": digest, "strategy_sha256": s_sha, "prereg_sha256": p_sha, "family": spec.get("family", []),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        try:
            m, tr = evaluate(path, cfgs[k], warm, trade, n_trials)
        except Exception as e:  # noqa: BLE001  a failed attempt is still a row
            append_row({**base, "status": "error", "error": repr(e)[:500], "pass": False})
            print(f"{cid}[{k}] {split}: ERROR {e!r}"[:300])
            return 2
        ok, why = criteria.gate(m, split)
        out = RUNS / cid / f"{split}_{k}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"metrics": m, "trades": tr}, default=float))
        row = {**base, "status": "ok", "gate_pass": ok, "gate_fails": why, "pass": ok, "metrics": m,
               "detail": str(out.relative_to(C.ML))}
        results[k] = row
        if split != "dev":
            append_row(row)
        else:
            results[k]["_pending"] = True
    if split == "dev":  # neighbour stability needs every configuration's result
        for k in todo:
            r = results[k]
            if not r.pop("_pending", False):
                continue
            nb = neighbours(grid, k)
            bad = [j for j in nb if not results[j]["metrics"]["mean_r_base"] > 0]
            r["neighbours"] = nb
            if C.CRITERIA["dev"]["neighbours_positive"] and bad:
                r["gate_fails"] = r["gate_fails"] + [f"neighbours not positive: {bad}"]
            r["pass"] = r["gate_pass"] and not bad
            append_row(r)
    for k in todo:
        r = results[k]
        m = r["metrics"]
        print(f"{cid}[{k}] {split} {json.dumps(r['params'])}: n={m['trades']} R={m['mean_r_base']:+.3f} "
              f"CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] stress={m['mean_r_stress']:+.3f} "
              f"p={m['twin']['p']:.4f} (coin {m['twin']['p_coin']:.4f}) -> {'PASS' if r['pass'] else 'FAIL'}")
        if not r["pass"]:
            print("   fails: " + "; ".join(r["gate_fails"])[:250])
    return 0


SANITY = {
    "_sanity_flat": "class Strategy:\n    def __init__(self, params):\n        pass\n\n    def on_bar(self, bar, pos):\n        return None\n",
    "_sanity_random": '''"""Accounting check only: one random-direction market entry per session at a random slot, 1:1 bracket of
`risk` points, flat by the close. Expected mean R ~ -cost."""
import numpy as np


class Strategy:
    def __init__(self, params):
        self.rng = np.random.default_rng(params["seed"])
        self.risk = params["risk"]
        self.day = None

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self.day = bar["day"]
            self.at = int(self.rng.integers(0, bar["flat_slot"] - 1))
            self.side = 1 if self.rng.random() < 0.5 else -1
        if pos is None and bar["slot"] == self.at:
            c, d = bar["c"], self.side
            return {"op": "enter", "side": d, "type": "market", "stop": c - d * self.risk, "target": c + d * self.risk}
        return None
''',
}


def cmd_sanity(seeds: int, split: str = "dev") -> int:
    """Always-flat and random strategies: accounting checks, not candidates (no budget, kind=sanity)."""
    digest = verify_eval()
    STRATS.mkdir(exist_ok=True)
    for name, src in SANITY.items():
        p = STRATS / f"{name}.py"
        if not p.exists() or p.read_text() != src:
            p.write_text(src)
    warm, trade = data.load_split(split)
    done = {r["run_key"] for r in ledger_rows() if r.get("kind") == "sanity" and r["status"] == "ok"}
    cfgs = [("_sanity_flat", {})] + [("_sanity_random", {"seed": s, "risk": 4.0}) for s in range(seeds)]
    for name, params in cfgs:
        p = STRATS / f"{name}.py"
        key = run_key(name, params.get("seed", -1), split, digest, sha(p), "sanity")
        if key in done:
            print(f"{name} {params}: already recorded")
            continue
        m, _ = evaluate(p, params, warm, trade, 1)
        append_row({"kind": "sanity", "id": name, "params": params, "split": split, "run_key": key, "status": "ok",
                    "eval_digest": digest, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "metrics": m})
        if m["trades"]:
            print(f"{name} {params}: n={m['trades']} R={m['mean_r_base']:+.4f} CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] "
                  f"gross={m['gross_r_mean']:+.4f} cost={m['cost_r_mean']:.4f} p={m['twin']['p']:.3f} {m['seconds']}s")
        else:
            print(f"{name}: n=0 trades, {m['seconds']}s")
    return 0


def cmd_status() -> int:
    rows = ledger_rows()
    cand = [r for r in rows if r.get("kind") == "candidate"]
    used = len({(r["id"], r["k"]) for r in cand if r["split"] == "dev"})
    print(f"configurations used {used}/{C.ATTEMPT_LIMIT}; ledger rows {len(rows)} ({len(cand)} candidate)")
    for r in cand[-10:]:
        print(f"  {r['id']}[{r['k']}] {r['split']} {r['status']} pass={r.get('pass')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("id")
    r.add_argument("--split", required=True)
    s = sub.add_parser("sanity")
    s.add_argument("--seeds", type=int, default=3)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "run":
            return cmd_run(a.id, a.split)
        if a.cmd == "sanity":
            return cmd_sanity(a.seeds)
        return cmd_status()
    except (Refused, sandbox.SandboxError) as e:
        print(f"REFUSED: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
