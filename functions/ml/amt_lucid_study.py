"""AMT for Lucid: three auction-market-theory setups, sized for a LucidFlex 50K account.

lucid_orb_study.py found that a 1:1 opening-range breakout has no entry edge; its small positive Lucid EV
was the firm's payout asymmetry. This study asks the same question of three classic Auction Market Theory
(value-area) setups, built from the prior RTH session's volume profile.

Rules (fixed before any number was looked at):
  - data: Databento XNAS.ITCH ohlcv-1m, RTH 09:30-15:59 ET, sessions with >= 380 RTH bars, research
    sessions only (holdout.py; the sealed verify block is never read).
      QQQ -> MNQ  (x41.2, $2/pt)    SPY -> MES  (x10.05, $5/pt)    tick 0.25 on the futures plane.
    Ratios as in the app's prop mode / flybrain; basis, rolls and Globex are ignored. Volume is Nasdaq-only
    (XNAS), a proxy for the consolidated / CME profile.
  - split (pinned dates, not a fraction):
      discovery  QQQ + SPY sessions <= DISCOVERY_END (2025-03-26).
      holdout    SPY sessions after DISCOVERY_END (to the research end, 2026-08-14), scored ONCE (--holdout).
    QQQ after 2025-03-26 is never loaded: it was spent as the Lucid ORB one-look holdout.
  - profile: each prior-session 1m bar's volume spread evenly over the $0.01 bins in [low, high]. POC = the
    bin with the most volume (ties -> nearest the session mid). Value area = from the POC add the larger
    neighbouring bin until >= 70% of the volume. VAH / VAL / POC are moved to the futures plane, rounded to
    the tick. Prior-day high / low come from the same bars.
  - setups (at most one trade per setup per session; signals use closed bars only; entry = the next 1m
    bar's open + 1 tick adverse; no entry after LAST_ENTRY = 14:00 ET):
      A  va_reentry ("80% rule", responsive). Open (09:30 bar open) outside the prior VA. Trigger: K
         consecutive 30m periods (09:30-anchored) close inside the VA. Trade toward the far side: opened
         above -> short. Stop: the session extreme on the open side so far, +1 tick. Target: the far VA edge
         or the prior POC (grid). Skipped if the target is not at least MIN_RR x the stop distance away.
         grid: K in {1, 2} x target in {far_edge, poc}.
      B  ov_accept (open outside value, accepted -> initiative continuation). Open above the prior VAH (or
         above the prior high: grid) and the first 30m period never trades back into the VA (low > VAH) and
         closes above the open-side reference -> long at the 10:00 bar; mirror for below. Stop: the first
         30m period's opposite extreme -1 tick. Target: R x the stop distance (grid).
         grid: reference in {va, range} x R in {1, 2}.
      C  va_fail (open inside value, failed probe at a VA edge -> fade, responsive). Open inside the prior
         VA. From 09:30, the first time price trades a tick beyond VAH (VAL) and then a P-minute period
         (09:30-anchored) closes back inside the VA -> short (long). Stop: the probe extreme +1 tick.
         Target: the prior POC or the far VA edge (grid). Same MIN_RR skip as A. One attempt per session
         (the first probe that resolves either way).
         grid: P in {5, 15} x target in {poc, far_edge}.
  - bracket: managed on 1m bars from the entry bar. A bar that opens through a level fills at its open (stop:
    +1 tick slippage). A bar that touches both fills the stop. The target fills only when price trades a
    tick THROUGH it. Otherwise flat at the 15:54 bar's close - 1 tick. (fill_study.py: tick-through targets
    ~ real fills; mean stop slip ~1.1 ticks.)
  - size: contracts = floor(RISK_USD / (stop_pts * point_value)), clamped to [1, 40] micros. Commission
    $1.00 per contract per side.
  - account: LucidFlex 50K, no daily loss limit, replayed with lucid_orb_study.replay (flybrain.prop.run_prop,
    5000 bootstrap accounts on 5-session blocks, 250-session horizon). EV = 90% of payouts - $90 fee.
  - selection (discovery only): per setup, among cells with >= MIN_TRADES trades on EACH of QQQ and SPY and a
    positive mean net R on BOTH, the one with the highest pooled mean net R. A setup without such a cell is
    dropped and never scored on the holdout.
  - holdout verdict per selected setup (SPY, $90 fee), with a Bonferroni alpha = 0.05 / 3:
      PASS            EV > 0, mean net R > 0 with the 95% block-bootstrap CI above 0, and random-direction
                      p < alpha (N_RANDOM seeds: same entries and stop / target distances, direction a coin).
      STRUCTURE-ONLY  EV > 0 without the above: profit comes from the account's payout asymmetry.
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
from flybrain.prop import resolve_plan  # noqa: E402
from lucid_orb_study import FLAT_DAY, replay, trade_stats, ev  # noqa: E402

ET = "America/New_York"
DATA = HERE / "data"
OUT = DATA / "amt_lucid"
BARS_DIR = DATA / "databento" / "eq-ohlcv-1m"

DISCOVERY_END = date(2025, 3, 26)
INSTRUMENTS = {"QQQ": dict(ratio=41.2, pv=2.0, fut="MNQ"), "SPY": dict(ratio=10.05, pv=5.0, fut="MES")}
HOLDOUT_SYMBOL = "SPY"
TICK = 0.25
COMMISSION_SIDE = 1.00
MAX_CONTRACTS = 40
RISK_USD = 750.0
OPEN, LAST_ENTRY, FLAT, CLOSE = 570, 840, 954, 960   # 09:30, 14:00, 15:54, 16:00 ET
MIN_BARS = 380
VA_PCT = 0.70
MIN_RR = 0.5
MIN_TRADES = 40
EVAL_FEE = 90.0
ALT_FEE = 130.0
BOOT_PATHS = 5000
CONTROL_PATHS = 2000
N_RANDOM = 200
ALPHA = 0.05 / 3
SEED = 42

GRID = {
    "va_reentry": [dict(k=k, target=t) for k in (1, 2) for t in ("far_edge", "poc")],
    "ov_accept": [dict(ref=r, rr=x) for r in ("va", "range") for x in (1.0, 2.0)],
    "va_fail": [dict(p=p, target=t) for p in (5, 15) for t in ("poc", "far_edge")],
}


def cell_name(setup: str, params: dict) -> str:
    return setup + "/" + "/".join(f"{k}={v}" for k, v in params.items())


# ---------------------------------------------------------------- data

def load_sessions(symbol: str, until: date) -> dict[date, pd.DataFrame]:
    """RTH 1m bars per session for sessions <= `until` (and inside the research side of holdout.py)."""
    cutoff = min(pd.Timestamp(until + pd.Timedelta(days=1), tz=ET), VERIFY_START).tz_convert("UTC")
    files = [f for f in sorted((BARS_DIR / symbol).glob("*.parquet")) if date.fromisoformat(f.name[:10]) < cutoff.date()]
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume"], filters=[("ts_event", "<", cutoff)])
                      for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    assert (bars.index < cutoff).all(), "LEAK: bar read reaches past the cutoff"
    et = bars.index.tz_convert(ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= OPEN) & (bars.minute < CLOSE)]
    # the verify gap belongs to the sessions just before VERIFY_START, not to the end of a truncated load
    keep = set(research_sessions(sorted(set(bars.day)))) if cutoff >= VERIFY_START else set(bars.day)
    out = {}
    for d, g in bars.groupby("day", sort=True):
        if d in keep and d <= until and len(g) >= MIN_BARS and g.minute.iloc[0] == OPEN and g.minute.iloc[-1] >= FLAT:
            out[d] = g
    return out


def profile(g: pd.DataFrame, ratio: float) -> dict:
    """Prior-session levels on the futures plane: VAH, VAL, POC, high, low."""
    lo_c = np.round(g.low.to_numpy() * 100).astype(np.int64)
    hi_c = np.round(g.high.to_numpy() * 100).astype(np.int64)
    base = lo_c.min()
    vols = np.zeros(hi_c.max() - base + 1)
    for lo, hi, v in zip(lo_c - base, hi_c - base, g.volume.to_numpy(dtype=float)):
        vols[lo:hi + 1] += v / (hi - lo + 1)
    return value_area(vols, base, ratio)


def value_area(vols: np.ndarray, base_cents: int, ratio: float) -> dict:
    n = len(vols)
    mid = (n - 1) / 2
    peak = vols.max()
    cands = np.flatnonzero(vols == peak)
    poc = int(cands[np.argmin(np.abs(cands - mid))])
    lo = hi = poc
    acc, total = vols[poc], vols.sum()
    while acc < VA_PCT * total and (lo > 0 or hi < n - 1):
        up = vols[hi + 1] if hi < n - 1 else -1.0
        dn = vols[lo - 1] if lo > 0 else -1.0
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    fut = lambda i: round((base_cents + i) / 100 * ratio / TICK) * TICK
    return dict(vah=fut(hi), val=fut(lo), poc=fut(poc), high=fut(n - 1), low=fut(0))


# ---------------------------------------------------------------- signals

def periods(m: np.ndarray, length: int) -> list[tuple[int, int]]:
    """(first index, last index) of each `length`-minute period, 09:30-anchored, in bar order."""
    b = (m - OPEN) // length
    edges = np.flatnonzero(np.diff(b)) + 1
    starts = np.r_[0, edges]
    ends = np.r_[edges - 1, len(m) - 1]
    return list(zip(starts.tolist(), ends.tolist()))


def plan_trade(d: int, j: int, stop: float, target_px: float | None, rr: float | None, O: np.ndarray, m: np.ndarray):
    """Turn a signal into (dir, entry index, stop distance, target distance), or None."""
    if j >= len(m) or m[j] >= LAST_ENTRY:
        return None
    entry = O[j] + d * TICK
    stop_d = (entry - stop) * d
    if stop_d < TICK:
        return None
    if rr is not None:
        tgt_d = max(TICK, round(rr * stop_d / TICK) * TICK)
    else:
        tgt_d = (target_px - entry) * d
        if tgt_d < MIN_RR * stop_d:
            return None
    return d, j, stop_d, tgt_d


def signal_va_reentry(lv: dict, O, H, L, C, m, k: int, target: str):
    o = O[0]
    if lv["val"] <= o <= lv["vah"]:
        return None
    d = -1 if o > lv["vah"] else 1
    run = 0
    for s, e in periods(m, 30):
        if m[e] + 1 > LAST_ENTRY:
            return None
        run = run + 1 if lv["val"] <= C[e] <= lv["vah"] else 0
        if run >= k:
            stop = (H[:e + 1].max() + TICK) if d < 0 else (L[:e + 1].min() - TICK)
            far = lv["val"] if d < 0 else lv["vah"]
            return plan_trade(d, e + 1, stop, far if target == "far_edge" else lv["poc"], None, O, m)
    return None


def signal_ov_accept(lv: dict, O, H, L, C, m, ref: str, rr: float):
    o = O[0]
    up_ref, dn_ref = (lv["vah"], lv["val"]) if ref == "va" else (lv["high"], lv["low"])
    d = 1 if o > up_ref else -1 if o < dn_ref else 0
    if not d:
        return None
    s, e = periods(m, 30)[0]
    if d > 0 and L[s:e + 1].min() > lv["vah"] and C[e] > up_ref:
        return plan_trade(1, e + 1, L[s:e + 1].min() - TICK, None, rr, O, m)
    if d < 0 and H[s:e + 1].max() < lv["val"] and C[e] < dn_ref:
        return plan_trade(-1, e + 1, H[s:e + 1].max() + TICK, None, rr, O, m)
    return None


def signal_va_fail(lv: dict, O, H, L, C, m, p: int, target: str):
    o = O[0]
    if not (lv["val"] <= o <= lv["vah"]):
        return None
    for s, e in periods(m, p):
        if m[e] + 1 > LAST_ENTRY:
            return None
        above = H[:e + 1].max() >= lv["vah"] + TICK
        below = L[:e + 1].min() <= lv["val"] - TICK
        if not (above or below):
            continue
        if above and below:   # both edges probed before any resolution: no clean failure
            return None
        d = -1 if above else 1
        if lv["val"] <= C[e] <= lv["vah"]:
            stop = (H[:e + 1].max() + TICK) if d < 0 else (L[:e + 1].min() - TICK)
            far = lv["val"] if d < 0 else lv["vah"]
            return plan_trade(d, e + 1, stop, lv["poc"] if target == "poc" else far, None, O, m)
        return None           # the probe was accepted (closed outside): no fade this session
    return None


SIGNALS = {"va_reentry": signal_va_reentry, "ov_accept": signal_ov_accept, "va_fail": signal_va_fail}


# ---------------------------------------------------------------- execution

def bracket(O, H, L, C, m, d: int, j: int, stop_d: float, tgt_d: float, pv: float) -> dict:
    """Net P&L and the worst / best equity of one bracket trade, in dollars."""
    entry = O[j] + d * TICK
    stop, target = entry - d * stop_d, entry + d * tgt_d
    n = int(min(MAX_CONTRACTS, max(1, math.floor(RISK_USD / (stop_d * pv)))))
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
    pnl = (exit_px - entry) * d * pv * n - fees
    return dict(pnl=pnl, lo=min(0.0, worst * pv * n - fees, pnl), hi=max(0.0, best * pv * n, pnl),
                r=pnl / (stop_d * pv * n), reason=reason, contracts=n, win=pnl > 0, rr=tgt_d / stop_d)


def build_rows(sessions: dict, symbol: str) -> dict:
    """{cell: {day: None | dict(dir, long, short)}} for every cell of every setup, days with a prior session."""
    spec = INSTRUMENTS[symbol]
    days = sorted(sessions)
    rows = {cell_name(s, p): {} for s, ps in GRID.items() for p in ps}
    for prev, d in zip(days, days[1:]):
        lv = profile(sessions[prev], spec["ratio"])
        g = sessions[d]
        O, H, L, C = (g[k].to_numpy() * spec["ratio"] for k in ("open", "high", "low", "close"))
        m = g.minute.to_numpy()
        for setup, ps in GRID.items():
            for p in ps:
                sig = SIGNALS[setup](lv, O, H, L, C, m, **p)
                if sig is None:
                    rows[cell_name(setup, p)][d] = None
                    continue
                side, j, sd, td = sig
                rows[cell_name(setup, p)][d] = dict(
                    dir=side, long=bracket(O, H, L, C, m, 1, j, sd, td, spec["pv"]),
                    short=bracket(O, H, L, C, m, -1, j, sd, td, spec["pv"]))
    return rows


# ---------------------------------------------------------------- scoring

def day_trades(rows: dict, days: list[date], dirs: dict | None = None) -> list[dict]:
    out = []
    for d in days:
        r = rows[d]
        if r is None:
            out.append(FLAT_DAY)
            continue
        side = (dirs or {}).get(d, r["dir"])
        out.append(r["long"] if side > 0 else r["short"])
    return out


def net_r(rows: dict) -> np.ndarray:
    return np.array([(r["long"] if r["dir"] > 0 else r["short"])["r"] for r in rows.values() if r is not None])


def score(rows: dict, plan: dict, with_controls: bool) -> dict:
    days = sorted(rows)
    trades = day_trades(rows, days)
    if not any("r" in t for t in trades):
        return dict(sessions=len(days), trades=dict(trades=0))
    rep = replay(trades, days, plan, BOOT_PATHS, True)
    taken = [t for t in trades if "r" in t]
    out = dict(sessions=len(days), first=str(days[0]), last=str(days[-1]), trades=trade_stats(trades), lucid=rep,
               ev=ev(rep, EVAL_FEE), ev_alt_fee=ev(rep, ALT_FEE), median_rr=float(np.median([t["rr"] for t in taken])))
    if with_controls:
        cell_ev = ev(replay(trades, days, plan, CONTROL_PATHS, False), EVAL_FEE)
        rng = np.random.default_rng(SEED + 1)
        evs, rs = [], []
        for _ in range(N_RANDOM):
            dirs = {d: int(rng.choice((-1, 1))) for d in days if rows[d] is not None}
            tr = day_trades(rows, days, dirs)
            evs.append(ev(replay(tr, days, plan, CONTROL_PATHS, False), EVAL_FEE))
            rs.append(np.mean([t["r"] for t in tr if "r" in t]))
        evs, rs = np.array(evs), np.array(rs)
        fade = day_trades(rows, days, {d: -rows[d]["dir"] for d in days if rows[d] is not None})
        out["controls"] = dict(
            ev_at_control_paths=cell_ev,
            fade=dict(mean_r=trade_stats(fade)["mean_r"], ev=ev(replay(fade, days, plan, BOOT_PATHS, False), EVAL_FEE)),
            random=dict(ev_mean=float(evs.mean()), ev_p05=float(np.quantile(evs, .05)), ev_p95=float(np.quantile(evs, .95)),
                        p=float((1 + (evs >= cell_ev).sum()) / (1 + N_RANDOM)),
                        mean_r=float(rs.mean()), p_r=float((1 + (rs >= out["trades"]["mean_r"]).sum()) / (1 + N_RANDOM))))
    return out


def verdict(h: dict) -> str:
    if h["ev"] <= 0:
        return "FAIL"
    if h["trades"]["mean_r_ci"][0] > 0 and h["controls"]["random"]["p"] < ALPHA:
        return "PASS"
    return "STRUCTURE-ONLY"


def select(disc: dict) -> dict:
    """Per setup: the eligible cell with the highest pooled mean net R, or None."""
    chosen = {}
    for setup, ps in GRID.items():
        best = None
        for p in ps:
            name = cell_name(setup, p)
            per = {s: net_r(disc[s][name]) for s in INSTRUMENTS}
            if any(len(r) < MIN_TRADES or r.mean() <= 0 for r in per.values()):
                continue
            pooled = float(np.concatenate(list(per.values())).mean())
            if best is None or pooled > best[1]:
                best = (name, pooled)
        chosen[setup] = best and dict(cell=best[0], pooled_mean_r=best[1])
    return chosen


# ---------------------------------------------------------------- main

def fmt(s: dict) -> str:
    t = s["trades"]
    if not t["trades"]:
        return "     0 trades"
    b = s["lucid"]["bootstrap"]
    return (f"{t['trades']:>6} {t['win_rate']:6.1%} {t['mean_r']:+7.3f} [{t['mean_r_ci'][0]:+.3f},{t['mean_r_ci'][1]:+.3f}] "
            f"{s['median_rr']:5.2f} | {b['passRate']:6.1%} {b['pPayout']:6.1%} {s['ev']:+8.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--holdout", action="store_true", help=f"score the selected cells on {HOLDOUT_SYMBOL} holdout (one look)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "holdout.lock"
    if args.holdout and lock.exists():
        print(f"holdout already scored ({lock.read_text().strip()}); refusing a second look")
        return 1

    plan = resolve_plan("flex", "50k", False)
    disc_rows, disc = {}, {}
    hdr = f"{'cell':<34} | {'trades':>6} {'win':>6} {'meanR':>7} {'R 95% CI':>16} {'rr':>5} | {'pass':>6} {'payout':>6} {'EV':>8}"
    for sym in INSTRUMENTS:
        sessions = load_sessions(sym, DISCOVERY_END)
        days = sorted(sessions)
        print(f"\n{sym} -> {INSTRUMENTS[sym]['fut']} DISCOVERY  {len(days)} sessions {days[0]} -> {days[-1]}")
        print(hdr)
        disc_rows[sym] = build_rows(sessions, sym)
        disc[sym] = {}
        for name, rows in disc_rows[sym].items():
            disc[sym][name] = score(rows, plan, False)
            print(f"{name:<34} | {fmt(disc[sym][name])}")

    chosen = select(disc_rows)
    print("\nSELECTION (>= %d trades and mean R > 0 on both; max pooled mean R)" % MIN_TRADES)
    for setup, c in chosen.items():
        msg = "-- dropped (no eligible cell)" if c is None else f"{c['cell']}  pooled R {c['pooled_mean_r']:+.3f}"
        print(f"  {setup:<11} {msg}")

    res = dict(spec=dict(instruments=INSTRUMENTS, risk_usd=RISK_USD, commission_side=COMMISSION_SIDE, fee=EVAL_FEE,
                         discovery_end=str(DISCOVERY_END), alpha=ALPHA, plan=plan),
               discovery=disc, selected=chosen)
    live = {s: c for s, c in chosen.items() if c}
    for setup, c in live.items():
        for sym in INSTRUMENTS:
            ctl = score(disc_rows[sym][c["cell"]], plan, True)["controls"]
            res.setdefault("discovery_controls", {}).setdefault(setup, {})[sym] = ctl
            print(f"  {setup} {sym} controls: random-dir EV {ctl['random']['ev_mean']:+.1f} p={ctl['random']['p']:.3f}, "
                  f"random-dir R {ctl['random']['mean_r']:+.3f} p_R={ctl['random']['p_r']:.3f}, fade R {ctl['fade']['mean_r']:+.3f}")

    if args.holdout:
        if not live:
            print("\nno setup selected; the holdout is left untouched")
        else:
            lock.write_text(" ".join(c["cell"] for c in live.values()) + f" at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
            sessions = load_sessions(HOLDOUT_SYMBOL, VERIFY_START.date())
            hold_days = [d for d in sorted(sessions) if d > DISCOVERY_END]
            prev = max(d for d in sessions if d <= DISCOVERY_END)
            sessions = {d: sessions[d] for d in [prev] + hold_days}
            rows = build_rows(sessions, HOLDOUT_SYMBOL)
            print(f"\nHOLDOUT (one look)  {HOLDOUT_SYMBOL} {hold_days[0]} -> {hold_days[-1]}, {len(hold_days)} sessions, alpha {ALPHA:.4f}")
            res["holdout"] = {}
            for setup, c in live.items():
                h = score(rows[c["cell"]], plan, True)
                h["verdict"] = verdict(h) if h["trades"]["trades"] else "FAIL"
                res["holdout"][setup] = dict(cell=c["cell"], **h)
                print(f"{c['cell']:<34} | {fmt(h)}")
                if h["trades"]["trades"]:
                    r = h["controls"]["random"]
                    print(f"    exits {h['trades']['exits']}; EV@$130 {h['ev_alt_fee']:+.1f}; historical-start EV "
                          f"{h['lucid']['historical']['meanTake'] - EVAL_FEE:+.1f}")
                    print(f"    random-dir EV {r['ev_mean']:+.1f} [{r['ev_p05']:+.1f},{r['ev_p95']:+.1f}] p={r['p']:.3f}; "
                          f"random-dir R {r['mean_r']:+.3f} p_R={r['p_r']:.3f}; fade R {h['controls']['fade']['mean_r']:+.3f}")
                print(f"    VERDICT: {h['verdict']}")
    (OUT / ("results.json" if args.holdout else "discovery.json")).write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
