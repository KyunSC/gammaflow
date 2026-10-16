"""Lucid write-up: the two "academic" intraday rules from a pasted LucidPro +EV write-up, frozen as written.

The write-up claims a 50K LucidPro account becomes +EV with (A) a volatility-conditioned 15-minute opening-range
breakout (citing Crabel 1990 and Zarattini, Aziz & Barbon 2024) and (B) late-session intraday momentum (citing
Gao, Han, Li & Zhou 2018, JFE). Its simulator assumes the edge (win rate x reward:risk) as an input. This study
measures it. Nothing is tuned: each rule has one specification, copied from the write-up, with every detail the
write-up leaves open pinned below before any number was looked at.

Data: Databento XNAS.ITCH ohlcv-1m, RTH 09:30-15:59 ET, sessions with >= 380 RTH bars, research sessions only
(amt_lucid_study.load_sessions -> holdout.py; the sealed verify block is never read), 2022-01-03 -> 2026-08-14.
    SPY -> MES (x10.05, $5/pt)    QQQ -> MNQ (x41.2, $2/pt)    tick 0.25 on the futures plane.
These bars have been used by earlier studies (lucid_orb: a 1:1 ORB on QQQ; amt_lucid / amt_regime: value-area
setups; close_auction: the overnight close->open). None of them traded 15:30-15:59 momentum or this filtered ORB,
and no parameter here was chosen from them. Rule A is still an ORB on the same QQQ sessions, so its QQQ result
is not a clean out-of-sample test; SPY is. Volume is Nasdaq-only, a proxy for CME volume.

A  orb15 (write-up section 2A)
   - opening range: high / low of the 09:30-09:44 1m bars.
   - RVOL: 09:30-09:44 volume >= 1.25 x the mean of the same window over the previous 20 sessions.
   - compression: range < 0.60 x ATR14, ATR14 = mean RTH true range (prior RTH close) of the previous 14 sessions.
   - entry: the first 1m bar from 09:45 that closes above the range high AND above session VWAP (typical price,
     from 09:30) -> long at the next bar's open + 1 tick; mirror for short. One trade a session. Pinned: no
     signal after 11:30 ET (the write-up gives no cut-off; lucid_orb_study uses 11:30).
   - stop: the range midpoint (the write-up's first option), +1 tick slippage when hit.
   - exit (the write-up's "wide chandelier / VWAP trail", pinned to its VWAP form): the first 1m close on the
     wrong side of session VWAP exits at the next bar's open - 1 tick; else flat at the 15:54 close - 1 tick.
B  itsm (write-up section 2B)
   - r1 = ln(close of the 09:59 bar / prior session's last RTH close); r12 = ln(close 15:29 / close 14:59).
   - filter: sign(r1) == sign(r12) != 0 and |ln(close 15:29 / open 09:30)| > 0.5 x its mean over the previous
     20 sessions.
   - entry: direction sign(r1) at the 15:30 bar's open + 1 tick.
   - stop: 1.2 x (high - low of the 15:00-15:29 bars) from entry, +1 tick slippage when hit.
   - exit: the 15:59 bar's open - 1 tick ("flatten unconditionally at 3:59").
Both: contracts = floor(RISK_USD / (stop_pts x point value)), clamped to [1, 40] micros; a trade whose 1-contract
risk exceeds 2 x RISK_USD is skipped. Commission $1.00 per contract per side. A bar that opens through the stop
fills at its open - 1 tick; a bar that touches it fills the stop - 1 tick.

Scoring (4 tests: 2 rules x 2 instruments, Bonferroni ALPHA = 0.05 / 4):
   - trades: mean net R with a block-bootstrap (5 trades) CI at 1 - ALPHA.
   - B only: random-direction control (same entries, stops and exits, direction a coin, N_RANDOM seeds),
     p on mean net R. A's VWAP exit is direction-bound (a reversed breakout sits on the wrong side of VWAP and
     exits at once), so a random-direction control would be rigged against chance; A instead reports the same
     rule with both filters off, to show what the filters add, as a description, not a test.
   - Lucid: the daily P&L replayed through flybrain.prop.run_prop (LucidPro 50K with the $1,200 DLL, fee $115,
     and LucidFlex 50K without DLL, fee $90), 5,000 bootstrap accounts on 5-session blocks, 250-session horizon.
     Flat sizing; the write-up's three-phase sizing lives in the lifecycle simulator, fed by this R list.
   - zero-edge reference: the same trades with every P&L shifted down by the mean gross P&L (so costs and
     variance stay, the edge goes). EV minus this is the part the rule earns; the rest is the account.
   verdict per rule x instrument, on LucidPro:
      PASS            EV > 0, the CI lower bound > 0, and (B) random p < ALPHA.
      STRUCTURE-ONLY  EV > 0 without the above.
      FAIL            EV <= 0.
One look: --score writes a lock and refuses a second run. Without it, only counts and trade frequencies print.

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
from lucid_orb_study import FLAT_DAY, replay  # noqa: E402

OUT = amt.DATA / "lucid_writeup"
RESEARCH_END = date(2026, 8, 14)
SYMBOLS = ("SPY", "QQQ")
TICK = 0.25
COMMISSION_SIDE = 1.00
MAX_CONTRACTS = 40
RISK_USD = 475.0               # the write-up's evaluation risk per trade
OPEN, OR_END, LAST_SIGNAL, FLAT = 570, 585, 690, 954           # 09:30, 09:45, 11:30, 15:54
B_R1, B_R12_START, B_ENTRY, B_EXIT = 599, 899, 930, 959        # 09:59, 14:59, 15:30, 15:59 bars
RVOL_N, RVOL_X, ATR_N, ATR_X = 20, 1.25, 14, 0.60
MOVE_N, MOVE_X, B_STOP_X = 20, 0.5, 1.2
ALPHA = 0.05 / 4
N_BOOT, BOOT_BLOCK, N_RANDOM, BOOT_PATHS, SEED = 2000, 5, 500, 5000, 42
PLANS = {"pro": (("pro", "50k", True), 115.0), "flex": (("flex", "50k", False), 90.0)}


# ---------------------------------------------------------------- one trade

def manage(O, H, L, C, m, d: int, j: int, stop_d: float, pv: float, exit_at: int, vwap=None) -> dict | None:
    """Stop / VWAP-trail / time exit from entry bar j. P&L, worst and best equity in dollars; None = skipped."""
    entry = O[j] + d * TICK
    stop = entry - d * stop_d
    if stop_d * pv > 2 * RISK_USD:
        return None
    n = int(min(MAX_CONTRACTS, max(1, math.floor(RISK_USD / (stop_d * pv)))))
    worst = best = 0.0
    exit_px, reason = None, "time"
    for i in range(j, len(m)):
        if m[i] >= exit_at and i > j and exit_at == B_EXIT:
            exit_px = O[i] - d * TICK
            break
        adv, fav = (L[i], H[i]) if d > 0 else (H[i], L[i])
        if i > j and (O[i] - stop) * d <= 0:
            exit_px, reason = O[i] - d * TICK, "stop"
        elif (adv - stop) * d <= 0:
            exit_px, reason = stop - d * TICK, "stop"
        if exit_px is not None:
            worst = min(worst, (exit_px - entry) * d)
            break
        worst = min(worst, (adv - entry) * d)
        best = max(best, (fav - entry) * d)
        if vwap is not None and (C[i] - vwap[i]) * d < 0 and i + 1 < len(m) and m[i + 1] < FLAT:
            exit_px, reason = O[i + 1] - d * TICK, "vwap"
            worst = min(worst, (exit_px - entry) * d)
            break
        if exit_at == FLAT and m[i] >= FLAT:
            exit_px = C[i] - d * TICK
            break
    if exit_px is None:                                  # data ended early: last close
        exit_px = C[-1] - d * TICK
    fees = 2 * COMMISSION_SIDE * n
    pnl = (exit_px - entry) * d * pv * n - fees
    risk = stop_d * pv * n
    return dict(pnl=pnl, gross=pnl + fees, lo=min(0.0, worst * pv * n - fees, pnl), hi=max(0.0, best * pv * n, pnl),
                r=pnl / risk, reason=reason, contracts=n, win=pnl > 0)


# ---------------------------------------------------------------- signals

def arrays(g: pd.DataFrame, ratio: float):
    O, H, L, C = (g[k].to_numpy(dtype=float) * ratio for k in ("open", "high", "low", "close"))
    v = g.volume.to_numpy(dtype=float)
    tp = (H + L + C) / 3
    vwap = np.cumsum(tp * v) / np.maximum(np.cumsum(v), 1e-9)
    return O, H, L, C, g.minute.to_numpy(), v, vwap


def orb_signal(O, H, L, C, m, vwap):
    """(direction, entry index, stop distance) of the first breakout bar, or None."""
    rng = m < OR_END
    hi, lo = H[rng].max(), L[rng].min()
    mid = (hi + lo) / 2
    for i in np.flatnonzero(m >= OR_END):
        if m[i] >= LAST_SIGNAL:
            return None
        d = 1 if C[i] > hi and C[i] > vwap[i] else -1 if C[i] < lo and C[i] < vwap[i] else 0
        if d:
            j = i + 1
            if j >= len(m) or m[j] >= FLAT:
                return None
            stop_d = max(TICK, round(((O[j] + d * TICK) - mid) * d / TICK) * TICK)
            return d, j, stop_d
    return None


def bar_at(m, minute):
    k = np.flatnonzero(m == minute)
    return int(k[0]) if len(k) else None


def itsm_features(O, H, L, C, m, prev_close):
    i1, a, b, e = bar_at(m, B_R1), bar_at(m, B_R12_START), bar_at(m, B_ENTRY - 1), bar_at(m, B_ENTRY)
    if None in (i1, a, b, e) or prev_close is None:
        return None
    r1 = math.log(C[i1] / prev_close)
    r12 = math.log(C[b] / C[a])
    move = abs(math.log(C[b] / O[0]))
    rng = H[a + 1:b + 1].max() - L[a + 1:b + 1].min()   # the 15:00-15:29 bars
    return dict(r1=r1, r12=r12, move=move, range=rng, entry=e)


def build(sessions: dict, symbol: str) -> dict:
    """{rule: {day: None | dict(dir, long, short)}}; sessions before every filter has its full history only warm up."""
    spec = amt.INSTRUMENTS[symbol]
    days = sorted(sessions)
    rows = {"orb15": {}, "orb15_unfiltered": {}, "itsm": {}}
    or_vol, tr, moves = [], [], []
    prev_close = None
    for d in days:
        O, H, L, C, m, v, vwap = arrays(sessions[d], spec["ratio"])
        ov = v[m < OR_END].sum()
        or_range = H[m < OR_END].max() - L[m < OR_END].min()
        f = itsm_features(O, H, L, C, m, prev_close)
        warm = len(or_vol) >= RVOL_N and len(tr) >= ATR_N and len(moves) >= MOVE_N
        if warm:
            s = orb_signal(O, H, L, C, m, vwap)
            both = lambda s: None if s is None else dict(
                dir=s[0], long=manage(O, H, L, C, m, 1, s[1], s[2], spec["pv"], FLAT, vwap),
                short=manage(O, H, L, C, m, -1, s[1], s[2], spec["pv"], FLAT, vwap))
            rows["orb15_unfiltered"][d] = both(s)
            ok = ov >= RVOL_X * np.mean(or_vol[-RVOL_N:]) and or_range < ATR_X * np.mean(tr[-ATR_N:])
            rows["orb15"][d] = both(s) if ok else None
            sig = None
            if f and np.sign(f["r1"]) == np.sign(f["r12"]) != 0 and f["move"] > MOVE_X * np.mean(moves[-MOVE_N:]):
                stop_d = max(TICK, round(B_STOP_X * f["range"] / TICK) * TICK)
                sig = dict(dir=int(np.sign(f["r1"])),
                           long=manage(O, H, L, C, m, 1, f["entry"], stop_d, spec["pv"], B_EXIT),
                           short=manage(O, H, L, C, m, -1, f["entry"], stop_d, spec["pv"], B_EXIT))
            rows["itsm"][d] = sig
        or_vol.append(ov)
        pc = prev_close if prev_close is not None else O[0]
        tr.append(max(H.max(), pc) - min(L.min(), pc))
        if f:
            moves.append(f["move"])
        prev_close = C[-1]
    for rule in rows:   # a skipped side (risk too wide) drops the whole day, so controls see the same days
        rows[rule] = {d: (r if r and r["long"] and r["short"] else None) for d, r in rows[rule].items()}
    return rows


# ---------------------------------------------------------------- scoring

def taken(rows: dict, days: list, dirs: dict | None = None) -> list[dict]:
    out = []
    for d in days:
        r = rows[d]
        if r is None:
            out.append(FLAT_DAY)
            continue
        out.append(r["long"] if (dirs or {}).get(d, r["dir"]) > 0 else r["short"])
    return out


def block_ci(r: np.ndarray, alpha: float, seed: int = SEED) -> list[float]:
    rng = np.random.default_rng(seed)
    n, b = len(r), min(BOOT_BLOCK, len(r))
    starts = rng.integers(0, n - b + 1, (N_BOOT, math.ceil(n / b)))
    idx = (starts[:, :, None] + np.arange(b)).reshape(N_BOOT, -1)[:, :n]
    means = r[idx].mean(1)
    return [float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))]


def lucid(trades: list[dict], days: list) -> dict:
    out = {}
    for name, (args, fee) in PLANS.items():
        b = replay(trades, days, resolve_plan(*args), BOOT_PATHS, False)["bootstrap"]
        out[name] = dict(ev=b["meanTake"] - fee, pass_rate=b["passRate"], p_payout=b["pPayout"], mean_payouts=b["meanPayouts"])
    return out


def score(rows: dict, random_control: bool) -> dict:
    days = sorted(rows)
    trades = taken(rows, days)
    t = [x for x in trades if "r" in x]
    if len(t) < 10:
        return dict(trades=len(t))
    r = np.array([x["r"] for x in t])
    mean_gross = float(np.mean([x["gross"] for x in t]))
    demeaned = [x if "r" not in x else {**x, "pnl": x["pnl"] - mean_gross, "lo": x["lo"] - mean_gross,
                                        "hi": x["hi"] - mean_gross} for x in trades]
    out = dict(sessions=len(days), first=str(days[0]), last=str(days[-1]), trades=len(t),
               trade_rate=len(t) / len(days), win_rate=float(np.mean([x["win"] for x in t])),
               mean_r=float(r.mean()), mean_r_ci=block_ci(r, ALPHA), mean_pnl=float(np.mean([x["pnl"] for x in t])),
               mean_cost=float(np.mean([x["gross"] - x["pnl"] for x in t])),
               exits=pd.Series([x["reason"] for x in t]).value_counts(normalize=True).round(3).to_dict(),
               by_year={str(y): dict(n=int(len(g)), mean_r=float(g.mean())) for y, g in
                        pd.Series(r, index=[d.year for d, x in zip(days, trades) if "r" in x]).groupby(level=0)},
               lucid=lucid(trades, days), lucid_zero_edge=lucid(demeaned, days), r_list=[round(float(x), 3) for x in r])
    if random_control:
        rng = np.random.default_rng(SEED + 1)
        live = [d for d in days if rows[d] is not None]
        rs = np.array([np.mean([x["r"] for x in taken(rows, days, {d: int(rng.choice((-1, 1))) for d in live}) if "r" in x])
                       for _ in range(N_RANDOM)])
        out["random"] = dict(mean_r=float(rs.mean()), p=float((1 + (rs >= out["mean_r"]).sum()) / (1 + N_RANDOM)))
    return out


def verdict(s: dict, needs_random: bool) -> str:
    if s.get("trades", 0) < 10 or s["lucid"]["pro"]["ev"] <= 0:
        return "FAIL"
    if s["mean_r_ci"][0] > 0 and (not needs_random or s["random"]["p"] < ALPHA):
        return "PASS"
    return "STRUCTURE-ONLY"


def fmt(s: dict) -> str:
    if s.get("trades", 0) < 10:
        return f"{s.get('trades', 0)} trades"
    p, z = s["lucid"]["pro"], s["lucid_zero_edge"]["pro"]
    f, zf = s["lucid"]["flex"], s["lucid_zero_edge"]["flex"]
    rnd = f"  random R {s['random']['mean_r']:+.3f} p={s['random']['p']:.3f}" if "random" in s else ""
    return (f"{s['trades']:>4} trades ({s['trade_rate']:.0%} of days)  win {s['win_rate']:.0%}  "
            f"mean R {s['mean_r']:+.3f} [{s['mean_r_ci'][0]:+.3f}, {s['mean_r_ci'][1]:+.3f}]  cost ${s['mean_cost']:.0f}/trade{rnd}\n"
            f"      Pro EV ${p['ev']:+.0f} (zero-edge ${z['ev']:+.0f}, pass {p['pass_rate']:.0%})   "
            f"Flex EV ${f['ev']:+.0f} (zero-edge ${zf['ev']:+.0f})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--score", action="store_true", help="score both rules once (writes the lock)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "score.lock"
    if args.score and lock.exists():
        print(f"already scored ({lock.read_text().strip()}); refusing a second look")
        return 1
    built = {}
    for sym in SYMBOLS:
        sessions = amt.load_sessions(sym, RESEARCH_END)
        built[sym] = build(sessions, sym)
        days = sorted(sessions)
        print(f"{sym}: {len(days)} sessions {days[0]} -> {days[-1]}; signal days: " +
              ", ".join(f"{k} {sum(v is not None for v in rows.values())}" for k, rows in built[sym].items()))
    if not args.score:
        print("\ncounts only; run with --score for the one look")
        return 0
    lock.write_text(f"scored at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    res = dict(spec=dict(risk_usd=RISK_USD, commission_side=COMMISSION_SIDE, alpha=ALPHA, plans=PLANS), results={})
    for sym in SYMBOLS:
        fut = amt.INSTRUMENTS[sym]["fut"]
        for rule in ("orb15", "itsm", "orb15_unfiltered"):
            s = score(built[sym][rule], random_control=rule == "itsm")
            if rule != "orb15_unfiltered":
                s["verdict"] = verdict(s, rule == "itsm")
            res["results"][f"{rule}/{fut}"] = s
            tag = f"  -> {s['verdict']}" if "verdict" in s else "  (description)"
            print(f"\n{rule:<17}{fut}: {fmt(s)}{tag}")
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"\nwrote {OUT / 'results.json'} (r_list per rule feeds the lifecycle simulator's empirical mode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
