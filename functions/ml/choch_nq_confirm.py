"""One-look NQ confirmation of the intraday CHoCH (C6L k=2, 15m) on CME futures 2022-01-03 -> 2026-08-14.

Why: on 2011-2021 (choch_futures_lucid.py, one look, FAIL) NQ alone came within a hair of the bar (twin p 0.0255, CI low
+0.0002) while ES showed nothing. This asks one question on data no CHoCH study has read: does the same rule, unchanged,
beat coin flips on NQ? Everything (bars, rule, stop, fills, costs, sizing, book, twins, Lucid replay) is
choch_futures_lucid's, imported, not copied. Only the window and the decision change. 2021 and earlier are spent; the
sealed verify block (holdout.VERIFY_START 2026-08-24 and its gap week) is never loaded.

    python choch_nq_confirm.py --check     # coverage and rolls only
    python choch_nq_confirm.py --confirm   # the one look; writes data/choch_futures/nq2022_{prereg.json,.lock,results.json}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import choch_futures_lucid as base  # noqa: E402
from open_ema_trail_study import ET, file_span  # noqa: E402

OUT = base.OUT
WINDOW = (date(2022, 1, 3), date(2026, 8, 14))  # inclusive; last research session before the verify gap week
PRIMARY_PRODUCT = "NQ"

SPEC = dict(
    id="C6L-NQ22",
    question="Does C6L k=2/15m (choch_futures_lucid.SPEC, unchanged) beat coin-flip twins on NQ in 2022-2026?",
    base_spec_id=base.SPEC["id"],
    data=("Databento GLBX.MDP3 fut-ohlcv-1m-cont NQ.v.0 / ES.v.0, sessions 2022-01-03 -> 2026-08-14, same RTH loading "
          "and session filter as choch_futures_lucid (one instrument_id, a bar at or after 15:30 ET). Refuse if any "
          "month 2022-01 .. 2026-08 is missing."),
    decision=("PASS iff NQ's k=2/15m twin test has p < 0.025 AND excess CI lower bound > 0. Otherwise STRUCTURE-ONLY if "
              "NQ's Lucid EV (DLL on) at $1,050 > 0, else FAIL. ES and the k/tf grid are reported only. $1,050 stays "
              "the primary Lucid size (as frozen in C6L); $1,550 and no-DLL are reported, not chosen."),
    window=[str(WINDOW[0]), str(WINDOW[1])],
)


def months() -> list[str]:
    out, y, m = [], WINDOW[0].year, WINDOW[0].month
    while (y, m) <= (WINDOW[1].year, WINDOW[1].month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


END_EXCL = WINDOW[1] + timedelta(days=1)  # 2026-08-15: files must reach it, and nothing may run past it
MIN_PRICE = {"NQ": 9000.0, "ES": 3000.0}  # 2022-26 lows were ~10.4k / ~3.49k; catches ETF prices slipping in


def files(product: str) -> list[Path]:
    return [f for f in sorted((base.FUT_BARS / product).glob("*.parquet"))
            if (sp := file_span(f)) and sp[0] < END_EXCL and sp[1] > WINDOW[0]]


def missing(product: str) -> list[str]:
    """Months with no file, plus a note if the data stops short of the window end or runs into the verify block."""
    have = {f.name[:7] for f in (base.FUT_BARS / product).glob("*.parquet")}
    out = [m for m in months() if m not in have]
    ends = [file_span(f)[1] for f in files(product)]
    if not ends or max(ends) < END_EXCL:
        out.append(f"data ends {max(ends) if ends else None}, before {END_EXCL}")
    if ends and max(ends) > END_EXCL:
        out.append(f"a file runs to {max(ends)}, past {END_EXCL} (verify-block bars); refusing to read it")
    return out


def load_rth(product: str):
    """choch_futures_lucid.load_rth on this window."""
    import pandas as pd
    lo, end_excl = WINDOW[0], END_EXCL
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume", "instrument_id"])
                      for f in files(product)]).sort_index()
    bars = bars[~bars.index.duplicated()]
    et = bars.index.tz_convert(ET)
    m = np.asarray(et.hour * 60 + et.minute)
    bars = bars[(m >= base.OPEN_M) & (m < base.CLOSE_M)]
    bars = bars[(bars.index >= pd.Timestamp(lo, tz=ET)) & (bars.index < pd.Timestamp(end_excl, tz=ET))]
    assert bars.low.min() > MIN_PRICE[product], f"{product}: prices below {MIN_PRICE[product]}"
    return bars


def nq_verdict(per: dict, lucid: dict) -> str:
    if base.passes(per[PRIMARY_PRODUCT].get("twins", {})):
        return "PASS"
    if lucid[PRIMARY_PRODUCT][str(base.RISKS[0])]["ev"] > 0:
        return "STRUCTURE-ONLY"
    return "FAIL"


def spec_hash() -> dict:
    sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
           for p in (HERE / "choch_rule.py", HERE / "choch_futures_lucid.py", Path(__file__).resolve(),
                     HERE / "orb15_2r_study.py", HERE / "open_ema_trail_study.py", HERE / "holdout.py",
                     HERE / "lucid_structure.py", HERE / "flybrain" / "prop.py")}
    body = json.dumps(dict(spec=SPEC, base=base.SPEC, sha256=sha), sort_keys=True, default=str)
    return dict(hash=hashlib.sha256(body.encode()).hexdigest()[:16], sha256=sha)


def check() -> int:
    miss = {p: missing(p) for p in base.PRODUCTS}
    print(f"missing months: {miss}")
    if any(miss.values()):
        return 2
    for p in base.PRODUCTS:
        t = base.make_tape(load_rth(p))
        starts = [str(t.d[i]) for i in np.flatnonzero(t.first)]
        years = {y: int(n) for y, n in zip(*np.unique([d.year for d in t.d], return_counts=True))}
        print(f"{p}: {len(t.d)} kept sessions {t.d[0]} -> {t.d[-1]}, {len(starts)} segments starting {starts}")
        print(f"  sessions per year: {years}")
    print("--check: coverage and rolls only; no signals or trades computed.")
    return 0


def confirm() -> int:
    lock = OUT / "nq2022.lock"
    if lock.exists():
        print(f"nq2022.lock exists ({lock.read_text().strip()}); refusing a second look")
        return 3
    miss = {p: missing(p) for p in base.PRODUCTS}
    if any(miss.values()):
        print(f"missing months, refusing (no lock written): {miss}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    h, now = spec_hash(), datetime.now(timezone.utc).isoformat()
    (OUT / "nq2022_prereg.json").write_text(json.dumps(dict(spec=SPEC, base_spec=base.SPEC, **h, written_utc=now,
                                                            note="written before any bar was loaded"), indent=1, default=str))
    with open(lock, "x") as fh:
        fh.write(f"{SPEC['id']} spec {h['hash']} locked {now} before any bar was loaded\n")
    tapes = {p: base.make_tape(load_rth(p)) for p in base.PRODUCTS}
    for p, t in tapes.items():
        print(f"{p}: {len(t.d)} sessions {t.d[0]} -> {t.d[-1]}")
    base.verdict = nq_verdict  # evaluate() prints and returns this test's decision
    res = base.evaluate(tapes)
    res.update(spec=SPEC, spec_hash=h["hash"], sha256=h["sha256"])
    (OUT / "nq2022_results.json").write_text(json.dumps(res, indent=1, default=float))
    print(f"(the VERDICT line above is this test's NQ-only decision: {SPEC['decision']})")
    with open(lock, "a") as fh:
        fh.write(f"finished {datetime.now(timezone.utc).isoformat()} verdict {res['verdict']}\n")
    print(f"wrote {OUT / 'nq2022_results.json'}")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--confirm", action="store_true")
    a = ap.parse_args(argv)
    return check() if a.check else confirm()


if __name__ == "__main__":
    raise SystemExit(main())
