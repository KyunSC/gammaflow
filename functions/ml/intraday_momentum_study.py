"""Intraday momentum into the close, sized for a LucidFlex 50K account.

Hypothesis (stated before any number was computed). Index returns in the last half-hour continue the
day's move: Gao, Han, Li & Zhou (2018, "Market intraday momentum", JFE) find the first half-hour return
(previous close -> 10:00) predicts the last half-hour (15:30 -> 16:00) on SPY; Baltussen, Da, Lammers &
Martens (2021, "Hedging demand and market intraday momentum", JFE) find the return up to 15:30 does, across
~60 futures, and tie it to flows that are mechanical, not informational: leveraged/inverse ETFs must buy
(sell) in proportion to the day's return near the close, and dealers short gamma hedge in the direction of
the move. Both flows scale with the size of the day's move, so a larger move should predict better.

Structure (lucid_structure.py, no market data): on LucidFlex 50K a zero-edge 1:1 trader earns most per
account when one win nets just over 1/3 of the $3,000 target (risk ~$1,050). This study keeps that risk.

Rules (fixed before any number was looked at):
  - data: Databento XNAS.ITCH ohlcv-1m, SPY (-> MES, ratio 10.05, $5/pt) and QQQ (-> MNQ, ratio 41.2,
    $2/pt), RTH 09:30-15:59 ET. Research sessions only (holdout.research_sessions; ts_event < VERIFY_START,
    the verify block is never loaded). Sessions with < 380 RTH bars are not traded. prev_close = the last
    RTH bar close of the previous trading day that has bars (a half day counts).
  - signals, using only bars that END by 15:30:
      first   log(close of the 09:59 bar / prev_close)      (Gao et al.)
      day     log(close of the 15:29 bar / prev_close)      (Baltussen et al.)
  - filter k: trade only when |signal| > k x sigma, sigma = std of the same signal over the previous 20
    traded sessions (not today); k in {0, 1}. k = 0 trades every session (once 20 prior sessions exist,
    so both k use the same eligible days).
  - direction: sign(signal). One trade per session.
  - entry: open of the 15:30 bar, + 1 tick adverse.
  - exits on 1m bars from the entry bar: 1:1 bracket, stop = target = STOP_PCT% of entry, rounded to the
    tick; STOP_PCT in {0.20, 0.35} (>= ~45 MES ticks / ~165 MNQ ticks, so commission is < 0.03R).
    The target fills only when a bar trades a tick THROUGH it (no slippage on the limit). The stop fills
    at stop - s ticks (a bar opening through it: at its open - s), s drawn from the measured NQ PMF
    fill_study results.json stop_slip_pmf["14:05-15:55"], seeded per (symbol, session, direction), used in
    the instrument's own ticks (conservative for MES: an ES tick is ~4x an NQ tick in %). A bar touching
    both fills the stop. Otherwise flat at the 15:59 bar's close - 1 tick.
  - size: contracts = floor(RISK_USD / (stop_pts x $/pt)), clamped to [1, 40]; RISK_USD = 1050.
    Commission $0.50 per contract per side.
  - account: LucidFlex 50K WITH the daily loss limit (flybrain.prop fixtures), fee $90.20, replayed by
    flybrain.prop.run_prop, one replay bar per session (open 0, low/high = worst/best equity, close = net
    P&L; no-trade sessions are flat days). Bootstrap 5000 accounts on 5-session blocks, 250-session horizon.
    EV per account = 90% of payouts - fee.
  - grid: 2 signals x 2 k x 2 STOP_PCT = 8 cells.
  - split: discovery = sessions 2022-01-03 .. 2025-03-26, both symbols (already seen by earlier studies,
    not for this signal). Holdout = SPY sessions 2025-03-27 .. 2026-08-14 only (QQQ's is spent).
    Without --holdout no holdout session is loaded.
  - selection: a cell is eligible if its discovery mean net R > 0 on BOTH SPY and QQQ. Among eligible
    cells, the one with the highest SPY discovery EV is selected. No eligible cell -> no holdout run.
  - controls (selected cell, same sessions and brackets): reversed direction; random direction with N_RANDOM
    = 200 seeds (p = (1 + #seeds with EV >= cell EV) / 201, all at CONTROL_PATHS = 2000 paths; the same
    p on mean R is reported as secondary); always-long (reported only: the drift).
  - verdict (SPY holdout): PASS if EV > 0, mean net R per trade > 0 with its 95% 5-session block-bootstrap
    CI above 0, and random-direction p < 0.05 (EV). STRUCTURE-ONLY if EV > 0 otherwise. FAIL if EV <= 0.
  - power (stated up front): the holdout has ~340 sessions, so ~340 trades at k = 0 and ~110 at k = 1.
    With a per-trade R sd near 0.8 the 95% CI half-width is ~0.085R (k = 0) / ~0.15R (k = 1), and 80%
    power needs a true mean of ~0.12R / ~0.21R. The published effect, converted to this bracket, is likely
    0.03-0.08R. The holdout can therefore only confirm an effect well above the literature's; a FAIL or
    STRUCTURE-ONLY is weak evidence against the hypothesis. The script prints the power from discovery's
    realized sd.

Specification: everything above was written down before the first run and is not changed after it.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from holdout import VERIFY_START, research_sessions  # noqa: E402
from flybrain.prop import resolve_plan, run_prop  # noqa: E402

ET = "America/New_York"
DATA = HERE / "data"
OUT = DATA / "intraday_momentum"
BARS_DIR = DATA / "databento" / "eq-ohlcv-1m"
FILL = DATA / "fill_study" / "results.json"

INSTR = {"SPY": dict(ratio=10.05, pv=5.0), "QQQ": dict(ratio=41.2, pv=2.0)}
TICK = 0.25
COMMISSION_SIDE = 0.50
MAX_CONTRACTS = 40
RISK_USD = 1050.0
OPEN, SIG_FIRST, ENTRY, LAST = 570, 600, 930, 959   # 09:30, 10:00, 15:30, 15:59
MIN_BARS = 380
SIGMA_WIN = 20
SIGNALS = ("first", "day")
KS = (0, 1)
STOP_PCT = (0.20, 0.35)
DISCOVERY_END = date(2025, 3, 26)
HOLDOUT_START = date(2025, 3, 27)
EVAL_FEE = 90.20
BOOT_PATHS = 5000
CONTROL_PATHS = 2000
N_RANDOM = 200
N_BOOT = 2000
BOOT_BLOCK = 5
SEED = 42


def slip_pmf():
    pmf = json.loads(FILL.read_text())["stop_slip_pmf"]["14:05-15:55"]
    t = np.array([int(k) for k in pmf]); p = np.array(list(pmf.values()))
    return t, p / p.sum()


SLIP_T, SLIP_P = slip_pmf()


# ---------------------------------------------------------------- data

def load(symbol: str, last_day: date) -> tuple[dict, dict]:
    """(tradeable sessions <= last_day, prev_close per session)."""
    cutoff = VERIFY_START.tz_convert("UTC")
    files = [f for f in sorted((BARS_DIR / symbol).glob("*.parquet")) if date.fromisoformat(f.name[:10]) <= last_day]
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close"], filters=[("ts_event", "<", cutoff)])
                      for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    assert (bars.index < cutoff).all(), "LEAK: bar read reaches the verify block"
    et = bars.index.tz_convert(ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= OPEN) & (bars.minute <= LAST) & (bars.day <= last_day)]
    all_days = sorted(set(bars.day))
    # research_sessions drops the gap week before VERIFY_START; it only applies when the load reaches it.
    keep = set(research_sessions(all_days)) if last_day >= VERIFY_START.date() - timedelta(days=14) else set(all_days)
    sessions, prev, last_close = {}, {}, None
    for d, g in bars.groupby("day", sort=True):
        if d in keep and last_close is not None and len(g) >= MIN_BARS and g.minute.iloc[0] == OPEN \
                and g.minute.iloc[-1] == LAST and (g.minute == ENTRY).any() and (g.minute == SIG_FIRST - 1).any():
            sessions[d] = g
            prev[d] = last_close
        last_close = float(g.close.iloc[-1])
    assert max(sessions) <= last_day
    return sessions, prev


# ---------------------------------------------------------------- one session

def raw_signals(g: pd.DataFrame, prev_close: float) -> dict:
    m = g.minute.to_numpy(); c = g.close.to_numpy()
    return dict(first=math.log(c[m == SIG_FIRST - 1][0] / prev_close), day=math.log(c[m == ENTRY - 1][0] / prev_close))


def trade(g: pd.DataFrame, d: int, stop_pct: float, symbol: str, rng: np.random.Generator) -> dict:
    spec = INSTR[symbol]
    m = g.minute.to_numpy()
    j = int(np.flatnonzero(m == ENTRY)[0])
    O, H, L, C = (g[k].to_numpy() * spec["ratio"] for k in ("open", "high", "low", "close"))
    entry = O[j] + d * TICK
    stop_pts = max(TICK, round(entry * stop_pct / 100 / TICK) * TICK)
    stop, target = entry - d * stop_pts, entry + d * stop_pts
    n = int(min(MAX_CONTRACTS, max(1, math.floor(RISK_USD / (stop_pts * spec["pv"])))))
    slip = int(rng.choice(SLIP_T, p=SLIP_P)) * TICK
    worst = best = 0.0
    exit_px, reason = None, "time"
    for i in range(j, len(m)):
        adv, fav = (L[i], H[i]) if d > 0 else (H[i], L[i])
        if i > j and (O[i] - stop) * d <= 0:
            exit_px, reason = O[i] - d * slip, "stop"
        elif (adv - stop) * d <= 0:
            exit_px, reason = stop - d * slip, "stop"
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
        if m[i] >= LAST:
            exit_px = C[i] - d * TICK
            break
    fees = 2 * COMMISSION_SIDE * n
    pnl = (exit_px - entry) * d * spec["pv"] * n - fees
    return dict(pnl=pnl, lo=min(0.0, worst * spec["pv"] * n - fees, pnl), hi=max(0.0, best * spec["pv"] * n, pnl),
                r=pnl / (stop_pts * spec["pv"] * n), reason=reason, contracts=n, win=pnl > 0)


def build_cells(symbol: str, sessions: dict, prev: dict) -> dict:
    days = sorted(sessions)
    sig = {d: raw_signals(sessions[d], prev[d]) for d in days}
    cells = {}
    for sp in STOP_PCT:
        trades = {}
        for d in days:
            seed = (d.toordinal() * 1000003 + (17 if symbol == "SPY" else 29)) % (2 ** 32)
            trades[d] = {+1: trade(sessions[d], 1, sp, symbol, np.random.default_rng(seed)),
                         -1: trade(sessions[d], -1, sp, symbol, np.random.default_rng(seed + 1))}
        for s in SIGNALS:
            x = np.array([sig[d][s] for d in days])
            for k in KS:
                rows = {}
                for i, d in enumerate(days):
                    if i < SIGMA_WIN or x[i] == 0:
                        rows[d] = None
                        continue
                    sigma = x[i - SIGMA_WIN:i].std(ddof=1)
                    rows[d] = None if abs(x[i]) <= k * sigma else dict(dir=int(np.sign(x[i])), long=trades[d][1], short=trades[d][-1])
                cells[(s, k, sp)] = rows
    return cells


# ---------------------------------------------------------------- scoring (as lucid_orb_study)

FLAT_DAY = dict(pnl=0.0, lo=0.0, hi=0.0)


def day_trades(rows: dict, days: list, dirs: dict | None = None) -> list:
    out = []
    for d in days:
        r = rows[d]
        if r is None:
            out.append(FLAT_DAY)
            continue
        side = (dirs or {}).get(d, r["dir"])
        out.append(r["long"] if side > 0 else r["short"])
    return out


def replay(trades: list, days: list, plan: dict, paths: int, history: bool) -> dict:
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


def ev(rep: dict) -> float:
    return rep["bootstrap"]["meanTake"] - EVAL_FEE


def trade_stats(trades: list) -> dict:
    taken = [t for t in trades if "r" in t]
    r = np.array([t["r"] for t in taken])
    rng = np.random.default_rng(SEED)
    n, b = len(r), min(BOOT_BLOCK, len(r))
    starts = rng.integers(0, n - b + 1, (N_BOOT, math.ceil(n / b)))
    idx = (starts[:, :, None] + np.arange(b)).reshape(N_BOOT, -1)[:, :n]
    means = r[idx].mean(1)
    reasons = pd.Series([t["reason"] for t in taken]).value_counts(normalize=True).round(3).to_dict()
    return dict(trades=n, win_rate=float(np.mean([t["win"] for t in taken])), mean_r=float(r.mean()), sd_r=float(r.std(ddof=1)),
                mean_r_ci=[float(np.quantile(means, .025)), float(np.quantile(means, .975))],
                mean_pnl=float(np.mean([t["pnl"] for t in taken])), exits=reasons,
                median_contracts=float(np.median([t["contracts"] for t in taken])))


def controls(rows: dict, days: list, plan: dict, cell_ev: float, cell_r: float) -> dict:
    taken = [d for d in days if rows[d] is not None]
    fade = day_trades(rows, days, {d: -rows[d]["dir"] for d in taken})
    longs = day_trades(rows, days, {d: 1 for d in taken})
    rng = np.random.default_rng(SEED + 1)
    evs, rs = [], []
    for _ in range(N_RANDOM):
        tr = day_trades(rows, days, {d: int(rng.choice((-1, 1))) for d in taken})
        evs.append(ev(replay(tr, days, plan, CONTROL_PATHS, False)))
        rs.append(np.mean([t["r"] for t in tr if "r" in t]))
    evs, rs = np.array(evs), np.array(rs)
    return dict(fade=dict(trades=trade_stats(fade), ev=ev(replay(fade, days, plan, BOOT_PATHS, False))),
                always_long=dict(trades=trade_stats(longs), ev=ev(replay(longs, days, plan, BOOT_PATHS, False))),
                random=dict(ev_mean=float(evs.mean()), ev_p05=float(np.quantile(evs, .05)), ev_p95=float(np.quantile(evs, .95)),
                            p=float((1 + (evs >= cell_ev).sum()) / (1 + N_RANDOM)),
                            r_mean=float(rs.mean()), p_r=float((1 + (rs >= cell_r).sum()) / (1 + N_RANDOM))))


def score_split(rows: dict, days: list, plan: dict, with_controls: bool) -> dict:
    trades = day_trades(rows, days)
    rep = replay(trades, days, plan, BOOT_PATHS, True)
    out = dict(sessions=len(days), first=str(days[0]), last=str(days[-1]), trades=trade_stats(trades), lucid=rep, ev=ev(rep))
    if with_controls:
        same = ev(replay(trades, days, plan, CONTROL_PATHS, False))
        out["controls"] = controls(rows, days, plan, same, out["trades"]["mean_r"])
        out["ev_at_control_paths"] = same
    return out


def verdict(h: dict) -> str:
    if h["ev"] <= 0:
        return "FAIL"
    if h["trades"]["mean_r_ci"][0] > 0 and h["controls"]["random"]["p"] < 0.05:
        return "PASS"
    return "STRUCTURE-ONLY"


def power(sd: float, n: int) -> dict:
    se = sd / math.sqrt(n)
    return dict(n=n, ci_half_width=1.96 * se, mde_80=2.8 * se)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--holdout", action="store_true", help="score the selected cell on the SPY holdout (one look)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "holdout.lock"
    if args.holdout and lock.exists():
        print(f"holdout already scored ({lock.read_text().strip()}); refusing a second look")
        return 1
    plan = resolve_plan("flex", "50k", True)

    disc = {}
    for sym in INSTR:
        sessions, prev = load(sym, DISCOVERY_END)
        days = sorted(sessions)
        disc[sym] = dict(days=days, cells=build_cells(sym, sessions, prev))
        print(f"{sym}: {len(days)} discovery sessions {days[0]} -> {days[-1]}")

    grid = []
    print(f"\nDISCOVERY (EV = 90% payouts - ${EVAL_FEE:.2f}; {BOOT_PATHS} bootstrap accounts, LucidFlex 50K with DLL)")
    print(f"{'sym':>4} {'signal':>6} {'k':>2} {'stop%':>6} | {'trades':>6} {'win':>6} {'meanR':>7} {'R 95% CI':>17} {'sdR':>5} | "
          f"{'pass':>6} {'paid':>6} {'EV':>8}")
    for key in disc["SPY"]["cells"]:
        row = dict(signal=key[0], k=key[1], stop_pct=key[2])
        for sym in INSTR:
            s = score_split(disc[sym]["cells"][key], disc[sym]["days"], plan, False)
            row[sym] = s
            t, b = s["trades"], s["lucid"]["bootstrap"]
            print(f"{sym:>4} {key[0]:>6} {key[1]:>2} {key[2]:>6.2f} | {t['trades']:>6} {t['win_rate']:6.1%} {t['mean_r']:+7.3f} "
                  f"[{t['mean_r_ci'][0]:+.3f},{t['mean_r_ci'][1]:+.3f}] {t['sd_r']:5.2f} | {b['passRate']:6.1%} {b['pPayout']:6.1%} {s['ev']:+8.1f}")
        row["eligible"] = row["SPY"]["trades"]["mean_r"] > 0 and row["QQQ"]["trades"]["mean_r"] > 0
        grid.append(row)

    res = dict(spec=dict(risk_usd=RISK_USD, fee=EVAL_FEE, plan=plan, discovery_end=str(DISCOVERY_END)),
               discovery=dict(grid=[{k: v for k, v in g.items()} for g in grid]))
    eligible = [g for g in grid if g["eligible"]]
    if not eligible:
        print("\nno cell has discovery mean R > 0 on both SPY and QQQ: nothing goes to the holdout")
        res["discovery"]["selected"] = None
        (OUT / "discovery.json").write_text(json.dumps(res, indent=1, default=str))
        return 0
    best = max(eligible, key=lambda g: g["SPY"]["ev"])
    sel = (best["signal"], best["k"], best["stop_pct"])
    print(f"\nselected: signal={sel[0]} k={sel[1]} stop={sel[2]}% (SPY discovery EV {best['SPY']['ev']:+.1f}, "
          f"QQQ {best['QQQ']['ev']:+.1f}; {len(eligible)}/{len(grid)} cells eligible)")
    ctl = {}
    for sym in INSTR:
        c = score_split(disc[sym]["cells"][sel], disc[sym]["days"], plan, True)
        ctl[sym] = c
        cc = c["controls"]
        print(f"  {sym} discovery controls: fade EV {cc['fade']['ev']:+.1f} (R {cc['fade']['trades']['mean_r']:+.3f}), always-long EV "
              f"{cc['always_long']['ev']:+.1f} (R {cc['always_long']['trades']['mean_r']:+.3f}), random EV {cc['random']['ev_mean']:+.1f} "
              f"[{cc['random']['ev_p05']:+.1f},{cc['random']['ev_p95']:+.1f}] p={cc['random']['p']:.3f}, mean-R p={cc['random']['p_r']:.3f}")
    sd = ctl["SPY"]["trades"]["sd_r"]
    rate = ctl["SPY"]["trades"]["trades"] / len(disc["SPY"]["days"])
    pw = power(sd, int(round(rate * 340)))
    print(f"  power on the SPY holdout (~340 sessions x {rate:.2f} trades/session, sd {sd:.2f}R): 95% CI half-width "
          f"{pw['ci_half_width']:.3f}R, 80%-power MDE {pw['mde_80']:.3f}R")
    res["discovery"].update(selected=dict(signal=sel[0], k=sel[1], stop_pct=sel[2]), selected_with_controls=ctl, holdout_power=pw)

    if args.holdout:
        lock.write_text(f"signal={sel[0]} k={sel[1]} stop_pct={sel[2]} at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
        sessions, prev = load("SPY", VERIFY_START.date() - timedelta(days=1))
        days = [d for d in sorted(sessions) if d >= HOLDOUT_START]
        assert days and days[0] >= HOLDOUT_START
        rows = build_cells("SPY", sessions, prev)[sel]   # sigma warms up on the sessions before the holdout
        h = score_split(rows, days, plan, True)
        h["verdict"] = verdict(h)
        res["holdout"] = h
        t, b, c = h["trades"], h["lucid"]["bootstrap"], h["controls"]
        print(f"\nHOLDOUT (one look, SPY)  {h['first']} -> {h['last']}")
        print(f"  trades {t['trades']}, win {t['win_rate']:.1%}, mean R {t['mean_r']:+.3f} [{t['mean_r_ci'][0]:+.3f}, "
              f"{t['mean_r_ci'][1]:+.3f}], exits {t['exits']}")
        print(f"  Lucid: pass {b['passRate']:.1%}, paid {b['pPayout']:.1%}, EV ${h['ev']:+.1f}; historical-start EV "
              f"${h['lucid']['historical']['meanTake'] - EVAL_FEE:+.1f}")
        print(f"  fade EV {c['fade']['ev']:+.1f}; always-long EV {c['always_long']['ev']:+.1f}; random EV {c['random']['ev_mean']:+.1f} "
              f"[{c['random']['ev_p05']:+.1f}, {c['random']['ev_p95']:+.1f}], p = {c['random']['p']:.3f} (mean-R p {c['random']['p_r']:.3f})")
        print(f"  VERDICT: {h['verdict']}")
    (OUT / ("results.json" if args.holdout else "discovery.json")).write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
