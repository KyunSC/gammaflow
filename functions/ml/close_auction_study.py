"""Is the closing print noisy enough to fade overnight? (Hu, Liu & Yu 2021, "Dual trading and
price discovery at market close", SSRN 3692785)

The paper measures how informative a close is by MSE = E[((open_{t+1} - close_t) / close_t)^2]:
the next open stands in for the fundamental, and the last-5m/15m VWAP is its alternative reference
price. Its cross-sectional result (off-exchange "guaranteed close" volume makes closes more
informative) needs TAQ/TRF data on ~1,500 stocks and is NOT tested here. What carries over to
QQQ/SPY is the mechanism: the close is a single auction dominated by passive, uninformed MOC
demand (index funds, ETFs), so the print can carry price pressure that the next open takes back.
This asks whether that pressure is large and regular enough to trade.

Rules (fixed before any out-of-sample number was looked at; see "Specification" below):
  - prices: the OFFICIAL close and next-day open come from yfinance daily rows (auto_adjust=False).
    Databento XNAS.ITCH ohlcv-1m bars do not contain the auction cross prints (the 16:00 bar's
    open matched the official QQQ close on 20% of days in a spot check; the 09:30 open matches the
    official open to a median 0 bp), so the 1-min bars are used only for pre-/post-close prices,
    VWAPs and volume. Volume is Nasdaq-only.
  - dividends: on the next session's ex-date, its cash dividend is added back to the open, so no
    ex-dividend drop (QQQ ~15 bp, SPY ~34 bp per quarter) reads as overnight reversal.
  - early closes (13:00 ET half days) are dropped: bars after 13:00 are post-market there.
    Detected as late-afternoon (14:00-15:54) volume < EARLY_CLOSE_FRAC of morning (09:30-12:59)
    volume. (Post-run fix: the first version used 13:00-15:59, which the post-close prints in the
    13:00 bar always cleared, so no half day was dropped. A data-cleaning bug, not a rule change.)
  - two executions, because a market-on-close order must be in before the cutoff (Nasdaq 15:55)
    and so cannot depend on the print it trades at:
      moc   decide at 15:55 ET from bars that END by 15:55, enter at the official close, exit at
            the next official open (MOO). Signals:
              dev_pre  log(price at 15:55 / VWAP of the bars 15:40-15:54)
              r_imb    log(price at 15:55 / price at 15:50)   (the window after imbalance
                       publication starts at 15:50)
      post  decide after the print, enter at the 16:05 post-market price (close of the 16:04 bar),
            exit at the next official open. Signals:
              dev_close  log(official close / VWAP of the bars 15:45-15:59)
              r_close    log(official close / price at 15:50)
    "price at T" = close of the last 1-min bar starting in [T-5min, T).
  - trade rule (one cell = execution x signal x k): sigma = std of the signal over the previous
    SIGMA_WIN sessions (excluding today); trade when |signal| > k * sigma, direction -sign(signal)
    (fade). k in KS. 12 cells, 6 per execution, selected separately per execution.
  - returns: log returns, reported in bp. Costs 0 / 1 / 2 bp per round trip; selection and
    verdicts use SELECT_COST_BP. For `post`, read the 2 bp column: post-market spreads are wider.
  - drift: QQQ/SPY drift up overnight, so a fade that wins only on its long leg has found nothing.
    edge = dir * (r - mu), mu = the execution's mean overnight return over ALL discovery sessions
    (frozen; holdout edges use the discovery mu).
  - split: research sessions = sessions before VERIFY_START minus the last GAP_SESSIONS (as
    holdout.split_holdout). Discovery = first DISCOVERY_FRAC, holdout = the rest. Per execution, the
    cell with the highest discovery mean edge among cells with >= MIN_TRADES discovery trades is
    selected and scored once on holdout.
  - controls, next to every selected cell, on both splits:
      always_long   long overnight every session (the drift)
      same_days     long overnight on the cell's trade days only
      flipped       the cell with the sign reversed (momentum)
      random        N_RANDOM sign permutations on the cell's trade days; p = (1 + #random mean >=
                    cell mean) / (1 + N_RANDOM)
  - verdict (holdout, at SELECT_COST_BP): PASS when the net mean > 0 with its 95% block-bootstrap CI
    above 0, the mean edge > 0, the net mean beats always_long's per-session net mean, and random
    p < 0.05. Otherwise FAIL, with the failed tests listed.
  - pre-declared subgroups of each selected cell (no new grids; n, net mean, edge per split):
      win_share   z-score (vs previous SIGMA_WIN sessions) of the 15:40-15:54 share of the day's
                  09:30-15:54 volume > 1 vs <= 1 (proxy for heavy closing-window flow; the auction
                  volume itself is not in the bars)
      calendar    month_end, quarter_end, opex (third Friday), quad_witch (third Friday of
                  Mar/Jun/Sep/Dec: S&P/NDX quarterly rebalances)
      gex         long vs short gamma (ThetaData net_gex / abs_gex_total > 0) at the last snapshot
                  computed at or before the decision time (15:55 moc, 16:00 post)
  - measurement (the paper's metric, not a strategy), all research sessions and by year:
      mse_close   E[log((open_next + div) / close)^2] x 1e4      (paper's MSE)
      mse_vwap15  the same with VWAP(15:45-15:59) in place of the close
      mse_p1559   the same with the 15:59 price
    The paired difference mse_close - mse_vwap15 (day-block bootstrap CI) asks whether the print
    is a worse forecast of the next open than the pre-close VWAP. Plus the reversal slope of the
    overnight return on dev_close and r_close (OLS, day-block CI), and the post-close spill:
    correlations of r_close with the 16:00->16:05 move, the 16:05->20:00 move and the overnight.

Holdout (holdout.py): the sealed verify block is NEVER LOADED. Daily rows are downloaded with an
exclusive end at VERIFY_START; 1-min bars are read with a pyarrow filter ts_event < the end of the
last research session's next session (its exit open sits in the gap week, which is not verify).
main() asserts that no row and no exit timestamp reaches VERIFY_START.

Specification: everything above was written down before the first run and not changed after it.

Caveats:
  - ITCH volume is Nasdaq-only and excludes auctions; win_share is a proxy, not the paper's
    close-auction share.
  - SPY lists on NYSE Arca (MOC cutoff 15:59); using QQQ's 15:55 for both is conservative.
  - yfinance official prices can be revised; the daily cache makes reruns reproducible.

Outputs (gitignored data/): data/close_auction/close_auction_<sym>.json (summary),
sessions_<sym>.parquet (per-session table for follow-up features), daily_<sym>.parquet (cache).
Plot: plots/close_auction_<sym>.png.

Run: .venv/bin/python functions/ml/close_auction_study.py --symbol QQQ
     .venv/bin/python functions/ml/close_auction_study.py --symbol SPY
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from holdout import GAP_SESSIONS, VERIFY_START, research_sessions  # noqa: E402

ET = "America/New_York"
DATA = HERE / "data"
OUT = DATA / "close_auction"
PLOTS = HERE / "plots"
BARS_DIR = DATA / "databento" / "eq-ohlcv-1m"
GEX_DIR = DATA / "thetadata_gex"


def hm(h: int, m: int) -> int:
    return h * 60 + m


OPEN, NOON1, LATE, CLOSE = hm(9, 30), hm(13, 0), hm(14, 0), hm(16, 0)
DECISION = hm(15, 55)
IMB = hm(15, 50)
VWAP_PRE = (hm(15, 40), DECISION)
VWAP_LAST = (hm(15, 45), CLOSE)
POST_ENTRY = hm(16, 5)
POST_LATE = hm(20, 0)
EARLY_CLOSE_FRAC = 0.05

SIGMA_WIN = 20
KS = (0.5, 1.0, 2.0)
COSTS_BP = (0.0, 1.0, 2.0)
SELECT_COST_BP = 1.0
DISCOVERY_FRAC = 0.7
MIN_TRADES = 50
N_RANDOM = 500
N_BOOT = 2000
BOOT_BLOCK = 5
BP = 1e4

EXECUTIONS = {
    "moc": dict(signals=("dev_pre", "r_imb"), ret="on_close", gex="long_gamma_moc"),
    "post": dict(signals=("dev_close", "r_close"), ret="on_post", gex="long_gamma_post"),
}
CALENDAR = ("month_end", "quarter_end", "opex", "quad_witch")


# ---------------------------------------------------------------- pure: sessions

def _day_minute(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    et = index.tz_convert(ET)
    return np.asarray(et.date), np.asarray(et.hour * 60 + et.minute)


def price_at(m: pd.DataFrame, day, mins, t: int) -> pd.Series:
    """Per session: close of the last 1-min bar starting in [t - 5, t)."""
    sel = (mins >= t - 5) & (mins < t)
    return m.loc[sel, "close"].groupby(day[sel]).last()


def window_vwap(m: pd.DataFrame, day, mins, lo: int, hi: int) -> pd.Series:
    """Per session: volume-weighted typical price of the bars starting in [lo, hi)."""
    sel = (mins >= lo) & (mins < hi)
    w = m.loc[sel]
    tp = (w["high"] + w["low"] + w["close"]) / 3
    g = day[sel]
    vol = w["volume"].groupby(g).sum()
    return ((tp * w["volume"]).groupby(g).sum() / vol).where(vol > 0)


def window_volume(m: pd.DataFrame, day, mins, lo: int, hi: int) -> pd.Series:
    sel = (mins >= lo) & (mins < hi)
    return m.loc[sel, "volume"].groupby(day[sel]).sum()


def calendar_flags(sessions: list[date]) -> pd.DataFrame:
    """month_end: the next session is in another month; opex: third Friday of the month."""
    s = pd.Series(sessions)
    nxt = s.shift(-1)
    month_end = np.array([n is not None and not pd.isna(n) and n.month != d.month
                          for d, n in zip(s, nxt)])
    opex = np.array([d.weekday() == 4 and 15 <= d.day <= 21 for d in s])
    quarter = np.array([d.month in (3, 6, 9, 12) for d in s])
    return pd.DataFrame({"month_end": month_end, "quarter_end": month_end & quarter,
                         "opex": opex, "quad_witch": opex & quarter}, index=list(sessions))


def session_table(m: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """One row per session with 1-min bars. `m`: 1-min OHLCV, UTC index. `daily`: official
    open/close/dividends indexed by ET date, every trading session in order (so the next row is the
    next session, across weekends and holidays)."""
    m = m[~m.index.duplicated()].sort_index()
    day, mins = _day_minute(m.index)
    d = daily.sort_index()
    nxt = pd.DataFrame({"next_session": pd.Series(d.index, index=d.index).shift(-1),
                        "open_next": d["open"].shift(-1), "div_next": d["dividends"].shift(-1)})
    morning = window_volume(m, day, mins, OPEN, NOON1)
    afternoon = window_volume(m, day, mins, LATE, DECISION)
    tab = pd.DataFrame({
        "close_off": d["close"], "open_off": d["open"],
        "p_1550": price_at(m, day, mins, IMB), "p_1555": price_at(m, day, mins, DECISION),
        "p_1600": price_at(m, day, mins, CLOSE), "p_1605": price_at(m, day, mins, POST_ENTRY),
        "p_2000": price_at(m, day, mins, POST_LATE),
        "vwap_pre": window_vwap(m, day, mins, *VWAP_PRE),
        "vwap_last": window_vwap(m, day, mins, *VWAP_LAST),
        "vol_win": window_volume(m, day, mins, VWAP_PRE[0], DECISION),
        "vol_rth": window_volume(m, day, mins, OPEN, DECISION),
        "early_close": (afternoon.reindex(d.index).fillna(0)
                        < EARLY_CLOSE_FRAC * morning.reindex(d.index).fillna(0)),
    }, index=d.index).join(nxt).join(calendar_flags(list(d.index)))
    tab = tab[tab.index.isin(set(day))]
    tab.index.name = "session"
    return tab


def add_signals(tab: pd.DataFrame) -> pd.DataFrame:
    """Signals, returns and the volume-share z. Rows without a next open, early closes and rows
    missing a signal price are dropped BEFORE any rolling statistic, so they never enter one."""
    t = tab[~tab["early_close"] & tab["open_next"].notna()].copy()
    exit_px = t["open_next"] + t["div_next"].fillna(0.0)
    t["on_close"] = np.log(exit_px / t["close_off"])
    t["on_post"] = np.log(exit_px / t["p_1605"])
    t["post_spill"] = np.log(t["p_1605"] / t["close_off"])
    t["post_late"] = np.log(t["p_2000"] / t["p_1605"])
    t["dev_pre"] = np.log(t["p_1555"] / t["vwap_pre"])
    t["r_imb"] = np.log(t["p_1555"] / t["p_1550"])
    t["dev_close"] = np.log(t["close_off"] / t["vwap_last"])
    t["r_close"] = np.log(t["close_off"] / t["p_1550"])
    share = t["vol_win"] / t["vol_rth"]
    prior = share.shift(1).rolling(SIGMA_WIN, min_periods=SIGMA_WIN)
    t["win_share_z"] = (share - prior.mean()) / prior.std()
    return t.dropna(subset=["on_close", "dev_pre", "r_imb", "dev_close", "r_close"])


def attach_gex(t: pd.DataFrame, snaps: pd.DataFrame) -> pd.DataFrame:
    """long_gamma_{moc,post}: net_gex / abs_gex_total > 0 at the last snapshot computed at or
    before 15:55:00 / 16:00:00 ET that session (NaN when there is none). Full time of day, so a
    snapshot at 15:55:40 is not visible at the 15:55 decision."""
    t = t.copy()
    c = pd.to_datetime(snaps["computed_at"], utc=True).dt.tz_convert(ET)
    s = pd.DataFrame({"day": c.dt.date.to_numpy(), "tod": (c - c.dt.normalize()).to_numpy(),
                      "regime": (snaps["net_gex"] / (snaps["abs_gex_total"] + 1e-8)).to_numpy()})
    for col, cut in (("long_gamma_moc", DECISION), ("long_gamma_post", CLOSE)):
        last = (s[s["tod"] <= pd.Timedelta(minutes=cut)]
                .sort_values(["day", "tod"]).groupby("day")["regime"].last())
        t[col] = (last.reindex(t.index) > 0).where(last.reindex(t.index).notna())
    return t


# ---------------------------------------------------------------- pure: rules and statistics

def cell_direction(t: pd.DataFrame, signal: str, k: float) -> pd.Series:
    """+1/-1 on trade days, 0 otherwise. Sigma excludes today (shift 1)."""
    sig = t[signal]
    sigma = sig.shift(1).rolling(SIGMA_WIN, min_periods=SIGMA_WIN).std()
    on = sig.abs() > k * sigma
    return (-np.sign(sig)).where(on, 0.0).fillna(0.0)


def block_idx(n: int, n_boot: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """n_boot x n indices of a moving-block bootstrap (blocks of `block` consecutive observations)."""
    starts = rng.integers(0, max(1, n - block + 1), size=(n_boot, -(-n // block)))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n_boot, -1)[:, :n]
    return np.minimum(idx, n - 1)


def block_boot_ci(x: np.ndarray, n_boot: int = N_BOOT, block: int = BOOT_BLOCK, seed: int = 0):
    """95% CI of the mean, resampling blocks of `block` consecutive observations."""
    n = len(x)
    if n < 2:
        return [None, None]
    means = x[block_idx(n, n_boot, block, np.random.default_rng(seed))].mean(1)
    return [round(float(q), 3) for q in np.percentile(means, [2.5, 97.5])]


def trade_stats(r: np.ndarray, dirs: np.ndarray, mu: float, cost_bp: float = SELECT_COST_BP) -> dict:
    """r: overnight log returns on trade days; dirs: +1/-1. All outputs in bp."""
    if len(r) == 0:
        return dict(n=0)
    gross = dirs * r * BP
    net = gross - cost_bp
    edge = dirs * (r - mu) * BP
    long_, short = dirs > 0, dirs < 0
    return dict(
        n=int(len(r)), n_long=int(long_.sum()), n_short=int(short.sum()),
        hit=round(float((net > 0).mean()), 3),
        net_bp=round(float(net.mean()), 3), net_ci=block_boot_ci(net),
        net_by_cost={f"{c:g}bp": round(float(gross.mean() - c), 3) for c in COSTS_BP},
        edge_bp=round(float(edge.mean()), 3), edge_ci=block_boot_ci(edge),
        long_net_bp=round(float(net[long_].mean()), 3) if long_.any() else None,
        short_net_bp=round(float(net[short].mean()), 3) if short.any() else None,
        total_net_bp=round(float(net.sum()), 1),
    )


def random_p(r: np.ndarray, dirs: np.ndarray, n: int = N_RANDOM, seed: int = 0) -> dict:
    """Random signs on the same trade days; p for the cell's gross mean."""
    if len(r) == 0:
        return dict(p=None)
    real = float((dirs * r).mean())
    rng = np.random.default_rng(seed)
    sims = (rng.choice([-1.0, 1.0], size=(n, len(r))) * r).mean(1)
    return dict(p=round(float((1 + (sims >= real).sum()) / (1 + n)), 4),
                random_mean_bp_p95=round(float(np.percentile(sims, 95) * BP - SELECT_COST_BP), 3))


def ols_slope(x: np.ndarray, y: np.ndarray, seed: int = 0) -> dict:
    """Slope of y on x with a day-block bootstrap CI (pairs resampled in blocks)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]

    def slope(a, b):
        a = a - a.mean()
        return float((a * (b - b.mean())).sum() / (a * a).sum())

    n = len(x)
    boot = [slope(x[i], y[i]) for i in block_idx(n, N_BOOT, BOOT_BLOCK, np.random.default_rng(seed))]
    return dict(slope=round(slope(x, y), 4), ci=[round(float(q), 4) for q in np.percentile(boot, [2.5, 97.5])],
                n=int(n))


def split_sessions(index) -> tuple[pd.Index, pd.Index]:
    idx = pd.Index(sorted(index))
    cut = int(len(idx) * DISCOVERY_FRAC)
    return idx[:cut], idx[cut:]


def evaluate_execution(t: pd.DataFrame, name: str) -> dict:
    ex = EXECUTIONS[name]
    t = t.dropna(subset=[ex["ret"]])
    disc_idx, hold_idx = split_sessions(t.index)
    ret = t[ex["ret"]]
    mu = float(ret.loc[disc_idx].mean())

    cells = {}
    for signal in ex["signals"]:
        for k in KS:
            d = cell_direction(t, signal, k)
            cells[f"{name}:{signal}:k{k:g}"] = dict(signal=signal, k=k, dirs=d)

    def score(dirs: pd.Series, idx) -> dict:
        on = dirs.loc[idx] != 0
        return trade_stats(ret.loc[idx][on].to_numpy(), dirs.loc[idx][on].to_numpy(), mu)

    table = {c: {"discovery": score(v["dirs"], disc_idx)} for c, v in cells.items()}
    eligible = [c for c in cells if table[c]["discovery"].get("n", 0) >= MIN_TRADES]
    best = max(eligible, key=lambda c: table[c]["discovery"]["edge_bp"]) if eligible else None
    out = dict(mu_discovery_bp=round(mu * BP, 3), cells={c: v["discovery"] for c, v in table.items()},
               selected=best,
               sessions=dict(discovery=[str(disc_idx[0]), str(disc_idx[-1]), len(disc_idx)],
                             holdout=[str(hold_idx[0]), str(hold_idx[-1]), len(hold_idx)]))
    if best is None:
        out["verdict"] = "no cell reached MIN_TRADES on discovery"
        return out

    out.update(signal=cells[best]["signal"], k=cells[best]["k"])
    dirs = cells[best]["dirs"]
    res = {}
    for split, idx in (("discovery", disc_idx), ("holdout", hold_idx)):
        on = dirs.loc[idx] != 0
        r, d = ret.loc[idx][on].to_numpy(), dirs.loc[idx][on].to_numpy()
        sub = {}
        days = t.loc[idx][on]
        groups = {"win_share_z>1": days["win_share_z"] > 1, "win_share_z<=1": days["win_share_z"] <= 1}
        for flag in CALENDAR:
            groups[flag] = days[flag].astype(bool)
            groups[f"not_{flag}"] = ~days[flag].astype(bool)
        g = days[ex["gex"]]
        groups["long_gamma"], groups["short_gamma"] = g == True, g == False  # noqa: E712 (NaN-safe)
        for gname, mask in groups.items():
            mask = mask.to_numpy(bool)
            sub[gname] = trade_stats(r[mask], d[mask], mu)
        res[split] = dict(
            cell=trade_stats(r, d, mu),
            always_long=trade_stats(ret.loc[idx].to_numpy(), np.ones(len(idx)), mu),
            same_days=trade_stats(r, np.ones_like(d), mu),
            flipped=trade_stats(r, -d, mu),
            random=random_p(r, d),
            subgroups=sub,
        )
    h = res["holdout"]
    tests = {
        "net_mean>0": h["cell"].get("net_bp", 0) > 0,
        "net_ci_lo>0": (h["cell"].get("net_ci") or [None])[0] is not None and h["cell"]["net_ci"][0] > 0,
        "edge>0": h["cell"].get("edge_bp", 0) > 0,
        "beats_always_long": h["cell"].get("net_bp", -1e9) > h["always_long"].get("net_bp", 1e9),
        "random_p<0.05": (h["random"].get("p") or 1.0) < 0.05,
    }
    out.update(results=res, tests=tests,
               verdict="PASS" if all(tests.values()) else "FAIL: " + ", ".join(k for k, v in tests.items() if not v))
    return out


def measurement(t: pd.DataFrame) -> dict:
    exit_px = t["open_next"] + t["div_next"].fillna(0.0)
    sq = pd.DataFrame({
        "mse_close": np.log(exit_px / t["close_off"]) ** 2,
        "mse_vwap15": np.log(exit_px / t["vwap_last"]) ** 2,
        "mse_p1559": np.log(exit_px / t["p_1600"]) ** 2,
    }, index=t.index).dropna() * 1e4
    diff = (sq["mse_close"] - sq["mse_vwap15"]).to_numpy()
    years = pd.Index([d.year for d in sq.index])
    return dict(
        note="x1e4, as the paper's Table 1; lower = the price is a better forecast of the next open",
        all={c: round(float(sq[c].mean()), 4) for c in sq},
        close_minus_vwap15=dict(mean=round(float(diff.mean()), 5), ci=block_boot_ci(diff)),
        by_year={int(y): {c: round(float(sq.loc[years == y, c].mean()), 4) for c in sq} for y in sorted(set(years))},
        reversal_slope={s: ols_slope(t[s].to_numpy(), t["on_close"].to_numpy()) for s in ("dev_close", "r_close")},
        post_close_spill={
            "corr(r_close, 16:00->16:05)": round(float(t[["r_close", "post_spill"]].corr().iloc[0, 1]), 4),
            "corr(r_close, 16:05->20:00)": round(float(t[["r_close", "post_late"]].corr().iloc[0, 1]), 4),
            "corr(r_close, 16:05->next open)": round(float(t[["r_close", "on_post"]].corr().iloc[0, 1]), 4),
        },
    )


# ---------------------------------------------------------------- I/O

def load_daily(symbol: str, out: Path, refresh: bool) -> pd.DataFrame:
    cache = out / f"daily_{symbol}.parquet"
    if cache.exists() and not refresh:
        d = pd.read_parquet(cache)
    else:
        import yfinance as yf
        h = yf.Ticker(symbol).history(start="2021-12-01", end=VERIFY_START.strftime("%Y-%m-%d"),
                                      auto_adjust=False, actions=True)
        if h.empty:
            raise SystemExit(f"yfinance returned no daily rows for {symbol}")
        d = pd.DataFrame({"open": h["Open"].to_numpy(), "close": h["Close"].to_numpy(),
                          "dividends": h["Dividends"].to_numpy()},
                         index=pd.Index([x.date() for x in h.index], name="date"))
        out.mkdir(parents=True, exist_ok=True)
        d.to_parquet(cache)
    d = d[[x < VERIFY_START.date() for x in d.index]]
    return d


def load_bars(symbol: str, cutoff: pd.Timestamp, bars_dir: Path = BARS_DIR) -> pd.DataFrame:
    files = [f for f in sorted((bars_dir / symbol).glob("*.parquet"))
             if date.fromisoformat(f.name[:10]) < cutoff.tz_convert(ET).date()]
    if not files:
        raise FileNotFoundError(f"no Databento bars for {symbol}; run databento_fetch.py eq-ohlcv-1m")
    return pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume"],
                                      filters=[("ts_event", "<", cutoff)]) for f in files])


def load_frame(symbol: str, out: Path, refresh: bool) -> pd.DataFrame:
    daily = load_daily(symbol, out, refresh)
    days = research_sessions(daily.index)
    # The last research session exits at the next session's open (in the gap week): read through
    # the end of that session, never to VERIFY_START.
    last_exit = daily.index[daily.index.get_loc(days[-1]) + 1]
    cutoff = pd.Timestamp(last_exit + timedelta(days=1), tz=ET).tz_convert("UTC")
    assert cutoff <= VERIFY_START.tz_convert("UTC"), "LEAK: bar cutoff reaches the verify block"
    bars = load_bars(symbol, cutoff)
    assert (bars.index < cutoff).all()
    tab = session_table(bars, daily)
    tab = tab[tab.index.isin(set(days))]
    t = add_signals(tab)
    snaps_path = GEX_DIR / f"{symbol.lower()}_gex_snapshots.parquet"
    if snaps_path.exists():
        snaps = pd.read_parquet(snaps_path, columns=["computed_at", "net_gex", "abs_gex_total"],
                                filters=[("computed_at", "<", cutoff)])
        t = attach_gex(t, snaps)
    else:
        t["long_gamma_moc"] = t["long_gamma_post"] = np.nan
    assert all(d < VERIFY_START.date() for d in t["next_session"]), "LEAK: exit in the verify block"
    print(f"{symbol}: {len(t)} usable research sessions {t.index[0]} -> {t.index[-1]} "
          f"(of {len(days)}; {int(tab['early_close'].sum())} early closes dropped); bars read < {cutoff}")
    return t


# ---------------------------------------------------------------- plot (aggregates only)

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SPLIT_COLORS = {"discovery": "#2a78d6", "holdout": "#eb6834"}  # categorical slots 1-2


def plot_study(t: pd.DataFrame, res: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sym = res["symbol"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 5.6), facecolor=SURFACE, gridspec_kw={"wspace": 0.3})
    fig.suptitle(f"{sym}: does the closing print reverse by the next open?  Research sessions "
                 f"{t.index[0]} to {t.index[-1]} (sealed verify block not loaded)",
                 x=0.01, y=0.99, ha="left", fontsize=11.5, color=INK)
    disc_idx, hold_idx = split_sessions(t.index)
    mu = res["executions"]["moc"]["mu_discovery_bp"] / BP
    for ax, title in ((a, "a  Overnight return minus discovery drift, by quintile of dev_close\n"
                          "    (official close vs 15:45-15:59 VWAP; 95% block CI)"),
                      (b, "b  Selected 15:55-decision cell vs always long, cumulative net bp\n"
                          f"    ({SELECT_COST_BP:g} bp per round trip; holdout starts at the line)")):
        ax.set_facecolor(SURFACE)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(INK2)
        ax.tick_params(colors=INK2, labelsize=8.5)
        ax.set_title(title, loc="left", fontsize=9.5, color=INK)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)

    edges = np.quantile(t.loc[disc_idx, "dev_close"], [0, .2, .4, .6, .8, 1])
    edges[0], edges[-1] = -np.inf, np.inf
    for i, (split, idx) in enumerate((("discovery", disc_idx), ("holdout", hold_idx))):
        x = t.loc[idx]
        q = np.clip(np.searchsorted(edges, x["dev_close"], side="right") - 1, 0, 4)
        y = (x["on_close"] - mu).to_numpy() * BP
        means = [y[q == j].mean() for j in range(5)]
        cis = [block_boot_ci(y[q == j]) for j in range(5)]
        xs = np.arange(5) + (i - 0.5) * 0.18
        a.vlines(xs, [c[0] for c in cis], [c[1] for c in cis], color=SPLIT_COLORS[split], lw=2)
        a.plot(xs, means, "o", ms=8, color=SPLIT_COLORS[split], mec=SURFACE, mew=2, label=split)
    a.axhline(0, color=INK2, lw=0.8)
    a.set_xticks(range(5), ["1\nclose far\nbelow VWAP", "2", "3", "4", "5\nclose far\nabove VWAP"], color=INK)
    a.set_ylabel("bp", color=INK2, fontsize=9)
    a.legend(fontsize=8.5, frameon=False, labelcolor=INK, loc="upper right")

    ex = res["executions"]["moc"]
    if ex.get("selected"):
        sig, k = ex["signal"], ex["k"]
        d = cell_direction(t, sig, k)
        net = (d * t["on_close"] * BP - SELECT_COST_BP * (d != 0)).cumsum()
        drift = (t["on_close"] * BP - SELECT_COST_BP).cumsum()
        x = pd.to_datetime(pd.Index(t.index))
        b.plot(x, net.to_numpy(), color=SPLIT_COLORS["discovery"], lw=2, label=f"fade: {ex['selected']}")
        b.plot(x, drift.to_numpy(), color=INK2, lw=2, ls=(0, (4, 2)), label="always long overnight")
        b.axvline(pd.Timestamp(hold_idx[0]), color=INK2, lw=0.8)
        b.set_ylabel("cumulative bp", color=INK2, fontsize=9)
        b.legend(fontsize=8.5, frameon=False, labelcolor=INK, loc="upper left")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------- main

def _jsonable(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="QQQ", choices=["QQQ", "SPY"])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--plots", type=Path, default=PLOTS)
    ap.add_argument("--refresh-daily", action="store_true", help="re-download the yfinance daily cache")
    args = ap.parse_args()

    t = load_frame(args.symbol, args.out, args.refresh_daily)
    res = dict(symbol=args.symbol, sessions=len(t), first=str(t.index[0]), last=str(t.index[-1]),
               measurement=measurement(t),
               executions={name: evaluate_execution(t, name) for name in EXECUTIONS})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"close_auction_{args.symbol.lower()}.json").write_text(json.dumps(res, indent=2, default=_jsonable))
    t.to_parquet(args.out / f"sessions_{args.symbol.lower()}.parquet")
    plot_study(t, res, args.plots / f"close_auction_{args.symbol.lower()}.png")

    me = res["measurement"]
    print(f"\nMSE x1e4 (all): {me['all']}  close - vwap15 = {me['close_minus_vwap15']}")
    print(f"reversal slope on_close ~ dev_close: {me['reversal_slope']['dev_close']}")
    print(f"reversal slope on_close ~ r_close:   {me['reversal_slope']['r_close']}")
    print(f"post-close spill: {me['post_close_spill']}")
    for name, ex in res["executions"].items():
        print(f"\n[{name}] discovery drift {ex['mu_discovery_bp']} bp/night; selected {ex['selected']}")
        for c, s in ex["cells"].items():
            print(f"   {c:<24} n={s.get('n', 0):>4}  net={s.get('net_bp')}  edge={s.get('edge_bp')}")
        for split, r in ex.get("results", {}).items():
            c = r["cell"]
            print(f"   {split:<9} cell n={c['n']} net={c['net_bp']} {c['net_ci']} edge={c['edge_bp']} "
                  f"long={c['long_net_bp']} short={c['short_net_bp']} | always_long={r['always_long']['net_bp']} "
                  f"same_days={r['same_days']['net_bp']} flipped={r['flipped']['net_bp']} random_p={r['random']['p']}")
        print(f"   verdict: {ex['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
