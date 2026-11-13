"""Step 1 bootstrap inventory: ES/NQ 1m `.v.0` files, sessions per era, roll days dropped; headline + plan checks.

Session handling copied from vwap_ema_3m_study.build: sessions 18:00 ET (D-1) -> 17:00 ET (D), labelled D; a roll
session has two contracts in it or a contract different from the previous session's. Weekends and sessions with
< 900 1m bars are skipped too (counted separately).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
BARS = HERE / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT = HERE / "data" / "prop_realtape"
TZ = "America/New_York"
SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")
ERAS = {"2011-18": (date(2011, 1, 3), date(2018, 12, 31)), "2019-21": (date(2019, 1, 1), date(2021, 12, 31)),
        "2022-26": (date(2022, 1, 1), date(2026, 8, 14)), "NQ-ext": (date(2026, 8, 15), date(2026, 11, 3))}


def era(d):
    return next((k for k, (lo, hi) in ERAS.items() if lo <= d <= hi), None)


def sessions(sym):
    files = sorted(f for f in (BARS / sym).glob("*.parquet") if SPAN.search(f.name))
    df = pd.concat([pd.read_parquet(f, columns=["open", "instrument_id"]) for f in files]).sort_index()
    df = df[~df.index.duplicated()]
    et = df.index.tz_convert(TZ)
    mod = np.asarray(et.hour * 60 + et.minute)
    wall = np.asarray(et.date)
    sday = np.where(mod >= 18 * 60, wall + timedelta(days=1), wall)
    rth = (mod >= 9 * 60 + 30) & (mod < 16 * 60)
    g = pd.DataFrame({"d": sday, "inst": df["instrument_id"].to_numpy(), "rth": rth})
    agg = g.groupby("d").agg(n=("inst", "size"), first=("inst", "first"), last=("inst", "last"),
                             nuniq=("inst", "nunique"), rth=("rth", "sum"))
    prev_last = agg["last"].shift(1)
    agg["roll"] = (agg["nuniq"] > 1) | (prev_last.notna() & (agg["first"] != prev_last))
    agg["weekend"] = [d.weekday() >= 5 for d in agg.index]
    agg["thin"] = agg["n"] < 900
    agg["era"] = [era(d) for d in agg.index]
    return files, agg


def main():
    inv = {"files": {}, "eras": {}, "roll_days": {}}
    for sym in ("ES", "NQ"):
        files, agg = sessions(sym)
        inv["files"][sym] = dict(n=len(files), first=files[0].name, last=files[-1].name,
                                 bad=[f.name for f in (BARS / sym).iterdir() if f.name.endswith(".tmp")])
        agg = agg[agg["era"].notna()]
        e = {}
        for k, a in agg.groupby("era"):
            wk = a[~a["weekend"]]
            e[k] = dict(sessions=int(len(wk)), roll=int(wk["roll"].sum()), thin=int((wk["thin"] & ~wk["roll"]).sum()),
                        usable=int((~wk["roll"] & ~wk["thin"]).sum()),
                        rth_short=int((~wk["roll"] & ~wk["thin"] & (wk["rth"] < 390)).sum()))
        inv["eras"][sym] = e
        r = agg[agg["roll"] & ~agg["weekend"]]
        inv["roll_days"][sym] = [str(d) for d in r.index]
    hl = {}
    for f in [HERE / "data/prop_structure/lucid_headline.json"] + sorted((HERE / "data/prop_structure").glob("*/headline.json")):
        rows = json.loads(f.read_text())
        hl[str(f.relative_to(HERE))] = [dict(plan=r["plan"], risk=r["risk"], st=r["stop_ticks"], n=r["contracts"], ev=round(r["ev"], 2)) for r in rows]
    apex = json.loads((HERE / "data/prop_structure/apex/study.json").read_text())
    hl["data/prop_structure/apex/study.json"] = [dict(plan=r["setup"] + " | " + r["scheme"], risk=r["risk"], st=r["stop_ticks"], ev=round(r["ev"], 2))
                                                 for r in apex if r["setup"].startswith("50K")]
    inv["headlines"] = hl
    import lucid_structure as L
    names = {L.plan_name(p) for firm in ("lucid", "topstep", "alpha", "mff", "apex") for p in L.all_plans(firm)}
    inv["plan_dicts"] = sorted(names)
    (OUT / "inventory.json").write_text(json.dumps(inv, indent=1))
    print(json.dumps({k: inv[k] for k in ("files", "eras")}, indent=1))
    for k, v in hl.items():
        print(k, [r["plan"] for r in v])
    print("plan dicts:", len(names))


if __name__ == "__main__":
    main()
