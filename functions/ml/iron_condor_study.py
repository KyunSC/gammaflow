"""Unhedged 0DTE iron condor on QQQ/SPY: does the premium survive four bid/ask spreads?

The negative-RR trade with its stop outside the volatility range, in the instrument that pays for
it. expected_move_study.py showed the futures bracket has no edge; delta_hedge.py showed a hedged ATM
0DTE straddle keeps 4-6% of premium. This asks whether a defined-risk, unhedged version keeps any.

Rules, one condor per session:
  - entry: 09:35 ET, the first quoted bar (see delta_hedge.py). Same-day expiry only, so 2022 is
    Mon/Wed/Fri. NYSE half days are skipped.
  - range: sigma = ATM straddle mid at entry x sqrt(pi/2), the dollar 1-sigma move to the close.
  - strikes: nearest listed strike to spot +/- k sigma. Shorts need bid > 0 and ask > 0, wings need
    ask > 0. A strike more than MAX_MISS sigma from its target skips the day.
  - fills: `full` sells at the bid and buys at the ask on all four legs (primary, as delta_hedge);
    `half` pays half of that, `mid` none. COMMISSION_LEG per leg at entry.
  - exit: held to expiry, settled at intrinsic on the 16:00 underlying. No exit spread or fee.
  - R: P&L / (widest wing - credit + fees), the most the condor can lose.

Discovery only: START -> END is every date this script can read. The later QQQ/SPY sessions and the
sealed verify block are out of reach here on purpose. 2016-2021 Mon/Wed/Fri expiries are also unread.

--count needs no outcome, --freeze pins the spec hash in iron_condor_prereg.json, and --explore
refuses to compute P&L unless that hash still matches.

Outputs: data/iron_condor/{trigger_counts.json, results.json, days.parquet}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import delta_hedge as dh  # noqa: E402

OUT = HERE / "data" / "iron_condor"
PREREG = HERE / "iron_condor_prereg.json"
SPEC_FILES = (HERE / "iron_condor_study.py", HERE / "delta_hedge.py")

START, END = date(2022, 1, 3), date(2025, 3, 26)
SYMBOLS = ("QQQ", "SPY")
CELLS = {"ic_1.0_2.0": (1.0, 2.0), "ic_0.75_1.75": (0.75, 1.75), "ic_1.5_2.5": (1.5, 2.5), "fly_0_1.0": (0.0, 1.0)}
PRIMARY = "ic_1.0_2.0"
FILLS = {"full": 1.0, "half": 0.5, "mid": 0.0}
COMMISSION_LEG = 0.65
LEGS = 4
MAX_MISS = 0.25  # sigma
ATM_TO_SIGMA = math.sqrt(math.pi / 2)
MIN_DAYS = 300
ALPHA_OTHER = 0.05 / len(CELLS)  # a non-primary cell needs a Bonferroni CI to count
GATE = dict(net_r_positive_both=True, pooled_ci_above_zero=0.95, years_positive=3, double_commission_positive=True)
SEED = 20261101


def pick(chain: pd.DataFrame, target: float, call: bool, sigma: float, need_bid: bool) -> dict | None:
    """Nearest usable strike to target, or None when none lies within MAX_MISS sigma."""
    c = chain[(chain["call"] == call) & (chain["ask"] > 0) & (chain["ask"] >= chain["bid"]) & (chain["bid"] >= 0)]
    if need_bid:
        c = c[c["bid"] > 0]
    if c.empty:
        return None
    r = c.iloc[int(np.argmin(np.abs(c["strike"].to_numpy(float) - target)))]
    if abs(float(r["strike"]) - target) > MAX_MISS * sigma:
        return None
    return dict(K=float(r["strike"]), bid=float(r["bid"]), ask=float(r["ask"]))


def build_legs(chain: pd.DataFrame, S: float, sigma: float, ks: float, kw: float) -> dict | None:
    """The four legs of a cell, or None when the chain can't carry it."""
    legs = dict(sc=pick(chain, S + ks * sigma, True, sigma, True), sp=pick(chain, S - ks * sigma, False, sigma, True),
                lc=pick(chain, S + kw * sigma, True, sigma, False), lp=pick(chain, S - kw * sigma, False, sigma, False))
    if any(v is None for v in legs.values()):
        return None
    if legs["lc"]["K"] <= legs["sc"]["K"] or legs["lp"]["K"] >= legs["sp"]["K"]:
        return None
    return legs


def condor(legs: dict, close: float, fill: float, commission: float = COMMISSION_LEG) -> dict | None:
    """Dollar P&L of one condor settled at close, or None when no positive credit or risk exists."""
    mid = {k: (v["bid"] + v["ask"]) / 2 for k, v in legs.items()}
    sold = {k: mid[k] - fill * (mid[k] - legs[k]["bid"]) for k in ("sc", "sp")}
    paid = {k: mid[k] + fill * (legs[k]["ask"] - mid[k]) for k in ("lc", "lp")}
    credit = sum(sold.values()) - sum(paid.values())
    width = max(legs["lc"]["K"] - legs["sc"]["K"], legs["sp"]["K"] - legs["lp"]["K"])
    fees = LEGS * commission
    risk = 100 * (width - credit) + fees
    if credit <= 0 or risk <= 0:
        return None
    payoff = (max(close - legs["sc"]["K"], 0) - max(close - legs["lc"]["K"], 0)
              + max(legs["sp"]["K"] - close, 0) - max(legs["lp"]["K"] - close, 0))
    pnl = 100 * (credit - payoff) - fees
    return dict(pnl=pnl, risk=risk, r=pnl / risk, credit=credit, width=width)


def chain_at_entry(symbol: str, day: date, exp: str) -> pd.DataFrame:
    path = dh.IV_ROOT / f"symbol={symbol}" / f"date={day.isoformat()}" / "part.parquet"
    df = pd.read_parquet(path, columns=dh.COLS, filters=[("expiration", "==", exp)])
    at0 = df[df["timestamp"].dt.tz_convert(dh.ET) == pd.Timestamp(f"{day} {dh.ENTRY}", tz=dh.ET)].copy()
    at0["call"] = at0["right"].astype(str).str.upper().str[0] == "C"
    return at0[["strike", "call", "bid", "ask"]]


def entry_day(symbol: str, day: date) -> dict | None:
    """Everything known at 09:35. The close stays in `_d` for run_day and is never used here."""
    d = dh.load_day(symbol, day, 0)
    if d is None or not d["settle"]:
        return None
    S = float(d["S"][0])
    sigma = (float(d["call_mid"][0]) + float(d["put_mid"][0])) * ATM_TO_SIGMA
    if not np.isfinite(sigma) or sigma <= 0:
        return None
    chain = chain_at_entry(symbol, day, d["expiration"])
    legs = {}
    for name, (ks, kw) in CELLS.items():
        legs[name] = build_legs(chain, S, sigma, ks, kw)
    return dict(S=S, sigma=sigma, legs=legs, _d=d)


def count_day(args: tuple[str, date]) -> dict:
    symbol, day = args
    e = entry_day(symbol, day)
    if e is None:
        return dict(symbol=symbol, day=day.isoformat(), eligible=False)
    return dict(symbol=symbol, day=day.isoformat(), eligible=True, sigma_pct=e["sigma"] / e["S"],
                **{name: v is not None for name, v in e["legs"].items()})


def run_day(args: tuple[str, date]) -> list[dict]:
    symbol, day = args
    e = entry_day(symbol, day)
    if e is None:
        return []
    close = float(e["_d"]["S"][-1])
    rows = []
    for name, legs in e["legs"].items():
        if legs is None:
            continue
        for fill, f in FILLS.items():
            x = condor(legs, close, f)
            if x is not None:
                x2 = condor(legs, close, f, 2 * COMMISSION_LEG)
                rows.append(dict(symbol=symbol, day=day.isoformat(), cell=name, fill=fill, **x, r_2x=x2["r"],
                                 in_band=abs(close - e["S"]) <= e["sigma"], sigma_pct=e["sigma"] / e["S"]))
    return rows


def days_for(symbol: str) -> list[date]:
    root = dh.IV_ROOT / f"symbol={symbol}"
    days = sorted(date.fromisoformat(p.name[5:]) for p in root.glob("date=*") if (p / "part.parquet").exists())
    return [d for d in days if START <= d <= END]


def spec_sha() -> str:
    h = hashlib.sha256()
    for f in SPEC_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def spec() -> dict:
    return dict(start=START.isoformat(), end=END.isoformat(), symbols=SYMBOLS, cells=CELLS, primary=PRIMARY, fills=FILLS,
                primary_fill="full", commission_leg=COMMISSION_LEG, max_miss=MAX_MISS, gate=GATE, seed=SEED,
                alpha_other=ALPHA_OTHER, min_days=MIN_DAYS)


def boot_ci(x: np.ndarray, level: float, n_boot: int = dh.BOOT_N, block: int = dh.BOOT_BLOCK) -> tuple[float, float]:
    """Moving day-block bootstrap CI of the mean."""
    idx = dh.block_boot_idx(len(x), n_boot, block, np.random.default_rng(SEED))
    m = x[idx].mean(axis=1)
    q = (1 - level) / 2
    return float(np.quantile(m, q)), float(np.quantile(m, 1 - q))


def worst_streak(r: np.ndarray) -> tuple[int, float]:
    """Longest run of losing days and the largest summed R of any losing run."""
    n = best = 0
    run = worst = 0.0
    for x in r:
        if x <= 0:
            n += 1
            run += x
            best = max(best, n)
            worst = min(worst, run)
        else:
            n, run = 0, 0.0
    return best, worst


def stats(g: pd.DataFrame, level: float = 0.95) -> dict:
    r = g["r"].to_numpy(float)
    lo, hi = boot_ci(r, level)
    eq = np.cumsum(r)
    streak, streak_r = worst_streak(r)
    avg_win, avg_loss = r[r > 0].mean() if (r > 0).any() else 0.0, r[r <= 0].mean() if (r <= 0).any() else 0.0
    return dict(days=len(r), win=float((r > 0).mean()), breakeven_win=float(-avg_loss / (avg_win - avg_loss)) if avg_win > avg_loss else None,
                mean_r=float(r.mean()), ci=(lo, hi), median_r=float(np.median(r)), mean_usd=float(g["pnl"].mean()),
                credit_width=float((g["credit"] / g["width"]).mean()), worst_r=float(r.min()), max_dd_r=float((np.maximum.accumulate(eq) - eq).max()),
                loss_streak=streak, loss_streak_r=streak_r, sharpe=float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else None,
                full_loss_rate=float((r <= -0.98).mean()), in_band=float(g["in_band"].mean()))


def pooled(df: pd.DataFrame, col: str = "r") -> pd.DataFrame:
    """One row per day: the mean across symbols, so SPY and QQQ don't count as two independent days."""
    return df.groupby("day", sort=True).agg(r=(col, "mean"), pnl=("pnl", "mean"), credit=("credit", "mean"),
                                            width=("width", "mean"), in_band=("in_band", "mean")).reset_index()


def gate(df: pd.DataFrame, cell: str = PRIMARY, fill: str = "full", level: float = 0.95) -> dict:
    g = df[(df["cell"] == cell) & (df["fill"] == fill)]
    by_sym = {s: float(g[g["symbol"] == s]["r"].mean()) for s in SYMBOLS}
    p = pooled(g)
    lo, hi = boot_ci(p["r"].to_numpy(float), level)
    years = p.assign(y=p["day"].str[:4]).groupby("y")["r"].mean()
    p2 = pooled(g, "r_2x")["r"].mean()
    items = dict(net_r_positive_both=all(v > 0 for v in by_sym.values()), pooled_ci_above_zero=lo > 0,
                 years_positive=int((years > 0).sum()) >= GATE["years_positive"], double_commission_positive=bool(p2 > 0))
    return dict(by_symbol=by_sym, pooled_mean=float(p["r"].mean()), pooled_ci=(lo, hi), years={k: float(v) for k, v in years.items()},
                pooled_2x_commission=float(p2), items=items, passed=all(items.values()))


def do_count(workers: int) -> dict:
    tasks = [(s, d) for s in SYMBOLS for d in days_for(s)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = pd.DataFrame(list(ex.map(count_day, tasks, chunksize=8)))
    out = {}
    for s, g in rows.groupby("symbol"):
        e = g[g["eligible"]]
        out[s] = dict(sessions=len(g), eligible=len(e), sigma_pct_median=float(e["sigma_pct"].median()),
                      **{c: int(e[c].fillna(False).astype(bool).sum()) for c in CELLS})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trigger_counts.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return out


def do_freeze() -> None:
    counts = json.loads((OUT / "trigger_counts.json").read_text())
    PREREG.write_text(json.dumps(dict(sha=spec_sha(), spec=spec(), counts=counts), indent=2))
    print(f"frozen {spec_sha()}")


def do_explore(workers: int) -> None:
    if not PREREG.exists() or json.loads(PREREG.read_text())["sha"] != spec_sha():
        raise SystemExit("spec is not frozen, or changed since --freeze")
    tasks = [(s, d) for s in SYMBOLS for d in days_for(s)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        df = pd.DataFrame([r for rows in ex.map(run_day, tasks, chunksize=8) for r in rows]).sort_values(["symbol", "cell", "fill", "day"])
    assert df["day"].max() <= END.isoformat(), "LEAK: a row reaches past discovery"
    df.to_parquet(OUT / "days.parquet")
    res = dict(sha=spec_sha(), cells={}, gate=gate(df))
    for cell in CELLS:
        level = 0.95 if cell == PRIMARY else 1 - ALPHA_OTHER
        res["cells"][cell] = {fill: {**{s: stats(df[(df["cell"] == cell) & (df["fill"] == fill) & (df["symbol"] == s)], level) for s in SYMBOLS},
                                     "pooled": stats(pooled(df[(df["cell"] == cell) & (df["fill"] == fill)]), level)} for fill in FILLS}
        res["cells"][cell]["gate_full"] = gate(df, cell, "full", level)
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    print(f"gate {PRIMARY}/full: {'PASS' if res['gate']['passed'] else 'FAIL'} {res['gate']['items']}")
    print(f"  by symbol {res['gate']['by_symbol']}  pooled {res['gate']['pooled_mean']:+.4f} CI {res['gate']['pooled_ci']}")
    print(f"  years {res['gate']['years']}  2x commission {res['gate']['pooled_2x_commission']:+.4f}")
    for cell in CELLS:
        for fill in FILLS:
            for who in (*SYMBOLS, "pooled"):
                s = res["cells"][cell][fill][who]
                print(f"{cell:13s} {fill:5s} {who:6s} n={s['days']:4d} win={s['win']:.3f} be={s['breakeven_win'] or 0:.3f} R={s['mean_r']:+.4f} "
                      f"[{s['ci'][0]:+.4f},{s['ci'][1]:+.4f}] ${s['mean_usd']:+7.2f} cr/w={s['credit_width']:.3f} band={s['in_band']:.3f} "
                      f"dd={s['max_dd_r']:.1f}R streak={s['loss_streak']}/{s['loss_streak_r']:.1f}R sharpe={s['sharpe'] or 0:+.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if args.count:
        do_count(args.workers)
    if args.freeze:
        do_freeze()
    if args.explore:
        do_explore(args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
