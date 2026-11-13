"""Cost and statistics wrapper for the delta-hedged 0DTE straddle confirmation (see PLAN.md).

The trade itself is delta_hedge.py, frozen by hash in prereg.json: load_day -> straddle_path (sell
at the bid at 09:35, settle at intrinsic at 16:00) -> hedge_pnl with the "5m" (primary) or "30m"
(secondary) clock. This file only adds:
  - costs: option commission per contract on entry (2 contracts; 0DTE settles, no exit leg) and a
    per-share hedge cost on every share traded (entry, rebalances and the 16:00 unwind). hedge_pnl
    runs with hedge_cost_bps = 0 so its own bp cost is not charged twice.
  - the 2016-2021 NYSE half days, which delta_hedge.EARLY_CLOSE (2022+ only) does not list.
  - margin per straddle (CBOE naked short formula) and return on margin.
  - the gate statistics and the window guard (each window opened once, B only after A).
Gate per cell (all required): mean net > 0, day-bootstrap 95% CI low > 0, one-sided t p < 0.05/4,
stress-cost mean > 0, no calendar year below -2x the mean annual gain, and the mean with the 5
worst days doubled > 0. A window PASSES iff the 5m cell passes on both QQQ and SPY (approved
2026-11-03); 30m is reported only.
Cash settlement at intrinsic stands in for assignment: real QQQ/SPY options are American and
physically settled, so pin risk at 16:00 is not modelled.

Run:  .venv/bin/python research_loop_straddle/confirm.py --window A
Test: .venv/bin/python -m unittest discover -s research_loop_straddle/tests -v
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
ML = HERE.parent
sys.path.insert(0, str(ML))
import delta_hedge as dh  # noqa: E402

LEDGER = HERE / "ledger.jsonl"
PREREG = HERE / "prereg.json"
OUT = ML / "data" / "research_loop_straddle"

VARIANTS = {"5m": 1, "30m": 6}  # name -> rebalance_every (5-minute bars); 5m is primary
PRIMARY = "5m"
SYMBOLS = ("QQQ", "SPY")
WINDOWS = {  # inclusive UTC dates per symbol
    "A": {"QQQ": ("2016-01-04", "2018-12-31"), "SPY": ("2017-01-03", "2018-12-31")},
    "B": {"QQQ": ("2019-01-02", "2021-12-31"), "SPY": ("2019-01-02", "2021-12-31")},
}
WINDOW_ORDER = ("A", "B")
FORWARD_HOLDOUT = ("2026-09-26", "2026-10-23")  # never opened by this loop
LAST_ALLOWED = "2021-12-31"  # 2022+ was the discovery sample
# NYSE 13:00 closes 2016-2021 (data/thetadata/_calendar); delta_hedge.EARLY_CLOSE starts in 2022.
EARLY_CLOSE_PRE2022 = frozenset({
    "2016-11-25", "2017-07-03", "2017-11-24", "2018-07-03", "2018-11-23", "2018-12-24",
    "2019-07-03", "2019-11-29", "2019-12-24", "2020-11-27", "2020-12-24", "2021-11-26"})

COSTS = {  # option $ per contract on entry, hedge $ per share traded
    "base": {"option_per_contract": 0.65, "hedge_per_share": 0.005},
    "stress": {"option_per_contract": 1.00, "hedge_per_share": 0.01},
}
CONTRACTS = 2  # one call + one put; 0DTE settles at intrinsic, so no exit commission
K_TESTS = 4  # 2 variants x 2 symbols
ALPHA = 0.05 / K_TESTS
BOOT_N, BOOT_SEED = 10_000, 0
YEAR_LOSS_MULT = 2.0  # no calendar year below -2x the mean annual gain
BIG_LOSS_MULT = 10.0  # days losing more than 10x the mean daily gain
WORST_K = 5
MARGIN_PCT, MARGIN_MIN_PCT = 0.20, 0.10  # CBOE naked short: prem + max(20% S - OTM, 10% of S / K)


class WindowGuardError(RuntimeError):
    pass


# ---- per day ---------------------------------------------------------------------------------

def shares_traded(h: np.ndarray) -> float:
    """Total shares bought + sold for a hedge path h (per bar, starts and ends flat)."""
    return float(np.abs(np.diff(np.r_[0.0, np.asarray(h, float), 0.0])).sum())


def margin_per_straddle(S: float, K: float, call: float, put: float, multiplier: int = dh.MULTIPLIER) -> float:
    """CBOE naked short straddle requirement: the larger leg's naked requirement plus the other
    leg's premium. Naked call: prem + max(20% S - OTM, 10% S); naked put: prem + max(20% S - OTM,
    10% K). Premiums are the entry fills."""
    otm_c, otm_p = max(K - S, 0.0), max(S - K, 0.0)
    req_c = call + max(MARGIN_PCT * S - otm_c, MARGIN_MIN_PCT * S)
    req_p = put + max(MARGIN_PCT * S - otm_p, MARGIN_MIN_PCT * K)
    return multiplier * max(req_c + put, req_p + call)


def price_day(path: dict, call_fill: float, put_fill: float, every: int) -> dict:
    """One variant on one straddle_path dict: gross P&L (bid entry, intrinsic settle, no costs)
    plus the cost-bearing quantities and the net P&L at each COSTS level."""
    res = dh.hedge_pnl(**path, rebalance_every=every, hedge_cost_bps=0.0)
    sh = shares_traded(res["bars"]["hedge"])
    S0, K = float(path["S"][0]), float(path["K"])
    out = {"gross": float(res["pnl"]), "premium": float(res["premium"]), "spread_cost": float(res["spread_cost"]),
           "option_pnl": float(res["option_pnl"]), "hedge_pnl": float(res["hedge_pnl"]),
           "n_rebalances": int(res["n_rebalances"]), "shares_traded": sh,
           "entry_iv": float(res["entry_iv"]), "rv": float(res["rv"]),
           "margin": margin_per_straddle(S0, K, call_fill, put_fill)}
    for lvl, c in COSTS.items():
        cost = CONTRACTS * c["option_per_contract"] + sh * c["hedge_per_share"]
        out[f"cost_{lvl}"] = cost
        out[f"net_{lvl}"] = out["gross"] - cost
    return out


def run_day(symbol: str, day: str) -> list[dict]:
    """Both variants for one day; [] when delta_hedge has no eligible 0DTE straddle or it is a half day."""
    if day in EARLY_CLOSE_PRE2022:
        return []
    d = dh.load_day(symbol, day, 0)
    if d is None or not d["settle"]:
        return []
    path = dh.straddle_path(d, mid=False)
    base = {"symbol": symbol, "date": d["date"], "strike": d["strike"], "spot0": float(d["S"][0])}
    return [{**base, "variant": v, **price_day(path, float(d["call_bid"][0]), float(d["put_bid"][0]), every)}
            for v, every in VARIANTS.items()]


# ---- statistics ------------------------------------------------------------------------------

def boot_ci(x: np.ndarray, n_boot: int = BOOT_N, seed: int = BOOT_SEED) -> tuple[float, float]:
    """95% percentile CI of the mean from an iid day bootstrap."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def cell_stats(df: pd.DataFrame) -> dict:
    """Gate statistics for one symbol x variant (rows = days, date-ordered inside)."""
    x = df.sort_values("date")
    net, stress = x["net_base"].to_numpy(float), x["net_stress"].to_numpy(float)
    n = len(net)
    mean, sd = float(net.mean()), float(net.std(ddof=1)) if n > 1 else float("nan")
    se = sd / np.sqrt(n)
    t = mean / se if se > 0 else float("nan")
    p = float(stats.t.sf(t, n - 1)) if np.isfinite(t) else float("nan")
    lo, hi = boot_ci(net)
    years = x.assign(y=x["date"].str[:4]).groupby("y")["net_base"].agg(["sum", "count"])
    mean_annual = float(years["sum"].mean())
    worst_year = float(years["sum"].min())
    year_ok = bool(worst_year >= -YEAR_LOSS_MULT * mean_annual) if mean_annual > 0 else False
    tail = dh.tail_stats(net)
    order = np.argsort(net)
    worst_k = order[:WORST_K]
    doubled = net.copy()
    doubled[worst_k] *= 2
    mask = np.ones(n, bool)
    mask[worst_k] = False
    margin = x["margin"].to_numpy(float)
    gate = {"mean_pos": mean > 0, "ci_lo_pos": lo > 0, "p_lt_alpha": bool(p < ALPHA),
            "stress_pos": float(stress.mean()) > 0, "years_ok": year_ok,
            "worst5_doubled_pos": float(doubled.mean()) > 0}
    return {
        "n": n, "first": x["date"].iloc[0], "last": x["date"].iloc[-1],
        "mean_gross": float(x["gross"].mean()), "mean_net_base": mean, "sd": sd, "se": se, "t": t, "p_one_sided": p,
        "ci95": [lo, hi], "mean_net_stress": float(stress.mean()),
        "mean_cost_base": float(x["cost_base"].mean()), "mean_cost_stress": float(x["cost_stress"].mean()),
        "mean_shares_traded": float(x["shares_traded"].mean()), "mean_spread_cost": float(x["spread_cost"].mean()),
        "mean_premium": float(x["premium"].mean()), "mean_spot0": float(x["spot0"].mean()),
        "pct_premium": float(100 * mean / x["premium"].mean()), "hit": float((net > 0).mean()),
        "years": {y: {"sum": float(r["sum"]), "n": int(r["count"])} for y, r in years.iterrows()},
        "mean_annual": mean_annual, "worst_year": worst_year,
        "worst_day": float(tail["worst"]), "worst_day_date": x["date"].iloc[int(order[0])],
        "worst5_dates": [x["date"].iloc[int(i)] for i in worst_k], "cvar5": float(tail["cvar5"]),
        "max_dd": float(tail["max_dd"]), "skew": float(tail["skew"]),
        "n_big_loss": int((net < -BIG_LOSS_MULT * mean).sum()) if mean > 0 else None,
        "mean_ex_worst5": float(net[mask].mean()), "mean_worst5_doubled": float(doubled.mean()),
        "mean_margin": float(margin.mean()), "return_on_margin_pct": float(100 * mean / margin.mean()),
        "gate": gate, "pass": all(gate.values()),
    }


def window_stats(df: pd.DataFrame) -> dict:
    """cell_stats per symbol x variant plus the window verdict: PASS iff the primary (5m) cell
    passes on BOTH symbols; 30m is reported as the secondary and does not decide."""
    cells = {f"{s}|{v}": cell_stats(x) for (s, v), x in df.groupby(["symbol", "variant"], sort=True)}
    need = [f"{s}|{PRIMARY}" for s in SYMBOLS]
    ok = all(k in cells and cells[k]["pass"] for k in need)
    return {"cells": cells, "decides": need, "verdict": "PASS" if ok else "FAIL"}


# ---- window guard ----------------------------------------------------------------------------

def read_ledger(path: Path | None = None) -> list[dict]:
    path = LEDGER if path is None else path  # resolved at call time, not at import
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check_window(window: str, ledger: list[dict]) -> None:
    """Raise WindowGuardError unless `window` may be opened now: known, not looked at before, and
    every earlier window already has a decided ledger row (B needs A's verdict, and A's PASS)."""
    if window not in WINDOWS:
        raise WindowGuardError(f"unknown window {window!r}")
    looked = {r["window"] for r in ledger}
    if window in looked:
        raise WindowGuardError(f"window {window} was already opened; one look only")
    for prev in WINDOW_ORDER[:WINDOW_ORDER.index(window)]:
        rows = [r for r in ledger if r["window"] == prev]
        if not rows or rows[-1].get("verdict") not in ("PASS", "FAIL"):
            raise WindowGuardError(f"window {window} needs window {prev}'s verdict in the ledger first")
        if rows[-1]["verdict"] != "PASS":
            raise WindowGuardError(f"window {prev} failed; window {window} stays closed")
    for s, (a, b) in WINDOWS[window].items():
        if b > LAST_ALLOWED or not (b < FORWARD_HOLDOUT[0] or a > FORWARD_HOLDOUT[1]):
            raise WindowGuardError(f"window {window} {s} {a}..{b} touches forbidden dates")


def window_days(symbol: str, window: str) -> list[str]:
    """Downloaded iv_5m days for symbol inside the window (directory listing only)."""
    a, b = WINDOWS[window][symbol]
    root = dh.IV_ROOT / f"symbol={symbol}"
    days = sorted(p.name[5:] for p in root.glob("date=*") if (p / "part.parquet").exists())
    return [d for d in days if a <= d <= b]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_hashes(prereg: dict) -> None:
    """Refuse to run when any frozen file differs from its prereg hash."""
    for rel, want in prereg["frozen_sha256"].items():
        got = sha256(ML / rel)
        if got != want:
            raise WindowGuardError(f"{rel} changed since the prereg ({got[:12]} != {want[:12]})")


def open_window(window: str, workers: int = 3) -> dict:
    prereg = json.loads(PREREG.read_text())
    check_hashes(prereg)
    check_window(window, read_ledger())
    t0, rows = time.time(), []
    with ProcessPoolExecutor(max_workers=min(workers, 3)) as ex:
        for s in SYMBOLS:
            days = window_days(s, window)
            for day_rows in ex.map(run_day, [s] * len(days), days, chunksize=4):
                rows.extend(day_rows)
            print(f"  {s}: {len(days)} files, {sum(r['symbol'] == s for r in rows) // len(VARIANTS)} traded "
                  f"({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"window_{window}_days.parquet", index=False)
    res = window_stats(df)
    row = {"window": window, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "verdict": res["verdict"], "decides": res["decides"],
           "n": {k: v["n"] for k, v in res["cells"].items()},
           "mean_net_base": {k: round(v["mean_net_base"], 3) for k, v in res["cells"].items()},
           "p_one_sided": {k: v["p_one_sided"] for k, v in res["cells"].items()},
           "frozen_sha256": prereg["frozen_sha256"]}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")
    (OUT / f"window_{window}_stats.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", required=True, choices=list(WINDOWS))
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    res = open_window(args.window, args.workers)
    for k, c in res["cells"].items():
        print(f"{k:9s} n={c['n']:4d} net {c['mean_net_base']:+7.2f} (SE {c['se']:.2f}, CI {c['ci95'][0]:+.2f}.."
              f"{c['ci95'][1]:+.2f}, p {c['p_one_sided']:.4f}) stress {c['mean_net_stress']:+7.2f} "
              f"worst {c['worst_day']:+8.2f} CVaR5 {c['cvar5']:+7.2f} maxDD {c['max_dd']:7.1f} "
              f"RoM {c['return_on_margin_pct']:+.3f}% {'PASS' if c['pass'] else 'FAIL'}")
    print(f"window {args.window}: {res['verdict']} (decided by {', '.join(res['decides'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
