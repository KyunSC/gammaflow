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

Five more, from Sunny's message of 2026-10-17 17:37 UTC (sources as Sunny gave them: Eddy Pips, r/AlphaGroupOfficial,
Ryley Trades, r/ICTMentorship). The win rates and pass records quoted there are the claims under test, not facts.
Each runs only on the futures its source names (ES -> SPY/MES, NQ -> QQQ/MNQ). Point rules are applied on the
futures plane (SPY x 10.05 ~ ES points, QQQ x 41.2 ~ NQ points); that ignores the futures basis and rolls, and an ETF
proxy's premarket is thinner than Globex. Risk per trade is the source's where it gives one, else $750.
  range_reclaim (Eddy Pips, ES; SPY only) Needs the extended-hours bars: the 08:00-08:59 ET hour (>= 30 of its
                1m bars present) with range 10-24 points and (close - low) / range outside [0.45, 0.55]. Skipped on
                CPI, NFP and ADP days (BLS schedule below; ADP = the Wednesday of the NFP week). From the 09:00 bar,
                the first bar trading a tick beyond the hour's high (low) sets the side: short (long) only; a bar
                breaking both aborts the day. Reclaim: the first 1m close back inside the range within 60 minutes of
                the break bar; none, or one 2-5 minutes after it, cancels the day. Retest: the first later bar within
                120 minutes of the reclaim that trades to or past the broken edge and closes inside -> entry at the
                next bar. Stop 12, target 12 points; exit at the latest 6 hours after entry (and by 15:54). Risk
                $625 (1.25% of 50K). One trade a day.
  orb15_mid     (Eddy Pips ORB, NQ; QQQ only) 09:30-09:44 range and its midpoint; the first 5m bar (09:30-anchored)
                from 09:45 closing beyond the range -> entry at the next bar (its close ~ the next open). Stop:
                midpoint -/+ 5 points. Target 2R. Flat at 15:54 (the source says 16:00). Risk $500 (1%).
                Differs from PR #5: that ORB uses 1m closes, a VWAP side check, RVOL and compression filters, the
                plain midpoint stop and a VWAP trailing exit; lucid_orb_study used 1:1 %-of-price brackets.
  orb_fvg       (r/AlphaGroupOfficial, NQ and ES) 09:30-09:44 range. A 1m bar from 09:45 to 10:59 that closes beyond
                the range and completes a 3-bar FVG (bar[-2].high < bar.low long; bar[-2].low > bar.high short) ->
                entry at the next bar. Stop: the FVG's far edge (bar[-2].high long / .low short). Target 2R if the
                stop is under 30 NQ points (8 ES points, ~ the same share of price in 2022-2025), else 1R. Pinned:
                one trade a day; the optional second attempt and the "breakeven past internal structure" move are
                left out (the second needs the day's first result; the move has no mechanical definition). The
                thread's 09:45-10:00 window is a subset chosen after the fact and is not used.
  cont_fvg      (Ryley Trades, NQ; QQQ only) The "15m magnet" is not mechanical as given; pinned to the nearer of
                the prior session's RTH high and low from the 09:30 open (open outside that range -> no trade). Then
                on 1m bars from 09:30: the first FVG aligned with the magnet; a later close beyond its far edge voids
                it; each bar touching it (up to 5) is a candidate, and one closing beyond the previous bar's high
                (long) / low (short) -> entry at the next bar. After a voided or exhausted gap, the next aligned FVG
                is used. Entries until 11:00; no trade once the magnet has traded. Stop = target = 20 points (the
                source says 15 or 20). One trade a day; no news filter (no intraday news calendar here).
  erl_irl       (r/ICTMentorship, NQ and ES) 60m bars (09:30-anchored): the first one trading a tick beyond the
                prior session's RTH high (low) and closing back inside is the sweep (a bar sweeping both: no trade).
                On 30m bars from the sweep hour on, the first FVG pointing away from the sweep (bearish after a high
                sweep) -> a limit order at its near edge, filled by the first later 1m bar trading a tick through it
                (at its open if it opens through). Stop: the far edge + 1 tick. Target: 2R. The order expires at
                14:00. Daily / Monday highs on 4H charts are out of scope for RTH bars.
  coin flips    reference only, not tests: every session at the 10:00 bar, direction a seeded coin.
      coin_1to1   stop = target = 0.25% of entry.
      coin_scalp  stop 0.30%, target 0.10%: the "small target, big stop" high-win-rate structure from the survey.

The coin-flip control for each strategy: N_RANDOM seeds, same sessions, entries and stop / target distances,
direction a fair coin. p = (1 + #seeds >= the strategy) / (1 + N_RANDOM), on mean net R and on Lucid EV.

The limit-entry erl_irl control keeps the fill bar and price and flips only the direction; limit fills are managed
from the bar after the fill for both directions (a bar that trades to the limit is one-sided around it).
Prop-rule ideas from the same message: rolling pass windows are what run_prop's historical replay already reports
(every start day); Lucid's drawdown is end-of-day (verified 2026-10-16), so the intraday-trailing variant does not
apply; circuit breakers and de-risking are sizing overlays, not entries, and the coin-flip test is about entries.
Slippage stays at 1 tick on market fills: fill_study.py measured ~1.1 ticks of stop slip on these bars.

Verdict per strategy x instrument x plan, Bonferroni ALPHA = 0.05 / 15 (15 strategy x instrument tests):
    BEATS-COIN-FLIP  EV > 0, mean net R 95% CI above 0, p (mean R) < ALPHA and p (EV) < ALPHA.
    STRUCTURE-ONLY   EV > 0 without the above: the account's payout shape pays, the entry does not.
    FAIL             EV <= 0.

Windows (amt_lucid_study's pinned split):
    default   QQQ and SPY sessions <= DISCOVERY_END (2025-03-26). Earlier studies read these sessions with other
              rules; none of the specs above was fitted to them. This is the main result.
    --score   SPY sessions after DISCOVERY_END to 2026-08-14, scored ONCE (lock file). Draft PR #5 keeps the same
              SPY window unread for its gated ORB check; this mode computes no ORB trades, but run it after that
              question is settled so one person is not looking at the window for several questions at once.
              QQQ after DISCOVERY_END was spent by lucid_orb_study, so NQ-only rules get no second window here.

Specification: everything above was written down before the first run and not changed after it.
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
import amt_lucid_study as amt  # noqa: E402
from flybrain.prop import resolve_plan  # noqa: E402
from lucid_orb_study import FLAT_DAY, replay, trade_stats  # noqa: E402

OUT = amt.DATA / "prop_survey"
TICK, OPEN, LAST_ENTRY = amt.TICK, amt.OPEN, amt.LAST_ENTRY
BOTH, ES, NQ = ("QQQ", "SPY"), ("SPY",), ("QQQ",)
TESTS = {"gap_fill": BOTH, "sweep": BOTH, "eighty_pct": BOTH, "vwap_fade": BOTH,
         "range_reclaim": ES, "orb15_mid": NQ, "orb_fvg": BOTH, "cont_fvg": NQ, "erl_irl": BOTH}
STRATEGIES = tuple(TESTS)
COINS = {"coin_1to1": (0.25, 0.25), "coin_scalp": (0.30, 0.10)}   # stop %, target %
PRE_OPEN, PRE_MIN_BARS = 480, 30                                   # 08:00 ET; bars needed in the 08:00 hour
RR_RANGE, RR_LOC, RR_STOP, RR_RISK = (10.0, 24.0), (0.45, 0.55), 12.0, 625.0
RR_RECLAIM, RR_BLACKOUT, RR_RETEST, RR_HOLD = 60, (2, 5), 120, 360
OM_BUFFER, OM_RR, OM_RISK = 5.0, 2.0, 500.0
OF_LAST, OF_WIDE = 660, {"QQQ": 30.0, "SPY": 8.0}                  # 11:00 ET; wide-stop threshold, points
CF_LAST, CF_STOP, CF_TOUCHES = 660, 20.0, 5
EI_RR = 2.0
# BLS release calendar (bls.gov/schedule/<year>, checked 2026-10-17), 2022-01 -> 2026-08
CPI_DAYS = """2022-01-12 2022-02-10 2022-03-10 2022-04-12 2022-05-11 2022-06-10 2022-07-13 2022-08-10 2022-09-13 2022-10-13
2022-11-10 2022-12-13 2023-01-12 2023-02-14 2023-03-14 2023-04-12 2023-05-10 2023-06-13 2023-07-12 2023-08-10 2023-09-13
2023-10-12 2023-11-14 2023-12-12 2024-01-11 2024-02-13 2024-03-12 2024-04-10 2024-05-15 2024-06-12 2024-07-11 2024-08-14
2024-09-11 2024-10-10 2024-11-13 2024-12-11 2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15
2025-08-12 2025-09-11 2025-10-24 2025-12-18 2026-01-13 2026-02-13 2026-03-11 2026-04-10 2026-05-12 2026-06-10 2026-07-14
2026-08-12""".split()
NFP_DAYS = """2022-01-07 2022-02-04 2022-03-04 2022-04-01 2022-05-06 2022-06-03 2022-07-08 2022-08-05 2022-09-02 2022-10-07
2022-11-04 2022-12-02 2023-01-06 2023-02-03 2023-03-10 2023-04-07 2023-05-05 2023-06-02 2023-07-07 2023-08-04 2023-09-01
2023-10-06 2023-11-03 2023-12-08 2024-01-05 2024-02-02 2024-03-08 2024-04-05 2024-05-03 2024-06-07 2024-07-05 2024-08-02
2024-09-06 2024-10-04 2024-11-01 2024-12-06 2025-01-10 2025-02-07 2025-03-07 2025-04-04 2025-05-02 2025-06-06 2025-07-03
2025-08-01 2025-09-05 2025-11-20 2025-12-16 2026-01-09 2026-02-11 2026-03-06 2026-04-03 2026-05-08 2026-06-05 2026-07-02
2026-08-07""".split()


def macro_days() -> set[date]:
    nfp = [date.fromisoformat(s) for s in NFP_DAYS]
    adp = {d - timedelta(days=d.weekday() - 2) for d in nfp if d.weekday() > 2}      # Wednesday of the NFP week
    return {date.fromisoformat(s) for s in CPI_DAYS} | set(nfp) | adp


MACRO = macro_days()
GAP_MIN, GAP_MAX, GAP_STOP_CAP = 0.0005, 0.0020, 0.0020
SWEEP_BARS, SWEEP_RR = 5, 2.0
VWAP_ENTRY, VWAP_EXIT, VWAP_STOP, ATR_N = 1.2, 0.2, 1.0, 14
COIN_MINUTE = 600                                                  # 10:00 ET
PLANS = {"flex": (("flex", "50k", False), 90.0), "pro": (("pro", "50k", True), 115.0)}
ALPHA = 0.05 / 15
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


def signal_range_reclaim(day: date, O, H, L, C, m):
    """On extended-hours arrays (from 08:00)."""
    if day in MACRO:
        return None
    hour = (m >= PRE_OPEN) & (m < PRE_OPEN + 60)
    if hour.sum() < PRE_MIN_BARS:
        return None
    hi, lo = H[hour].max(), L[hour].min()
    rng = hi - lo
    if not RR_RANGE[0] <= rng <= RR_RANGE[1]:
        return None
    loc = (C[np.flatnonzero(hour)[-1]] - lo) / rng
    if RR_LOC[0] <= loc <= RR_LOC[1]:
        return None
    inside = lambda i: lo <= C[i] <= hi
    after = np.flatnonzero(m >= PRE_OPEN + 60)
    b = d = None
    for i in after:
        up, dn = H[i] >= hi + TICK, L[i] <= lo - TICK
        if up and dn:
            return None
        if up or dn:
            b, d = int(i), (-1 if up else 1)
            break
    if b is None:
        return None
    k = next((i for i in range(b, len(m)) if m[i] - m[b] <= RR_RECLAIM and inside(i)), None)
    if k is None or k >= len(m) or m[k] - m[b] > RR_RECLAIM or RR_BLACKOUT[0] <= m[k] - m[b] <= RR_BLACKOUT[1]:
        return None
    edge = hi if d < 0 else lo
    for q in range(k + 1, len(m)):
        if m[q] - m[k] > RR_RETEST:
            return None
        if ((H[q] >= edge) if d < 0 else (L[q] <= edge)) and inside(q):
            j = q + 1
            if j >= len(m) or m[j] >= LAST_ENTRY:
                return None
            return d, j, RR_STOP, RR_STOP, dict(risk=RR_RISK, until=m[j] + RR_HOLD)
    return None


def signal_orb15_mid(O, H, L, C, m):
    rng = m < OPEN + 15
    hi, lo = H[rng].max(), L[rng].min()
    mid = (hi + lo) / 2
    for s, e in amt.periods(m, 5):
        if m[s] < OPEN + 15:
            continue
        if m[e] + 1 > LAST_ENTRY:
            return None
        d = 1 if C[e] > hi else -1 if C[e] < lo else 0
        if d:
            j = e + 1
            if j >= len(m):
                return None
            stop = mid - d * OM_BUFFER
            sd = round(((O[j] + d * TICK) - stop) * d / TICK) * TICK
            if sd < TICK:
                return None
            return d, j, sd, round(OM_RR * sd / TICK) * TICK, dict(risk=OM_RISK)
    return None


def signal_orb_fvg(O, H, L, C, m, wide: float):
    rng = m < OPEN + 15
    hi, lo = H[rng].max(), L[rng].min()
    for i in range(2, len(m)):
        if m[i] < OPEN + 15:
            continue
        if m[i] >= OF_LAST:
            return None
        if C[i] > hi and H[i - 2] < L[i]:
            d, stop = 1, H[i - 2]
        elif C[i] < lo and L[i - 2] > H[i]:
            d, stop = -1, L[i - 2]
        else:
            continue
        j = i + 1
        if j >= len(m):
            return None
        sd = round(((O[j] + d * TICK) - stop) * d / TICK) * TICK
        if sd < TICK:
            continue
        return d, j, sd, round((2.0 if sd < wide else 1.0) * sd / TICK) * TICK
    return None


def signal_cont_fvg(prev_high: float, prev_low: float, O, H, L, C, m):
    if not prev_low <= O[0] <= prev_high:
        return None
    d = 1 if prev_high - O[0] < O[0] - prev_low else -1
    magnet = prev_high if d > 0 else prev_low
    gap = None                                   # (near edge, far edge, touches)
    for i in range(len(m)):
        if m[i] + 1 > CF_LAST or (H[i] >= magnet if d > 0 else L[i] <= magnet):
            return None
        if gap is not None:
            near, far, n = gap
            if (C[i] < far) if d > 0 else (C[i] > far):
                gap = None
            elif (L[i] <= near) if d > 0 else (H[i] >= near):
                n += 1
                if (C[i] > H[i - 1]) if d > 0 else (C[i] < L[i - 1]):
                    j = i + 1
                    return (d, j, CF_STOP, CF_STOP) if j < len(m) else None
                gap = None if n >= CF_TOUCHES else (near, far, n)
            continue
        if i >= 2 and ((H[i - 2] < L[i]) if d > 0 else (L[i - 2] > H[i])):
            gap = (L[i], H[i - 2], 0) if d > 0 else (H[i], L[i - 2], 0)
    return None


def signal_erl_irl(prev_high: float, prev_low: float, O, H, L, C, m):
    hours = amt.periods(m, 60)
    sweep = None
    for s, e in hours:
        up = H[s:e + 1].max() >= prev_high + TICK and C[e] < prev_high
        dn = L[s:e + 1].min() <= prev_low - TICK and C[e] > prev_low
        if up and dn:
            return None
        if up or dn:
            sweep = (s, -1 if up else 1)
            break
    if sweep is None:
        return None
    s0, d = sweep
    bars = [(s, e, H[s:e + 1].max(), L[s:e + 1].min()) for s, e in amt.periods(m, 30) if s >= s0]
    for a, c in zip(bars, bars[2:]):
        if d < 0 and a[3] > c[2]:                 # bearish 30m FVG: sell limit at its lower (near) edge
            limit, stop = c[2], a[3] + TICK
        elif d > 0 and a[2] < c[3]:               # bullish: buy limit at its upper (near) edge
            limit, stop = c[3], a[2] - TICK
        else:
            continue
        for t in range(c[1] + 1, len(m)):
            if m[t] >= LAST_ENTRY:
                return None
            if (H[t] >= limit + TICK) if d < 0 else (L[t] <= limit - TICK):
                entry = max(limit, O[t]) if d < 0 else min(limit, O[t])
                sd = round((entry - stop) * d / TICK) * TICK
                if sd < TICK:
                    return None
                return d, t, sd, round(EI_RR * sd / TICK) * TICK, dict(entry=entry)
        return None
    return None


# ---------------------------------------------------------------- execution

def bracket(O, H, L, C, m, d: int, j: int, stop_d: float, tgt_d: float, pv: float, risk: float = amt.RISK_USD,
            entry: float | None = None, until: int | None = None) -> dict:
    """amt_lucid_study.bracket with a per-trade risk, an optional limit-fill entry price and an optional time exit."""
    # A limit fill is managed from the next bar: inside the fill bar the order of prices is unknown, and the bar's
    # excursion is one-sided relative to the order (it traded to the limit), so checking it would favour the
    # original direction over its coin-flipped twin.
    start = j if entry is None else j + 1
    entry = O[j] + d * TICK if entry is None else entry
    flat = amt.FLAT if until is None else min(amt.FLAT, until)
    stop, target = entry - d * stop_d, entry + d * tgt_d
    n = int(min(amt.MAX_CONTRACTS, max(1, math.floor(risk / (stop_d * pv)))))
    worst = best = 0.0
    exit_px, reason = None, "time"
    for i in range(start, len(m)):
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
        if m[i] >= flat:
            exit_px = C[i] - d * TICK
            break
    if exit_px is None:                                    # data ended early (or a fill on the last bar): last close
        exit_px = C[-1] - d * TICK
    fees = 2 * amt.COMMISSION_SIDE * n
    pnl = (exit_px - entry) * d * pv * n - fees
    return dict(pnl=pnl, lo=min(0.0, worst * pv * n - fees, pnl), hi=max(0.0, best * pv * n, pnl),
                r=pnl / (stop_d * pv * n), reason=reason, contracts=n, win=pnl > 0, rr=tgt_d / stop_d)


# ---------------------------------------------------------------- data

def load_extended(symbol: str, until: date) -> dict[date, pd.DataFrame]:
    """amt_lucid_study.load_sessions' sessions, each with its 08:00-09:29 ET bars kept in front of the RTH bars."""
    rth = amt.load_sessions(symbol, until)
    if not rth:
        return {}
    cutoff = min(pd.Timestamp(until + timedelta(days=1), tz=amt.ET), amt.VERIFY_START).tz_convert("UTC")
    files = [f for f in sorted((amt.BARS_DIR / symbol).glob("*.parquet")) if date.fromisoformat(f.name[:10]) < cutoff.date()]
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume"], filters=[("ts_event", "<", cutoff)])
                      for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    et = bars.index.tz_convert(amt.ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    pre = bars[(bars.minute >= PRE_OPEN) & (bars.minute < OPEN) & bars.day.isin(set(rth))]
    out = {}
    for d, g in rth.items():
        p = pre[pre.day == d] if len(pre) else pre
        out[d] = pd.concat([p, g]) if len(p) else g
    n_pre = sum((g.minute < OPEN).any() for g in out.values())
    print(f"{symbol}: {len(out)} sessions, {n_pre} with 08:00-09:29 bars")
    return out


# ---------------------------------------------------------------- rows

def build_rows(sessions: dict, symbol: str) -> dict:
    """{name: {day: None | dict(dir, long, short)}} for this instrument's strategies and the coin flips; days with a
    prior session. Sessions may carry 08:00-09:29 bars in front (load_extended); only range_reclaim reads them."""
    spec = amt.INSTRUMENTS[symbol]
    ratio, pv = spec["ratio"], spec["pv"]
    days = sorted(sessions)
    names = [n for n in STRATEGIES if symbol in TESTS[n]]
    rows = {n: {} for n in (*names, *COINS)}
    rng = np.random.default_rng(SEED)
    rth = lambda g: g[g.minute >= OPEN]
    for prev, d in zip(days, days[1:]):
        p, x = rth(sessions[prev]), sessions[d]
        g = rth(x)
        lv = amt.profile(p, ratio)
        prev_close = p.close.iloc[-1] * ratio
        prev_high, prev_low = p.high.max() * ratio, p.low.min() * ratio
        arr = lambda f: tuple(f[k].to_numpy(dtype=float) * ratio for k in ("open", "high", "low", "close")) + (f.minute.to_numpy(),)
        O, H, L, C, m = rth_arrays = arr(g)
        ext_arrays = arr(x)
        V = g.volume.to_numpy(dtype=float)
        coin = int(rng.choice((-1, 1)))
        make = dict(gap_fill=lambda: signal_gap_fill(prev_close, O, H, L, C, m),
                    sweep=lambda: signal_sweep(prev_high, prev_low, O, H, L, C, m),
                    eighty_pct=lambda: amt.signal_va_reentry(lv, O, H, L, C, m, k=2, target="far_edge"),
                    vwap_fade=lambda: signal_vwap_fade(O, H, L, C, V, m),
                    range_reclaim=lambda: signal_range_reclaim(d, *ext_arrays),
                    orb15_mid=lambda: signal_orb15_mid(O, H, L, C, m),
                    orb_fvg=lambda: signal_orb_fvg(O, H, L, C, m, OF_WIDE[symbol]),
                    cont_fvg=lambda: signal_cont_fvg(prev_high, prev_low, O, H, L, C, m),
                    erl_irl=lambda: signal_erl_irl(prev_high, prev_low, O, H, L, C, m))
        sigs = {n: make[n]() for n in names}
        sigs.update({n: coin_signal(O, m, *pc, coin) for n, pc in COINS.items()})
        for name, sig in sigs.items():
            if sig is None:
                rows[name][d] = None
                continue
            side, j, sd, td, *kw = sig
            kw = kw[0] if kw else {}
            a = ext_arrays if name == "range_reclaim" else rth_arrays
            rows[name][d] = dict(dir=side, long=bracket(*a[:4], a[4], 1, j, sd, td, pv, **kw),
                                 short=bracket(*a[:4], a[4], -1, j, sd, td, pv, **kw))
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
    print(f"{'rule':<13} | {'trades':>6} {'win':>6} {'meanR':>7} {'R 95% CI':>16} {'coinR':>7} {'p_R':>6} | "
          f"{'plan':<4} {'pass':>6} {'paid':>6} {'EV':>7} {'coinEV':>7} {'p_EV':>6}  verdict")
    for name, s in scored.items():
        t = s["trades"]
        if not t.get("trades") or "plans" not in s:
            print(f"{name:<13} | {t.get('trades', 0):>6} trades")
            continue
        head = (f"{name:<13} | {t['trades']:>6} {t['win_rate']:6.1%} {t['mean_r']:+7.3f} "
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
    res = dict(spec=dict(alpha=ALPHA, n_random=N_RANDOM, tests=TESTS, risk_usd=amt.RISK_USD, commission_side=amt.COMMISSION_SIDE,
                         fees={n: f for n, (_, f) in PLANS.items()}), windows={})
    if args.score:
        lock.write_text(f"scored at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
        spy = load_extended("SPY", date(2026, 8, 14))
        first = max(d for d in spy if d <= amt.DISCOVERY_END)    # prior-day levels only; never traded
        sessions = {d: g for d, g in spy.items() if d >= first}
        windows = {"SPY score": sessions}
    else:
        windows = {f"{s} discovery": load_extended(s, amt.DISCOVERY_END) for s in amt.INSTRUMENTS}
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
