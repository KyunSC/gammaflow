"""Daily-bracket research-loop controller: runs pre-registered candidates through the frozen evaluator.
(Adapted copy of research_loop_volsig/controller.py; not frozen.)

    DAILY_PRODUCT=ES ../../.venv/bin/python -B -m research_loop_free.b2.es_daily.controller run <id> --split dev|val1|val2
    DAILY_PRODUCT=ES ../../.venv/bin/python -B -m research_loop_free.b2.es_daily.controller sanity [--seeds 3]
    DAILY_PRODUCT=ES ../../.venv/bin/python -B -m research_loop_free.b2.es_daily.controller status

The traded product comes from DAILY_PRODUCT (the frozen config refuses to import without it) and must equal the
prereg's "product". This loop has ONE dev split, "dev" (2011-02 -> 2018-12); dev_opt and uses_opt are refused (no
options ideas here). Every ledger row records the product and the actual split.

TRADE SHAPE (plan "Trade shape", enforced here on every run, sanity included; any violation makes the run an error
row): per session at most ONE trade; a market entry decided on the 09:30 bar and filled at the 09:35 open; a target;
stop and target symmetric around the 09:30 bar close (1:1, within 2 ticks of grid snapping); stop distance = k x ATR20
as of the prior close (within 1 tick), with ATR20 = mean of the last 20 bar['hist'] entries of `atr_def` ("tr" =
roll-adjusted true range, "range" = h - l). k and atr_def come from each configuration's params.

Every run first verifies eval/MANIFEST.sha256 against the digest pinned in data/research_loop_daily/state.json and
refuses on any mismatch. Each configuration's result is one append-only line in research_loop_daily/ledger.jsonl,
written only once the run completed (fsync'd), so a killed run leaves no row and a rerun resumes without
duplicates. Refusals:
  * no prereg/<id>.json, a prereg or strategy that changed after its first dev run, or a grid of more than
    3 configurations;
  * the loop's configuration budget (config.ATTEMPT_LIMIT) would be exceeded;
  * a candidate family that data_spend_ledger.json marks as spent (one_look) on NQ or ES over the split's dates
    (the shared research_loop/data_spend_ledger.json; ES counts because the two are ~0.9 correlated intraday);
  * val1/val2 for a configuration that did not pass dev (gate + neighbour stability), or val2 before val1 passed;
  * a prereg whose product differs from DAILY_PRODUCT, whose dev_split is not "dev", or with uses_opt not false;
  * a configuration without k (> 0) and atr_def ("tr" | "range").

Shared files (research_loop/CLOSED_IDEAS.md, research_loop/data_spend_ledger.json) are written only through
shared_append_md / shared_append_spend: exclusive fcntl.flock on research_loop/.shared.lock, re-read under the lock,
append this loop's rows only, atomic temp file + os.replace. Other loops' rows are never rewritten or reordered.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import os
import sys
import tempfile
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
SPEND = C.ML / "research_loop" / "data_spend_ledger.json"      # shared with the other research loops
CLOSED = C.ML / "research_loop" / "CLOSED_IDEAS.md"            # shared with the other research loops
SHARED_LOCK = C.ML / "research_loop" / ".shared.lock"
LOOP_NAME = "research_loop_free/b2/es_daily"
MARKETS = {C.PRODUCT, C.COMPANION}
MAX_GRID = 3
ENTRY_SLOT = 1            # the 09:35 bar: decided on slot 0's close, filled at slot 1's first 1m open
ATR_N = 20
ATR_DEFS = ("tr", "range")


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


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class _SharedLock:
    def __init__(self, lock: Path = SHARED_LOCK):
        self.lock = lock

    def __enter__(self):
        self.f = open(self.lock, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def shared_append_spend(rows: list[dict], path: Path = SPEND, lock: Path = SHARED_LOCK) -> None:
    """Append rows to the shared spend ledger's "rows" under the lock; everything else is kept byte-for-byte in order."""
    with _SharedLock(lock):
        cur = path.read_text()
        d = json.loads(cur)
        before = list(d["rows"])
        d["rows"] = before + list(rows)
        # keep the file's own ending (other loops write it with or without a final newline)
        _atomic_write(path, json.dumps(d, indent=1, ensure_ascii=False) + ("\n" if cur.endswith("\n") else ""))


def shared_append_md(text: str, path: Path = CLOSED, lock: Path = SHARED_LOCK) -> None:
    """Append a block to the shared CLOSED_IDEAS.md under the lock (re-read inside it)."""
    with _SharedLock(lock):
        cur = path.read_text()
        sep = "" if cur.endswith("\n\n") else ("\n" if cur.endswith("\n") else "\n\n")
        _atomic_write(path, cur + sep + text.rstrip("\n") + "\n")


def shared_append_table_row(row: str, path: Path = CLOSED, lock: Path = SHARED_LOCK) -> None:
    """Append one markdown table row to CLOSED_IDEAS.md's last table (the file must end with a table row; checked
    under the lock after re-reading, so a block another loop appended in between is never split)."""
    row = row.strip()
    if not (row.startswith("| ") and row.endswith(" |")) or "\n" in row:
        raise ValueError("not a single markdown table row")
    with _SharedLock(lock):
        cur = path.read_text()
        last = cur.rstrip("\n").rsplit("\n", 1)[-1]
        if not cur.endswith("\n") or cur.endswith("\n\n") or not (last.startswith("|") and last.endswith("|")):
            raise Refused(f"{path.name} does not end with a table row; append refused (last line: {last[:80]!r})")
        if last.count("|") != row.count("|"):
            raise Refused(f"column count {row.count('|') - 1} != table's {last.count('|') - 1}")
        _atomic_write(path, cur + row + "\n")


def dev_split_of(spec: dict) -> str:
    """This loop's only dev split is "dev"; refuse anything else, options ideas, and a product mismatch."""
    ds = spec.get("dev_split")
    if ds != "dev":
        raise Refused(f"daily loop: prereg dev_split must be 'dev' (2011-02 -> 2018-12), got {ds!r}")
    if spec.get("uses_opt") is not False:
        raise Refused("daily loop: prereg must state uses_opt: false (no options ideas in this loop)")
    if spec.get("product") != C.PRODUCT:
        raise Refused(f"prereg product {spec.get('product')!r} != DAILY_PRODUCT {C.PRODUCT!r}")
    return ds


def shape_params(params: dict) -> tuple[float, str]:
    k, a = params.get("k"), params.get("atr_def")
    if isinstance(k, bool) or not isinstance(k, (int, float)) or not k > 0 or a not in ATR_DEFS:
        raise Refused(f"configuration needs k > 0 and atr_def in {ATR_DEFS}: {params}")
    return float(k), a


def atr20(hist: list[dict], atr_def: str) -> float | None:
    """Mean of the last ATR_N entries of hist (tr, or h - l); None if fewer than ATR_N usable values."""
    rows = hist[-ATR_N:]
    if len(rows) < ATR_N:
        return None
    v = [r["tr"] if atr_def == "tr" else r["h"] - r["l"] for r in rows]
    if any(x is None for x in v):
        return None
    return float(np.mean(v))


def shape_violations(trades: list[dict], sessions: list, params: dict) -> list[str]:
    """Plan trade shape: <= 1 trade per session, market entry filled at the 09:35 open, 1:1 around the 09:30 close,
    stop distance = k x ATR20 (prior close). Returns human-readable violations (empty = OK)."""
    k, a = shape_params(params)
    by = {s.day.isoformat(): s for s in sessions}
    out, seen = [], set()
    tol = 1e-9
    for t in trades:
        d = t["day"]
        if d in seen:
            out.append(f"{d}: more than one trade in the session")
            continue
        seen.add(d)
        s = by[d]
        if t["entry_kind"] != "market" or not t["at_open"] or t["entry_mod"] != C.RTH_OPEN + ENTRY_SLOT * C.BAR_MINUTES:
            out.append(f"{d}: entry {t['entry_kind']} at mod {t['entry_mod']} (must be market at the 09:35 open)")
            continue
        if t["target"] is None:
            out.append(f"{d}: no target (1:1 bracket required)")
            continue
        c0 = float(s.b5["c"][0])
        if int(s.b5["slot"][0]) != 0:
            out.append(f"{d}: session has no 09:30 bar")
            continue
        if abs(t["target"] + t["stop_init"] - 2 * c0) > 2 * C.TICK + tol:
            out.append(f"{d}: not 1:1 around the 09:30 close {c0}: stop {t['stop_init']} target {t['target']}")
        atr = atr20(s.hist, a)
        if atr is None:
            out.append(f"{d}: traded without {ATR_N} sessions of history")
            continue
        if abs(abs(c0 - t["stop_init"]) - k * atr) > C.TICK + tol:
            out.append(f"{d}: stop distance {abs(c0 - t['stop_init']):.2f} != k*ATR20 {k * atr:.2f}")
    return out


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
    return hashlib.sha256(f"{C.PRODUCT}|{cid}|{k}|{split}|{digest}|{strat_sha}|{prereg_sha}".encode()).hexdigest()[:24]


def spent_conflicts(families: list[str], split: str) -> list[str]:
    lo, hi = C.SPLITS[split]
    out = []
    for r in json.loads(SPEND.read_text())["rows"]:
        if r["kind"] != "one_look" or not MARKETS & set(r["market"]):
            continue
        if set(r["families"]) & set(families) and date.fromisoformat(r["start"]) < hi and date.fromisoformat(r["end"]) >= lo:
            out.append(f"{r['study']} ({r['start']}..{r['end']}, {sorted(set(r['families']) & set(families))})")
    return out


class ShapeError(RuntimeError):
    pass


def evaluate(path: Path, params: dict, warm, trade, n_trials: int) -> tuple[dict, list[dict]]:
    t0 = time.time()
    with engine.ChildStrategy(path, params) as strat:
        res = engine.run(warm, trade, strat)
    tr = res["trades"]
    bad = shape_violations(tr, trade, params)
    if bad:
        raise ShapeError(f"{len(bad)} trade-shape violations: " + "; ".join(bad[:5]))
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
    if split not in ("dev", "val1", "val2"):
        raise Refused(f"split {split!r} is not dev/val1/val2 (the holdout is never run inside the loop; "
                      "'dev' means the prereg's dev_split)")
    digest = verify_eval()
    spec, path, s_sha, p_sha = _load_candidate(cid)
    dev = dev_split_of(spec)
    if split == "dev":
        split = dev
    grid = spec["grid"]
    cfgs = configs(grid)
    if len(cfgs) > MAX_GRID:
        raise Refused(f"grid has {len(cfgs)} configurations (max {MAX_GRID})")
    for c in cfgs:
        shape_params(c)
    rows = [r for r in ledger_rows() if r.get("kind") == "candidate"]
    mine = [r for r in rows if r["id"] == cid and r["status"] == "ok"]
    first_dev = [r for r in mine if r["split"] in C.DEV_SPLITS]
    if any(r["split"] != dev or r.get("product") != C.PRODUCT for r in first_dev):
        raise Refused(f"{cid}: earlier dev rows used another split/product; a change needs a new id")
    if first_dev and (first_dev[0]["strategy_sha256"] != s_sha or first_dev[0]["prereg_sha256"] != p_sha):
        raise Refused(f"{cid}: strategy or prereg changed after its dev run; a refinement needs a new id")
    conflicts = spent_conflicts(spec.get("family", []), split)
    if conflicts:
        raise Refused(f"{cid}: family already spent on {split}: " + "; ".join(conflicts))
    todo = list(range(len(cfgs)))
    if split in C.DEV_SPLITS:
        done = {r["k"] for r in first_dev}
        new = [k for k in todo if k not in done]
        used = len({(r["id"], r["k"]) for r in rows if r["split"] in C.DEV_SPLITS})
        if used + len(new) > C.ATTEMPT_LIMIT:
            raise Refused(f"budget: {used} configurations used, {len(new)} more would exceed {C.ATTEMPT_LIMIT}")
    else:
        need = dev if split == "val1" else "val1"
        passed = {r["k"] for r in mine if r["split"] == need and r["pass"] and r.get("product") == C.PRODUCT}
        if not passed:
            raise Refused(f"{cid}: no configuration passed {need}; {split} not allowed")
        todo = sorted(passed)
    warm, trade = data.load_split(split)
    n_trials = max(1, len({(r["id"], r["k"]) for r in rows if r["split"] in C.DEV_SPLITS})
                   + (len(todo) if split in C.DEV_SPLITS else 0))
    results: dict[int, dict] = {r["k"]: r for r in mine if r["split"] == split}
    RUNS.mkdir(parents=True, exist_ok=True)
    for k in todo:
        key = run_key(cid, k, split, digest, s_sha, p_sha)
        if any(r.get("run_key") == key for r in mine):
            continue  # resumed: already recorded
        base = {"kind": "candidate", "id": cid, "k": k, "split": split, "product": C.PRODUCT, "params": cfgs[k], "run_key": key,
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
        if split not in C.DEV_SPLITS:
            append_row(row)
        else:
            results[k]["_pending"] = True
    if split in C.DEV_SPLITS:  # neighbour stability needs every configuration's result
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
    "_sanity_random": '''"""Accounting check only: a random-direction market entry decided on the 09:30 bar (fills at the 09:35 open),
1:1 bracket of k x ATR20 (mean of the last 20 bar['hist'] true ranges) around the 09:30 close, flat 15:55: the plan's
trade shape. Expected mean R ~ -cost. With need_all, it trades only when bar['mtd'], bar['daily']['UST10Y'] and
bar['sessions_left_in_month'] are present too, which shows the new keys reach the strategy process."""
import numpy as np


class Strategy:
    def __init__(self, params):
        self.rng = np.random.default_rng(params["seed"])
        self.k = params["k"]
        self.need_all = params.get("need_all", False)

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None:
            return None
        side = 1 if self.rng.random() < 0.5 else -1
        h = bar["hist"][-20:]
        if len(h) < 20 or any(r["tr"] is None for r in h):
            return None
        if self.need_all and (bar["mtd"] is None or bar["daily"] is None or bar["daily"]["UST10Y"] is None
                              or bar["sessions_left_in_month"] is None):
            return None
        risk = self.k * float(np.mean([r["tr"] for r in h]))
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
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
    shape = {"k": 0.5, "atr_def": "tr"}
    cfgs = [("_sanity_flat", dict(shape))] + [("_sanity_random", {**shape, "seed": s}) for s in range(seeds)]
    cfgs += [("_sanity_random", {**shape, "seed": 100, "need_all": True})]
    for name, params in cfgs:
        p = STRATS / f"{name}.py"
        key = run_key(name, params.get("seed", -1) + (1000 if params.get("need_all") else 0), split, digest, sha(p), "sanity")
        if key in done:
            print(f"{name} {params}: already recorded")
            continue
        m, _ = evaluate(p, params, warm, trade, 1)
        append_row({"kind": "sanity", "id": name, "params": params, "split": split, "product": C.PRODUCT, "run_key": key, "status": "ok",
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
    used = len({(r["id"], r["k"]) for r in cand if r["split"] in C.DEV_SPLITS})
    print(f"configurations used {used}/{C.ATTEMPT_LIMIT}; ledger rows {len(rows)} ({len(cand)} candidate)")
    for r in cand[-10:]:
        print(f"  {r['id']}[{r['k']}] {r.get('product')} {r['split']} {r['status']} pass={r.get('pass')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("id")
    r.add_argument("--split", required=True)
    s = sub.add_parser("sanity")
    s.add_argument("--seeds", type=int, default=3)
    s.add_argument("--split", default="dev")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "run":
            return cmd_run(a.id, a.split)
        if a.cmd == "sanity":
            return cmd_sanity(a.seeds, a.split)
        return cmd_status()
    except (Refused, sandbox.SandboxError, ShapeError) as e:
        print(f"REFUSED: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
