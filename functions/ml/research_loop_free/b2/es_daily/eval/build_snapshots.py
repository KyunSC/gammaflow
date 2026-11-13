"""One-time snapshot of the evaluator's external inputs into eval/ so MANIFEST.sha256 covers them.

    news.json            high-impact US releases: RTH event minutes per ET date (2011+) and news days (2012+)
    stop_slip_pmf.json   measured stop slippage PMF in ticks by ET clock bucket (data/fill_study/results.json)

Volsig: news.json and stop_slip_pmf.json were COPIED byte-identical from research_loop_nq/eval (frozen there); do
not rerun this here. Daily loop: copied byte-identical again from research_loop_volsig/eval.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date

from . import config as C

PR15_HIST = C.ML.parents[1].parent / "azure-market-data-pr15" / "functions" / "ml" / "econ_calendar_hist.py"


def news() -> dict:
    sys.path.insert(0, str(C.ML))
    import econ_calendar as ec
    from orb15_2r_study import pre2022_rth_events

    rth: dict[str, list[int]] = {}
    for d, mins in pre2022_rth_events().items():
        if d in C.UNSCHEDULED_EVENT_DAYS:
            continue
        rth[d.isoformat()] = sorted(set(mins))
    high = ec.events("high")
    for e in high:
        hh, mm = map(int, e.time_et.split(":"))
        m = hh * 60 + mm
        if C.RTH_OPEN <= m < C.RTH_CLOSE:
            rth.setdefault(e.day.isoformat(), [])
            rth[e.day.isoformat()] = sorted(set(rth[e.day.isoformat()] + [m]))
    spec = importlib.util.spec_from_file_location("econ_calendar_hist", PR15_HIST)
    hist = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hist)
    days = {d.isoformat() for d in hist.news_days()} | {e.day.isoformat() for e in high}
    last = ec.covered_through("high")  # not the last listed future event
    rth = {d: v for d, v in rth.items() if d <= last.isoformat()}
    days = {d for d in days if d <= last.isoformat()}
    return {
        "_doc": "rth: {ET date: [ET minutes of high-impact releases inside 09:30-16:00]} 2011-01..; "
                "news_days: ET dates with any high-impact release (incl. 08:30) inside news_days_coverage. "
                "Outside that coverage a session's news_day is unknown (None).",
        "sources": ["orb15_2r_study.pre2022_rth_events (FOMC decision/presser/minutes, ISM rule) 2011-2021",
                    "econ_calendar.events('high') 2022+", f"econ_calendar_hist.news_days() 2012-2021 ({PR15_HIST.name}, pr15 worktree)"],
        "rth_coverage": ["2011-01-01", last.isoformat()],
        "news_days_coverage": ["2012-01-01", last.isoformat()],
        "rth": dict(sorted(rth.items())),
        "news_days": sorted(days),
    }


def pmf() -> dict:
    r = json.loads((C.ML / "data" / "fill_study" / "results.json").read_text())
    return {"_doc": "stop slip in ticks, P(k) by ET clock bucket; NQ trades 2025-10-24..2026-08-14 (fill_study.py)",
            "buckets": r["stop_slip_pmf"]}


def main() -> int:
    n = news()
    (C.EVAL_DIR / "news.json").write_text(json.dumps(n, indent=0))
    (C.EVAL_DIR / "stop_slip_pmf.json").write_text(json.dumps(pmf(), indent=1))
    print(f"news.json: {len(n['rth'])} RTH-event days, {len(n['news_days'])} news days, rth {n['rth_coverage']}")
    print("stop_slip_pmf.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
