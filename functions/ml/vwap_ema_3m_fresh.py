"""One-look fresh-data test for the VWAP/EMA 3m study (user approval 2026-11-03).

Frozen BEFORE the data was bought: one NQ configuration, chosen after seeing 2022-2026,
tested once on NQ sessions that no study has read (2026-08-17 -> 2026-11-02).

    python vwap_ema_3m_fresh.py --freeze   # writes vwap_ema_3m_fresh_prereg.json (refuses if it exists)
    python vwap_ema_3m_fresh.py --run      # creates fresh.lock, reads the new bars once, writes fresh.json

Simulation, costs and fills are imported unchanged from vwap_ema_3m_study.py; its hash is in the prereg.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import vwap_ema_3m_study as S

HERE = Path(__file__).resolve().parent
PREREG = HERE / "vwap_ema_3m_fresh_prereg.json"
OUT = HERE / "data" / "vwap_ema_3m"
LOCK = OUT / "fresh.lock"
RESULT = OUT / "fresh.json"
BARS_DIR = HERE / "data" / "databento" / "fut-ohlcv-1m-cont"

SYM = "NQ"
FRESH_LO, FRESH_HI = date(2026, 8, 17), date(2026, 11, 2)       # inclusive session dates
PRIMARY = "v2|ema|flip|rth|ema34|none"
REPORT_ONLY = ["v2|ema|noflip|rth|ema34|none"]
SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")
AN = math.sqrt(252)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def hashes() -> dict:
    return {"runner_sha256": sha(Path(__file__)), "study_sha256": sha(S.HERE / "vwap_ema_3m_study.py"),
            "spec_sha256": sha(S.SPEC), "spec2_sha256": sha(S.SPEC2)}


def freeze() -> None:
    if PREREG.exists():
        raise SystemExit(f"{PREREG.name} exists; the spec is already frozen")
    PREREG.write_text(json.dumps({
        "frozen": date.today().isoformat(),
        "approval": "User in chat 2026-11-03: 'ok do it' (lock one config, buy NQ after 2026-08-14, test once).",
        "symbol": SYM,
        "window_sessions": [FRESH_LO.isoformat(), FRESH_HI.isoformat()],
        "data": "Databento GLBX.MDP3 ohlcv-1m NQ.v.0, bought after this file was written",
        "primary": PRIMARY,
        "report_only": REPORT_ONLY,
        "chosen_how": "best NQ Sharpe in 2024-2026 among the 32 regular-hours cells, picked after seeing 2022-2026",
        "pass_rule": "PASS if the primary's net $ total after costs > 0 AND it beats the always-long twin of the "
                     "same trades (net $ total). Otherwise FAIL. No retries, no parameter changes.",
        "power_note": "2024-26 rate (+$16.9/day, sd $246/day) over ~52 sessions gives an expected total near "
                      "+$880 with a standard error near $1,770, so even a true edge passes only about 70% of the "
                      "time. A PASS is a sanity check, not proof; a FAIL is weak evidence against it.",
        **hashes(),
    }, indent=1) + "\n")
    print(f"wrote {PREREG}")


def load_fresh(pad_days: int = 10) -> pd.DataFrame:
    first, end = FRESH_LO - timedelta(days=pad_days), FRESH_HI + timedelta(days=1)
    files = [f for f in sorted((BARS_DIR / SYM).glob("*.parquet"))
             if (m := SPAN.search(f.name)) and date.fromisoformat(m[1]) < end and date.fromisoformat(m[2]) > first]
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in files]).sort_index()
    df = df[(df.index >= pd.Timestamp(first, tz="UTC")) & (df.index < pd.Timestamp(end, tz="UTC"))]
    last = df.index.max().tz_convert(S.TZ)
    if last.date() < FRESH_HI:
        raise SystemExit(f"bars end {last}; the frozen window needs sessions through {FRESH_HI}")
    return df


def daily_stats(s: pd.Series) -> dict:
    sd = s.std(ddof=1)
    cum = s.cumsum()
    return {"days": int(len(s)), "total": float(s.sum()), "per_day": float(s.mean()), "sd_day": float(sd),
            "sharpe": float(s.mean() / sd * AN) if sd > 0 else None,
            "max_dd": float((cum.cummax().clip(lower=0) - cum).max())}


def run() -> dict:
    if not PREREG.exists():
        raise SystemExit("no prereg; run --freeze first")
    pr = json.loads(PREREG.read_text())
    if any(pr[k] != v for k, v in hashes().items()):
        raise SystemExit("runner, study or spec changed after the freeze; refusing")
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOCK, "x") as f:
            f.write(date.today().isoformat() + "\n")
    except FileExistsError:
        raise SystemExit("fresh.lock exists: the one look is spent")
    D = S.build(load_fresh(), SYM, FRESH_LO, FRESH_HI)
    days = pd.Index([s["day"] for s in D.sessions])
    years = sorted({d.year for d in days})
    pv = S.POINT_VALUE[SYM]
    hold = pd.Series([(D.c1[s["jl"]] - D.o1[s["j0"]]) * pv for s in D.sessions], index=days)
    res = {"prereg": PREREG.name, "sessions": len(D.sessions), "skipped": D.skipped,
           "first_session": str(days.min()), "last_session": str(days.max()), "variants": {},
           "benchmark_long_every_session_no_costs": daily_stats(hold)}
    by_id = {v["id"]: v for v in S.GRID2}
    for vid in [PRIMARY, *REPORT_ONLY]:
        v = by_id[vid]
        trades = S.simulate(D, v)
        st = S.stats(D, v, trades, years)
        arrays = st.pop("_arrays", None)
        if arrays is None:
            res["variants"][vid] = st | {"daily": None}
            continue
        net, rl, _, _ = arrays
        tday = [t["day"] for t in trades]
        daily = pd.Series(net).groupby(tday).sum().reindex(days, fill_value=0.0)
        along = pd.Series(rl).groupby(tday).sum().reindex(days, fill_value=0.0)
        st["daily"] = daily_stats(daily)
        st["always_long_daily"] = daily_stats(along)
        st["trades"] = [{"day": str(t["day"]), "side": int(t["side"]), "net": float(x)} for t, x in zip(trades, net)]
        res["variants"][vid] = st
    p = res["variants"][PRIMARY]
    ok = bool(p.get("n", 0) > 0 and p["daily"]["total"] > 0 and p["daily"]["total"] > p["always_long_daily"]["total"])
    res["verdict"] = "PASS" if ok else "FAIL"
    RESULT.write_text(json.dumps(res, indent=1, default=str) + "\n")
    return res


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze", action="store_true")
    g.add_argument("--run", action="store_true")
    a = ap.parse_args(argv)
    if a.freeze:
        freeze()
        return
    res = run()
    for vid, st in res["variants"].items():
        d = st.get("daily") or {}
        print(f"{vid}: n={st.get('n')} net/trade={st.get('net_per_trade', 0):+.2f} total={d.get('total', 0):+.0f} "
              f"sharpe={d.get('sharpe')} always-long total={st.get('always_long_daily', {}).get('total')}")
    print("benchmark", res["benchmark_long_every_session_no_costs"])
    print("VERDICT", res["verdict"])


if __name__ == "__main__":
    main()
