"""Lucid ORB: an opening-range breakout sized for a LucidFlex 50K account.

The Monte Carlo behind this (a coin-flip 1:1 strategy) found LucidFlex 50K pays a small positive EV per
evaluation when one trade a day risks ~$750 at win rates >= ~48% net of costs: the account fee is the only
real money at risk, and payouts average out to the drawdown a funded account consumes. That says nothing
about whether any entry rule reaches 48%. This study asks whether a plain opening-range breakout does,
and whether it does better than the same trades with a random direction.

Rules (fixed before any number was looked at):
  - data: Databento XNAS.ITCH QQQ ohlcv-1m, RTH 09:30-15:59 ET, research sessions only (holdout.py:
    sessions before VERIFY_START minus the GAP_SESSIONS gap week; bars are read with ts_event <
    VERIFY_START and the verify block is never loaded). Sessions with < 380 RTH bars (half days, gaps)
    are dropped. Prices are put on the NQ plane with the app's QQQ->NQ ratio (prop/contracts.js
    DEFAULT_RATIO = 41.2); that ignores basis and rolls, as the app's prop mode does.
  - opening range: high/low of the 1m bars in the first N minutes, N in ORB_MINUTES.
  - signal: the first 5m bar (09:30-anchored) after the range whose CLOSE is beyond the range, and that
    closes by 11:30 ET. Close above -> long, below -> short. One trade per session.
  - entry: the open of the next 1m bar (= the next 5m bar's open), + 1 tick adverse slippage.
  - bracket: stop and target both STOP_PCT% of the entry price away (1:1), rounded to the tick. Managed
    on 1m bars from the entry bar. A bar that opens through a level fills at its open (stop: +1 tick
    slippage). A bar that touches both fills the stop. The target fills only when price trades a tick
    THROUGH it (a touch may not fill a resting limit). Otherwise flat at the 15:54 bar's close - 1 tick.
  - size: MNQ ($2/pt), contracts = floor(RISK_USD / (stop_pts * 2)), clamped to [1, 40] (40 MNQ = the
    plan's 4-mini limit). Commission $1.00 per contract per side (Lucid's MNQ all-in is ~$0.50-1.00).
  - account: LucidFlex 50K without the daily loss limit, rule values from the exported fixtures
    (flybrain/fixtures/lucid_plans.json, checked against frontend/lib/backtest/prop/account.js), replayed
    by flybrain.prop.run_prop. One replay "bar" per session: open = 0, low/high = the trade's worst/best
    equity, close = its net P&L. Expected value per evaluation = 90% of payouts - fee (EVAL_FEE; $130
    also reported, the third-party list price). Bootstrap: BOOT_PATHS accounts on 5-session blocks,
    250-session horizon.
  - split: research sessions -> first DISCOVERY_FRAC discovery, the rest holdout. Of the
    len(ORB_MINUTES) x len(STOP_PCT) cells, the one with the highest discovery bootstrap EV is selected
    and scored ONCE on holdout (run with --holdout; without it nothing from the holdout is computed).
  - controls for the selected cell, on both splits:
      fade     the same entries with the direction reversed
      random   N_RANDOM seeds: same entry times and brackets, direction a fair coin.
               p = (1 + #seeds with EV >= cell EV) / (1 + N_RANDOM), all at CONTROL_PATHS paths
  - verdict (holdout, $90 fee):
      PASS            EV > 0, net mean R per trade > 0 with its 95% block-bootstrap CI above 0, and
                      random p < 0.05: the entry adds something on top of the account structure.
      STRUCTURE-ONLY  EV > 0 but the entry does not beat random direction (p >= 0.05): any profit is
                      the firm's payout asymmetry, not the signal.
      FAIL            EV <= 0.

Specification: everything above was written down before the first run and not changed after it.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from holdout import VERIFY_START, research_sessions  # noqa: E402
from flybrain.prop import resolve_plan, run_prop  # noqa: E402

ET = "America/New_York"
DATA = HERE / "data"
OUT = DATA / "lucid_orb"
BARS_DIR = DATA / "databento" / "eq-ohlcv-1m"

RATIO = 41.2
TICK = 0.25
POINT_VALUE = 2.0          # MNQ
COMMISSION_SIDE = 1.00     # per contract per side
MAX_CONTRACTS = 40
RISK_USD = 750.0

OPEN, LAST_SIGNAL, FLAT = 570, 690, 954   # 09:30, 11:30, 15:54 (minutes after midnight ET)
MIN_BARS = 380
ORB_MINUTES = (5, 15, 30)
STOP_PCT = (0.20, 0.35, 0.50)
DISCOVERY_FRAC = 0.7
EVAL_FEE = 90.0
ALT_FEE = 130.0
BOOT_PATHS = 5000
CONTROL_PATHS = 2000
N_RANDOM = 200
N_BOOT = 2000
BOOT_BLOCK = 5
SEED = 42


# ---------------------------------------------------------------- data

def load_sessions() -> dict[date, pd.DataFrame]:
    cutoff = VERIFY_START.tz_convert("UTC")
    files = [f for f in sorted((BARS_DIR / "QQQ").glob("*.parquet")) if date.fromisoformat(f.name[:10]) < VERIFY_START.date()]
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close"], filters=[("ts_event", "<", cutoff)])
                      for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    assert (bars.index < cutoff).all(), "LEAK: bar read reaches the verify block"
    et = bars.index.tz_convert(ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= OPEN) & (bars.minute < 960)]
    keep = set(research_sessions(sorted(set(bars.day))))
    out = {}
    for d, g in bars.groupby("day", sort=True):
        if d in keep and len(g) >= MIN_BARS and g.minute.iloc[0] == OPEN and g.minute.iloc[-1] >= FLAT:
            out[d] = g
    return out


# ---------------------------------------------------------------- one session

def signal(g: pd.DataFrame, orb: int):
    """(direction, index of the entry 1m bar) or None."""
    m = g.minute.to_numpy()
    in_range = m < OPEN + orb
    hi, lo = g.high.to_numpy()[in_range].max(), g.low.to_numpy()[in_range].min()
    bucket = (m - OPEN) // 5
    closes = g.close.groupby(bucket).last()
    for b, c in closes.items():
        start = OPEN + 5 * b
        if start < OPEN + orb:
            continue
        if start + 5 > LAST_SIGNAL:
            return None
        d = 1 if c > hi else -1 if c < lo else 0
        if d:
            j = int(np.searchsorted(m, start + 5))
            return (d, j) if j < len(m) and m[j] < FLAT else None
    return None


def trade(g: pd.DataFrame, d: int, j: int, stop_pct: float) -> dict:
    """Net P&L and the worst / best equity of one bracket trade, in dollars."""
    O, H, L, C = (g[k].to_numpy() * RATIO for k in ("open", "high", "low", "close"))
    m = g.minute.to_numpy()
    entry = O[j] + d * TICK
    stop_pts = max(TICK, round(entry * stop_pct / 100 / TICK) * TICK)
    stop, target = entry - d * stop_pts, entry + d * stop_pts
    n = int(min(MAX_CONTRACTS, max(1, math.floor(RISK_USD / (stop_pts * POINT_VALUE)))))
    worst = best = 0.0
    exit_px, reason = None, "time"
    for i in range(j, len(m)):
        adv, fav = (L[i], H[i]) if d > 0 else (H[i], L[i])
        if i > j and (O[i] - stop) * d <= 0:
            exit_px, reason = O[i] - d * TICK, "stop"
        elif (adv - stop) * d <= 0:
            exit_px, reason = stop - d * TICK, "stop"
        elif i > j and (O[i] - target) * d >= 0:
            exit_px, reason = O[i], "target"
        elif (fav - target) * d >= TICK:
            exit_px, reason = target, "target"
        if exit_px is not None:
            worst = min(worst, (exit_px - entry) * d if reason == "stop" else (adv - entry) * d)
            best = max(best, (exit_px - entry) * d if reason == "target" else 0.0)
            break
        worst = min(worst, (adv - entry) * d)
        best = max(best, (fav - entry) * d)
        if m[i] >= FLAT:
            exit_px = C[i] - d * TICK
            break
    fees = 2 * COMMISSION_SIDE * n
    pts = (exit_px - entry) * d
    pnl = pts * POINT_VALUE * n - fees
    return dict(pnl=pnl, lo=min(0.0, worst * POINT_VALUE * n - fees, pnl), hi=max(0.0, best * POINT_VALUE * n, pnl),
                r=pnl / (stop_pts * POINT_VALUE * n), reason=reason, contracts=n, win=pnl > 0)


def build_cells(sessions: dict) -> dict:
    """Per cell, per session: the signal and both directions' trades (the controls need the flip)."""
    cells = {}
    for orb in ORB_MINUTES:
        sig = {d: signal(g, orb) for d, g in sessions.items()}
        for sp in STOP_PCT:
            rows = {}
            for d, g in sessions.items():
                s = sig[d]
                rows[d] = None if s is None else dict(dir=s[0], long=trade(g, 1, s[1], sp), short=trade(g, -1, s[1], sp))
            cells[(orb, sp)] = rows
    return cells


# ---------------------------------------------------------------- scoring

FLAT_DAY = dict(pnl=0.0, lo=0.0, hi=0.0)


def day_trades(rows: dict, days: list[date], dirs: dict | None = None) -> list[dict]:
    """The trade taken each session (flat days included). `dirs` overrides the direction."""
    out = []
    for d in days:
        r = rows[d]
        if r is None:
            out.append(FLAT_DAY)
            continue
        side = (dirs or {}).get(d, r["dir"])
        out.append(r["long"] if side > 0 else r["short"])
    return out


def replay(trades: list[dict], days: list[date], plan: dict, paths: int, history: bool) -> dict:
    pnl = np.array([t["pnl"] for t in trades])
    base = plan["startBalance"] + np.r_[0.0, np.cumsum(pnl)[:-1]]
    t = np.array([pd.Timestamp(d).tz_localize("UTC").timestamp() + 15 * 3600 for d in days])
    result = dict(equity=(base + pnl).tolist(), barLo=(base + [x["lo"] for x in trades]).tolist(),
                  barHi=(base + [x["hi"] for x in trades]).tolist(), barOpen=base.tolist(), time=t.tolist(),
                  initialCapital=plan["startBalance"])
    res = run_prop(result, plan=plan, paths=paths, block_size=BOOT_BLOCK, horizon=250, seed=SEED,
                   keep_attempts=False, replay_history=history)
    keys = ("passRate", "pPayout", "meanPayouts", "meanTake", "ev", "evP50", "medianDaysToPass", "meanDaysUsed", "outcomes")
    pick = lambda s: None if s is None else {k: s[k] for k in keys}
    return dict(bootstrap=pick(res["bootstrap"]), historical=pick(res["historical"]))


def ev(rep: dict, fee: float) -> float:
    return rep["bootstrap"]["meanTake"] - fee


def trade_stats(trades: list[dict]) -> dict:
    taken = [t for t in trades if "r" in t]
    r = np.array([t["r"] for t in taken])
    rng = np.random.default_rng(SEED)
    n, b = len(r), min(BOOT_BLOCK, len(r))
    starts = rng.integers(0, n - b + 1, (N_BOOT, math.ceil(n / b)))
    idx = (starts[:, :, None] + np.arange(b)).reshape(N_BOOT, -1)[:, :n]
    means = r[idx].mean(1)
    reasons = pd.Series([t["reason"] for t in taken]).value_counts(normalize=True).round(3).to_dict()
    return dict(trades=n, win_rate=float(np.mean([t["win"] for t in taken])), mean_r=float(r.mean()),
                mean_r_ci=[float(np.quantile(means, .025)), float(np.quantile(means, .975))],
                mean_pnl=float(np.mean([t["pnl"] for t in taken])), exits=reasons,
                median_contracts=float(np.median([t["contracts"] for t in taken])))


def controls(rows: dict, days: list[date], plan: dict, cell_ev: float) -> dict:
    fade = {d: -rows[d]["dir"] for d in days if rows[d] is not None}
    fade_trades = day_trades(rows, days, fade)
    rng = np.random.default_rng(SEED + 1)
    evs = []
    for _ in range(N_RANDOM):
        dirs = {d: int(rng.choice((-1, 1))) for d in days if rows[d] is not None}
        evs.append(ev(replay(day_trades(rows, days, dirs), days, plan, CONTROL_PATHS, False), EVAL_FEE))
    evs = np.array(evs)
    return dict(fade=dict(trades=trade_stats(fade_trades), ev=ev(replay(fade_trades, days, plan, BOOT_PATHS, False), EVAL_FEE)),
                random=dict(ev_mean=float(evs.mean()), ev_p05=float(np.quantile(evs, .05)), ev_p95=float(np.quantile(evs, .95)),
                            p=float((1 + (evs >= cell_ev).sum()) / (1 + N_RANDOM))))


def score_split(rows: dict, days: list[date], plan: dict, with_controls: bool) -> dict:
    trades = day_trades(rows, days)
    rep = replay(trades, days, plan, BOOT_PATHS, True)
    out = dict(sessions=len(days), first=str(days[0]), last=str(days[-1]), trades=trade_stats(trades), lucid=rep,
               ev=ev(rep, EVAL_FEE), ev_alt_fee=ev(rep, ALT_FEE))
    if with_controls:
        same_paths = ev(replay(trades, days, plan, CONTROL_PATHS, False), EVAL_FEE)
        out["controls"] = controls(rows, days, plan, same_paths)
        out["ev_at_control_paths"] = same_paths
    return out


def verdict(h: dict) -> str:
    if h["ev"] <= 0:
        return "FAIL"
    if h["trades"]["mean_r_ci"][0] > 0 and h["controls"]["random"]["p"] < 0.05:
        return "PASS"
    return "STRUCTURE-ONLY"


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--holdout", action="store_true", help="score the selected cell on the holdout (one look)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "holdout.lock"
    if args.holdout and lock.exists():
        print(f"holdout already scored ({lock.read_text().strip()}); refusing a second look")
        return 1

    plan = resolve_plan("flex", "50k", False)
    sessions = load_sessions()
    days = sorted(sessions)
    cut = int(len(days) * DISCOVERY_FRAC)
    disc, hold = days[:cut], days[cut:]
    print(f"{len(days)} research sessions {days[0]} -> {days[-1]}; discovery {len(disc)} ({disc[0]} -> {disc[-1]}), "
          f"holdout {len(hold)} ({hold[0]} -> {hold[-1]})")
    cells = build_cells(sessions)

    grid = []
    print(f"\nDISCOVERY  (EV = 90% payouts - ${EVAL_FEE:.0f}; {BOOT_PATHS} bootstrap accounts)")
    print(f"{'orb':>4} {'stop%':>6} | {'trades':>6} {'win':>6} {'meanR':>7} {'R 95% CI':>16} | {'pass':>6} {'payout':>6} {'EV':>8}")
    for key, rows in cells.items():
        s = score_split(rows, disc, plan, False)
        grid.append(dict(orb=key[0], stop_pct=key[1], **s))
        t, b = s["trades"], s["lucid"]["bootstrap"]
        print(f"{key[0]:>4} {key[1]:>6.2f} | {t['trades']:>6} {t['win_rate']:6.1%} {t['mean_r']:+7.3f} "
              f"[{t['mean_r_ci'][0]:+.3f},{t['mean_r_ci'][1]:+.3f}] | {b['passRate']:6.1%} {b['pPayout']:6.1%} {s['ev']:+8.1f}")
    best = max(grid, key=lambda g: g["ev"])
    sel = (best["orb"], best["stop_pct"])
    print(f"\nselected: ORB {sel[0]}m, stop {sel[1]}% (discovery EV {best['ev']:+.1f})")
    disc_ctl = score_split(cells[sel], disc, plan, True)
    c = disc_ctl["controls"]
    print(f"discovery controls: fade EV {c['fade']['ev']:+.1f}, random-direction EV {c['random']['ev_mean']:+.1f} "
          f"[{c['random']['ev_p05']:+.1f}, {c['random']['ev_p95']:+.1f}], p = {c['random']['p']:.3f}")

    res = dict(spec=dict(ratio=RATIO, risk_usd=RISK_USD, commission_side=COMMISSION_SIDE, fee=EVAL_FEE, plan=plan),
               discovery=dict(grid=grid, selected=dict(orb=sel[0], stop_pct=sel[1]), selected_with_controls=disc_ctl))
    if args.holdout:
        lock.write_text(f"orb={sel[0]} stop_pct={sel[1]} at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
        h = score_split(cells[sel], hold, plan, True)
        h["verdict"] = verdict(h)
        res["holdout"] = h
        t, b, c = h["trades"], h["lucid"]["bootstrap"], h["controls"]
        print(f"\nHOLDOUT (one look)  {h['first']} -> {h['last']}")
        print(f"  trades {t['trades']}, win {t['win_rate']:.1%}, mean R {t['mean_r']:+.3f} "
              f"[{t['mean_r_ci'][0]:+.3f}, {t['mean_r_ci'][1]:+.3f}], exits {t['exits']}")
        print(f"  Lucid: pass {b['passRate']:.1%}, any payout {b['pPayout']:.1%}, EV ${h['ev']:+.1f} (fee $90) / "
              f"${h['ev_alt_fee']:+.1f} (fee $130); historical-start EV ${h['lucid']['historical']['meanTake'] - EVAL_FEE:+.1f}")
        print(f"  fade EV {c['fade']['ev']:+.1f}; random direction EV {c['random']['ev_mean']:+.1f} "
              f"[{c['random']['ev_p05']:+.1f}, {c['random']['ev_p95']:+.1f}], p = {c['random']['p']:.3f}")
        print(f"  VERDICT: {h['verdict']}")
    (OUT / ("results.json" if args.holdout else "discovery.json")).write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
