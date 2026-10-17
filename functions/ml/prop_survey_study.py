"""Prop survey: strategies people online say pass prop evaluations, each frozen as one spec and scored against a coin flip.

Sunny asked (2026-10-17) to test the strategies collected in studies/prop-strategies-survey/SURVEY.md with the fees and
slippage of a firm like Lucid, and to keep only those that beat a coin flip. A coin flip already has a positive EV
on a Lucid 50K account at one ~$750 trade a day (lucid_orb_study.py), so "the account made money" says nothing about the
entry. The test here is whether the entry beats the same trades with the direction chosen by a coin.

Not here: the opening-range breakout and late-session momentum (lucid_writeup_study.py, draft PR #5), and the
discretionary setups (ICT confluence stacks, order-flow reading, price action), which have no rule a script can follow.

Data, execution and costs are amt_lucid_study.py's, unchanged:
  - Databento XNAS.ITCH ohlcv-1m, RTH 09:30-15:59 ET, sessions with >= 380 RTH bars, research side of holdout.py only.
      QQQ -> MNQ (x41.2, $2/pt)    SPY -> MES (x10.05, $5/pt)    tick 0.25 on the futures plane.
  - signals use closed 1m bars; entry = the next 1m bar's open + 1 tick adverse; no entry from 14:00 ET.
  - bracket on 1m bars: a bar that opens through a level fills at its open (stop: +1 tick); a bar touching both fills
    the stop; a target fills only when price trades a tick THROUGH it; else flat at the 15:54 close - 1 tick.
  - size: floor($750 / (stop_pts x point value)) micros, clamped to [1, 40]. Commission $1.00 per micro per side.
  - Lucid: daily P&L replayed by flybrain.prop.run_prop (lucid_orb_study.replay), 5,000 bootstrap accounts on 5-session
    blocks, 250-session horizon, for LucidFlex 50K (no DLL, fee $90) and LucidPro 50K (DLL $1,200, fee $115).
    EV per evaluation = 90% of payouts - fee.

Strategies (one spec each, written down from the sources before any run; no grid, so nothing is selected):
  gap_fill      TradeThatSwing ES gap fill. gap = (09:30 open - prior RTH close) / prior close, 0.05% <= |gap| <= 0.20%.
                Skip if the first 5 minutes already trade back to the prior close. Entry at the 09:35 bar toward
                the prior close; target = the prior close; stop = the target distance (1:1), capped at 0.20% of
                entry (the source's 12 ES points was 0.20-0.34% of ES over 2022-2025).
  sweep         ICT-style liquidity sweep, the loose form (the 25,000-config study found killzones and bias added
                nothing). Needs the 09:30 open inside the prior session's range. The first time price trades a tick
                beyond the prior high (low), if a bar within SWEEP_BARS minutes of that closes back inside, fade it:
                short (long) at the next bar. Stop: the sweep extreme +1 tick. Target: 2R. A side that stays
                outside SWEEP_BARS minutes is spent; if both sides are swept before a signal, no trade.
  eighty_pct    Market Profile "80% rule": amt_lucid_study.signal_va_reentry with k = 2 and target = far edge, i.e.
                open outside the prior value area, two consecutive 30m closes inside, trade to the far edge.
                (amt_lucid_study scanned this cell inside a 4-cell grid; here it is the only spec.)
  vwap_fade     The app's vwapReversion.js defaults on 5m bars (09:30-anchored), ATR14 of 5m true ranges inside the
                session (first signal possible on the bar ending 10:45). The first 5m close >= 1.2 ATR from session
                VWAP (typical price x volume from 09:30) -> fade at the next 1m bar. Target: the 0.2 ATR exit band
                at the signal bar's VWAP, frozen. Stop: 1.0 ATR from entry (the app's rule has none; an account
                needs one). Skipped if the target is under 0.5x the stop (amt_lucid_study.MIN_RR).
  coin flips    reference only, not tests: every session at the 10:00 bar, direction a seeded coin.
      coin_1to1   stop = target = 0.25% of entry.
      coin_scalp  stop 0.30%, target 0.10%: the "small target, big stop" high-win-rate structure from the survey.

The coin-flip control for each strategy: N_RANDOM seeds, same sessions, entries and stop / target distances,
direction a fair coin. p = (1 + #seeds >= the strategy) / (1 + N_RANDOM), on mean net R and on Lucid EV.

Verdict per strategy x instrument x plan, Bonferroni ALPHA = 0.05 / 8 (4 strategies x 2 instruments):
    BEATS-COIN-FLIP  EV > 0, mean net R 95% CI above 0, p (mean R) < ALPHA and p (EV) < ALPHA.
    STRUCTURE-ONLY   EV > 0 without the above: the account's payout shape pays, the entry does not.
    FAIL             EV <= 0.

Windows (amt_lucid_study's pinned split):
    default   QQQ and SPY sessions <= DISCOVERY_END (2025-03-26). Earlier studies read these sessions with other
              rules; none of the four specs above was fitted to them. This is the main result.
    --score   SPY sessions after DISCOVERY_END to 2026-08-14, scored ONCE (lock file). Draft PR #5 keeps the same
              SPY window unread for its gated ORB check; this mode computes no ORB trades, but run it after that
              question is settled so one person is not looking at the window for several questions at once.

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
import amt_lucid_study as amt  # noqa: E402
from flybrain.prop import resolve_plan  # noqa: E402
from lucid_orb_study import FLAT_DAY, replay, trade_stats  # noqa: E402

OUT = amt.DATA / "prop_survey"
TICK, OPEN, LAST_ENTRY = amt.TICK, amt.OPEN, amt.LAST_ENTRY
STRATEGIES = ("gap_fill", "sweep", "eighty_pct", "vwap_fade")
COINS = {"coin_1to1": (0.25, 0.25), "coin_scalp": (0.30, 0.10)}   # stop %, target %
GAP_MIN, GAP_MAX, GAP_STOP_CAP = 0.0005, 0.0020, 0.0020
SWEEP_BARS, SWEEP_RR = 5, 2.0
VWAP_ENTRY, VWAP_EXIT, VWAP_STOP, ATR_N = 1.2, 0.2, 1.0, 14
COIN_MINUTE = 600                                                  # 10:00 ET
PLANS = {"flex": (("flex", "50k", False), 90.0), "pro": (("pro", "50k", True), 115.0)}
ALPHA = 0.05 / 8
BOOT_PATHS, CONTROL_PATHS, N_RANDOM, SEED = 5000, 2000, 500, 42


# ---------------------------------------------------------------- signals: (dir, entry index, stop dist, target dist) | None

def signal_gap_fill(prev_close: float, O, H, L, C, m):
    gap = (O[0] - prev_close) / prev_close
    if not GAP_MIN <= abs(gap) <= GAP_MAX:
        return None
    d = -1 if gap > 0 else 1
    first = m < OPEN + 5
    if (L[first].min() <= prev_close) if d < 0 else (H[first].max() >= prev_close):
        return None
    j = int(np.argmax(m >= OPEN + 5))
    if m[j] < OPEN + 5:
        return None
    entry = O[j] + d * TICK
    tgt_d = (prev_close - entry) * d
    if tgt_d < TICK:
        return None
    cap = max(TICK, round(GAP_STOP_CAP * entry / TICK) * TICK)
    return amt.plan_trade(d, j, entry - d * min(tgt_d, cap), prev_close, None, O, m)


def signal_sweep(prev_high: float, prev_low: float, O, H, L, C, m):
    if not prev_low <= O[0] <= prev_high:
        return None
    first = {1: None, -1: None}            # index of the bar where each side first traded a tick beyond
    for i in range(len(m)):
        if m[i] + 1 > LAST_ENTRY:
            return None
        if first[1] is None and H[i] >= prev_high + TICK:
            first[1] = i
        if first[-1] is None and L[i] <= prev_low - TICK:
            first[-1] = i
        a = first[1]
        if a is not None and i - a < SWEEP_BARS and C[i] < prev_high:
            return amt.plan_trade(-1, i + 1, H[a:i + 1].max() + TICK, None, SWEEP_RR, O, m)
        b = first[-1]
        if b is not None and i - b < SWEEP_BARS and C[i] > prev_low:
            return amt.plan_trade(1, i + 1, L[b:i + 1].min() - TICK, None, SWEEP_RR, O, m)
        if a is not None and b is not None:
            return None
    return None


def signal_vwap_fade(O, H, L, C, V, m):
    tp = (H + L + C) / 3
    vwap = np.cumsum(tp * V) / np.maximum(np.cumsum(V), 1e-9)
    prev_c = None
    trs = []
    for s, e in amt.periods(m, 5):
        hi, lo, c = H[s:e + 1].max(), L[s:e + 1].min(), C[e]
        trs.append(hi - lo if prev_c is None else max(hi, prev_c) - min(lo, prev_c))
        prev_c = c
        if m[e] + 1 > LAST_ENTRY:
            return None
        if len(trs) < ATR_N + 1:            # the ATR uses the 14 bars before the signal bar's own
            continue
        atr = float(np.mean(trs[-ATR_N - 1:-1]))
        if atr <= 0:
            continue
        dev = (c - vwap[e]) / atr
        if abs(dev) < VWAP_ENTRY:
            continue
        d = -1 if dev > 0 else 1
        j = e + 1
        if j >= len(m):
            return None
        entry = O[j] + d * TICK
        stop = entry - d * max(TICK, round(VWAP_STOP * atr / TICK) * TICK)
        target = round((vwap[e] - d * VWAP_EXIT * atr) / TICK) * TICK
        return amt.plan_trade(d, j, stop, target, None, O, m)
    return None


def coin_signal(O, m, stop_pct: float, tgt_pct: float, d: int):
    k = np.flatnonzero(m == COIN_MINUTE)
    if not len(k):
        return None
    j = int(k[0])
    entry = O[j] + d * TICK
    sd = max(TICK, round(stop_pct / 100 * entry / TICK) * TICK)
    td = max(TICK, round(tgt_pct / 100 * entry / TICK) * TICK)
    return d, j, sd, td


# ---------------------------------------------------------------- rows

def build_rows(sessions: dict, symbol: str) -> dict:
    """{name: {day: None | dict(dir, long, short)}} for the strategies and the coin flips; days with a prior session."""
    spec = amt.INSTRUMENTS[symbol]
    ratio, pv = spec["ratio"], spec["pv"]
    days = sorted(sessions)
    rows = {n: {} for n in (*STRATEGIES, *COINS)}
    rng = np.random.default_rng(SEED)
    for prev, d in zip(days, days[1:]):
        p, g = sessions[prev], sessions[d]
        lv = amt.profile(p, ratio)
        prev_close = p.close.iloc[-1] * ratio
        prev_high, prev_low = p.high.max() * ratio, p.low.min() * ratio
        O, H, L, C = (g[k].to_numpy(dtype=float) * ratio for k in ("open", "high", "low", "close"))
        V, m = g.volume.to_numpy(dtype=float), g.minute.to_numpy()
        coin = int(rng.choice((-1, 1)))
        sigs = dict(gap_fill=signal_gap_fill(prev_close, O, H, L, C, m),
                    sweep=signal_sweep(prev_high, prev_low, O, H, L, C, m),
                    eighty_pct=amt.signal_va_reentry(lv, O, H, L, C, m, k=2, target="far_edge"),
                    vwap_fade=signal_vwap_fade(O, H, L, C, V, m),
                    **{n: coin_signal(O, m, *pc, coin) for n, pc in COINS.items()})
        for name, sig in sigs.items():
            if sig is None:
                rows[name][d] = None
                continue
            side, j, sd, td = sig
            rows[name][d] = dict(dir=side, long=amt.bracket(O, H, L, C, m, 1, j, sd, td, pv),
                                 short=amt.bracket(O, H, L, C, m, -1, j, sd, td, pv))
    return rows


# ---------------------------------------------------------------- scoring

def ev(rep: dict, fee: float) -> float:
    return rep["bootstrap"]["meanTake"] - fee


def mean_r(trades: list[dict]) -> float:
    return float(np.mean([t["r"] for t in trades if "r" in t]))


def score(rows: dict, plans: dict, n_random: int = N_RANDOM, boot_paths: int = BOOT_PATHS,
          control_paths: int = CONTROL_PATHS) -> dict:
    """Trade stats, Lucid EV per plan, and the coin-flip control (same trades, random direction)."""
    days = sorted(rows)
    trades = amt.day_trades(rows, days)
    if sum("r" in t for t in trades) < 2:
        return dict(sessions=len(days), trades=dict(trades=sum("r" in t for t in trades)))
    out = dict(sessions=len(days), first=str(days[0]), last=str(days[-1]), trades=trade_stats(trades), plans={})
    rng = np.random.default_rng(SEED + 1)
    flips = [{d: int(rng.choice((-1, 1))) for d in days if rows[d] is not None} for _ in range(n_random)]
    flip_trades = [amt.day_trades(rows, days, f) for f in flips]
    rs = np.array([mean_r(t) for t in flip_trades])
    out["coin"] = dict(mean_r=float(rs.mean()), mean_r_p05=float(np.quantile(rs, .05)), mean_r_p95=float(np.quantile(rs, .95)),
                       p_r=float((1 + (rs >= out["trades"]["mean_r"]).sum()) / (1 + n_random)))
    for name, (key, fee) in plans.items():
        rep = replay(trades, days, key, boot_paths, False)
        same = ev(replay(trades, days, key, control_paths, False), fee)
        evs = np.array([ev(replay(t, days, key, control_paths, False), fee) for t in flip_trades])
        b = rep["bootstrap"]
        out["plans"][name] = dict(ev=ev(rep, fee), pass_rate=b["passRate"], p_payout=b["pPayout"], ev_at_control_paths=same,
                                  coin_ev=float(evs.mean()), coin_ev_p05=float(np.quantile(evs, .05)),
                                  coin_ev_p95=float(np.quantile(evs, .95)),
                                  p_ev=float((1 + (evs >= same).sum()) / (1 + n_random)))
    return out


def verdict(s: dict, plan: str) -> str:
    if not s["trades"].get("trades"):
        return "NO-TRADES"
    p = s["plans"][plan]
    if p["ev"] <= 0:
        return "FAIL"
    if s["trades"]["mean_r_ci"][0] > 0 and s["coin"]["p_r"] < ALPHA and p["p_ev"] < ALPHA:
        return "BEATS-COIN-FLIP"
    return "STRUCTURE-ONLY"


def resolved_plans() -> dict:
    return {n: (resolve_plan(*key), fee) for n, (key, fee) in PLANS.items()}


def report(label: str, scored: dict) -> None:
    print(f"\n{label}")
    print(f"{'rule':<11} | {'trades':>6} {'win':>6} {'meanR':>7} {'R 95% CI':>16} {'coinR':>7} {'p_R':>6} | "
          f"{'plan':<4} {'pass':>6} {'paid':>6} {'EV':>7} {'coinEV':>7} {'p_EV':>6}  verdict")
    for name, s in scored.items():
        t = s["trades"]
        if not t.get("trades") or "plans" not in s:
            print(f"{name:<11} | {t.get('trades', 0):>6} trades")
            continue
        head = (f"{name:<11} | {t['trades']:>6} {t['win_rate']:6.1%} {t['mean_r']:+7.3f} "
                f"[{t['mean_r_ci'][0]:+.3f},{t['mean_r_ci'][1]:+.3f}] {s['coin']['mean_r']:+7.3f} {s['coin']['p_r']:6.3f} | ")
        for k, plan in enumerate(s["plans"]):
            p = s["plans"][plan]
            v = "reference" if name in COINS else verdict(s, plan)
            print((head if k == 0 else " " * (len(head) - 2) + "| ") +
                  f"{plan:<4} {p['pass_rate']:6.1%} {p['p_payout']:6.1%} {p['ev']:+7.0f} {p['coin_ev']:+7.0f} {p['p_ev']:6.3f}  {v}")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--score", action="store_true", help="score SPY after DISCOVERY_END once (lock file)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "score.lock"
    if args.score and lock.exists():
        print(f"already scored ({lock.read_text().strip()}); refusing a second look")
        return 1
    plans = resolved_plans()
    res = dict(spec=dict(alpha=ALPHA, n_random=N_RANDOM, risk_usd=amt.RISK_USD, commission_side=amt.COMMISSION_SIDE,
                         fees={n: f for n, (_, f) in PLANS.items()}), windows={})
    if args.score:
        lock.write_text(f"scored at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
        spy = amt.load_sessions("SPY", date(2026, 8, 14))
        first = max(d for d in spy if d <= amt.DISCOVERY_END)    # prior-day levels only; never traded
        sessions = {d: g for d, g in spy.items() if d >= first}
        windows = {"SPY score": sessions}
    else:
        windows = {f"{s} discovery": amt.load_sessions(s, amt.DISCOVERY_END) for s in amt.INSTRUMENTS}
    for label, sessions in windows.items():
        sym = label.split()[0]
        days = sorted(sessions)
        rows = build_rows(sessions, sym)
        scored = {name: score(r, plans) for name, r in rows.items()}
        report(f"{sym} -> {amt.INSTRUMENTS[sym]['fut']} {label.split()[1].upper()}  {len(days)} sessions {days[0]} -> {days[-1]}"
               f"  (alpha {ALPHA:.4f}, {N_RANDOM} coin-flip seeds)", scored)
        for s in scored.values():
            if "plans" in s:
                s["verdicts"] = {p: verdict(s, p) for p in s["plans"]}
        res["windows"][label] = scored
    (OUT / ("score.json" if args.score else "discovery.json")).write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
