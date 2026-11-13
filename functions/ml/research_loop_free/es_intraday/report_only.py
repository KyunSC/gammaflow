"""Report-only readouts named in a prereg's against_the_mechanism (never gated, never in the config budget).

    ../../.venv/bin/python -B -m research_loop_free.es_intraday.report_only <id> --split dev --set key=value ...

Runs the candidate's strategy with every grid configuration, overriding the given params, through the frozen engine
and cost model (manifest verified first). Prints n, net/gross/cost R and twin p per configuration, and mirrors one
kind="report" row per configuration into the shared research_loop/ledger.jsonl.
"""
from __future__ import annotations

import argparse
import json
import time

from research_loop_free.shared import mirror_run

from . import controller as K
from .eval import data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--set", nargs="*", default=[])
    a = ap.parse_args(argv)
    if a.split != "dev":
        raise SystemExit("report-only readouts run on dev only")
    digest = K.verify_eval()
    spec, path, s_sha, p_sha = K._load_candidate(a.id)
    over = dict(kv.split("=", 1) for kv in a.set)
    over = {k: json.loads(v) if v[:1] in "0123456789-[{tf" else v for k, v in over.items()}
    warm, trade = data.load_split(a.split)
    for k, cfg in enumerate(K.configs(spec["grid"])):
        params = {**cfg, **over}
        m, tr = K.evaluate(path, params, warm, trade, 1)
        by_year = {}
        for t in tr:
            by_year.setdefault(t["day"][:4], []).append(t["r_base"])
        row = {"kind": "report", "id": a.id, "k": k, "split": a.split, "params": params, "eval_digest": digest,
               "strategy_sha256": s_sha, "prereg_sha256": p_sha, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "metrics": {x: m[x] for x in ("trades", "mean_r_base", "mean_r_stress", "gross_r_mean", "cost_r_mean")}
               | {"twin_p": m["twin"]["p"] if m["trades"] else None},
               "net_r_by_year": {y: round(sum(v), 2) for y, v in sorted(by_year.items())}}
        mirror_run(row, K.LOOP_NAME)
        print(json.dumps(row["params"]), json.dumps(row["metrics"], default=float), row["net_r_by_year"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
