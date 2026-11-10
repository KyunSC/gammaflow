"""Do month-end forced flows still pay after the papers that found them? (one look, frozen from the papers)

Three published, mechanical flows around the turn of the month, each tested exactly as its paper
specifies it, so there is nothing to tune here:

  H1  balanced-fund rebalancing (Harvey, Mazzoleni & Melone 2025, "The Unintended Consequences of
      Rebalancing", SSRN 5122748). A 60/40 stock/10y portfolio drifts during the month and is reset
      on its last trading day. When stocks have outrun bonds, funds sell stocks and buy bonds in the
      last week. Their Calendar leg: on each of the last 5 trading days hold -sign(w - 0.60) units of
      (stock - bond), w = the drifted stock weight at the previous close. Paper: ~17 bp next-day
      stock and ~19 bp stock-minus-bond per 1-SD signal, 1997-09 -> 2023-03-17. Their first-day-of-
      next-month leg is left out: its definition is not recoverable from the public text.
  H2  turn of the month (McConnell & Xu 2008; Etula, Rinne, Suominen & Vaittinen 2020, "Dash for
      Cash"): stocks earn more on the last trading day and the first 3 of the next month than on
      other days. Paper sample to 2005.
  H3  Treasury month-end extension (Hartley & Schwarz 2019): 10y notes earn more on the last 3
      trading days of the month (index duration extension). Paper sample 1990 -> 2018.

Data: daily total-return closes (yfinance auto_adjust=True) of SPY (stocks) and IEF (7-10y notes)
from 2002-07-30 (IEF launch). Both are total-return ETFs, so financing cancels in H1's pair and
in H2/H3's "these days minus other days" contrasts. Execution would be MES and ZN (or micro
Treasury) futures, held overnight, so this is a personal-account trade: prop rules force you flat.

Units: one observation per month (H1: the month's last-5-day block; H2: the turn-of-month block
around its last day; H3: its last-3-day block), in bp of notional. Costs per round trip:
EQ_RT_BP on the stock leg, BD_RT_BP on the bond leg (H1 pays half a round trip per leg on each
position change, so a flip inside a block costs a full round trip). H2/H3 edge = block return -
cost - block length x the mean daily return on the window's other days (the same asset's drift).

Windows (fixed from the papers' sample ends, never moved):
  replication  2002-08 -> each paper's sample end. Repeatable (--replicate). A hypothesis whose
               replication edge is not > 0 is dropped automatically: it is a bug, a proxy problem
               or a dead effect, and either way its test window stays unscored. Only windows of
               >= MIN_GATE_MONTHS months gate (H1 ~247, H3 ~197). H2's overlap with McConnell & Xu
               is ~41 months, too few to drop it on, so it is reported and not gated.
  test         the day after the paper's sample -> RESEARCH_CAP (2026-08-14, the project research
               cap; the sealed Aug 24 block and its gap week are never downloaded). --score reads it
               ONCE, appends the look to month_end_flows_looks.log (committed) and refuses again.
               Forward scoring from 2026-09-28 would be a separate, later look.

Verdict per hypothesis on the test window: PASS when the mean monthly net edge > 0, its 95%
bootstrap CI (months resampled) is above 0, and the Holm-adjusted (3 tests) random-placement p
< ALPHA. Random null: H1 multiplies each month's gross by a random sign (keeps its cost); H2/H3
move the block to a random same-length run of non-flagged days in the same month. Diagnostics,
never selection: by-year means, 2x costs, and H1 on the 5 days before the last 5 ("week 3"), the
place front-runners would move it to once the paper is known.

script_sha() hashes this file; the tests pin it (SPEC_SHA), so any change after the first
commit is visible in review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

from holdout import VERIFY_START  # noqa: E402

OUT = HERE / "data" / "month_end_flows"
LOOKS = HERE / "month_end_flows_looks.log"   # committed, unlike OUT

EQ, BD = "SPY", "IEF"
DATA_START = date(2002, 7, 30)
RESEARCH_CAP = date(2026, 8, 14)   # last research session before the gap week and sealed verify

TARGET_W = 0.60
H1_DAYS = 5          # last 5 trading days
TOM_LAST, TOM_FIRST = 1, 3   # H2: last day of the month + first 3 of the next
H3_DAYS = 3          # last 3 trading days
EQ_RT_BP, BD_RT_BP = 1.0, 2.0
ALPHA = 0.05
N_BOOT, N_RANDOM = 5000, 5000
MIN_SESSIONS_PER_YEAR = 240
MIN_GATE_MONTHS = 120   # a replication window shorter than this is too noisy to drop a hypothesis on
BP = 1e4

HYPS = {
    "H1_rebalance": dict(rep_end=date(2023, 3, 17), test_start=date(2023, 3, 20)),
    "H2_turn_of_month": dict(rep_end=date(2005, 12, 31), test_start=date(2006, 1, 1)),
    "H3_treasury_month_end": dict(rep_end=date(2018, 12, 31), test_start=date(2019, 1, 1)),
}


# ---------------------------------------------------------------- calendar and signals

def month_table(px: pd.DataFrame) -> pd.DataFrame:
    """Daily rows (index = date) with simple returns re/rb, the month key, k (1 = first trading day
    of the month) and j (1 = last). The first and last months in the data are dropped: their k or j
    would be wrong because the month is cut off."""
    t = px[[EQ, BD]].astype(float).sort_index()
    t = pd.DataFrame({"re": t[EQ].pct_change(), "rb": t[BD].pct_change()}, index=t.index).iloc[1:]
    t["month"] = [d.year * 12 + d.month - 1 for d in t.index]
    months = t["month"].unique()
    t = t[(t["month"] != months.min()) & (t["month"] != months.max())].copy()
    g = t.groupby("month")
    t["k"] = g.cumcount() + 1
    t["j"] = g["k"].transform("max") - t["k"] + 1
    return t


def drift_weight(t: pd.DataFrame, target: float = TARGET_W) -> np.ndarray:
    """Stock weight of a 60/40 portfolio at each close, before that day's month-end reset. Reset to
    `target` after the last close of each month, so the first day of a month starts from target."""
    w = np.empty(len(t))
    cur = target
    for i, (re, rb, j) in enumerate(zip(t["re"].to_numpy(), t["rb"].to_numpy(), t["j"].to_numpy())):
        s, b = cur * (1 + re), (1 - cur) * (1 + rb)
        w[i] = s / (s + b)
        cur = target if j == 1 else w[i]
    return w


def h1_positions(t: pd.DataFrame, lo: int = 1, hi: int = H1_DAYS) -> np.ndarray:
    """Position in (stock - bond) held from the previous close to this close: -sign(w_prev - 0.6)
    on days with lo <= j <= hi, else 0. Uses only the previous close (no look-ahead)."""
    w = drift_weight(t)
    prev = np.r_[np.nan, w[:-1]]
    j = t["j"].to_numpy()
    on = (j >= lo) & (j <= hi) & ~np.isnan(prev)
    return np.where(on, -np.sign(np.nan_to_num(prev) - TARGET_W), 0.0)


def h1_blocks(t: pd.DataFrame, lo: int = 1, hi: int = H1_DAYS, cost_mult: float = 1.0) -> pd.DataFrame:
    """One row per month: gross and net bp of the month's block of (stock - bond) positions."""
    pos = h1_positions(t, lo, hi)
    pair = (t["re"] - t["rb"]).to_numpy()
    rows = []
    for m, idx in t.groupby("month").indices.items():
        p = pos[idx]
        if not np.any(p):
            continue
        p0 = np.r_[0.0, p, 0.0]
        changes = np.abs(np.diff(p0)).sum()            # entry + exit = 2; a flip adds 2
        cost = changes * (EQ_RT_BP + BD_RT_BP) / 2 * cost_mult
        gross = float((p * pair[idx]).sum() * BP)
        rows.append(dict(month=m, date=t.index[idx[-1]], gross=gross, cost=cost, net=gross - cost,
                         days=int((p != 0).sum())))
    return pd.DataFrame(rows)


def flag_blocks(t: pd.DataFrame, kind: str) -> list[np.ndarray]:
    """Row-index arrays of each month's flagged block. H2: last day of month m + first 3 of m+1,
    keyed to month m. H3: last H3_DAYS days of month m."""
    k, j, m = t["k"].to_numpy(), t["j"].to_numpy(), t["month"].to_numpy()
    out = []
    for mm in np.unique(m):
        if kind == "H2":
            a = np.flatnonzero((m == mm) & (j <= TOM_LAST))
            b = np.flatnonzero((m == mm + 1) & (k <= TOM_FIRST))
            if len(a) == TOM_LAST and len(b) == TOM_FIRST:
                out.append(np.r_[a, b])
        else:
            a = np.flatnonzero((m == mm) & (j <= H3_DAYS))
            if len(a) == H3_DAYS:
                out.append(a)
    return out


def contrast_blocks(t: pd.DataFrame, kind: str, cost_mult: float = 1.0) -> tuple[pd.DataFrame, np.ndarray]:
    """H2 (stocks) / H3 (bonds): per-block gross, net, and edge over the window's other days.
    Returns (blocks, other-day mask)."""
    r = (t["re"] if kind == "H2" else t["rb"]).to_numpy()
    rt = (EQ_RT_BP if kind == "H2" else BD_RT_BP) * cost_mult
    blocks = flag_blocks(t, kind)
    flagged = np.zeros(len(t), bool)
    for b in blocks:
        flagged[b] = True
    mu_other = float(r[~flagged].mean() * BP)
    rows = []
    for b in blocks:
        gross = float(r[b].sum() * BP)
        rows.append(dict(month=int(t["month"].iloc[b[0]]), date=t.index[b[-1]], gross=gross, cost=rt,
                         net=gross - rt, edge=gross - rt - len(b) * mu_other, days=len(b)))
    return pd.DataFrame(rows), ~flagged


# ---------------------------------------------------------------- statistics

def boot_ci(x: np.ndarray, n: int = N_BOOT, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), (n, len(x)))].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def random_p_h1(blocks: pd.DataFrame, n: int = N_RANDOM, seed: int = 0) -> float:
    """Random sign per month on the gross (cost kept): is the signal's direction worth anything?"""
    rng = np.random.default_rng(seed)
    g, c = blocks["gross"].to_numpy(), blocks["cost"].to_numpy()
    obs = (g - c).mean()
    sims = (g * rng.choice([-1.0, 1.0], (n, len(g))) - c).mean(axis=1)
    return float((1 + (sims >= obs).sum()) / (1 + n))


def random_p_contrast(t: pd.DataFrame, kind: str, blocks: pd.DataFrame, other: np.ndarray,
                      n: int = N_RANDOM, seed: int = 0) -> float:
    """Move each month's block to a random run of the same length of other days in that month
    (contiguous trading days, all unflagged). p = share of placements whose mean net >= observed."""
    rng = np.random.default_rng(seed)
    r = (t["re"] if kind == "H2" else t["rb"]).to_numpy() * BP
    m = t["month"].to_numpy()
    obs = blocks["net"].mean()
    cand = []
    for mm, L, c in zip(blocks["month"], blocks["days"], blocks["cost"]):
        idx = np.flatnonzero((m == mm) & other)
        starts = [s for s in range(len(idx) - L + 1) if idx[s + L - 1] - idx[s] == L - 1]
        if starts:
            sums = np.array([r[idx[s]: idx[s] + L].sum() for s in starts]) - c
            cand.append(sums)
    if not cand:
        return 1.0
    sims = np.zeros(n)
    for sums in cand:
        sims += sums[rng.integers(0, len(sums), n)]
    sims /= len(cand)
    return float((1 + (sims >= obs).sum()) / (1 + n))


def holm(ps: dict[str, float]) -> dict[str, float]:
    order = sorted(ps, key=ps.get)
    out, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (len(order) - i) * ps[k]))
        out[k] = run
    return out


def summarize(blocks: pd.DataFrame, col: str) -> dict:
    if blocks.empty:
        return dict(n=0)
    x = blocks[col].to_numpy()
    sd = float(x.std(ddof=1)) if len(x) > 1 else float("nan")
    lo, hi = boot_ci(x)
    years = blocks.assign(y=[d.year for d in blocks["date"]]).groupby("y")[col].agg(["count", "mean"])
    return dict(n=int(len(x)), mean=float(x.mean()), t=float(x.mean() / sd * np.sqrt(len(x))) if sd else None,
                ci95=[lo, hi], hit=float((x > 0).mean()), worst=float(x.min()),
                by_year={int(y): [int(r["count"]), round(float(r["mean"]), 2)] for y, r in years.iterrows()})


def window(t: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    return t[(t.index >= start) & (t.index <= end)]


def evaluate(t: pd.DataFrame, hyp: str, start: date, end: date) -> dict:
    """All numbers for one hypothesis on one window. Blocks are built on the full table (so H1's
    drift and month flags see whole months) and kept when their last day is inside the window."""
    def keep(b: pd.DataFrame) -> pd.DataFrame:
        return b if b.empty else b[[(start <= d <= end) for d in b["date"]]].reset_index(drop=True)

    w = window(t, start, end)
    if hyp.startswith("H1"):
        b, b2, wk3 = (keep(h1_blocks(t)), keep(h1_blocks(t, cost_mult=2.0)),
                      keep(h1_blocks(t, H1_DAYS + 1, 2 * H1_DAYS)))
        res = dict(main=summarize(b, "net"), gross=summarize(b, "gross"), net_2x=summarize(b2, "net"),
                   week3_diag=summarize(wk3, "net"), p_rand=random_p_h1(b) if len(b) else 1.0)
        res["edge_mean"] = res["main"].get("mean")
    else:
        kind = hyp[:2]
        # the other-day drift and random placements come from the window's own days
        b, other = contrast_blocks(w, kind)
        b2, _ = contrast_blocks(w, kind, cost_mult=2.0)
        res = dict(main=summarize(b, "edge"), net=summarize(b, "net"), edge_2x=summarize(b2, "edge"),
                   p_rand=random_p_contrast(w, kind, b, other) if len(b) else 1.0)
        res["edge_mean"] = res["main"].get("mean")
    res["window"] = [str(start), str(end)]
    return res


def verdict(res: dict, p_adj: float) -> str:
    m = res["main"]
    fails = []
    if not m.get("n"):
        return "FAIL (no blocks)"
    if not m["mean"] > 0:
        fails.append("mean <= 0")
    if not m["ci95"][0] > 0:
        fails.append("CI includes 0")
    if not p_adj < ALPHA:
        fails.append(f"Holm p {p_adj:.3f} >= {ALPHA}")
    return "PASS" if not fails else "FAIL (" + "; ".join(fails) + ")"


# ---------------------------------------------------------------- I/O and modes

def script_sha() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]


def looks() -> list[str]:
    return [l for l in LOOKS.read_text().splitlines() if l.strip()] if LOOKS.exists() else []


def load_prices(refresh: bool = False) -> pd.DataFrame:
    """Daily total-return closes, cached. Downloaded with an exclusive end the day after
    RESEARCH_CAP, so nothing from the gap week or sealed verify block is ever fetched."""
    assert RESEARCH_CAP < VERIFY_START.date()
    cache = OUT / "daily_spy_ief.parquet"
    if cache.exists() and not refresh:
        px = pd.read_parquet(cache)
    else:
        import yfinance as yf
        cols = {}
        for sym in (EQ, BD):
            h = yf.Ticker(sym).history(start=str(DATA_START), end=str(RESEARCH_CAP + timedelta(days=1)),
                                       auto_adjust=True)
            if h.empty:
                raise SystemExit(f"yfinance returned no daily rows for {sym}")
            cols[sym] = pd.Series(h["Close"].to_numpy(), index=[x.date() for x in h.index])
        px = pd.DataFrame(cols).dropna()
        px.index.name = "date"
        OUT.mkdir(parents=True, exist_ok=True)
        px.to_parquet(cache)
    return check_cap(px)


def check_cap(px: pd.DataFrame) -> pd.DataFrame:
    if max(px.index) > RESEARCH_CAP:
        raise SystemExit(f"LEAK: price rows after {RESEARCH_CAP}; refusing")
    return px


def coverage_problems(t: pd.DataFrame, start: date, end: date) -> list[str]:
    per = pd.Series([d.year for d in window(t, start, end).index]).value_counts()
    full = range(start.year + 1, end.year)   # partial first/last years are allowed
    return [f"{y}: {int(per.get(y, 0))} sessions" for y in full if per.get(y, 0) < MIN_SESSIONS_PER_YEAR]


def fmt_block(name: str, r: dict) -> str:
    m = r["main"]
    if not m.get("n"):
        return f"  {name:<24} no blocks"
    return (f"  {name:<24} n={m['n']:>4}  mean {m['mean']:+7.2f} bp  t {m['t']:+5.2f}  "
            f"CI [{m['ci95'][0]:+6.2f},{m['ci95'][1]:+6.2f}]  hit {m['hit']:.2f}  p_rand {r['p_rand']:.4f}")


def replicate(t: pd.DataFrame) -> dict:
    res = {}
    print(f"REPLICATION (papers' windows, repeatable; script {script_sha()})")
    for hyp, spec in HYPS.items():
        r = evaluate(t, hyp, t.index[0], spec["rep_end"])
        r["gated"] = r["main"].get("n", 0) >= MIN_GATE_MONTHS
        r["replicates"] = bool(not r["gated"] or (r["edge_mean"] is not None and r["edge_mean"] > 0))
        res[hyp] = r
        note = ("" if r["replicates"] else "   <- did NOT replicate: dropped from --score") if r["gated"] \
            else f"   (overlap < {MIN_GATE_MONTHS} months: reported, not gated)"
        print(fmt_block(hyp, r) + note)
        if hyp.startswith("H1"):
            print(f"  {'':<24} gross {r['gross']['mean']:+.2f}  net 2x {r['net_2x']['mean']:+.2f}  "
                  f"week-3 diag {r['week3_diag'].get('mean', float('nan')):+.2f}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "replication.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def score(t: pd.DataFrame) -> int:
    if looks() or (OUT / "results.json").exists():
        print(f"already scored ({'; '.join(looks()) or OUT / 'results.json'}); refusing a second look")
        return 1
    gaps = [f"{h} {g}" for h, s in HYPS.items() for g in coverage_problems(t, s["test_start"], RESEARCH_CAP)]
    if gaps:
        print(f"price history incomplete ({', '.join(gaps)}); nothing scored, the look is not spent")
        return 1
    rep = replicate(t)
    live = [h for h in HYPS if rep[h]["replicates"]]
    sha = script_sha()
    with LOOKS.open("a") as f:
        f.write(f"script={sha} hyps={','.join(live) or 'none'} cap={RESEARCH_CAP} "
                f"at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    print(f"\nlook logged in {LOOKS.name}: commit it with the results\n\nTEST (one look, -> {RESEARCH_CAP})")
    res = {h: evaluate(t, h, HYPS[h]["test_start"], RESEARCH_CAP) for h in live}
    adj = holm({h: r["p_rand"] for h, r in res.items()}) if res else {}
    for h, r in res.items():
        r["p_holm"], r["verdict"] = adj[h], verdict(r, adj[h])
        print(fmt_block(h, r) + f"  Holm {adj[h]:.4f}  {r['verdict']}")
    for h in HYPS:
        if h not in res:
            print(f"  {h:<24} dropped: did not replicate on the paper's window; test window left unread")
    (OUT / "results.json").write_text(json.dumps(dict(script_sha=sha, replication=rep, test=res),
                                                  indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replicate", action="store_true", help="papers' sample windows only (repeatable)")
    mode.add_argument("--score", action="store_true", help="one look at the post-paper windows to 2026-08-14")
    ap.add_argument("--refresh", action="store_true", help="re-download the daily closes")
    args = ap.parse_args()
    px = load_prices(args.refresh)
    t = month_table(px)
    if args.replicate:
        # never hand the test windows to the replication path
        last_rep = max(s["rep_end"] for s in HYPS.values())
        replicate(t[t.index <= last_rep + timedelta(days=10)])   # +10d: the last month's TOM days
        return 0
    return score(t)


if __name__ == "__main__":
    raise SystemExit(main())
