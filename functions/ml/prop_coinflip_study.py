"""Coin-flip MNQ through a Topstep 50K: a reproduction of Youngblood (2026).

Paper: Z. Youngblood, "The Inherent Value of Retail Prop Firms for Fixed-Size Trading Strategies",
Fordham Gabelli, Aug 2026, SSRN 7514219. Only the abstract was readable from here. Its setup: one trade
a day at 10:00 ET, 8 MNQ, side by coin flip, symmetric 100-tick (25-point, $400) target and stop,
~10 years of 1m NQ data, 10,000 random paths through a modelled Topstep $50K. Reported: win rate
49.98%, about -$24,670 per path on its own after commissions, mean payouts $9,368.50 against $7,878.30
of fees, net +$1,490.19, 39.7% of paths lose, and the two five-year halves differ materially.

Why this needs almost no market data: the side is random, so a day contributes +X or -X with equal odds,
where X is what a long bracket earned that day. Once NQ's 10:00-16:00 move is large next to 25 points
(every year since ~2020), X is +-$400 on nearly every day and the market drops out: the result is a
property of the account rules, the fee schedule and the commission. Only the share of days on which
neither level is hit by 16:00 (and how adverse a winning trade went first) needs real bars.

Day outcomes come from one of:
  --bars PATH   Databento GLBX ohlcv-1m parquet/CSV of one NQ or MNQ series (ts_event, open, high,
                low, close). Sessions <= --end (default 2025-03-26, the project's exploration cap).
                A bar that spans both levels counts as a stop for whichever side is held.
  (default)     Brownian minutes, 10:00-16:00, with a per-year session sd from APPROX_NQ (rough
                public NQ levels and realised vols, written from memory: a stand-in, not data), plus
                fixed-ratio sweeps (bracket / session sd) to show what the unresolved-day share does.

Topstep 50K, Standard path, as published on help.topstep.com and summarised by proptradingvibes.com
(checked 2026-10-24; both linked in the findings note):
  Combine: $49 a month, billed every 21 sessions while in the Combine; each bill carries one free reset,
           further resets $49. Target $3,000 (end of day). Max loss $2,000 trailing the end-of-day
           balance, breached on intraday equity, locking at the starting balance. 55% consistency and
           the optional $1,000 DLL never bind at $400 a day. Passing costs $149 activation and ends the
           subscription.
  XFA:     balance starts at $0, MLL -$2,000 trailing end of day, locks at $0; after the first payout
           the MLL is $0 for good. Standard payout path: 5 winning days (net >= $150) per cycle, request
           up to 50% of the balance, capped at $2,000, minimum $125, profit since the last payout > 0,
           90% to the trader. A breach sends the trader back to a new Combine subscription.
  Not modelled: Live Funded call-ups, Back2Funded, several accounts at once, the consistency payout
  path, scaling-plan limits (8 MNQ = 0.8 lots, under every tier).
Commission: TopstepX MNQ $1.22 round turn per contract (help center), i.e. $9.76 per trade. That alone
reproduces the paper's -$24,670 over ~2,530 trades.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

TICK = 0.25
PT_USD = 2.0                 # MNQ $ per index point
CONTRACTS = 8
BRACKET_TICKS = 100
A_PTS = BRACKET_TICKS * TICK  # 25 points = $400 on 8 MNQ
USD_PER_PT = PT_USD * CONTRACTS
SESSION_MIN = 360            # 10:00 -> 16:00 ET
BILL_SESSIONS = 21           # one monthly bill per 21 sessions in the Combine
EXPLORE_END = "2025-03-26"   # project exploration cap; later sessions are reserved

# Rough NQ (average level, close-to-close annualised vol) per year, from memory of public index history.
# Only used to set how often 25 points is NOT reached by 16:00; the binary regime needs none of it.
APPROX_NQ = {
    2016: (4600, .17), 2017: (5900, .10), 2018: (6900, .22), 2019: (7800, .16), 2020: (10500, .34),
    2021: (14500, .19), 2022: (12500, .31), 2023: (14500, .19), 2024: (19500, .19), 2025: (21000, .23),
    2026: (24000, .18),
}
SESSION_VAR_SHARE = 0.55     # share of daily variance between 10:00 and 16:00 (assumption)


@dataclass(frozen=True)
class Rules:
    monthly: float = 49.0
    reset: float = 49.0
    activation: float = 149.0
    target: float = 3000.0
    max_loss: float = 2000.0
    win_day: float = 150.0
    win_days: int = 5
    payout_frac: float = 0.5
    payout_cap: float = 2000.0
    payout_min: float = 125.0
    split: float = 0.9
    full_split_first: float = 0.0   # lifetime profit paid at 100% before the split applies
    commission: float = 1.22 * CONTRACTS
    stop_slip_ticks: float = 0.0
    mll_zero_after_payout: bool = True  # False: the XFA floor keeps trailing (and locking at $0) after payouts


TOPSTEP_50K = Rules()
VARIANTS = {
    "base (Oct 2026 rules, $1.22 RT)": TOPSTEP_50K,
    "zero commission": replace(TOPSTEP_50K, commission=0.0),
    "half commission ($0.61 RT)": replace(TOPSTEP_50K, commission=0.61 * CONTRACTS),
    "+1 tick slippage on stops": replace(TOPSTEP_50K, stop_slip_ticks=1.0),
    "100% split": replace(TOPSTEP_50K, split=1.0),
    "pre-Jan-2026 signup: 100% of first $10K": replace(TOPSTEP_50K, full_split_first=10000.0),
    "no paid resets (one free reset a month is enough)": replace(TOPSTEP_50K, reset=0.0),
    "XFA floor keeps trailing after payouts": replace(TOPSTEP_50K, mll_zero_after_payout=False),
    "No-Activation path ($95/mo, $0 act.)": replace(TOPSTEP_50K, monthly=95.0, reset=95.0, activation=0.0),
    "activation $299": replace(TOPSTEP_50K, activation=299.0),
    "DLL promo: caps doubled ($4,000)": replace(TOPSTEP_50K, payout_cap=4000.0),
    "payout cap $1,000": replace(TOPSTEP_50K, payout_cap=1000.0),
}


# ---------------------------------------------------------------- day outcomes

@dataclass
class Days:
    """Per session, for each side (0 long, 1 short): exit P&L and worst open P&L, in points."""
    dates: np.ndarray        # datetime64[D]
    x: np.ndarray            # (D, 2)
    mae: np.ndarray          # (D, 2), <= 0
    stopped: np.ndarray      # (D, 2) bool: exit at the stop

    @property
    def resolved_share(self) -> float:
        return float(np.mean(np.abs(self.x[:, 0]) >= A_PTS - 1e-9))


def bracket_from_path(path: np.ndarray, a: float = A_PTS):
    """Exit for a long and a short entered at path[0] == 0 on a (minutes,) price path; each later point
    is a bar with (lo, hi, close). Here path is (n, 3) columns lo, hi, close; returns arrays for
    (long, short): x, mae, stopped. A bar touching both levels is a stop for either side."""
    lo, hi, cl = path[:, 0], path[:, 1], path[:, 2]
    out_x, out_mae, out_stop = np.zeros(2), np.zeros(2), np.zeros(2, bool)
    for side, sgn in ((0, 1.0), (1, -1.0)):
        fav = hi if sgn > 0 else -lo     # best open P&L within each bar
        adv = lo if sgn > 0 else -hi     # worst open P&L within each bar
        stop_i = np.flatnonzero(adv <= -a)
        tgt_i = np.flatnonzero(fav >= a)
        s = stop_i[0] if len(stop_i) else len(cl)
        t = tgt_i[0] if len(tgt_i) else len(cl)
        if s <= t and s < len(cl):
            out_x[side], out_mae[side], out_stop[side] = -a, -a, True
        elif t < len(cl):
            out_x[side] = a
            out_mae[side] = min(0.0, adv[:t].min()) if t else 0.0
        else:
            out_x[side] = sgn * cl[-1]
            out_mae[side] = min(0.0, adv.min())
    return out_x, out_mae, out_stop


def brownian_days(dates: pd.DatetimeIndex, session_sd_pts: np.ndarray, seed: int = 0,
                  steps: int = SESSION_MIN) -> Days:
    """Minute Brownian paths; the long bracket is resolved on minute closes (no bar ranges)."""
    rng = np.random.default_rng(seed)
    n = len(dates)
    inc = rng.standard_normal((n, steps)) * (session_sd_pts[:, None] / np.sqrt(steps))
    p = np.cumsum(inc, axis=1)
    up = p >= A_PTS
    dn = p <= -A_PTS
    first_up = np.where(up.any(1), up.argmax(1), steps)
    first_dn = np.where(dn.any(1), dn.argmax(1), steps)
    x = np.zeros((n, 2))
    mae = np.zeros((n, 2))
    stopped = np.zeros((n, 2), bool)
    run_min = np.minimum(np.minimum.accumulate(p, axis=1), 0.0)
    run_max = np.maximum(np.maximum.accumulate(p, axis=1), 0.0)
    idx = np.arange(n)
    long_tgt = first_up < first_dn
    long_stop = first_dn < first_up
    neither = ~long_tgt & ~long_stop
    # long
    x[long_tgt, 0], x[long_stop, 0] = A_PTS, -A_PTS
    x[neither, 0] = p[neither, -1]
    stopped[long_stop, 0] = True
    pre = np.clip(first_up - 1, 0, steps - 1)
    mae[:, 0] = np.where(long_tgt, np.where(first_up > 0, run_min[idx, pre], 0.0),
                         np.where(long_stop, -A_PTS, run_min[:, -1]))
    # short: mirror
    x[:, 1] = -x[:, 0]
    stopped[long_tgt, 1] = True
    pre = np.clip(first_dn - 1, 0, steps - 1)
    mae[:, 1] = np.where(long_stop, np.where(first_dn > 0, -run_max[idx, pre], 0.0),
                         np.where(long_tgt, -A_PTS, -run_max[:, -1]))
    return Days(dates.values.astype("datetime64[D]"), x, np.maximum(mae, -A_PTS), stopped)


def session_dates(start="2016-06-01", end="2026-06-01") -> pd.DatetimeIndex:
    from pandas.tseries.holiday import USFederalHolidayCalendar
    hol = USFederalHolidayCalendar().holidays(start, end)
    return pd.bdate_range(start, end, freq="C", holidays=hol, inclusive="left")


def approx_session_sd(dates: pd.DatetimeIndex) -> np.ndarray:
    lvl = np.array([APPROX_NQ[d.year][0] for d in dates], float)
    vol = np.array([APPROX_NQ[d.year][1] for d in dates], float)
    return lvl * vol / np.sqrt(252) * np.sqrt(SESSION_VAR_SHARE)


def load_bar_days(path: Path, end: str = EXPLORE_END) -> Days:
    """10:00 ET entry at the 10:00 bar's open, bracket on 1m bars through the 15:59 bar."""
    df = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    ts = pd.to_datetime(df["ts_event"] if "ts_event" in df else df.index, utc=True)
    df = df.assign(t=ts.tz_convert("America/New_York")).set_index("t").sort_index()
    df = df[df.index.date <= pd.Timestamp(end).date()]
    df = df.between_time("10:00", "15:59")
    dates, xs, maes, stops = [], [], [], []
    for d, g in df.groupby(df.index.date):
        if len(g) < 300 or g.index[0].strftime("%H:%M") != "10:00":
            continue
        e = float(g["open"].iloc[0])
        bars = np.column_stack([g["low"] - e, g["high"] - e, g["close"] - e]).astype(float)
        x, m, s = bracket_from_path(bars)
        dates.append(np.datetime64(d, "D")); xs.append(x); maes.append(m); stops.append(s)
    if not dates:
        raise SystemExit(f"no usable sessions in {path} up to {end}")
    return Days(np.array(dates), np.array(xs), np.array(maes), np.array(stops))


# ---------------------------------------------------------------- account replay

def simulate(days: Days, rules: Rules = TOPSTEP_50K, n_paths: int = 10_000, seed: int = 1,
             split_date=None, sides: np.ndarray | None = None) -> dict:
    """Replay every path through Combine -> XFA -> (breach) -> new Combine, one trade a session.
    Cash is trader-side only: + net payouts, - subscription, resets and activation.
    `sides` (sessions, paths) of 0 long / 1 short replaces the coin flips (tests)."""
    rng = np.random.default_rng(seed)
    side = rng.integers(0, 2, size=(len(days.dates), n_paths)) if sides is None else np.asarray(sides)
    D, P = side.shape
    r = rules
    slip = r.stop_slip_ticks * TICK * USD_PER_PT

    phase = np.zeros(P, np.int8)                      # 0 Combine, 1 XFA
    bal = np.zeros(P); peak = np.zeros(P); floor = np.full(P, -r.max_loss)
    next_bill = np.zeros(P, np.int64); credit = np.zeros(P, bool)
    wins = np.zeros(P, np.int64); paid_once = np.zeros(P, bool); last_paid_bal = np.zeros(P)
    lifetime_paid = np.zeros(P)
    fees = np.zeros(P); pay_gross = np.zeros(P); pay_net = np.zeros(P)
    attempts = np.ones(P, np.int64); passes = np.zeros(P, np.int64); n_pay = np.zeros(P, np.int64)
    xfa_breaches = np.zeros(P, np.int64); own = np.zeros(P)
    bills = np.zeros(P, np.int64); paid_resets = np.zeros(P, np.int64)
    split_i = D if split_date is None else int(np.searchsorted(days.dates, np.datetime64(split_date, "D")))
    cash_at_split = np.zeros(P)

    for d in range(D):
        if d == split_i:
            cash_at_split = pay_net - fees
        s = side[d]
        x = days.x[d, s] * USD_PER_PT
        mae = days.mae[d, s] * USD_PER_PT
        pnl = x - r.commission - np.where(days.stopped[d, s], slip, 0.0)
        own += pnl

        comb = phase == 0
        bill = comb & (d >= next_bill)
        fees[bill] += r.monthly
        bills[bill] += 1
        credit[bill] = True
        next_bill[bill] = d + BILL_SESSIONS

        # breach on intraday equity (worst open P&L before the exit), or on the close
        worst = bal + np.minimum(mae - np.where(days.stopped[d, s], slip, 0.0), pnl)
        breach = worst <= floor
        bal = np.where(breach, bal, bal + pnl)

        # Combine
        cb = comb & breach
        fees[cb & ~credit] += r.reset
        paid_resets[cb & ~credit] += 1
        credit[cb] = False
        attempts[cb] += 1
        bal[cb], peak[cb], floor[cb] = 0.0, 0.0, -r.max_loss
        ok = comb & ~breach
        peak[ok] = np.maximum(peak[ok], bal[ok])
        floor[ok] = np.minimum(peak[ok] - r.max_loss, 0.0)
        passed = ok & (bal >= r.target)
        fees[passed] += r.activation
        passes[passed] += 1
        phase[passed] = 1
        bal[passed], peak[passed], floor[passed] = 0.0, 0.0, -r.max_loss
        wins[passed], paid_once[passed], last_paid_bal[passed] = 0, False, 0.0

        # XFA (accounts that just passed start tomorrow)
        xf = (phase == 1) & ~passed
        xb = xf & breach
        xfa_breaches[xb] += 1
        phase[xb] = 0
        next_bill[xb] = d + 1
        attempts[xb] += 1
        bal[xb], peak[xb], floor[xb] = 0.0, 0.0, -r.max_loss
        xo = xf & ~breach
        wins[xo & (pnl >= r.win_day)] += 1
        peak[xo] = np.maximum(peak[xo], bal[xo])
        locked = paid_once[xo] if r.mll_zero_after_payout else np.zeros(xo.sum(), bool)
        floor[xo] = np.where(locked, 0.0, np.minimum(peak[xo] - r.max_loss, 0.0))
        can = xo & (wins >= r.win_days) & (bal > 0) & (~paid_once | (bal > last_paid_bal))
        amt = np.minimum(r.payout_frac * bal, r.payout_cap)
        go = can & (amt >= r.payout_min)
        if go.any():
            a = amt[go]
            full = np.clip(r.full_split_first - lifetime_paid[go], 0.0, a)
            pay_net[go] += full + r.split * (a - full)
            lifetime_paid[go] += a
            pay_gross[go] += a
            n_pay[go] += 1
            bal[go] -= a
            last_paid_bal[go] = bal[go]
            wins[go] = 0
            paid_once[go] = True
            if r.mll_zero_after_payout:
                floor[go] = 0.0

    net = pay_net - fees
    out = dict(net=net, fees=fees, pay_gross=pay_gross, pay_net=pay_net, attempts=attempts,
               passes=passes, payouts=n_pay, xfa_breaches=xfa_breaches, own=own,
               bills=bills, paid_resets=paid_resets)
    if split_date is not None:
        out["first_half"] = cash_at_split
        out["second_half"] = net - cash_at_split
    return out


def summarise(res: dict) -> dict:
    net = res["net"]
    att = res["attempts"].sum()
    return dict(
        mean_net=net.mean(), se=net.std(ddof=1) / np.sqrt(len(net)), sd=net.std(ddof=1),
        p_loss=float(np.mean(net < 0)), p5=np.percentile(net, 5), p50=np.median(net),
        p95=np.percentile(net, 95), payouts_net=res["pay_net"].mean(), payouts_gross=res["pay_gross"].mean(),
        fees=res["fees"].mean(), attempts=res["attempts"].mean(), pass_rate=res["passes"].sum() / att,
        n_payouts=res["payouts"].mean(), own=res["own"].mean(),
        per_attempt=net.sum() / att, bills=res["bills"].mean(), paid_resets=res["paid_resets"].mean(),
        passes=res["passes"].mean(), xfa_breaches=res["xfa_breaches"].mean(),
        first_half=res.get("first_half", np.array([np.nan])).mean(),
        second_half=res.get("second_half", np.array([np.nan])).mean(),
    )


def fmt_row(name: str, s: dict) -> str:
    return (f"| {name} | {s['mean_net']:+,.0f} ± {1.96 * s['se']:,.0f} | {s['p_loss']:.0%} | "
            f"{s['payouts_net']:,.0f} | {s['fees']:,.0f} | {s['pass_rate']:.1%} | {s['n_payouts']:.1f} | "
            f"{s['per_attempt']:+,.1f} |")


HEADER = ("| setup | mean net per path (95% CI) | paths losing | net payouts | fees | pass rate | "
          "payouts/path | net per Combine attempt |\n|---|---:|---:|---:|---:|---:|---:|---:|")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bars", type=Path, help="Databento ohlcv-1m file for one NQ/MNQ series")
    ap.add_argument("--end", default=EXPLORE_END, help="last session read from --bars (inclusive)")
    ap.add_argument("--paths", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    if args.bars:
        days = load_bar_days(args.bars, args.end)
        dates = pd.DatetimeIndex(days.dates)
        regimes = {f"real bars {dates[0].date()}..{dates[-1].date()}": days}
    else:
        dates = session_dates()
        regimes = {"approx NQ history 2016-06..2026-05": brownian_days(dates, approx_session_sd(dates))}
        for k in (0.1, 0.5, 0.75, 1.0, 1.5):
            regimes[f"bracket = {k:g} x session sd"] = brownian_days(dates, np.full(len(dates), A_PTS / k), seed=7)
    split = str(dates[len(dates) // 2].date())

    print(f"{len(dates)} sessions, {dates[0].date()} .. {dates[-1].date()}, halves split at {split}\n")
    print("Regimes, base Topstep rules:\n")
    print(HEADER.replace("| setup |", "| regime (share of days hitting a level) |"))
    for name, days in regimes.items():
        s = summarise(simulate(days, TOPSTEP_50K, args.paths, args.seed, split))
        print(fmt_row(f"{name} ({days.resolved_share:.0%})", s))
        print(f"|  ↳ own money {s['own']:+,.0f}; halves {s['first_half']:+,.0f} / {s['second_half']:+,.0f}; "
              f"sd {s['sd']:,.0f}; p5/p50/p95 {s['p5']:+,.0f}/{s['p50']:+,.0f}/{s['p95']:+,.0f} |||||||")

    base_days = next(iter(regimes.values()))
    print("\nRule and cost variants on the first regime:\n")
    print(HEADER)
    for name, rules in VARIANTS.items():
        print(fmt_row(name, summarise(simulate(base_days, rules, args.paths, args.seed, split))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
