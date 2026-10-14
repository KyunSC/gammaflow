"""AMT NQ confirm: one frozen rule, scored once on QQQ data no study here has ever loaded.

The rule is the best NQ-side result of amt_regime_study.py (exploration on QQQ 2022-01-03 -> 2025-03-26,
picked from ~72 QQQ combinations, so its discovery numbers are inflated by selection):
    ov_accept/ref=range/rr=2.0 on 5-session bracket BREAKOUT days
    discovery: 103 trades, mean net R +0.277 [+0.065, +0.487], LucidFlex 50K EV +$674 (fee $90)

Rule, verbatim from amt_lucid_study.py / amt_regime_study.py (their code is imported, not copied):
  - regime: the 09:30 open is outside the high / low of the prior 5 RTH sessions.
  - setup: the open is also outside the prior session's high (low); the first 30m period (09:30-09:59)
    never trades back into the prior value area (low > VAH for longs, high < VAL for shorts) and closes
    beyond the prior high (low) -> long (short) at the 10:00 bar's open + 1 tick.
  - bracket: stop at the first 30m period's opposite extreme -/+ 1 tick, target 2x the stop distance,
    tick-through target fills, +1 tick stop slippage, flat at the 15:54 close.
  - QQQ x41.2 -> MNQ ($2/pt), $750 risk, <= 40 micros, $1/side commission. LucidFlex 50K without DLL.

Data (fresh): Databento XNAS.ITCH QQQ ohlcv-1m 2018-05-01 -> 2021-12-31, fetched by
`databento_fetch.py eq-ohlcv-1m-early` into its own folder. No script in this repo had loaded these bars
before this one. Sessions with < 380 RTH bars are dropped; the first 5 sessions only warm up the regime.

Verdict (one look, single pre-registered test, alpha 0.05):
    PASS            mean net R > 0 with the 95% block-bootstrap CI above 0, random-direction p < 0.05
                    (same entries and stop / target distances, direction a coin; EV-based, as in
                    amt_lucid_study), and LucidFlex EV > 0.
    STRUCTURE-ONLY  EV > 0 without the above.
    FAIL            EV <= 0.
Expected power is modest: ~13% of sessions trade, so ~120 trades; if the true edge is half the discovery
estimate (+0.14R), the CI excludes 0 only about one time in four.

Specification: everything above was written down before the first run and not changed after it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import amt_lucid_study as amt  # noqa: E402
import amt_regime_study as reg  # noqa: E402
from flybrain.prop import resolve_plan  # noqa: E402

SYMBOL = "QQQ"
BARS_DIR = amt.DATA / "databento" / "eq-ohlcv-1m-early" / SYMBOL
START, END = date(2018, 5, 1), date(2021, 12, 31)
CELL = "ov_accept/ref=range/rr=2.0"
REGIME, SIDE = "bracket", "breakout"
ALPHA = 0.05
OUT = amt.DATA / "amt_nq_confirm"


def load_sessions() -> dict[date, pd.DataFrame]:
    files = sorted(BARS_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bars in {BARS_DIR}; run databento_fetch.py eq-ohlcv-1m-early")
    cutoff = pd.Timestamp(END + pd.Timedelta(days=1), tz=amt.ET).tz_convert("UTC")
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume"], filters=[("ts_event", "<", cutoff)])
                      for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    et = bars.index.tz_convert(amt.ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= amt.OPEN) & (bars.minute < amt.CLOSE) & (bars.day >= START) & (bars.day <= END)]
    out = {}
    for d, g in bars.groupby("day", sort=True):
        if len(g) >= amt.MIN_BARS and g.minute.iloc[0] == amt.OPEN and g.minute.iloc[-1] >= amt.FLAT:
            out[d] = g
    return out


def verdict(h: dict) -> str:
    if h["ev"] <= 0:
        return "FAIL"
    if h["trades"]["mean_r_ci"][0] > 0 and h["controls"]["random"]["p"] < ALPHA:
        return "PASS"
    return "STRUCTURE-ONLY"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "confirm.lock"
    if lock.exists():
        print(f"already scored ({lock.read_text().strip()}); refusing a second look")
        return 1
    src = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    sessions = load_sessions()
    days = sorted(sessions)
    lock.write_text(f"{CELL} {REGIME}={SIDE} script={src} at {pd.Timestamp.now(tz='UTC').isoformat()}\n")

    plan = resolve_plan("flex", "50k", False)
    rows = amt.build_rows(sessions, SYMBOL)[CELL]
    labels = reg.regimes(sessions, SYMBOL)[REGIME]
    sub = reg.subset(rows, labels, SIDE)
    h = amt.score(sub, plan, True)
    if not h["trades"]["trades"]:
        print("no trades")
        return 1
    h["verdict"] = verdict(h)
    other = reg.summary(reg.subset(rows, labels, "range"), plan, False)
    taken = {d: (r["long"] if r["dir"] > 0 else r["short"]) for d, r in sub.items() if r is not None}
    by_year = {}
    for d, t in taken.items():
        by_year.setdefault(d.year, []).append(t["r"])
    by_year = {y: dict(n=len(v), mean_r=float(np.mean(v))) for y, v in sorted(by_year.items())}

    t, b, c = h["trades"], h["lucid"]["bootstrap"], h["controls"]
    print(f"{SYMBOL} -> MNQ  {days[0]} -> {days[-1]}, {len(days)} sessions ({sum(v == SIDE for v in labels.values())} {SIDE} days)")
    print(f"{CELL} on {REGIME} {SIDE} days (one look)")
    print(f"  trades {t['trades']}, win {t['win_rate']:.1%}, mean R {t['mean_r']:+.3f} [{t['mean_r_ci'][0]:+.3f}, {t['mean_r_ci'][1]:+.3f}], "
          f"exits {t['exits']}")
    print(f"  Lucid: pass {b['passRate']:.1%}, any payout {b['pPayout']:.1%}, EV ${h['ev']:+.1f} (fee $90) / ${h['ev_alt_fee']:+.1f} ($130); "
          f"historical-start EV ${h['lucid']['historical']['meanTake'] - amt.EVAL_FEE:+.1f}")
    print(f"  random direction: EV {c['random']['ev_mean']:+.1f} [{c['random']['ev_p05']:+.1f}, {c['random']['ev_p95']:+.1f}] p={c['random']['p']:.3f}; "
          f"R {c['random']['mean_r']:+.3f} p_R={c['random']['p_r']:.3f}; fade R {c['fade']['mean_r']:+.3f}")
    print(f"  same setup on range days (descriptive): {other['n']} trades, mean R {other['mean_r']:+.3f}")
    print("  by year: " + ", ".join(f"{y} {v['n']}t {v['mean_r']:+.2f}R" for y, v in by_year.items()))
    print(f"  VERDICT: {h['verdict']}")
    (OUT / "results.json").write_text(json.dumps(dict(cell=CELL, regime=REGIME, side=SIDE, script_sha=src, sessions=len(days),
                                                      result=h, range_days=other, by_year=by_year), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
