"""Build data/research_loop_daily/treasury/ust10y_daily.csv from the raw home.treasury.gov per-year par yield curve
downloads (par_yield_YYYY.csv, "10 Yr" column), and rewrite treasury/SHA256SUMS. Bootstrap (LOG iteration 1).

    ../../.venv/bin/python -B -m research_loop_daily.build_ust [--check]

--check rebuilds in memory and fails unless it equals the frozen file byte for byte (also run by the tests).
Raw files were fetched with plain curl, 2026-11-04 01:08 ET:
  https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/<Y>/all?type=daily_treasury_yield_curve&field_tdr_date_value=<Y>&page&_format=csv
"""
from __future__ import annotations

import csv
import hashlib
import sys
from datetime import datetime
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "research_loop_daily" / "treasury"
YEARS = range(2010, 2027)


def raw_files(d: Path = DIR) -> list[Path]:
    return [d / f"par_yield_{y}.csv" for y in YEARS]


def build(d: Path = DIR) -> str:
    rows: dict = {}
    for f in raw_files(d):
        for r in csv.DictReader(open(f, newline="")):
            day = datetime.strptime(r["Date"], "%m/%d/%Y").date()
            if day in rows:
                raise ValueError(f"duplicate date {day} in {f.name}")
            v = (r.get("10 Yr") or "").strip()
            if v in ("", "N/A"):
                continue                     # 2010-10-11 only (Columbus Day row with blanks)
            rows[day] = float(v)
    return "date,y10\n" + "".join(f"{k.isoformat()},{rows[k]:.2f}\n" for k in sorted(rows))


def sums(d: Path = DIR) -> str:
    fs = raw_files(d) + [d / "ust10y_daily.csv"]
    return "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  data/research_loop_daily/treasury/{f.name}\n" for f in fs)


if __name__ == "__main__":
    text = build()
    out = DIR / "ust10y_daily.csv"
    if "--check" in sys.argv:
        ok = out.read_text() == text and (DIR / "SHA256SUMS").read_text() == sums()
        print("ok" if ok else "MISMATCH")
        sys.exit(0 if ok else 1)
    out.write_text(text)
    (DIR / "SHA256SUMS").write_text(sums())
    print(f"wrote {out} ({text.count(chr(10)) - 1} rows) and SHA256SUMS")
