"""ES 1m continuous-futures data-quality inventory for the research loop (bootstrap step).

Reads data/databento/fut-ohlcv-1m-cont/<PRODUCT>/*.parquet (Databento ES.v.0: front month, volume roll,
unadjusted prices) and writes data/research_loop/inventory_<product>.json. Prints a short summary.
Strategy-free: it looks at coverage and bar hygiene only, never at returns by rule, so it spends no window.

    .venv/bin/python research_loop/data_inventory.py [--product ES]
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ML = Path(__file__).resolve().parents[1]
BARS = ML / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT = ML / "data" / "research_loop"
ET = "America/New_York"
RTH_OPEN, RTH_CLOSE = 9 * 60 + 30, 16 * 60  # minutes after midnight ET, [open, close)
SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")
# Plan splits (PLAN.md "Data the loop would use"); a 5-session gap is dropped between blocks later.
SPLITS = {"dev": ("2011-01-01", "2019-01-01"), "val1": ("2019-01-01", "2022-01-01"), "val2": ("2022-01-01", "2026-08-15")}


def months(a: date, b: date) -> list[str]:
    """Months touched by [a, b)."""
    out, y, m = [], a.year, a.month
    end = b - timedelta(days=1)
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def coverage(product: str) -> dict:
    d = BARS / product
    covered, files = set(), []
    for f in sorted(d.glob("*.parquet")):
        if m := SPAN.search(f.name):
            a, b = date.fromisoformat(m[1]), date.fromisoformat(m[2])
            covered.update(months(a, b))
            files.append(f)
    first, last = min(covered), max(covered)
    want = months(date.fromisoformat(first + "-01"), date.fromisoformat(last + "-01") + timedelta(days=1))
    return {
        "files": files,
        "first_month": first,
        "last_month": last,
        "missing_months": [m for m in want if m not in covered],
        "tmp_leftovers": sorted(p.name for p in d.glob("*.tmp")),
        "reconcile_markers": sorted(p.name for p in (BARS / "_reconcile").glob(f"*{product}*")) if (BARS / "_reconcile").exists() else [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="ES")
    args = ap.parse_args()
    cov = coverage(args.product)
    raw = pd.concat(
        [pd.read_parquet(f, columns=["open", "high", "low", "close", "volume", "instrument_id"]) for f in cov.pop("files")]
    ).sort_index()
    n_dup = int(raw.index.duplicated().sum())
    bars = raw[~raw.index.duplicated()]
    et = bars.index.tz_convert(ET)
    mins = np.asarray(et.hour * 60 + et.minute)
    rth = bars[(mins >= RTH_OPEN) & (mins < RTH_CLOSE)].copy()
    rth["day"] = rth.index.tz_convert(ET).date
    rth["m"] = mins[(mins >= RTH_OPEN) & (mins < RTH_CLOSE)]

    # Bar hygiene across all hours.
    bad_ohlc = int(((bars.high < bars[["open", "close"]].max(axis=1)) | (bars.low > bars[["open", "close"]].min(axis=1)) | (bars.low <= 0)).sum())
    zero_vol_rth = int((rth.volume == 0).sum())

    g = rth.groupby("day")
    per = pd.DataFrame({
        "n": g.size(),
        "first_m": g.m.min(),
        "last_m": g.m.max(),
        "n_inst": g.instrument_id.nunique(),
        "range_pct": (g.high.max() - g.low.min()) / g.open.first() * 100,
    })
    per = per[pd.to_datetime(per.index).dayofweek < 5]
    # Genuine NYSE half days end 13:15 ET (last bar 13:14). CME also runs a short session to 12:00/13:00 ET on
    # stock-market holidays (MLK, Presidents, Memorial, Juneteenth, July 4, Labor, Thanksgiving): not RTH.
    early_close = per[(per.last_m == 13 * 60 + 14) & (per.n >= 200)]
    cme_holiday = per[per.last_m <= 13 * 60]
    full = per[per.last_m >= RTH_CLOSE - 1]
    short_full = full[full.n < 380]
    mixed = per[per.n_inst > 1]

    # Missing minutes inside a full session (Databento omits minutes with no trades).
    gaps = (390 - full.n).clip(lower=0)

    # Roll jumps: instrument change between consecutive bars, any hour. Unadjusted continuous series.
    inst = bars.instrument_id.to_numpy()
    chg = np.flatnonzero(inst[1:] != inst[:-1]) + 1
    roll = []
    for i in chg:
        jump = bars.open.iat[i] - bars.close.iat[i - 1]
        roll.append({"ts": str(bars.index[i]), "from": int(inst[i - 1]), "to": int(inst[i]), "jump_pts": round(float(jump), 2)})
    flips = [r for r in roll if any(r2["from"] == r["to"] and r2["to"] == r["from"] for r2 in roll)]

    # 1m RTH outliers (same-instrument consecutive bars only).
    same = rth.instrument_id.eq(rth.instrument_id.shift()) & rth.day.eq(pd.Series(rth.day, index=rth.index).shift())
    ret = (rth.close / rth.close.shift() - 1).where(same).abs()
    rng = (rth.high - rth.low) / rth.open
    outliers = rth[(ret > 0.02) | (rng > 0.02)]

    split_counts = {}
    days = pd.to_datetime(full.index.union(early_close.index))
    for k, (a, b) in SPLITS.items():
        split_counts[k] = int(((days >= a) & (days < b)).sum())

    res = {
        "product": args.product,
        "generated": pd.Timestamp.now(tz=ET).isoformat(timespec="seconds"),
        **cov,
        "rows_all_hours": int(len(bars)),
        "duplicate_timestamps": n_dup,
        "bad_ohlc_bars": bad_ohlc,
        "rth_sessions_weekday": int(len(per)),
        "rth_full_sessions": int(len(full)),
        "rth_early_close_sessions": int(len(early_close)),
        "early_close_dates": [str(d) for d in early_close.index],
        "cme_holiday_sessions_not_rth": {"count": int(len(cme_holiday)), "dates": [str(d) for d in cme_holiday.index]},
        "rth_other_partial_sessions": [{"day": str(d), "n": int(r.n), "first_m": int(r.first_m), "last_m": int(r.last_m)} for d, r in per.drop(full.index.union(early_close.index).union(cme_holiday.index)).iterrows()],
        "full_sessions_lt_380_bars": [{"day": str(d), "n": int(r.n)} for d, r in short_full.iterrows()],
        "missing_minutes_full_sessions": {"total": int(gaps.sum()), "sessions_with_any": int((gaps > 0).sum()), "max": int(gaps.max()), "p99": float(np.percentile(gaps, 99))},
        "zero_volume_rth_bars": zero_vol_rth,
        "rth_sessions_mixed_contract": {"count": int(len(mixed)), "dates": [str(d) for d in mixed.index]},
        "roll_events": {"count": len(roll), "abs_jump_pts_median": float(np.median([abs(r["jump_pts"]) for r in roll])) if roll else 0.0,
                        "abs_jump_pts_max": max((abs(r["jump_pts"]) for r in roll), default=0.0), "flip_flops": len(flips), "events": roll},
        "rth_1m_outliers_gt2pct": [{"ts": str(t), "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": int(r.volume)} for t, r in outliers.iterrows()],
        "session_range_pct": {"median": float(per.range_pct.median()), "max": float(per.range_pct.max()), "max_day": str(per.range_pct.idxmax())},
        "sessions_per_split_before_gaps": split_counts,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"inventory_{args.product.lower()}.json"
    out.write_text(json.dumps(res, indent=1, default=str))

    print(f"{args.product}: {res['first_month']}..{res['last_month']}, missing months {res['missing_months'] or 'none'}, tmp {res['tmp_leftovers'] or 'none'}")
    print(f"rows {res['rows_all_hours']:,}, dup ts {n_dup}, bad OHLC {bad_ohlc}, zero-vol RTH bars {zero_vol_rth}")
    print(f"RTH weekday sessions {len(per)}: full {len(full)}, half-day {len(early_close)}, CME-holiday (drop) {len(cme_holiday)}, other partial {len(res['rth_other_partial_sessions'])}")
    mm = res["missing_minutes_full_sessions"]
    print(f"full sessions <380 bars: {len(short_full)}; missing minutes total {mm['total']} in {mm['sessions_with_any']} sessions (max {mm['max']})")
    print(f"mixed-contract RTH sessions {len(mixed)}; roll events {len(roll)} (median |jump| {res['roll_events']['abs_jump_pts_median']:.2f} pts, max {res['roll_events']['abs_jump_pts_max']:.2f}, flip-flops {len(flips)})")
    print(f"RTH 1m outliers >2%: {len(outliers)}; session range median {res['session_range_pct']['median']:.2f}% max {res['session_range_pct']['max']:.2f}% ({res['session_range_pct']['max_day']})")
    print(f"sessions per split (before 5-session gaps): {split_counts}")
    print(f"-> {out.relative_to(ML)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
