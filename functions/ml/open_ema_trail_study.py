"""Opening 5m candle vs the 12 EMA, managed with trailing stops: a train/test study on NQ and ES proxies.

Idea (Sunny, 2026-10-24): at the close of the first 5-minute candle of the NY session (09:30-09:35 ET),
buy if it closed above the 12-period EMA, sell if below. Replace the fixed stop and target with a trailing
stop, and compare several ways of trailing.

Rules (written down before any number was computed, not changed after the first run):
  - data: Databento XNAS.ITCH ohlcv-1m QQQ and SPY (data/databento/eq-ohlcv-1m), RTH 09:30-15:59 ET only,
    sessions with >= 380 RTH bars. Prices are scaled to futures points (QQQ x 41.2 -> NQ, SPY x 10.05 -> ES,
    as in the other proxy studies) and traded as 1 MNQ ($2/pt) / 1 MES ($5/pt), tick 0.25 in those points.
    (Sunny chose this free proxy over buying 2011-2021 CME bars, $27.36, on 2026-10-24.)
  - 5m bars: RTH 1m bars grouped on the ET clock (:00, :05, ...).
  - EMA12: alpha = 2/13 over RTH 5m closes, carried across sessions (a stock chart with extended hours
    off), seeded with the first close loaded; >= 36 5m bars must precede the signal.
  - signal: the 09:30 5m candle (its 09:30 1m bar must exist, >= 4 of its 5). close > EMA12 at that
    close -> long, close < EMA12 -> short, equal -> no trade. One trade a session.
  - entry: open of the 09:35 1m bar, 1 tick adverse.
  - scale: ATR14 = mean true range of the previous 14 RTH sessions (09:30-16:00 bars; prior close only from
    the same contract, else high-low). Days without 14 prior sessions are skipped. D = initial stop distance
    = f x ATR14 (or p% of entry for trail_pct). 1R = D.
  - exits on 1m bars from 09:35, per bar: (1) open through the stop -> fill at the open - 1 tick;
    (2) low through the stop -> stop - 1 tick; (3) update the best price with the bar's high and ratchet the
    stop (it never loosens); (4) close through the new stop (so price fell through it after the high) ->
    new stop - 1 tick. Otherwise flat at the close of the last bar before 16:00 ET, - 1 tick.
    Targets (reference brackets only) fill only when a bar trades a tick through them.
  - costs: the slippage above plus $0.50 per contract per side. Stress test: 2 ticks on stops.
  - trailing methods (D = f x ATR14 unless noted):
      trail_pct  p in {0.15,0.25,0.40,0.60}%  stop = best - p% of entry (a fixed "trailing drawdown")
      trail_atr  f in {0.10,0.15,0.25,0.40}   stop = best - D
      be_trail   f in {0.15,0.25,0.40}        stop = best - D, and >= entry once best >= entry + 0.5D
      tighten    f in {0.15,0.25,0.40}        fixed at entry - D until best >= entry + D, then best - 0.5D
      step       f in {0.10,0.15,0.25,0.40}   each time best reaches entry + kD (k >= 1), stop -> entry + (k-1)D
      ema_exit   f in {0.15,0.25,0.40}        fixed stop entry - D; exit at the next bar's open after a 5m close
                                              on the wrong side of EMA12
      swing      N in {3,6} x f in {0.15,0.25} stop = max(entry - D, lowest low of the last N completed 5m bars)
    25 selectable cells. Reference only (never selected): bracket f=0.25 with a 1R and a 2R target, and
    hold-to-close with a 0.25 ATR stop.
  - split: TRAIN = sessions 2022-01-03 .. 2024-12-31; TEST = 2025-01-02 .. 2026-08-14 (the last research
    session; the sealed verify block from holdout.VERIFY_START is never loaded). The default run loads no
    bar on or after 2025-01-01 UTC. --test is one look: it writes test.lock and refuses a rerun.
  - selection (train only): a cell is eligible if its mean net R > 0 on BOTH NQ and ES. The selected cell is
    the eligible one with the highest average of the two. The best cell of each family is reported too.
    No eligible cell -> --test refuses to run.
  - controls (same days, same exits): random direction (2,000 seeds; p = (1 + #seeds with mean R >= the
    signal's) / 2,001), reversed signal, always long (the drift).
  - verdict (TEST, selected cell): PASS if the day-pooled (NQ+ES average) mean net R > 0 with its 95%
    5-session block-bootstrap CI above 0, mean net R > 0 on both symbols, and random-direction p < 0.05.
    WEAK if pooled mean > 0 but a condition fails. FAIL if pooled mean <= 0. Family bests are secondary
    (7 tests, so read them at alpha 0.05/7).

Prior data use (read the test result with this in mind): QQQ 2025-03-27 -> 2026-08-14 was the one-look
holdout of lucid_orb_study (5m opening-range breakout, STRUCTURE-ONLY); SPY's same window was the
close_auction holdout and was scored by the write-up 15m ORB rule. This signal and these exits were never
tested there, but the window is not pristine for opening-range ideas. TRAIN years were seen by many studies.

    python open_ema_trail_study.py            # train only
    python open_ema_trail_study.py --test     # one look at 2025-2026-08, selected cell frozen from train
    python open_ema_trail_study.py --news     # train only: the same grid with high-impact news filters
    python open_ema_trail_study.py --news-test  # diagnostic only: news filters on the already-seen TEST
    python open_ema_trail_study.py --timeframes 15,30,45,60   # the same idea on bigger opening candles
    python open_ema_trail_study.py --gamma    # only trade in negative / positive dealer gamma
    python open_ema_trail_study.py --confirm-check   # 2016-2021 futures: coverage only, no results
    python open_ema_trail_study.py --confirm  # ONE look: frozen 5m/neg/step/0.25atr on NQ/ES 2016-2021

Gamma regime (added 2026-10-24 at Sunny's request, after the TEST results above). Regime of a day = sign of
net_gex (data/thetadata_gex/<qqq|spy>_gex_snapshots.parquet; QQQ for NQ, SPY for ES) at the latest
snapshot with computed_at <= the entry time, same session (no snapshot -> no trade). For each of the
5 opening-candle sizes x {neg, pos}: train the 25 cells on that regime's TRAIN days, select as above,
then run the selection and family bests on that regime's TEST days once (test_gamma_<tf>_<regime>.lock).
10 combinations on a reused window: PASS needs random-direction p < 0.005 (0.05/10) on both symbols.
Prior: dealers short gamma (neg) push moves further, so a trend signal should do better there; long
gamma (pos) dampens moves. TRAIN neg days are mostly 2022 (a bear year), so regime and year overlap.

Bigger opening candles (added 2026-10-24 at Sunny's request, after the 5m TEST FAIL). For tf in
{15, 30, 45, 60} minutes the chart is tf-minute RTH candles anchored at 09:30 (09:30-10:30, 10:30-11:30, ...
for 60; the last candle of the day may be short). Signal = the 09:30 candle's close vs EMA12 of tf-candle
closes; entry at the open of 09:30 + tf. The exits are unchanged except that ema_exit and swing use tf
candles. Each tf is trained and selected on TRAIN exactly as above, then its selection and family bests are
run on TEST once (test_tf<tf>.lock). The TEST window was already seen by the 5m version, and there are 4
timeframes, so read each TEST at alpha 0.05/4 and treat it as weaker evidence than a fresh window.

Confirmation on 2016-2021 CME futures (--confirm; rules written 2026-10-25 BEFORE any 2016-2021 futures bar
was downloaded or any trade there simulated; not to be changed after the run). One look at the frozen version
"5m opening candle / negative gamma / step/0.25atr" (the only coherent thread of --gamma above) on years no
study has used for this idea:
  - data: Databento GLBX.MDP3 ohlcv-1m, continuous front month by volume (NQ.v.0 / ES.v.0;
    data/databento/fut-ohlcv-1m-cont), native index points, NO ETF ratios. RTH 09:30-15:59 ET, sessions with
    >= 380 RTH bars. NQ sessions 2016-01-04 -> 2021-12-31, ES 2017-01-03 -> 2021-12-31 (SPY options IV
    is empty for 2016 on our ThetaData plan). Every monthly file in those windows must exist or the run
    refuses before the lock is written.
  - rolls: a contract segment is a run of consecutive bars with one instrument_id (a flip back to an older
    contract starts a new segment). The EMA12 restarts in each segment and needs >= 36 5m bars, so the first
    session of every contract is skipped; ATR14 never takes a prior close across a roll (that day's true
    range is its high-low); a session that mixes contracts is skipped.
  - rules unchanged from the 5m study: signal = the 09:30 5m candle close vs EMA12 of RTH-only 5m closes;
    entry 09:35 open + 1 tick; ATR14 of the previous 14 RTH sessions; exit step/0.25atr (frozen; asserted
    against gamma_5_neg.json); 1 tick on stops and the time exit; $0.50/side; flat at the last bar before
    16:00. Traded as 1 MNQ ($2/pt) / 1 MES ($5/pt), as if micros had existed (only matters for the $1
    commission in R).
  - regime: sign of net_gex at the latest snapshot with computed_at <= 09:35 ET that session
    (data/thetadata_gex/<qqq|spy>_gex_snapshots_2016_2021.parquet, built by thetadata_gex.py with the same
    code as the 2022+ file; QQQ for NQ, SPY for ES). No snapshot -> no trade. Traded: negative gamma only.
  - verdict (negative-gamma days, step/0.25atr): PASS if the pooled mean net R > 0 with its 95% 5-session
    block-bootstrap CI above 0, mean net R > 0 on BOTH NQ and ES, and random-direction p < 0.05 on BOTH
    (2,000 seeds, same days and exits). WEAK if the pooled mean > 0 but a condition fails; FAIL if <= 0.
    Pooled = per-session average of NQ and ES net R where both traded, the one that traded otherwise
    (2016 is NQ only).
  - bars are loaded from each window's first day only (no earlier warm-up), so the first 14 sessions of
    each window have no ATR and are skipped.
  - reported, never part of the verdict: reversed signal, always long, random-direction mean, the same rule
    on positive-gamma days (side check), on all days regardless of regime, 2-tick stop stress, and results
    per calendar year.
  - one look: confirm.lock is written just before the first trade is simulated; a second --confirm refuses.
    --confirm-check prints data coverage, rolls and regime day counts only (no trade results) and may be
    run any number of times.

News filters (added 2026-10-24 at Sunny's request, AFTER the test above FAILED, so they are judged on
TRAIN only; the test window cannot confirm them). High-impact events from econ_calendar.py (coverage
2022+), fixed before the first run:
  skip_day       no trade on a session with any high-impact event (08:30 releases included)
  skip_intraday  no trade only if a high-impact event lands 09:30-16:00 ET (10:00 ISM, 14:00 FOMC/minutes)
  skip_big3      no trade on CPI, NFP or FOMC-decision days
  flat_news      trade every day; if a high-impact event lands after entry and before 16:00, exit at the
                 close of the last 1m bar ending <= event - 5 min (no re-entry)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from holdout import VERIFY_START  # noqa: E402

DATA = HERE / "data"
BARS = DATA / "databento" / "eq-ohlcv-1m"
OUT = DATA / "open_ema_trail"
ET = "America/New_York"

TRAIN = (date(2022, 1, 3), date(2024, 12, 31))
TEST = (date(2025, 1, 2), date(2026, 8, 14))
TRAIN_END_EXCL, TEST_END_EXCL = date(2025, 1, 1), date(2026, 8, 15)
PROXY = {"NQ": ("QQQ", 41.2), "ES": ("SPY", 10.05)}
MIN_RTH_BARS = 380
TICK = 0.25
PT_USD = {"NQ": 2.0, "ES": 5.0}  # micro contracts
COMM_RT = 1.0
OPEN_M, ENTRY_M, CLOSE_M = 9 * 60 + 30, 9 * 60 + 35, 16 * 60
EMA_LEN, MIN_5M = 12, 36
ATR_LEN = 14
N_RANDOM = 2000
BLOCK = 5
SEED = 20261024


@dataclass(frozen=True)
class Cell:
    family: str
    f: float          # ATR fraction (or percent for trail_pct)
    n: int = 0        # swing lookback
    target: float = 0.0
    reference: bool = False

    @property
    def name(self) -> str:
        if self.family == "trail_pct":
            return f"trail_pct/{self.f:.2f}%"
        s = f"{self.family}/{self.f:.2f}atr"
        if self.n:
            s += f"/N{self.n}"
        if self.target:
            s += f"/{self.target:g}R"
        return s


CELLS = (
    [Cell("trail_pct", p) for p in (0.15, 0.25, 0.40, 0.60)]
    + [Cell("trail_atr", f) for f in (0.10, 0.15, 0.25, 0.40)]
    + [Cell("be_trail", f) for f in (0.15, 0.25, 0.40)]
    + [Cell("tighten", f) for f in (0.15, 0.25, 0.40)]
    + [Cell("step", f) for f in (0.10, 0.15, 0.25, 0.40)]
    + [Cell("ema_exit", f) for f in (0.15, 0.25, 0.40)]
    + [Cell("swing", f, n) for n in (3, 6) for f in (0.15, 0.25)]
)
REFERENCE = [Cell("bracket", 0.25, target=1, reference=True), Cell("bracket", 0.25, target=2, reference=True),
             Cell("hold", 0.25, reference=True)]
SWING_N = sorted({c.n for c in CELLS if c.n})


# ---------------------------------------------------------------- data

def load_bars(product: str, end_excl: date) -> pd.DataFrame:
    """RTH 1m bars of the product's ETF proxy, in futures points."""
    sym, ratio = PROXY[product]
    assert end_excl <= VERIFY_START.date(), "LEAK: would read the sealed verify block"
    files = sorted((BARS / sym).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bars in {BARS / sym}; run databento_fetch.py eq-ohlcv-1m")
    cutoff = pd.Timestamp(end_excl, tz="UTC")
    keep = [f for f in files if date.fromisoformat(f.name[:10]) < end_excl]
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    bars = pd.concat([pd.read_parquet(f, columns=cols) for f in keep]).sort_index()
    bars = bars[~bars.index.duplicated()]
    bars = bars[bars.index < cutoff]
    assert (bars.index < cutoff).all(), "LEAK: bars reach past the requested window"
    et = bars.index.tz_convert(ET)
    m = et.hour * 60 + et.minute
    bars = bars[(m >= OPEN_M) & (m < CLOSE_M)].copy()
    bars[["open", "high", "low", "close"]] *= ratio
    bars["instrument_id"] = 0  # one continuous series, no rolls
    n = bars.groupby(bars.index.tz_convert(ET).date).size()
    full = set(n.index[n >= MIN_RTH_BARS])
    return bars[np.isin(bars.index.tz_convert(ET).date, list(full))]


@dataclass
class Day:
    d: date
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    end5: np.ndarray        # bool: this 1m bar completes a 5m bar
    ema: np.ndarray         # EMA12 after that 5m bar (valid where end5)
    swlo: dict              # N -> lowest low of the last N completed 5m bars (valid where end5)
    swhi: dict
    sig_close: float
    sig_ema: float
    atr: float
    m: np.ndarray | None = None  # ET minute of each 1m bar


def build_days(bars: pd.DataFrame, lo: date, hi: date, tf: int = 5) -> list[Day]:
    """tf = candle size in minutes, anchored at 09:30 (bars are RTH only). 5 = the clock 5m grid."""
    et = bars.index.tz_convert(ET)
    minute = et.hour * 60 + et.minute
    entry_m = OPEN_M + tf
    start = bars.index.floor("min") - pd.to_timedelta((minute - OPEN_M) % tf, unit="min")
    df = bars.assign(minute=minute, day=et.date, b5=start)
    # ---- 5m bars per contract, EMA and swing extremes
    g5 = df.groupby(["instrument_id", "b5"], sort=True)
    five = pd.DataFrame({"h": g5.high.max(), "l": g5.low.min(), "c": g5.close.last()}).reset_index()
    five["ema"] = five.groupby("instrument_id").c.transform(lambda s: s.ewm(alpha=2 / (EMA_LEN + 1), adjust=False).mean())
    five["k"] = five.groupby("instrument_id").cumcount() + 1
    for n in SWING_N:
        five[f"lo{n}"] = five.groupby("instrument_id").l.transform(lambda s: s.rolling(n, min_periods=n).min())
        five[f"hi{n}"] = five.groupby("instrument_id").h.transform(lambda s: s.rolling(n, min_periods=n).max())
    five = five.set_index(["instrument_id", "b5"])

    # ---- RTH daily ranges for ATR (contract-aware prior close)
    rth = df[(df.minute >= OPEN_M) & (df.minute < CLOSE_M)]
    gd = rth.groupby("day", sort=True)
    daily = pd.DataFrame({"h": gd.high.max(), "l": gd.low.min(), "c": gd.close.last(),
                          "iid": gd.instrument_id.last()})
    pc = daily.c.shift(1).where(daily.iid.shift(1) == daily.iid)
    tr = np.maximum(daily.h - daily.l, np.maximum((daily.h - pc).abs(), (daily.l - pc).abs()).fillna(0))
    daily["atr_prev"] = tr.rolling(ATR_LEN, min_periods=ATR_LEN).mean().shift(1)

    out = []
    for d, g in rth.groupby("day", sort=True):
        if d < lo or d > hi:
            continue
        atr = daily.atr_prev.get(d, np.nan)
        if not np.isfinite(atr) or atr <= 0:
            continue
        iid = int(g.instrument_id.iloc[0])
        if g.instrument_id.nunique() != 1:
            continue
        m = g.minute.to_numpy()
        first = (m >= OPEN_M) & (m < entry_m)
        if first.sum() < max(4, int(0.8 * tf)) or m[0] != OPEN_M:
            continue
        b5_open = g.b5.iloc[0]
        try:
            sig = five.loc[(iid, b5_open)]
        except KeyError:
            continue
        if sig.k < MIN_5M:
            continue
        tr_ = g[m >= entry_m]
        if len(tr_) < 2 or tr_.minute.iloc[0] != entry_m:
            continue
        b5 = tr_.b5.to_numpy()
        end5 = np.r_[b5[1:] != b5[:-1], True]
        fv = five.loc[iid].reindex(tr_.b5)
        out.append(Day(d, tr_.open.to_numpy(float), tr_.high.to_numpy(float), tr_.low.to_numpy(float),
                       tr_.close.to_numpy(float), end5, fv.ema.to_numpy(float),
                       {n: fv[f"lo{n}"].to_numpy(float) for n in SWING_N},
                       {n: fv[f"hi{n}"].to_numpy(float) for n in SWING_N},
                       float(sig.c), float(sig.ema), float(atr), tr_.minute.to_numpy()))
    return out


# ---------------------------------------------------------------- simulation

def simulate(day: Day, direction: int, cell: Cell, stop_slip: int = 1) -> tuple[float, float, int]:
    """One trade. Returns (pnl in points incl. slippage, D in points, bars held). Short = mirrored long."""
    s = direction
    if s > 0:
        O, H, L, C, ema = day.O, day.H, day.L, day.C, day.ema
        swing = day.swlo.get(cell.n)
    else:
        O, H, L, C, ema = -day.O, -day.L, -day.H, -day.C, -day.ema
        swing = -day.swhi[cell.n] if cell.n else None
    end5 = day.end5
    entry = O[0] + TICK
    D = cell.f / 100 * abs(entry) if cell.family == "trail_pct" else cell.f * day.atr
    D = max(round(D / TICK) * TICK, TICK)
    stop = entry - D
    target = entry + cell.target * D if cell.target else np.inf
    best = entry
    slip = stop_slip * TICK
    n = len(O)
    fam = cell.family
    for i in range(n):
        if O[i] <= stop:
            return O[i] - slip - entry, D, i + 1
        if L[i] <= stop:
            return stop - slip - entry, D, i + 1
        if H[i] > target:  # tick-through only
            return target - entry, D, i + 1
        if H[i] > best:
            best = H[i]
        new = stop
        if fam in ("trail_pct", "trail_atr"):
            new = best - D
        elif fam == "be_trail":
            new = best - D
            if best >= entry + 0.5 * D:
                new = max(new, entry)
        elif fam == "tighten":
            if best >= entry + D:
                new = best - 0.5 * D
        elif fam == "step":
            k = int((best - entry) // D)
            if k >= 1:
                new = entry + (k - 1) * D
        elif fam == "swing" and end5[i] and np.isfinite(swing[i]):
            new = swing[i]
        if new > stop:
            stop = new
            if C[i] <= stop:
                return stop - slip - entry, D, i + 1
        if fam == "ema_exit" and end5[i] and C[i] < ema[i]:
            if i + 1 < n:
                return O[i + 1] - TICK - entry, D, i + 2
            return C[i] - TICK - entry, D, i + 1
    return C[-1] - TICK - entry, D, n


def run_cell(days: list[Day], product: str, cell: Cell, stop_slip: int = 1) -> dict:
    """Both directions for every day, so controls are free. Arrays aligned with days."""
    usd = PT_USD[product]
    res = {}
    for s in (1, -1):
        pnl = np.empty(len(days)); Ds = np.empty(len(days)); held = np.empty(len(days))
        for j, day in enumerate(days):
            p, D, h = simulate(day, s, cell, stop_slip)
            pnl[j], Ds[j], held[j] = p, D, h
        usd_net = pnl * usd - COMM_RT
        res[s] = {"gross_R": pnl / Ds, "net_R": usd_net / (Ds * usd), "net_usd": usd_net, "held": held}
    return res


NEWS_FILTERS = ("skip_day", "skip_intraday", "skip_big3", "flat_news")


def apply_news(days: list[Day], mode: str, events: list) -> list[Day]:
    """events: (day, ET minute, type) of high-impact releases. Returns the filtered / truncated days."""
    by_day: dict = {}
    for d, minute, kind in events:
        by_day.setdefault(d, []).append((minute, kind))
    out = []
    for day in days:
        ev = by_day.get(day.d, [])
        intraday = sorted(m for m, _ in ev if OPEN_M <= m < CLOSE_M)
        if mode == "skip_day" and ev:
            continue
        if mode == "skip_intraday" and intraday:
            continue
        if mode == "skip_big3" and any(k in ("cpi", "nfp", "fomc") for _, k in ev):
            continue
        if mode == "flat_news":
            first = next((m for m in intraday if m > ENTRY_M), None)
            if first is not None:
                keep = day.m + 1 <= first - 5
                if keep.sum() < 1:
                    continue
                k = int(keep.sum())
                day = Day(day.d, day.O[:k], day.H[:k], day.L[:k], day.C[:k], day.end5[:k], day.ema[:k],
                          {n: v[:k] for n, v in day.swlo.items()}, {n: v[:k] for n, v in day.swhi.items()},
                          day.sig_close, day.sig_ema, day.atr, day.m[:k])
        out.append(day)
    return out


def high_impact_events(lo: date, hi: date) -> list:
    import econ_calendar as ec
    assert ec.covered_through("high") >= hi, "news calendar does not cover the window"
    out = []
    for e in ec.events("high"):
        if lo <= e.day <= hi:
            h, mm = map(int, e.time_et.split(":"))
            out.append((e.day, h * 60 + mm, e.event))
    return out


def signals(days: list[Day]) -> np.ndarray:
    return np.array([np.sign(d.sig_close - d.sig_ema) for d in days], dtype=int)


def pick(res: dict, dirs: np.ndarray, key: str) -> np.ndarray:
    out = np.where(dirs > 0, res[1][key], res[-1][key])
    return np.where(dirs == 0, np.nan, out)


# ---------------------------------------------------------------- statistics

def block_ci(x: np.ndarray, rng: np.random.Generator, reps: int = 5000) -> tuple[float, float]:
    x = x[np.isfinite(x)]
    nb = int(np.ceil(len(x) / BLOCK))
    starts = rng.integers(0, max(len(x) - BLOCK, 1), size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(BLOCK)).reshape(reps, -1)[:, :len(x)]
    m = x[idx].mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def max_dd(usd: np.ndarray) -> float:
    eq = np.cumsum(np.nan_to_num(usd))
    return float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max())


def summarize(res: dict, dirs: np.ndarray, rng: np.random.Generator) -> dict:
    net = pick(res, dirs, "net_R"); gross = pick(res, dirs, "gross_R")
    usd = pick(res, dirs, "net_usd"); held = pick(res, dirs, "held")
    ok = np.isfinite(net)
    wins = usd[ok][usd[ok] > 0].sum(); losses = -usd[ok][usd[ok] < 0].sum()
    daily = np.nan_to_num(usd)
    lo, hi = block_ci(net, rng)
    return {
        "trades": int(ok.sum()), "long_share": float((dirs[ok] > 0).mean()),
        "mean_net_R": float(np.nanmean(net)), "ci95": [lo, hi], "mean_gross_R": float(np.nanmean(gross)),
        "median_net_R": float(np.nanmedian(net)), "win_rate": float((net[ok] > 0).mean()),
        "avg_win_R": float(net[ok][net[ok] > 0].mean()) if (net[ok] > 0).any() else 0.0,
        "avg_loss_R": float(net[ok][net[ok] <= 0].mean()) if (net[ok] <= 0).any() else 0.0,
        "profit_factor": float(wins / losses) if losses else float("inf"),
        "total_usd_1ct": float(usd[ok].sum()), "max_dd_usd_1ct": max_dd(usd),
        "sharpe": float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() else 0.0,
        "avg_hold_min": float(np.nanmean(held)),
    }


def random_p(res: dict, dirs: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """Random direction on the same traded days. Returns (p, mean of the random means)."""
    traded = dirs != 0
    L, S = res[1]["net_R"][traded], res[-1]["net_R"][traded]
    actual = np.nanmean(pick(res, dirs, "net_R"))
    coins = rng.integers(0, 2, size=(N_RANDOM, traded.sum())).astype(bool)
    means = np.where(coins, L, S).mean(axis=1)
    return float((1 + (means >= actual).sum()) / (N_RANDOM + 1)), float(means.mean())


# ---------------------------------------------------------------- driver

def evaluate(days_by: dict, cells: list[Cell], stop_slip: int = 1) -> dict:
    rng = np.random.default_rng(SEED)
    table = {}
    for cell in cells:
        row = {}
        for prod, days in days_by.items():
            res = run_cell(days, prod, cell, stop_slip)
            dirs = signals(days)
            s = summarize(res, dirs, rng)
            s["random_p"], s["random_mean_R"] = random_p(res, dirs, rng)
            s["reversed_mean_R"] = float(np.nanmean(pick(res, -dirs, "net_R")))
            s["always_long_mean_R"] = float(np.nanmean(res[1]["net_R"]))
            row[prod] = s
            row[f"_{prod}_daily"] = (pd.Series(pick(res, dirs, "net_R"), index=[d.d for d in days]))
        both = pd.concat([row.pop("_NQ_daily"), row.pop("_ES_daily")], axis=1).mean(axis=1, skipna=True).dropna()
        row["pooled_mean_R"] = float(both.mean())
        row["pooled_ci95"] = list(block_ci(both.to_numpy(), rng))
        row["avg_mean_R"] = float(np.mean([row[p]["mean_net_R"] for p in days_by]))
        table[cell.name] = row
    return table


def print_table(table: dict, title: str) -> None:
    print(f"\n{title}")
    print(f"{'cell':<26}{'NQ R':>8}{'ES R':>8}{'pool R':>8}  {'pool 95% CI':<17}{'NQ win':>7}{'NQ PF':>6}"
          f"{'ES PF':>6}{'NQ rnd p':>9}{'ES rnd p':>9}{'NQ $':>9}{'ES $':>9}{'hold':>6}")
    for name, r in table.items():
        nq, es = r["NQ"], r["ES"]
        ci = r["pooled_ci95"]
        print(f"{name:<26}{nq['mean_net_R']:>+8.3f}{es['mean_net_R']:>+8.3f}{r['pooled_mean_R']:>+8.3f}  "
              f"[{ci[0]:+.3f},{ci[1]:+.3f}]  {nq['win_rate']:>6.0%}{nq['profit_factor']:>6.2f}{es['profit_factor']:>6.2f}"
              f"{nq['random_p']:>9.3f}{es['random_p']:>9.3f}{nq['total_usd_1ct']:>9.0f}{es['total_usd_1ct']:>9.0f}"
              f"{nq['avg_hold_min']:>6.0f}")


def select(table: dict) -> tuple[str | None, dict]:
    eligible = {k: v for k, v in table.items() if v["NQ"]["mean_net_R"] > 0 and v["ES"]["mean_net_R"] > 0}
    chosen = max(eligible, key=lambda k: table[k]["avg_mean_R"]) if eligible else None
    fam_best = {}
    for k, v in table.items():
        fam = k.split("/")[0]
        if fam not in fam_best or v["avg_mean_R"] > table[fam_best[fam]]["avg_mean_R"]:
            fam_best[fam] = k
    return chosen, fam_best


def verdict(r: dict) -> str:
    pooled_ok = r["pooled_mean_R"] > 0
    if not pooled_ok:
        return "FAIL"
    if (r["pooled_ci95"][0] > 0 and r["NQ"]["mean_net_R"] > 0 and r["ES"]["mean_net_R"] > 0
            and max(r["NQ"]["random_p"], r["ES"]["random_p"]) < 0.05):
        return "PASS"
    return "WEAK"


def news_study(days: dict) -> int:
    ev = high_impact_events(*TRAIN)
    base = evaluate(days, CELLS + REFERENCE)
    results = {"none": base}
    for mode in NEWS_FILTERS:
        fd = {p: apply_news(ds, mode, ev) for p, ds in days.items()}
        print(f"\n{mode}: NQ {len(fd['NQ'])} / ES {len(fd['ES'])} sessions traded (of {len(days['NQ'])})")
        results[mode] = evaluate(fd, CELLS + REFERENCE)
    modes = ["none", *NEWS_FILTERS]
    print("\nTRAIN 2022-2024 pooled mean net R (NQ+ES day average), by news filter")
    print(f"{'cell':<26}" + "".join(f"{m:>15}" for m in modes))
    for name in base:
        print(f"{name:<26}" + "".join(f"{results[m][name]['pooled_mean_R']:>+15.3f}" for m in modes))
    print("\nper filter: cells positive on both, the cell selection would pick, its NQ/ES R and random p")
    for m in modes:
        sel = {k: v for k, v in results[m].items() if not k.startswith(("bracket", "hold"))}
        chosen, _ = select(sel)
        npos = sum(v["NQ"]["mean_net_R"] > 0 and v["ES"]["mean_net_R"] > 0 for v in sel.values())
        if chosen:
            r = results[m][chosen]
            print(f"  {m:<14} {npos:>2}/25 eligible  pick {chosen:<20} NQ {r['NQ']['mean_net_R']:+.3f} "
                  f"(p {r['NQ']['random_p']:.3f})  ES {r['ES']['mean_net_R']:+.3f} (p {r['ES']['random_p']:.3f})  "
                  f"pooled CI [{r['pooled_ci95'][0]:+.3f},{r['pooled_ci95'][1]:+.3f}]")
        else:
            print(f"  {m:<14}  0/25 eligible")
    (OUT / "train_news.json").write_text(json.dumps(results, indent=1, default=float))
    return 0


def news_test() -> int:
    """Requested by Sunny after the TEST FAIL. The window was already looked at, so this is a description
    of what the filters would have done there, not an out-of-sample test. The frozen cells are the TRAIN
    selection and family bests (unchanged by every news filter on TRAIN)."""
    lock = OUT / "test.lock"
    if not lock.exists():
        print("TEST has not been looked at yet; use --test for the one-look run first.")
        return 2
    frozen_names = json.loads((OUT / "train.json").read_text())
    names = [frozen_names["selected"]] + [k for k in frozen_names["family_best"].values()
                                          if k != frozen_names["selected"]]
    by_name = {c.name: c for c in CELLS + REFERENCE}
    cells = [by_name[k] for k in names] + REFERENCE
    lo, hi = TEST
    days = {p: build_days(load_bars(p, TEST_END_EXCL), lo, hi) for p in ("NQ", "ES")}
    ev = high_impact_events(lo, hi)
    results = {"none": evaluate(days, cells)}
    for mode in NEWS_FILTERS:
        fd = {p: apply_news(ds, mode, ev) for p, ds in days.items()}
        print(f"{mode}: {len(fd['NQ'])} of {len(days['NQ'])} sessions traded")
        results[mode] = evaluate(fd, cells)
    modes = ["none", *NEWS_FILTERS]
    print("\nTEST 2025-01 -> 2026-08-14, DIAGNOSTIC (window already seen): pooled mean net R by news filter")
    print(f"{'cell':<26}" + "".join(f"{m:>15}" for m in modes))
    for name in results["none"]:
        print(f"{name:<26}" + "".join(f"{results[m][name]['pooled_mean_R']:>+15.3f}" for m in modes))
    sel = names[0]
    print(f"\n{sel} by filter:")
    for m in modes:
        r = results[m][sel]
        print(f"  {m:<14} NQ {r['NQ']['mean_net_R']:+.3f} (rnd p {r['NQ']['random_p']:.3f}, ${r['NQ']['total_usd_1ct']:,.0f})"
              f"  ES {r['ES']['mean_net_R']:+.3f} (rnd p {r['ES']['random_p']:.3f}, ${r['ES']['total_usd_1ct']:,.0f})"
              f"  pooled CI [{r['pooled_ci95'][0]:+.3f},{r['pooled_ci95'][1]:+.3f}]")
    (OUT / "test_news_diagnostic.json").write_text(json.dumps(results, indent=1, default=float))
    return 0


def timeframes_study(tfs: list[int]) -> int:
    by_name = {c.name: c for c in CELLS + REFERENCE}
    train_bars = {p: load_bars(p, TRAIN_END_EXCL) for p in ("NQ", "ES")}
    test_bars = None
    summary = {}
    for tf in tfs:
        assert tf in (15, 30, 45, 60), "timeframes are fixed in the spec"
        days = {p: build_days(b, *TRAIN, tf=tf) for p, b in train_bars.items()}
        print(f"\n==== {tf}m opening candle: TRAIN {len(days['NQ'])} sessions, long signals "
              f"NQ {np.mean(signals(days['NQ']) > 0):.0%} / ES {np.mean(signals(days['ES']) > 0):.0%}")
        train = evaluate(days, CELLS)
        print_table(train, f"TRAIN 2022-2024, {tf}m")
        ref = evaluate(days, REFERENCE)
        print_table(ref, f"TRAIN reference exits, {tf}m")
        chosen, fam_best = select(train)
        npos = sum(v["NQ"]["mean_net_R"] > 0 and v["ES"]["mean_net_R"] > 0 for v in train.values())
        print(f"{tf}m: {npos}/25 cells positive on both; selected {chosen}")
        out = {"train": train, "reference": ref, "selected": chosen, "family_best": fam_best}
        summary[tf] = {"selected": chosen, "eligible": npos,
                       "train": train[chosen] if chosen else None}
        lock = OUT / f"test_tf{tf}.lock"
        if chosen is None:
            print(f"{tf}m: no eligible cell, TEST not run")
        elif lock.exists():
            print(f"{tf}m: TEST already looked at ({lock.read_text().strip()}); not rerun")
        else:
            lock.write_text(f"selected={chosen} at {datetime.now(timezone.utc).isoformat()}\n")
            if test_bars is None:
                test_bars = {p: load_bars(p, TEST_END_EXCL) for p in ("NQ", "ES")}
            tdays = {p: build_days(b, *TEST, tf=tf) for p, b in test_bars.items()}
            frozen = [by_name[chosen]] + [by_name[k] for k in fam_best.values() if k != chosen]
            test = evaluate(tdays, frozen)
            print_table(test, f"TEST 2025-01 -> 2026-08-14, {tf}m (selected first; window reused, alpha 0.05/4)")
            tref = evaluate(tdays, REFERENCE)
            print_table(tref, f"TEST reference exits, {tf}m")
            v = verdict(test[chosen])
            if v == "PASS" and max(test[chosen]["NQ"]["random_p"], test[chosen]["ES"]["random_p"]) >= 0.0125:
                v = "WEAK (p not below 0.05/4)"
            print(f"{tf}m VERDICT ({chosen}): {v}")
            out.update(test=test, test_reference=tref, verdict=v)
            summary[tf].update(test=test[chosen], verdict=v)
        (OUT / f"tf{tf}.json").write_text(json.dumps(out, indent=1, default=float))
    print("\nSUMMARY (selected cell per timeframe; R = mean net R per trade)")
    print(f"{'tf':>4} {'selected':<22}{'train NQ':>9}{'train ES':>9}{'test NQ':>9}{'test ES':>9}{'test pool':>10}"
          f"  {'NQ p':>6}{'ES p':>6}  verdict")
    for tf, r in summary.items():
        if not r["selected"]:
            print(f"{tf:>4} none eligible")
            continue
        t = r.get("test")
        tr = r["train"]
        tt = (f"{t['NQ']['mean_net_R']:>+9.3f}{t['ES']['mean_net_R']:>+9.3f}{t['pooled_mean_R']:>+10.3f}  "
              f"{t['NQ']['random_p']:>6.3f}{t['ES']['random_p']:>6.3f}") if t else f"{'':>40}"
        print(f"{tf:>4} {r['selected']:<22}{tr['NQ']['mean_net_R']:>+9.3f}{tr['ES']['mean_net_R']:>+9.3f}{tt}  "
              f"{r.get('verdict', '-')}")
    return 0


def gamma_by_day(product: str, entry_m: int, path: Path | None = None) -> dict:
    sym = PROXY[product][0].lower()
    path = path or DATA / "thetadata_gex" / f"{sym}_gex_snapshots.parquet"
    return regime_by_day(pd.read_parquet(path, columns=["computed_at", "net_gex"]), entry_m)


def regime_by_day(g: pd.DataFrame, entry_m: int) -> dict:
    """day -> net_gex of the latest snapshot with ET minute <= entry_m that day (zero / NaN dropped)."""
    t = g.computed_at.dt.tz_convert(ET)
    g = g.assign(day=t.dt.date, m=t.dt.hour * 60 + t.dt.minute)
    g = g[g.m <= entry_m].sort_values("computed_at")
    last = g.groupby("day").net_gex.last()
    return {d: float(v) for d, v in last.items() if np.isfinite(v) and v != 0}


def gamma_study() -> int:
    by_name = {c.name: c for c in CELLS + REFERENCE}
    train_bars = {p: load_bars(p, TRAIN_END_EXCL) for p in ("NQ", "ES")}
    test_bars = None
    summary = []
    for tf in (5, 15, 30, 45, 60):
        gm = {p: gamma_by_day(p, OPEN_M + tf) for p in ("NQ", "ES")}
        all_train = {p: build_days(b, *TRAIN, tf=tf) for p, b in train_bars.items()}
        for regime, sign in (("neg", -1), ("pos", 1)):
            key = f"{tf}m/{regime}"
            days = {p: [d for d in ds if d.d in gm[p] and np.sign(gm[p][d.d]) == sign] for p, ds in all_train.items()}
            print(f"\n==== {key}: TRAIN NQ {len(days['NQ'])} / ES {len(days['ES'])} sessions")
            train = evaluate(days, CELLS)
            print_table(train, f"TRAIN 2022-2024, {key}")
            chosen, fam_best = select(train)
            npos = sum(v["NQ"]["mean_net_R"] > 0 and v["ES"]["mean_net_R"] > 0 for v in train.values())
            print(f"{key}: {npos}/25 eligible; selected {chosen}")
            row = {"key": key, "selected": chosen, "eligible": npos, "train": train[chosen] if chosen else None}
            out = {"train": train, "selected": chosen, "family_best": fam_best}
            lock = OUT / f"test_gamma_{tf}_{regime}.lock"
            if chosen and not lock.exists():
                lock.write_text(f"selected={chosen} at {datetime.now(timezone.utc).isoformat()}\n")
                if test_bars is None:
                    test_bars = {p: load_bars(p, TEST_END_EXCL) for p in ("NQ", "ES")}
                tdays = {p: [d for d in build_days(b, *TEST, tf=tf) if d.d in gm[p] and np.sign(gm[p][d.d]) == sign]
                         for p, b in test_bars.items()}
                frozen = [by_name[chosen]] + [by_name[k] for k in fam_best.values() if k != chosen]
                test = evaluate(tdays, frozen)
                print_table(test, f"TEST 2025-01 -> 2026-08-14, {key} (window reused; alpha 0.05/10)")
                t = test[chosen]
                v = verdict(t)
                if v == "PASS" and max(t["NQ"]["random_p"], t["ES"]["random_p"]) >= 0.005:
                    v = "WEAK (p not below 0.005)"
                row.update(test=t, verdict=v, n_test=(len(tdays["NQ"]), len(tdays["ES"])))
                out.update(test=test, verdict=v)
            elif chosen:
                row["verdict"] = f"already looked: {lock.read_text().strip()}"
            (OUT / f"gamma_{tf}_{regime}.json").write_text(json.dumps(out, indent=1, default=float))
            summary.append(row)
    print("\nSUMMARY (selected cell per timeframe x regime; mean net R per trade)")
    print(f"{'combo':<9}{'selected':<22}{'elig':>5}{'trn NQ':>8}{'trn ES':>8}{'tst NQ':>8}{'tst ES':>8}{'tst pool':>9}"
          f"{'rev NQ':>8}{'rev ES':>8}{'NQ p':>7}{'ES p':>7}  verdict")
    for r in summary:
        if not r["selected"]:
            print(f"{r['key']:<9}{'none eligible':<22}{0:>5}")
            continue
        tr, t = r["train"], r.get("test")
        tt = (f"{t['NQ']['mean_net_R']:>+8.3f}{t['ES']['mean_net_R']:>+8.3f}{t['pooled_mean_R']:>+9.3f}"
              f"{t['NQ']['reversed_mean_R']:>+8.3f}{t['ES']['reversed_mean_R']:>+8.3f}"
              f"{t['NQ']['random_p']:>7.3f}{t['ES']['random_p']:>7.3f}") if t else ""
        print(f"{r['key']:<9}{r['selected']:<22}{r['eligible']:>5}{tr['NQ']['mean_net_R']:>+8.3f}"
              f"{tr['ES']['mean_net_R']:>+8.3f}{tt}  {r.get('verdict', '-')}")
    return 0


# ---------------------------------------------------------------- 2016-2021 futures confirmation

FUT_BARS = DATA / "databento" / "fut-ohlcv-1m-cont"
CONFIRM = {"NQ": (date(2016, 1, 4), date(2021, 12, 31)), "ES": (date(2017, 1, 3), date(2021, 12, 31))}
CONFIRM_END_EXCL = date(2022, 1, 1)
CONFIRM_GEX = {p: DATA / "thetadata_gex" / f"{PROXY[p][0].lower()}_gex_snapshots_2016_2021.parquet" for p in PROXY}
FROZEN_CELL = Cell("step", 0.25)
MIN_PRICE = {"NQ": 2000.0, "ES": 1000.0}  # native index points; anything lower means ETF prices slipped in


def months_between(lo: date, end_excl: date) -> list[str]:
    return [m.strftime("%Y-%m") for m in pd.period_range(lo, end_excl - pd.Timedelta(days=1), freq="M")]


def file_span(path: Path) -> tuple[date, date] | None:
    try:
        s, e = path.name.split(".")[0].split("_")
        return date.fromisoformat(s), date.fromisoformat(e)
    except ValueError:
        return None


def missing_months(folder: Path, lo: date, end_excl: date) -> list[str]:
    """Months of [lo, end_excl) not covered by a converted <start>_<end>.parquet in folder."""
    covered = set()
    for f in folder.glob("*.parquet"):
        span = file_span(f)
        if span:
            covered.update(months_between(*span))
    return [m for m in months_between(lo, end_excl) if m not in covered]


def contract_segments(iid: pd.Series) -> pd.Series:
    """1, 2, ... for each run of consecutive equal instrument_ids (a flip back starts a new run)."""
    return (iid != iid.shift()).cumsum().astype(int)


def load_fut_bars(product: str, lo: date, end_excl: date) -> pd.DataFrame:
    """RTH 1m bars of the continuous front month, native points, instrument_id -> contract segment."""
    assert end_excl <= CONFIRM_END_EXCL, "confirmation data stops at 2022-01-01"
    folder = FUT_BARS / product
    files = [f for f in sorted(folder.glob("*.parquet"))
             if (sp := file_span(f)) and sp[0] < end_excl and sp[1] > lo]
    if not files:
        raise FileNotFoundError(f"no bars in {folder}; run databento_fetch.py fut-ohlcv-1m-cont")
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    bars = pd.concat([pd.read_parquet(f, columns=cols) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    bars = bars[(bars.index >= pd.Timestamp(lo, tz=ET).tz_convert("UTC"))
                & (bars.index < pd.Timestamp(end_excl, tz=ET).tz_convert("UTC"))].copy()
    bars["instrument_id"] = contract_segments(bars.instrument_id).to_numpy()  # on the full tape, not RTH only
    et = bars.index.tz_convert(ET)
    m = et.hour * 60 + et.minute
    bars = bars[(m >= OPEN_M) & (m < CLOSE_M)]
    assert bars.low.min() > MIN_PRICE[product], f"{product}: prices below {MIN_PRICE[product]}, not index points"
    n = bars.groupby(bars.index.tz_convert(ET).date).size()
    full = set(n.index[n >= MIN_RTH_BARS])
    return bars[np.isin(bars.index.tz_convert(ET).date, list(full))]


def split_regime(days: list[Day], gm: dict) -> dict:
    out = {"neg": [], "pos": [], "none": []}
    for d in days:
        g = gm.get(d.d)
        out["none" if g is None else ("neg" if g < 0 else "pos")].append(d)
    return out


def per_year(days_by: dict, cell: Cell) -> pd.DataFrame:
    """Calendar-year table: trades, signal mean net R and reversed mean net R per symbol, pooled mean."""
    cols = {}
    for p, days in days_by.items():
        if not days:
            continue
        res = run_cell(days, p, cell)
        dirs = signals(days)
        idx = pd.Index([d.d for d in days])
        cols[f"{p}_R"] = pd.Series(pick(res, dirs, "net_R"), index=idx)
        cols[f"{p}_rev_R"] = pd.Series(pick(res, -dirs, "net_R"), index=idx)
    df = pd.DataFrame(cols)
    sig = [c for c in df if c.endswith("_R") and "_rev" not in c]
    df["pooled_R"] = df[sig].mean(axis=1, skipna=True)
    year = pd.Index([d.year for d in df.index], name="year")
    g = df.groupby(year)
    out = pd.DataFrame({f"{c[:2]}_n": g[c].count() for c in sig})
    for c in [*sig, *[f"{c[:2]}_rev_R" for c in sig], "pooled_R"]:
        out[c] = g[c].mean()
    return out


def confirm_lock_ok(lock: Path) -> bool:
    if lock.exists():
        print(f"\nCONFIRM already looked at: {lock.read_text().strip()}. Refusing a second look.")
        return False
    return True


def confirm(check_only: bool) -> int:
    frozen = json.loads((OUT / "gamma_5_neg.json").read_text())["selected"]
    assert frozen == FROZEN_CELL.name, f"frozen cell drifted: gamma_5_neg.json says {frozen}"
    lock = OUT / "confirm.lock"
    if not check_only and not confirm_lock_ok(lock):
        return 3
    bad = False
    for p, (lo, hi) in CONFIRM.items():
        miss = missing_months(FUT_BARS / p, lo, CONFIRM_END_EXCL)
        if miss:
            print(f"{p}: missing {len(miss)} monthly files ({miss[0]} .. {miss[-1]}) in {FUT_BARS / p}")
            bad = True
        if not CONFIRM_GEX[p].exists():
            print(f"{p}: missing {CONFIRM_GEX[p]}; build it with thetadata_gex.py --out")
            bad = True
    if bad:
        print("Data incomplete; nothing simulated, no lock written.")
        return 2

    bars = {p: load_fut_bars(p, lo, CONFIRM_END_EXCL) for p, (lo, _) in CONFIRM.items()}
    days = {p: build_days(bars[p], *CONFIRM[p]) for p in CONFIRM}
    gm = {p: gamma_by_day(p, ENTRY_M, CONFIRM_GEX[p]) for p in CONFIRM}
    reg = {p: split_regime(days[p], gm[p]) for p in CONFIRM}
    print(f"CONFIRM data (2016-2021 CME continuous front month, native points), frozen cell {FROZEN_CELL.name}")
    for p in CONFIRM:
        sessions = sorted(set(bars[p].index.tz_convert(ET).date))
        segs = bars[p].groupby("instrument_id").size().size
        r = reg[p]
        print(f"  {p}: {len(sessions)} full RTH sessions {sessions[0]} -> {sessions[-1]}, {segs} contract segments, "
              f"{len(days[p])} tradable (ATR/EMA warm-up and roll days skipped) -> neg {len(r['neg'])}, "
              f"pos {len(r['pos'])}, no snapshot {len(r['none'])}; neg long-signal share "
              f"{np.mean(signals(r['neg']) > 0):.0%}")
    if check_only:
        print("--confirm-check: coverage only, no trades simulated.")
        return 0

    lock.write_text(f"cell={FROZEN_CELL.name} regime=neg windows=NQ {CONFIRM['NQ'][0]}..{CONFIRM['NQ'][1]}, "
                    f"ES {CONFIRM['ES'][0]}..{CONFIRM['ES'][1]} at {datetime.now(timezone.utc).isoformat()}\n")
    cell = FROZEN_CELL
    neg = {p: reg[p]["neg"] for p in CONFIRM}
    pos = {p: reg[p]["pos"] for p in CONFIRM}
    test = evaluate(neg, [cell])
    print_table(test, "CONFIRM negative gamma, NQ 2016-2021 / ES 2017-2021 (the one look)")
    t = test[cell.name]
    for p in CONFIRM:
        s = t[p]
        print(f"  {p}: {s['trades']} trades, mean net R {s['mean_net_R']:+.3f} (CI [{s['ci95'][0]:+.3f},"
              f"{s['ci95'][1]:+.3f}]), reversed {s['reversed_mean_R']:+.3f}, always long "
              f"{s['always_long_mean_R']:+.3f}, random mean {s['random_mean_R']:+.3f} (p {s['random_p']:.3f}), "
              f"long share {s['long_share']:.0%}, ${s['total_usd_1ct']:,.0f}/1 micro")
    stress = evaluate(neg, [cell], stop_slip=2)
    print_table(stress, "side: 2 ticks of slippage on every stop (negative gamma)")
    side_pos = evaluate(pos, [cell])
    print_table(side_pos, "side: positive-gamma days (not part of the verdict)")
    side_all = evaluate({p: days[p] for p in CONFIRM}, [cell])
    print_table(side_all, "side: all days regardless of regime (not part of the verdict)")
    yr = per_year(neg, cell)
    print("\nper calendar year, negative gamma (mean net R per trade; rev = reversed signal)")
    print(yr.to_string(float_format=lambda x: f"{x:+.3f}"))
    v = verdict(t)
    print(f"\nCONFIRM VERDICT ({cell.name}, negative gamma): {v}")
    (OUT / "confirm.json").write_text(json.dumps({
        "cell": cell.name, "verdict": v, "test": test, "stress": stress, "positive_gamma": side_pos,
        "all_days": side_all, "per_year": json.loads(yr.to_json(orient="index"))}, indent=1, default=float))
    return 0


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="one look at the 2025-01 -> 2026-08-14 test set")
    ap.add_argument("--news", action="store_true", help="train only: compare high-impact news filters")
    ap.add_argument("--gamma", action="store_true", help="neg / pos dealer-gamma days only, all timeframes")
    ap.add_argument("--timeframes", default=None, help="comma-separated opening-candle sizes, e.g. 15,30,45,60")
    ap.add_argument("--news-test", action="store_true",
                    help="diagnostic: news filters on the TEST window already looked at (not a confirmation)")
    ap.add_argument("--confirm", action="store_true",
                    help="ONE look: frozen 5m / negative gamma / step/0.25atr on NQ 2016-2021, ES 2017-2021 futures")
    ap.add_argument("--confirm-check", action="store_true",
                    help="2016-2021 futures coverage, rolls and regime counts only (no trades)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.confirm or args.confirm_check:
        return confirm(check_only=not args.confirm)

    if args.news_test:
        return news_test()
    if args.gamma:
        return gamma_study()
    if args.timeframes:
        return timeframes_study([int(x) for x in args.timeframes.split(",")])
    lo, hi = TRAIN
    days = {p: build_days(load_bars(p, TRAIN_END_EXCL), lo, hi) for p in ("NQ", "ES")}
    for p, ds in days.items():
        print(f"TRAIN {p}: {len(ds)} sessions {ds[0].d} -> {ds[-1].d}, long signals {np.mean(signals(ds) > 0):.0%}")
    if args.news:
        return news_study(days)
    train = evaluate(days, CELLS)
    print_table(train, "TRAIN 2022-2024 (selectable cells)")
    ref = evaluate(days, REFERENCE)
    print_table(ref, "TRAIN reference exits (fixed bracket / hold), never selected")
    chosen, fam_best = select(train)
    print(f"\nselected: {chosen}")
    print("family bests:", ", ".join(fam_best.values()))
    (OUT / "train.json").write_text(json.dumps({"train": train, "reference": ref, "selected": chosen,
                                                "family_best": fam_best}, indent=1, default=float))
    if not args.test:
        return 0

    lock = OUT / "test.lock"
    if lock.exists():
        print(f"\nTEST already looked at: {lock.read_text().strip()}. Refusing a second look.")
        return 3
    if chosen is None:
        print("\nNo cell is positive on both NQ and ES in TRAIN, so TEST stays sealed.")
        return 2
    lock.write_text(f"selected={chosen} family_best={','.join(fam_best.values())} at "
                    f"{datetime.now(timezone.utc).isoformat()}\n")
    lo, hi = TEST
    days = {p: build_days(load_bars(p, TEST_END_EXCL), lo, hi) for p in ("NQ", "ES")}
    for p, ds in days.items():
        print(f"TEST {p}: {len(ds)} sessions {ds[0].d} -> {ds[-1].d}, long signals {np.mean(signals(ds) > 0):.0%}")
    by_name = {c.name: c for c in CELLS + REFERENCE}
    frozen = [by_name[chosen]] + [by_name[k] for k in fam_best.values() if k != chosen]
    test = evaluate(days, frozen)
    print_table(test, "TEST 2025-01 -> 2026-08-14 (selected first, then the other family bests)")
    stress = evaluate(days, [by_name[chosen]], stop_slip=2)
    print_table(stress, "TEST stress: 2 ticks of slippage on every stop")
    ref_t = evaluate(days, REFERENCE)
    print_table(ref_t, "TEST reference exits")
    v = verdict(test[chosen])
    print(f"\nVERDICT ({chosen}): {v}")
    (OUT / "test.json").write_text(json.dumps({"test": test, "stress": stress, "reference": ref_t,
                                               "selected": chosen, "verdict": v}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
