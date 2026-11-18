"""Buy NQ at 5 pm ET after a red day: explore on 2012-2021, freeze one cell, score it once on 2022-01 -> 2026-08-14.

Sunny's rule (2026-11-18): "buy NQ futures at 5pm if it was a red day". The parts the request leaves open are
parameters, and every combination is one cell of the exploration grid (3 x 2 x 3 = 18 cells):

  red day (--red)
    globex   the Globex daily candle is red: the 16:58 bar's close (the price at 16:59:00, a minute before the
             entry) is below the 18:00 ET open the evening before. This is the NQ1! daily candle on TradingView.
    rth      the cash-session candle is red: 15:59 close < 09:30 open.
    settle   down on the day: 15:59 close < the previous session's 15:59 close (close to the 16:00 settlement).
  entry
    close1700  the close of the session's last minute (the 16:59 bar, filled at about 17:00:00). CME halts NQ
               from 17:00 to 18:00 ET, so "5 pm" is the last price before the halt.
    open1800   the open of the 18:00 ET reopen, the first price you can actually get after 5 pm.
  exit (on the next session; a holiday session without that time is held through to the next one)
    rth_open       09:30 open    (overnight hold only)
    rth_close      15:59 close   (through the next cash session)
    session_close  16:59 close   (one full Globex session)

Long only, one contract, no stop. A trade costs 1 tick of slippage on each fill plus a round-trip commission
(NQ $20/pt, $4.50; MNQ $2/pt, $1.00 at about $0.50 per side). Each cell is also scored with doubled friction (2x).

The question is not "is it profitable" alone. NQ drifts up overnight, so buying at 17:00 on ANY day made money in
most years. The baseline is always-long: the same entry and exit on every eligible day. The rule has an edge only
if red days beat the average day: edge = mean(red) - mean(all), with a one-sided permutation p-value that shuffles
the red label across the same days. Pass = net mean > 0, 2x-friction mean > 0, and p < 0.05.

Data: Databento GLBX.MDP3 NQ.v.0 ohlcv-1m (volume-rolled front contract), read from two folders:
  data/databento/nq-ohlcv-1m-early/NQ   2012-2021 (the PR #16 job; Sunny may already have it)
  data/databento/nq-ohlcv-1m/NQ         any window (the job this PR adds), e.g. 2022-01-01 -> 2026-08-15
A trade whose exit is on a different contract than its entry (a roll inside the hold) is skipped and counted,
as are sessions without a 16:5x bar (early closes) and holds longer than 6 calendar days (data holes).

Windows. Explore = sessions 2012-01-03 -> 2021-12-31. That window has been read for other rules (PR #11's
confirmation set, PR #16's one look), never for this one. Confirm = 2022-01-03 -> 2026-08-14, read once for ONE
frozen cell. Nothing after 2026-08-14 is ever loaded: the sealed verify block starts 2026-08-24 (holdout.py) with
a one-week gap.

    python functions/ml/databento_fetch.py nq-ohlcv-1m --start 2022-01-01 --end 2026-08-15                     # free quote
    python functions/ml/databento_fetch.py nq-ohlcv-1m --start 2022-01-01 --end 2026-08-15 --download --max-cost 25
    python functions/ml/red_day_nq_study.py --explore                  # all 18 cells, 2012-2021, as often as you like
    python functions/ml/red_day_nq_study.py --explore --contract MNQ --years settle/close1700/session_close
    python functions/ml/red_day_nq_study.py --freeze globex/close1700/session_close     # writes red_day_nq_prereg.json
    python functions/ml/red_day_nq_study.py --check                    # confirm coverage; reads no prices
    python functions/ml/red_day_nq_study.py --confirm                  # once; then commit red_day_nq_looks.log
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ET = "America/New_York"
DATA = HERE / "data" / "databento"
DIRS = (DATA / "nq-ohlcv-1m-early" / "NQ", DATA / "nq-ohlcv-1m" / "NQ")
OUT = HERE / "data" / "red_day_nq"
PREREG, LOOKS = HERE / "red_day_nq_prereg.json", HERE / "red_day_nq_looks.log"   # committed, unlike OUT

EXPLORE = (date(2012, 1, 3), date(2021, 12, 31))
CONFIRM = (date(2022, 1, 3), date(2026, 8, 14))
RESEARCH_END = date(2026, 8, 14)   # holdout.VERIFY_START 2026-08-24 minus the one-week gap
MIN_SESSIONS = {2022: 230, 2023: 230, 2024: 230, 2025: 230, 2026: 140}   # 2026 runs Jan -> Aug 14

TICK = 0.25
CONTRACTS = {"NQ": dict(pv=20.0, comm_rt=4.50), "MNQ": dict(pv=2.0, comm_rt=1.00)}
SLIP_TICKS = 1
MAX_HOLD_DAYS = 6
ALPHA = 0.05
N_PERM = 5000

RED_DEFS = ("globex", "rth", "settle")
ENTRIES = ("close1700", "open1800")
EXITS = ("rth_open", "rth_close", "session_close")
CELLS = tuple(f"{r}/{e}/{x}" for r in RED_DEFS for e in ENTRIES for x in EXITS)

# Bar START times as minutes after midnight ET; a 1m bar starting at 16:59 closes at 17:00.
RTH_OPEN = (570, 574)        # 09:30-09:34, first bar: its open
RTH_CLOSE = (955, 959)       # 15:55-15:59, last bar: its close
SESSION_END = (1010, 1019)   # 16:50-16:59, last bar: its close (the 5 pm price)
REOPEN = (1080, 1084)        # 18:00-18:04, first bar: its open
FEATURES = ("g_open", "pre_close", "close1700", "rth_open", "rth_close")


# ---------------------------------------------------------------- data

def load(window: tuple[date, date], dirs=None, columns=("open", "high", "low", "close", "volume", "instrument_id")
         ) -> pd.DataFrame:
    """1m bars from 18:00 ET a week before the window (for the prior-settle lookup) to 17:00 ET on its last day."""
    if window[1] > RESEARCH_END:
        raise ValueError(f"window ends {window[1]}, past the research end {RESEARCH_END}")
    dirs = DIRS if dirs is None else dirs
    files = [f for d in dirs for f in sorted(Path(d).glob("*.parquet"))]
    if not files:
        raise FileNotFoundError(f"no bars in {', '.join(map(str, dirs))}; run databento_fetch.py nq-ohlcv-1m")
    lo = (pd.Timestamp(window[0], tz=ET) - pd.Timedelta(days=7, hours=6)).tz_convert("UTC")
    hi = (pd.Timestamp(window[1], tz=ET) + pd.Timedelta(hours=17)).tz_convert("UTC")
    df = pd.concat([pd.read_parquet(f, columns=list(columns), filters=[("ts_event", ">=", lo), ("ts_event", "<", hi)])
                    for f in files])
    df = df.reset_index().drop_duplicates(["ts_event", "instrument_id"]).set_index("ts_event").sort_index(kind="stable")
    assert len(df) == 0 or df.index.max() < hi, "LEAK: bar read reaches past the window"
    return df


def session_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (Globex trade date, instrument): volume and the prices the rule needs (NaN when missing).

    The trade date of a bar is its ET date after adding 6 hours, so 18:00 ET Sunday belongs to Monday."""
    et = df.index.tz_convert(ET).tz_localize(None)
    b = pd.DataFrame({
        "td": (et + pd.Timedelta(hours=6)).normalize(),
        "inst": df["instrument_id"].to_numpy(np.int64),
        "mod": np.asarray(et.hour * 60 + et.minute),
        "o": df["open"].to_numpy(float), "c": df["close"].to_numpy(float), "v": df["volume"].to_numpy(float),
    })
    keys = ["td", "inst"]
    b["prev_c"] = b.groupby(keys, sort=False)["c"].shift(1)
    tab = b.groupby(keys).agg(volume=("v", "sum"))

    def pick(window, col, how, name):
        m = (b["mod"] >= window[0]) & (b["mod"] <= window[1])
        tab[name] = b[m].groupby(keys)[col].agg(how)

    pick(REOPEN, "o", "first", "g_open")
    pick(SESSION_END, "c", "last", "close1700")
    pick(SESSION_END, "prev_c", "last", "pre_close")   # the bar before the session's last bar
    pick(RTH_OPEN, "o", "first", "rth_open")
    pick(RTH_CLOSE, "c", "last", "rth_close")
    return tab


def sessions_per_year(df: pd.DataFrame) -> dict[int, int]:
    et = df.index.tz_convert(ET).tz_localize(None)
    td = pd.DatetimeIndex((et + pd.Timedelta(hours=6)).normalize().unique())
    return {int(y): int(n) for y, n in pd.Series(td.year).value_counts().sort_index().items()}


# ---------------------------------------------------------------- signal days

def day_table(tab: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """One row per signal day in [start, end] on the session's front (highest-volume) contract: the three red
    flags (NaN when undefined), both entry prices and the three exit prices on that same contract."""
    front = tab["volume"].groupby(level="td").idxmax()
    by_inst = {i: sub.droplevel("inst") for i, sub in tab.groupby(level="inst")}
    lim = pd.Timedelta(days=MAX_HOLD_DAYS)
    rows = []
    for td, inst in front.to_numpy():
        if not (pd.Timestamp(start) <= td <= pd.Timestamp(end)):
            continue
        s = by_inst[inst]
        k = s.index.get_loc(td)
        d = s.iloc[k]
        row = dict(td=td, inst=inst)

        def later(col, j0):
            """first value of col at or after position j0 within MAX_HOLD_DAYS of td (same contract)."""
            for j in range(j0, len(s)):
                if s.index[j] - td > lim:
                    break
                if pd.notna(s[col].iat[j]):
                    return s[col].iat[j], s.index[j]
            return np.nan, pd.NaT

        prev_settle = np.nan
        for j in range(k - 1, -1, -1):
            if td - s.index[j] > lim:
                break
            if pd.notna(s["rth_close"].iat[j]):
                prev_settle = s["rth_close"].iat[j]
                break
        row["red_globex"] = _flag(d["pre_close"], d["g_open"])
        row["red_rth"] = _flag(d["rth_close"], d["rth_open"])
        row["red_settle"] = _flag(d["rth_close"], prev_settle)
        row["px_close1700"] = d["close1700"]
        nxt = k + 1 < len(s) and s.index[k + 1] - td <= lim
        row["px_open1800"] = s["g_open"].iat[k + 1] if nxt else np.nan
        row["x_rth_open"], row["xd_rth_open"] = later("rth_open", k + 1)
        row["x_rth_close"], row["xd_rth_close"] = later("rth_close", k + 1)
        row["x_session_close"], row["xd_session_close"] = later("close1700", k + 1)
        rows.append(row)
    return pd.DataFrame(rows)


def _flag(close, ref) -> float:
    return float(close < ref) if pd.notna(close) and pd.notna(ref) else np.nan


# ---------------------------------------------------------------- scoring

def cell_returns(days: pd.DataFrame, cell: str, contract: str = "NQ", friction: float = 1.0
                 ) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """(eligible days, net points per contract long on every eligible day, red mask)."""
    red, entry, exit_ = cell.split("/")
    c = CONTRACTS[contract]
    px_in, px_out, flag = days[f"px_{entry}"], days[f"x_{exit_}"], days[f"red_{red}"]
    ok = (px_in.notna() & px_out.notna() & flag.notna()).to_numpy()
    cost = friction * (2 * SLIP_TICKS * TICK + c["comm_rt"] / c["pv"])
    net = (px_out - px_in).to_numpy(float)[ok] - cost
    return days[ok], net, flag.to_numpy(float)[ok] == 1.0


def perm_p(x: np.ndarray, mask: np.ndarray, reps: int = N_PERM, seed: int = 0) -> float:
    """One-sided p that a random set of mask.sum() days beats the mean of all days by as much as the red days do."""
    k = int(mask.sum())
    if k == 0 or k == len(x):
        return float("nan")
    rng = np.random.default_rng(seed)
    obs = x[mask].mean()
    null = np.array([x[rng.permutation(len(x))[:k]].mean() for _ in range(reps)])
    return float((1 + (null >= obs - 1e-12).sum()) / (reps + 1))


def max_drawdown(pnl: np.ndarray) -> float:
    eq = np.cumsum(pnl)
    return float((np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq).max()) if len(pnl) else 0.0


def score(days: pd.DataFrame, cell: str, contract: str = "NQ", reps: int = N_PERM) -> dict:
    sub, net, red = cell_returns(days, cell, contract)
    if not red.any():
        return dict(cell=cell, n_days=len(net), n_red=0)
    _, net2, _ = cell_returns(days, cell, contract, friction=2.0)
    _, gross, _ = cell_returns(days, cell, contract, friction=0.0)
    pv = CONTRACTS[contract]["pv"]
    r = net[red]
    daily = np.where(red, net, 0.0) * pv   # $ per eligible day, flat on non-red days
    years = sub["td"].dt.year.to_numpy()
    by_year = {}
    for y in np.unique(years):
        m = years == y
        if m.sum() and (red & m).any():
            by_year[int(y)] = dict(n=int((red & m).sum()), red=float(net[red & m].mean()),
                                   all=float(net[m].mean()), edge=float(net[red & m].mean() - net[m].mean()))
    sd = r.std(ddof=1) if len(r) > 1 else np.nan
    return dict(
        cell=cell, contract=contract, n_days=len(net), n_red=int(red.sum()),
        mean=float(r.mean()), gross=float(gross[red].mean()), mean_2x=float(net2[red].mean()),
        t=float(r.mean() / sd * np.sqrt(len(r))) if sd > 0 else np.nan,
        win=float((r > 0).mean()), usd_total=float(r.sum() * pv), usd_per_trade=float(r.mean() * pv),
        all_mean=float(net.mean()), green_mean=float(net[~red].mean()) if (~red).any() else np.nan,
        edge=float(r.mean() - net.mean()), p=perm_p(net, red, reps),
        sharpe=float(daily.mean() / daily.std(ddof=1) * np.sqrt(252)) if daily.std(ddof=1) > 0 else np.nan,
        maxdd_usd=max_drawdown(r * pv), by_year=by_year,
    )


def verdict(res: dict) -> str:
    if not res.get("n_red"):
        return "NO TRADES"
    return "PASS" if res["mean"] > 0 and res["mean_2x"] > 0 and res["p"] < ALPHA else "FAIL"


def print_row(res: dict) -> None:
    if not res.get("n_red"):
        print(f"{res['cell']:<32} no trades")
        return
    print(f"{res['cell']:<32}{res['n_red']:>5}/{res['n_days']:<5}{res['win']:>6.1%}{res['gross']:>+8.2f}"
          f"{res['mean']:>+8.2f}{res['mean_2x']:>+8.2f}{res['t']:>+6.2f}{res['usd_per_trade']:>+9.0f}"
          f"{res['all_mean']:>+8.2f}{res['edge']:>+8.2f}{res['p']:>8.4f}{res['sharpe']:>+7.2f}{res['maxdd_usd']:>9.0f}")


HEADER = (f"{'cell':<32}{'red/all':>11}{'win':>6}{'gross':>8}{'net':>8}{'2x':>8}{'t':>6}{'$/trade':>9}"
          f"{'always':>8}{'edge':>8}{'p':>8}{'SR':>7}{'maxDD$':>9}")


# ---------------------------------------------------------------- one look

def script_sha() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]


def looks() -> list[str]:
    return [x for x in LOOKS.read_text().splitlines() if x.strip()] if LOOKS.exists() else []


def coverage_problems(per_year: dict[int, int]) -> list[str]:
    return [f"{y}: {per_year.get(y, 0)} sessions (need {n})" for y, n in MIN_SESSIONS.items() if per_year.get(y, 0) < n]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--explore", action="store_true", help="all cells on 2012-2021; repeatable")
    mode.add_argument("--freeze", metavar="CELL", choices=CELLS, help="pin one cell and this file's hash")
    mode.add_argument("--check", action="store_true", help="confirm-window coverage only; reads no prices")
    mode.add_argument("--confirm", action="store_true", help="the one look at 2022-01-03 -> 2026-08-14")
    ap.add_argument("--contract", choices=sorted(CONTRACTS), default="NQ")
    ap.add_argument("--perms", type=int, default=N_PERM)
    ap.add_argument("--years", metavar="CELL", nargs="+", choices=CELLS, help="with --explore: print these cells by year")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    if a.explore:
        days = day_table(session_table(load(EXPLORE)), *EXPLORE)
        days.to_csv(OUT / "explore_days.csv", index=False)
        print(f"explore {EXPLORE[0]} -> {EXPLORE[1]}: {len(days)} signal days, {a.contract}, points per contract "
              f"(net = after {SLIP_TICKS} tick per fill + commission). 'always' = same trade every eligible day; "
              f"edge = net - always; p = permutation vs random days. {len(CELLS)} cells: Bonferroni alpha "
              f"{ALPHA / len(CELLS):.4f}.\n")
        print(HEADER)
        results = [score(days, c, a.contract, a.perms) for c in CELLS]
        for res in results:
            print_row(res)
        (OUT / "explore.json").write_text(json.dumps(results, indent=1, default=float))
        for res in results:
            if res["cell"] in (a.years or []):
                print(f"\n{res['cell']} by year (net points, red days vs always-long):")
                for y, v in res.get("by_year", {}).items():
                    print(f"  {y}: n={v['n']:>4} red {v['red']:+7.2f} always {v['all']:+7.2f} edge {v['edge']:+7.2f}")
        print(f"\nall rows with by-year detail: {OUT / 'explore.json'}; per-day table: {OUT / 'explore_days.csv'}")
        return 0

    if a.freeze:
        if PREREG.exists():
            print(f"{PREREG.name} already exists: {PREREG.read_text().strip()}; refusing to re-freeze")
            return 1
        pin = dict(cell=a.freeze, contract=a.contract, script_sha=script_sha(), alpha=ALPHA,
                   window=[str(CONFIRM[0]), str(CONFIRM[1])], frozen_at=pd.Timestamp.now(tz="UTC").isoformat())
        PREREG.write_text(json.dumps(pin, indent=1) + "\n")
        print(f"frozen {a.freeze} ({a.contract}) at {pin['script_sha']}: commit {PREREG.name} before --confirm")
        return 0

    if not PREREG.exists():
        print("no frozen cell: run --explore, then --freeze CELL, and commit the prereg file")
        return 1
    pin = json.loads(PREREG.read_text())
    if pin["script_sha"] != script_sha():
        print(f"script changed since the freeze ({pin['script_sha']} -> {script_sha()}); refusing")
        return 1
    if looks():
        print(f"already scored ({'; '.join(looks())}); refusing a second look")
        return 1
    per_year = sessions_per_year(load(CONFIRM, columns=("instrument_id",)))
    print(f"confirm window sessions per year: {per_year}")
    gaps = coverage_problems(per_year)
    if gaps:
        print(f"download incomplete ({'; '.join(gaps)}): nothing scored, the look is not spent")
        return 1
    if a.check:
        print(f"coverage ok; frozen {pin['cell']} at {pin['script_sha']}: ready for --confirm")
        return 0
    with LOOKS.open("a") as f:
        f.write(f"cell={pin['cell']} contract={pin['contract']} script={pin['script_sha']} "
                f"at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    print(f"look logged in {LOOKS.name}: commit it with the results\n")
    days = day_table(session_table(load(CONFIRM)), *CONFIRM)
    res = score(days, pin["cell"], pin["contract"], a.perms)
    res["verdict"] = verdict(res)
    print(HEADER)
    print_row(res)
    for y, v in res.get("by_year", {}).items():
        print(f"  {y}: n={v['n']:>4} red {v['red']:+7.2f} always {v['all']:+7.2f} edge {v['edge']:+7.2f}")
    print(f"\n{pin['cell']} on 2022-01-03 -> 2026-08-14: {res['verdict']} "
          f"(needs net > 0, 2x > 0, p < {ALPHA})")
    (OUT / "confirm.json").write_text(json.dumps(dict(prereg=pin, result=res), indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
