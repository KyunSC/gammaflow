"""Intraday momentum on short-gamma days only (H2), sized for a LucidFlex 50K account.

Hypothesis (stated before any H2 number was computed; H1 = intraday_momentum_study.py had already shown the
UNCONDITIONAL effect is ~0 gross in discovery). Baltussen, Da, Lammers & Martens (2021, JFE) attribute market
intraday momentum to dealers' gamma hedging: when dealers are net SHORT gamma they must buy into rallies and
sell into declines, most of it near the close, which pushes the last half-hour in the day's direction; when
they are long gamma the hedging leans against the move. The prediction is conditional: momentum on
short-gamma days, none (or reversal) on long-gamma days, which could net to ~0 unconditionally.

Rules (fixed before any number was looked at). Everything is H1's (data, prev_close, signals `first` / `day`,
entry at the 15:30 bar's open + 1 tick, 1:1 tick-through bracket, measured stop slippage, flat at the 15:59
close - 1 tick, RISK_USD 1050, $0.50/side, LucidFlex 50K with DLL at $90.20, 5000 bootstrap accounts), except:
  - filter: trade only when dealers are net short gamma at the decision: gex_regime < 0 in the GEX snapshot
    stamped 15:25 ET (thetadata_gex.py via data/gex_vol/frame_{sym}.parquet; OI = prior close, quotes and
    spot as of 15:25, so known before the 15:30 entry). No 15:25 snapshot -> no trade. k = 0 (no magnitude
    filter): the gamma sign is the one condition.
  - grid: 2 signals x 2 STOP_PCT {0.20, 0.35} = 4 cells.
  - diagnostic, pre-declared and NOT selectable: the same cells on long-gamma days (gex_regime >= 0), where
    the mechanism predicts mean R <= 0.
  - split, selection, controls, verdict: as H1. Discovery 2022-01-03 .. 2025-03-26 on SPY and QQQ; a cell is
    eligible if its discovery mean net R > 0 on BOTH; the eligible cell with the highest SPY discovery EV is
    selected; no eligible cell -> no holdout. Holdout = SPY 2025-03-27 .. 2026-08-14, one look (--holdout,
    lock file data/intraday_momentum/holdout_gamma.lock). PASS: EV > 0, mean net R 95% block CI > 0, and
    random-direction p < 0.05 (EV, 200 seeds). STRUCTURE-ONLY: EV > 0 otherwise. FAIL: EV <= 0.
  - power (stated up front): ~45% of sessions are short-gamma, so the holdout has ~150 trades. With an R sd
    of ~0.6-0.8 (H1) the 95% CI half-width is ~0.10-0.13R and 80% power needs a true mean of ~0.14-0.18R.
    Only a large conditional effect can pass.

Specification: everything above was written down before the first run and is not changed after it.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import intraday_momentum_study as h1  # noqa: E402
from flybrain.prop import resolve_plan  # noqa: E402
from holdout import VERIFY_START  # noqa: E402

GEX = h1.DATA / "gex_vol"
STOP_PCT = (0.20, 0.35)
SIGNALS = ("first", "day")


def gamma_by_day(symbol: str) -> dict:
    f = pd.read_parquet(GEX / f"frame_{symbol.lower()}.parquet", columns=["date", "gex_regime"])
    t = pd.to_datetime(f["date"], utc=True).dt.tz_convert(h1.ET)
    f = f.assign(day=t.dt.date, minute=t.dt.hour * 60 + t.dt.minute)
    snap = f[f.minute == 15 * 60 + 25]
    return dict(zip(snap.day, snap.gex_regime))


def cells_for(symbol: str, last_day) -> tuple[list, dict]:
    sessions, prev = h1.load(symbol, last_day)
    base = h1.build_cells(symbol, sessions, prev)
    g = gamma_by_day(symbol)
    out = {}
    for s in SIGNALS:
        for sp in STOP_PCT:
            rows = base[(s, 0, sp)]
            for side, keep in (("short", lambda x: x < 0), ("long", lambda x: x >= 0)):
                out[(s, sp, side)] = {d: (r if r is not None and d in g and keep(g[d]) else None) for d, r in rows.items()}
    return sorted(sessions), out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--holdout", action="store_true", help="score the selected cell on the SPY holdout (one look)")
    args = ap.parse_args()
    h1.OUT.mkdir(parents=True, exist_ok=True)
    lock = h1.OUT / "holdout_gamma.lock"
    if args.holdout and lock.exists():
        print(f"holdout already scored ({lock.read_text().strip()}); refusing a second look")
        return 1
    plan = resolve_plan("flex", "50k", True)
    disc = {sym: cells_for(sym, h1.DISCOVERY_END) for sym in h1.INSTR}

    print(f"DISCOVERY {disc['SPY'][0][0]} -> {disc['SPY'][0][-1]} (EV = 90% payouts - ${h1.EVAL_FEE:.2f}, LucidFlex 50K with DLL)")
    print(f"{'gamma':>6} {'sym':>4} {'signal':>6} {'stop%':>6} | {'trades':>6} {'win':>6} {'meanR':>7} {'R 95% CI':>17} {'sdR':>5} | "
          f"{'pass':>6} {'paid':>6} {'EV':>8}")
    grid = []
    for side in ("short", "long"):
        for s in SIGNALS:
            for sp in STOP_PCT:
                row = dict(gamma=side, signal=s, stop_pct=sp)
                for sym in h1.INSTR:
                    days, cells = disc[sym]
                    sc = h1.score_split(cells[(s, sp, side)], days, plan, False)
                    row[sym] = sc
                    t, b = sc["trades"], sc["lucid"]["bootstrap"]
                    print(f"{side:>6} {sym:>4} {s:>6} {sp:>6.2f} | {t['trades']:>6} {t['win_rate']:6.1%} {t['mean_r']:+7.3f} "
                          f"[{t['mean_r_ci'][0]:+.3f},{t['mean_r_ci'][1]:+.3f}] {t['sd_r']:5.2f} | {b['passRate']:6.1%} "
                          f"{b['pPayout']:6.1%} {sc['ev']:+8.1f}")
                row["eligible"] = side == "short" and row["SPY"]["trades"]["mean_r"] > 0 and row["QQQ"]["trades"]["mean_r"] > 0
                grid.append(row)
        print()
    res = dict(spec=dict(filter="gex_regime<0 at 15:25 ET", risk_usd=h1.RISK_USD, fee=h1.EVAL_FEE), discovery=dict(grid=grid))
    eligible = [g for g in grid if g["eligible"]]
    if not eligible:
        print("no short-gamma cell has discovery mean R > 0 on both SPY and QQQ: nothing goes to the holdout")
        res["discovery"]["selected"] = None
        (h1.OUT / "discovery_gamma.json").write_text(json.dumps(res, indent=1, default=str))
        return 0
    best = max(eligible, key=lambda g: g["SPY"]["ev"])
    sel = (best["signal"], best["stop_pct"], "short")
    print(f"selected: signal={sel[0]} stop={sel[1]}% on short-gamma days (SPY EV {best['SPY']['ev']:+.1f}, QQQ {best['QQQ']['ev']:+.1f}; "
          f"{len(eligible)}/4 eligible)")
    ctl = {}
    for sym in h1.INSTR:
        days, cells = disc[sym]
        c = h1.score_split(cells[sel], days, plan, True)
        ctl[sym] = c
        cc = c["controls"]
        print(f"  {sym} discovery controls: fade EV {cc['fade']['ev']:+.1f} (R {cc['fade']['trades']['mean_r']:+.3f}), always-long EV "
              f"{cc['always_long']['ev']:+.1f} (R {cc['always_long']['trades']['mean_r']:+.3f}), random EV {cc['random']['ev_mean']:+.1f} "
              f"[{cc['random']['ev_p05']:+.1f},{cc['random']['ev_p95']:+.1f}] p={cc['random']['p']:.3f}, mean-R p={cc['random']['p_r']:.3f}")
    sd = ctl["SPY"]["trades"]["sd_r"]
    rate = ctl["SPY"]["trades"]["trades"] / len(disc["SPY"][0])
    pw = h1.power(sd, int(round(rate * 340)))
    print(f"  power on the SPY holdout (~340 sessions x {rate:.2f} trades/session, sd {sd:.2f}R): 95% CI half-width "
          f"{pw['ci_half_width']:.3f}R, 80%-power MDE {pw['mde_80']:.3f}R")
    res["discovery"].update(selected=dict(signal=sel[0], stop_pct=sel[1], gamma="short"), selected_with_controls=ctl, holdout_power=pw)

    if args.holdout:
        lock.write_text(f"signal={sel[0]} stop_pct={sel[1]} gamma=short at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
        days, cells = cells_for("SPY", VERIFY_START.date() - timedelta(days=1))
        days = [d for d in days if d >= h1.HOLDOUT_START]
        h = h1.score_split(cells[sel], days, plan, True)
        h["verdict"] = h1.verdict(h)
        res["holdout"] = h
        t, b, c = h["trades"], h["lucid"]["bootstrap"], h["controls"]
        print(f"\nHOLDOUT (one look, SPY)  {h['first']} -> {h['last']}")
        print(f"  trades {t['trades']}, win {t['win_rate']:.1%}, mean R {t['mean_r']:+.3f} [{t['mean_r_ci'][0]:+.3f}, "
              f"{t['mean_r_ci'][1]:+.3f}], exits {t['exits']}")
        print(f"  Lucid: pass {b['passRate']:.1%}, paid {b['pPayout']:.1%}, EV ${h['ev']:+.1f}")
        print(f"  fade EV {c['fade']['ev']:+.1f}; always-long EV {c['always_long']['ev']:+.1f}; random EV {c['random']['ev_mean']:+.1f} "
              f"p = {c['random']['p']:.3f} (mean-R p {c['random']['p_r']:.3f})")
        print(f"  VERDICT: {h['verdict']}")
    (h1.OUT / ("results_gamma.json" if args.holdout else "discovery_gamma.json")).write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
