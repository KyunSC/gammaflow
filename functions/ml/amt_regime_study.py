"""AMT regime filter: run each amt_lucid_study setup only in the market state it is built for.

Auction Market Theory says a market is either in balance (rotating inside an accepted range: fade the
edges) or in imbalance (value migrating, range breaking: go with it). amt_lucid_study.py traded every
setup on every day. This study keeps the same setups, cells, execution and Lucid replay, and switches each
setup off on days whose regime does not suit it:
    continuation  ov_accept                 -> trades only on BREAKOUT days
    responsive    va_reentry, va_fail       -> trades only on RANGE days
The opposite subset (the wrong regime) is scored too: a regime filter that works should make the in-regime
subset better than the out-of-regime one, on both instruments.

Regimes (known before the 09:30 open; each splits the days that have enough history into two sides):
    overlap   RANGE if the prior session's value area overlaps the value area of the session before it,
              BREAKOUT if it does not (value migrated).
    er        5-session efficiency ratio of RTH closes, |C[-1] - C[-6]| / sum |C[i] - C[i-1]|. BREAKOUT if
              above its trailing 100-session median (that median excludes the day), RANGE if at or below.
    bracket   the 5-session composite range (high / low of the prior 5 RTH sessions). BREAKOUT if the
              09:30 open is outside it, RANGE if inside.

Data: discovery only (QQQ + SPY <= 2025-03-26), which amt_lucid_study.py has already looked at. These
numbers are exploration, not a test.

Holdout candidate rule (fixed before the first run): among (cell, regime) pairs in the setup's own regime,
eligible if >= MIN_TRADES trades on each instrument, mean net R > 0 on both, and in-regime mean R above
out-of-regime mean R on both; the one with the highest pooled mean R. --holdout scores it once on SPY
2025-03-27 -> 2026-08-14 and shares amt_lucid_study's lock, so the SPY window can be spent only once across
both scripts. The verdict follows amt_lucid_study (alpha 0.05 / 3).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

import numpy as np
import pandas as pd

import amt_lucid_study as amt
from flybrain.prop import resolve_plan

ER_N, ER_MEDIAN_N, BRACKET_N = 5, 100, 5
MIN_TRADES = 30
REGIMES = ("overlap", "er", "bracket")
WANTS = {"ov_accept": "breakout", "va_reentry": "range", "va_fail": "range"}


def regimes(sessions: dict, symbol: str) -> dict[str, dict[date, str]]:
    """{regime: {day: 'range' | 'breakout'}} for days that have the needed history."""
    ratio = amt.INSTRUMENTS[symbol]["ratio"]
    days = sorted(sessions)
    va = {d: amt.profile(sessions[d], ratio) for d in days}
    close = np.array([sessions[d].close.iloc[-1] for d in days])
    hi = np.array([sessions[d].high.max() for d in days]) * ratio
    lo = np.array([sessions[d].low.min() for d in days]) * ratio
    opn = np.array([sessions[d].open.iloc[0] for d in days]) * ratio
    out = {k: {} for k in REGIMES}
    er = np.full(len(days), np.nan)
    for i in range(ER_N + 1, len(days)):
        c = close[i - ER_N - 1:i]
        er[i] = abs(c[-1] - c[0]) / max(np.abs(np.diff(c)).sum(), 1e-12)
    for i, d in enumerate(days):
        if i >= 2:
            a, b = va[days[i - 1]], va[days[i - 2]]
            out["overlap"][d] = "range" if a["val"] <= b["vah"] and b["val"] <= a["vah"] else "breakout"
        prior = er[max(0, i - ER_MEDIAN_N):i]
        prior = prior[~np.isnan(prior)]
        if not np.isnan(er[i]) and len(prior) >= ER_MEDIAN_N // 2:
            out["er"][d] = "breakout" if er[i] > np.median(prior) else "range"
        if i >= BRACKET_N:
            h, l = hi[i - BRACKET_N:i].max(), lo[i - BRACKET_N:i].min()
            out["bracket"][d] = "range" if l <= opn[i] <= h else "breakout"
    return out


def subset(rows: dict, labels: dict, side: str) -> dict:
    """Same days (flat outside the regime), so the Lucid replay sees the idle days too."""
    return {d: (r if labels.get(d) == side else None) for d, r in rows.items() if d in labels}


def summary(rows: dict, plan: dict, lucid: bool) -> dict:
    r = amt.net_r(rows)
    out = dict(n=len(r), mean_r=float(r.mean()) if len(r) else float("nan"),
               win=float((r > 0).mean()) if len(r) else float("nan"))
    if lucid and len(r):
        s = amt.score(rows, plan, False)
        out.update(ci=s["trades"]["mean_r_ci"], ev=s["ev"], pass_rate=s["lucid"]["bootstrap"]["passRate"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--holdout", action="store_true", help="score the candidate on the SPY holdout (one look, shared lock)")
    args = ap.parse_args()
    amt.OUT.mkdir(parents=True, exist_ok=True)
    lock = amt.OUT / "holdout.lock"
    if args.holdout and lock.exists():
        print(f"AMT holdout already scored ({lock.read_text().strip()}); refusing a second look")
        return 1
    plan = resolve_plan("flex", "50k", False)

    res, rows_by, regs_by = {}, {}, {}
    for sym in amt.INSTRUMENTS:
        sessions = amt.load_sessions(sym, amt.DISCOVERY_END)
        rows_by[sym], regs_by[sym] = amt.build_rows(sessions, sym), regimes(sessions, sym)
        share = {k: f"{np.mean([v == 'breakout' for v in lab.values()]):.0%}" for k, lab in regs_by[sym].items()}
        print(f"{sym}: breakout share of days {share}")

    print(f"\n{'cell':<34} {'regime':<8} | " + " | ".join(f"{s}: {'in n':>4} {'inR':>7} {'outR':>7} {'allR':>7} {'inEV':>7}"
                                                     for s in amt.INSTRUMENTS))
    cands = []
    for setup, ps in amt.GRID.items():
        want = WANTS[setup]
        other = "range" if want == "breakout" else "breakout"
        for p in ps:
            name = amt.cell_name(setup, p)
            for reg in REGIMES:
                line, per = [], {}
                for sym in amt.INSTRUMENTS:
                    rows, lab = rows_by[sym][name], regs_by[sym][reg]
                    i = summary(subset(rows, lab, want), plan, True)
                    o = summary(subset(rows, lab, other), plan, False)
                    a = summary({d: r for d, r in rows.items() if d in lab}, plan, False)
                    per[sym] = dict(inside=i, outside=o, all=a)
                    line.append(f"{sym}: {i['n']:>4} {i['mean_r']:+7.3f} {o['mean_r']:+7.3f} {a['mean_r']:+7.3f} {i.get('ev', float('nan')):+7.1f}")
                print(f"{name:<34} {reg:<8} | " + " | ".join(line))
                res.setdefault(name, {})[reg] = per
                ok = all(per[s]["inside"]["n"] >= MIN_TRADES and per[s]["inside"]["mean_r"] > 0
                         and per[s]["inside"]["mean_r"] > per[s]["outside"]["mean_r"] for s in amt.INSTRUMENTS)
                if ok:
                    pooled = np.concatenate([amt.net_r(subset(rows_by[s][name], regs_by[s][reg], want)) for s in amt.INSTRUMENTS])
                    cands.append(dict(cell=name, regime=reg, side=want, pooled_mean_r=float(pooled.mean())))
        print()

    cands.sort(key=lambda c: -c["pooled_mean_r"])
    print("ELIGIBLE (>= %d trades, R > 0 on both, in-regime beats out-of-regime on both):" % MIN_TRADES)
    for c in cands:
        print(f"  {c['cell']:<34} {c['regime']:<8} pooled R {c['pooled_mean_r']:+.3f}")
    if not cands:
        print("  none")
    out = dict(discovery=res, eligible=cands)

    if cands:
        best = cands[0]
        for sym in amt.INSTRUMENTS:
            sub = subset(rows_by[sym][best["cell"]], regs_by[sym][best["regime"]], best["side"])
            ctl = amt.score(sub, plan, True)["controls"]["random"]
            print(f"  candidate {sym} random-direction: EV p={ctl['p']:.3f}, R {ctl['mean_r']:+.3f} p_R={ctl['p_r']:.3f}")
            out.setdefault("candidate_controls", {})[sym] = ctl

    if args.holdout and cands:
        best = cands[0]
        lock.write_text(f"{best['cell']} regime={best['regime']} (amt_regime_study) at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
        sessions = amt.load_sessions(amt.HOLDOUT_SYMBOL, amt.VERIFY_START.date())
        days = sorted(sessions)
        first = next(i for i, d in enumerate(days) if d > amt.DISCOVERY_END)
        warm = max(ER_N + 1 + ER_MEDIAN_N, BRACKET_N, 2)
        sessions = {d: sessions[d] for d in days[first - warm:]}   # history for the regime labels only
        rows = amt.build_rows(sessions, amt.HOLDOUT_SYMBOL)[best["cell"]]
        lab = {d: v for d, v in regimes(sessions, amt.HOLDOUT_SYMBOL)[best["regime"]].items() if d > amt.DISCOVERY_END}
        h = amt.score(subset(rows, lab, best["side"]), plan, True)
        h["verdict"] = amt.verdict(h) if h["trades"]["trades"] else "FAIL"
        out["holdout"] = dict(candidate=best, **h)
        print(f"\nHOLDOUT (one look) {best['cell']} on {best['side']} days by {best['regime']}: {amt.fmt(h)}")
        print(f"  VERDICT: {h['verdict']}")
    (amt.OUT / ("regime_results.json" if args.holdout else "regime_discovery.json")).write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
