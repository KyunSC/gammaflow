"""Volume profile claims: three frozen tests of a volume-profile / auction-market-theory trading post.

Sunny pasted a post (2026-10-22) claiming that volume nodes act as magnets, that high-volume nodes (HVNs) are
hard for market orders to chew through (so stops belong behind them), and that on a balanced day with a flat
VWAP you fade the edges of the profile, take partials at the POC and the rest at the other extreme. Its other
claims are already covered here: the 80% rule and value-area fades (amt_lucid_study.py, prop_survey_study.py),
trend-day continuation (amt_regime_study.py, amt_nq_confirm.py) and footprint absorption (orderflow_backtest.py,
ORDERFLOW_GEX_PREREG.md). Review: https://claude.ai/artifact/BkeYfNcQmDWY6MUCZSXWPv

Rules (fixed before any number was looked at; revised once after review, before any run, 2026-10-22):
  - data, exploration: Databento XNAS.ITCH SPY + QQQ ohlcv-1m sessions <= DISCOVERY_END (2025-03-26), loaded by
    amt_lucid_study.load_sessions (RTH 09:30-15:59 ET, >= 380 bars). Prices go to the futures plane (SPY x10.05 ~ ES,
    QQQ x41.2 ~ NQ, tick 0.25). Unlimited runs: amt_lucid_study has already read these sessions.
  - data, confirmation: Databento GLBX.MDP3 ES.v.0 ohlcv-1m, RTH sessions 2012-01-03 -> 2021-12-31
    (databento_fetch.py es-ohlcv-1m-early), a folder no other script reads. CME volume, as the post insists.
    Scored ONCE (--confirm). Its last ~3.5 years share days with amt_nq_confirm.py's QQQ window; run that first.
  - pairs: a session is scored only when its prior session is the previous NYSE trading day (holidays and the
    special closures below; a half-day or a missing day breaks the pair) and, on ES, the same contract (no roll).
  - profile: the prior RTH session's 1m bars, each bar's volume spread evenly over the ticks in [low, high] on the
    futures plane. POC = the tick with the most volume (ties -> nearest the range mid); value area = from the POC add
    the larger neighbouring tick until >= 70% of the volume (amt_lucid_study.value_area, at tick resolution).
    Nodes: ticks summed into bins of NODE_BIN_PCT (0.05%) of the prior close, smoothed by a 3-bin mean. HVN = local
    max >= 1.5x the median bin; LVN = local min <= 0.5x the median with an above-median bin on each side. Nodes
    within 2 bins of the prior high, low or POC are dropped.
  - T1 magnet. Sessions whose 09:30 open is at least 0.1x the prior range from the level. Outcome: the level lies
    inside [low, high] of the 09:35-15:55 bars. Control (distance-matched): every prior-range tick more than 2 node
    bins from the POC, in cells of (side of the open) x (open inside the prior VA / inside the prior range /
    outside it) x (distance from the open in 0.05x prior-range buckets, capped at 2x); each session weighs at most
    1 per cell. Statistic: mean over sessions of touch(level) - the control's touch rate in the level's cell, i.e.
    is the POC reached more often than other prior-range prices as far from the open, on the same side? Levels: the
    POC (primary), the prior VWAP, range midpoint and close (secondaries, same statistic). Also reported only: the
    first version's touch(POC) - touch(mirror = open - (POC - open)), which reversion into the prior range inflates.
  - T2 barrier. For each prior-session node and placebo price (10 per session, uniform over the prior range, at
    least 2 bins from any node, POC or extreme; seeded by the date): the first 1m bar from 09:45 that trades the
    price while the bar before did not (an approach from one side). From that bar, first passage: does price trade
    D = 0.15x the prior range THROUGH the price before trading D back the way it came? On the approach bar only
    the through side counts (its far side printed before the touch); from the next bar both. A bar reaching both is
    ambiguous and dropped; no resolution by 15:55 is dropped. Both counts are reported. Strata: (price inside the
    prior VA or not) x (distance from the 09:30 open: < 0.25, 0.25-0.5, >= 0.5x the prior range). Statistic:
    stratified pass-through rate at LVNs minus HVNs (per-stratum rate differences weighted by the two kinds' event
    count, strata where both have events; sums over sessions). Raw, unstratified rates are reported too. Even a
    random walk passes through less than 50% here (the approach bar tends to close back on its own side), so only
    differences between kinds mean anything.
  - T3 balanced-day fade on the developing profile. Decision points: 5m bar closes (09:30-anchored) from 11:00 to
    14:30 ET. Balanced at a decision point: |VWAP now - VWAP 60 minutes ago| <= s x the session range so far, and
    >= 2 sign changes of (5m close - VWAP) over the last 90 minutes. VWAP is session VWAP from 09:30 on typical
    price; the developing profile runs from 09:30 through the decision bar. Signal: the 5m bar trades a tick above
    the developing VAH and closes inside the VA -> short at the next 1m open - 1 tick (VAL: the mirror long; a bar
    probing both edges is skipped). Stop: the 5m bar's extreme + k ticks, widened to >= 4 ticks; no trade if the
    entry opens through it. Targets frozen at entry: half at the developing POC, half at the opposite VA edge;
    skipped if the POC is not at least a tick in the trade's favour or the VA is narrower than 2x the stop. After
    the first half fills the stop stays or moves to entry (be). At most one trade per side per session; signals at
    decision points that fail the gate form the "unbalanced twin" (also one per side). A trade's edge =
    (R - R with the direction flipped) / 2, i.e. its R minus what a coin-flip direction would expect, so the twin
    comparison is not driven by the twin's wider stops. Costs cancel in it: edge is gross. Grid: s in
    {0.05, 0.10, 0.15} x k in {1, 4} x be in {False, True}.
  - execution (T3): 1m bars from the entry bar. Stop checked before targets in every bar; a bar opening through the
    stop fills at its open, else at the stop, both 1 tick worse. A target fills at its price only when a bar trades
    a tick THROUGH it, or at the open of a bar opening through it. Otherwise flat at the 15:54 bar's close - 1 tick.
    Costs: $4.50 round trip per full-size contract (ES $50/pt, NQ $20/pt), as in ORDERFLOW_GEX_PREREG.md.
    R = (mean of the two halves' points - cost points) / stop distance. Stops and slippage are in ticks, so costs
    weigh ~2x more in R on ES 2012-2021 (index ~1,300-4,800) than on the 2022-2025 exploration plane (~3,600-6,000).
    So every trade is also replayed at doubled friction (2 ticks of slippage, 2x commission): mean_2x. Exploration
    also prints the median stop in ticks and the mean commission + slippage per trade in R.
  - T3 selection (--freeze, exploration only): the cell with >= 60 balanced trades on each of SPY and QQQ, mean net
    R > 0 on both, mean_2x > 0 on both, and balanced mean edge > twin mean edge on both; the highest pooled mean R.
    No such cell: T3 is dropped and never confirmed.
  - inference: moving-block bootstrap (blocks of 5 sessions or trades, N_BOOT draws, seed 0). A test passes when the
    one-sided lower bound at ALPHA = 0.05 / 3 is above 0.
  - verdicts on ES (--confirm):
      T1 PASS  POC excess over the distance-matched control > 0 at ALPHA, and (point estimates) the POC excess is
               above the VWAP, midpoint and close excesses; otherwise the profile adds nothing simpler levels lack.
      T2 PASS  stratified LVN - HVN pass-through > 0 at ALPHA, and (point estimate) the stratified HVN rate is
               below the placebo rate.
      T3 PASS  mean net R > 0 at ALPHA, coin-flip p < ALPHA (N_RANDOM draws: same entries and brackets, direction a
               coin), and (point estimate) balanced mean edge > twin mean edge.
  - power: ~2,500 ES sessions put T1's standard error near 1.4 percentage points; T2 and T3 depend on event
    counts the exploration will show.

One look, enforced: script_sha() hashes this file AND amt_lucid_study.py (its constants and loader); the test
suite pins that hash (SPEC_SHA), so any spec change is a visible diff. explore.json records the hash and --freeze
refuses a stale one, recomputing the T3 pick rather than trusting the file. --freeze writes vp_claims_prereg.json
next to this script (commit it). --confirm refuses when vp_claims_looks.log (committed) already has a look, when the
hash changed, or when the ES download misses any year (>= 230 sessions in each of 2012-2021); then it appends the
look before scoring. Deleting either file shows in git.

--profile-check is not a test: on the NQ trades already held (data/databento/nq-trades, research side of
holdout.VERIFY_START only) it measures how far the 1m-bar profile's POC and HVNs sit from the exact prints'
profile, in node bins, which says whether 1m bars are sharp enough.

    python functions/ml/vp_claims_study.py --explore
    python functions/ml/vp_claims_study.py --profile-check
    python functions/ml/vp_claims_study.py --freeze          # then commit functions/ml/vp_claims_prereg.json
    python functions/ml/databento_fetch.py es-ohlcv-1m-early --start 2012-01-01 --end 2022-01-01            # free quote
    python functions/ml/databento_fetch.py es-ohlcv-1m-early --start 2012-01-01 --end 2022-01-01 --download --max-cost 30
    python functions/ml/vp_claims_study.py --confirm         # then commit functions/ml/vp_claims_looks.log

Specification: everything above was written down before the first run and not changed after it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday,
                                    sunday_to_monday)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import amt_lucid_study as amt  # noqa: E402
from holdout import VERIFY_START  # noqa: E402

ET = amt.ET
TICK = amt.TICK
OPEN, FLAT, CLOSE = amt.OPEN, amt.FLAT, amt.CLOSE    # 09:30, 15:54, 16:00
MIN_BARS = amt.MIN_BARS
VA_PCT = amt.VA_PCT
DISCOVERY_END = amt.DISCOVERY_END

OUT = amt.DATA / "vp_claims"
PREREG, LOOKS = HERE / "vp_claims_prereg.json", HERE / "vp_claims_looks.log"     # committed, unlike OUT
SPEC_FILES = (Path(__file__).resolve(), HERE / "amt_lucid_study.py")
ES_MIN_SESSIONS_PER_YEAR = 230
ES_DIR = amt.DATA / "databento" / "es-ohlcv-1m-early" / "ES"
CONFIRM_START, CONFIRM_END = date(2012, 1, 3), date(2021, 12, 31)

INSTRUMENTS = {"SPY": dict(ratio=10.05, pv=50.0), "QQQ": dict(ratio=41.2, pv=20.0), "ES": dict(ratio=1.0, pv=50.0)}
COMMISSION_RT = 4.50

NODE_BIN_PCT = 0.0005
HVN_MULT, LVN_MULT, NODE_GAP = 1.5, 0.5, 2

T1_MIN_DIST = 0.1
T1_START, T1_END = 575, 955          # 09:35, 15:55 (bar start minutes, inclusive)
T1_BUCKET, T1_NBUCKET = 0.05, 40     # control distance buckets, x prior range (last bucket: >= 1.95)
T1_LEVELS = ("poc", "vwap", "mid", "close")
T1_NCELL = 2 * 3 * T1_NBUCKET        # side x open location x distance

T2_START, T2_END = 585, 955          # 09:45, 15:55
T2_D = 0.15
N_PLACEBO = 10
T2_DIST_EDGES = (0.25, 0.5)          # distance from the open, x prior range
T2_NSTRATA = 2 * (len(T2_DIST_EDGES) + 1)
T2_KINDS = ("hvn", "lvn", "placebo")

T3_FIRST, T3_LAST = 660, 870         # decision bar END minutes: 11:00, 14:30
T3_LOOKBACK, T3_CROSS_WIN, T3_MIN_CROSS = 60, 90, 2
T3_MIN_STOP_TICKS = 4
T3_GRID = [dict(s=s, k=k, be=be) for s in (0.05, 0.10, 0.15) for k in (1, 4) for be in (False, True)]
T3_MIN_TRADES = 60

ALPHA = 0.05 / 3
N_BOOT, BLOCK, N_RANDOM, SEED = 4000, 5, 5000, 0


class NYSECalendar(AbstractHolidayCalendar):
    rules = [Holiday("New Year", month=1, day=1, observance=sunday_to_monday), USMartinLutherKingJr, USPresidentsDay,
             GoodFriday, USMemorialDay, Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01",
                                                observance=nearest_workday),
             Holiday("Independence Day", month=7, day=4, observance=nearest_workday), USLaborDay, USThanksgivingDay,
             Holiday("Christmas", month=12, day=25, observance=nearest_workday)]


SPECIAL_CLOSURES = {date(2012, 10, 29), date(2012, 10, 30), date(2018, 12, 5), date(2025, 1, 9)}
NYSE_HOLIDAYS = {t.date() for t in NYSECalendar().holidays("2010-01-01", "2027-12-31")} | SPECIAL_CLOSURES


def prev_session(d: date) -> date:
    """The NYSE trading day before d."""
    d -= timedelta(days=1)
    while d.weekday() >= 5 or d in NYSE_HOLIDAYS:
        d -= timedelta(days=1)
    return d


def cell_name(p: dict) -> str:
    return f"s={p['s']}/k={p['k']}/be={'y' if p['be'] else 'n'}"


# ---------------------------------------------------------------- data

def session(g: pd.DataFrame, ratio: float, inst=None) -> dict:
    return dict(O=g.open.to_numpy(float) * ratio, H=g.high.to_numpy(float) * ratio, L=g.low.to_numpy(float) * ratio,
                C=g.close.to_numpy(float) * ratio, V=g.volume.to_numpy(float), m=g.minute.to_numpy(int), inst=inst)


def load_xnas(symbol: str) -> dict[date, dict]:
    ratio = INSTRUMENTS[symbol]["ratio"]
    return {d: session(g, ratio) for d, g in amt.load_sessions(symbol, DISCOVERY_END).items()}


def load_es(bars_dir: Path = ES_DIR, start: date = CONFIRM_START, end: date = CONFIRM_END) -> dict[date, dict]:
    files = sorted(bars_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bars in {bars_dir}; run databento_fetch.py es-ohlcv-1m-early")
    cutoff = pd.Timestamp(end + pd.Timedelta(days=1), tz=ET).tz_convert("UTC")
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    bars = pd.concat([pd.read_parquet(f, columns=cols, filters=[("ts_event", "<", cutoff)]) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    assert (bars.index < cutoff).all(), "LEAK: bar read reaches past the confirmation window"
    et = bars.index.tz_convert(ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= OPEN) & (bars.minute < CLOSE) & (bars.day >= start) & (bars.day <= end)]
    out = {}
    for d, g in bars.groupby("day", sort=True):
        if (len(g) >= MIN_BARS and g.minute.iloc[0] == OPEN and g.minute.iloc[-1] >= FLAT
                and g.instrument_id.nunique() == 1):
            out[d] = session(g, 1.0, int(g.instrument_id.iloc[0]))
    return out


def pairs(sessions: dict[date, dict]) -> list[tuple[date, date]]:
    """(prior, day) where prior is the previous NYSE trading day, on the same contract (inst None = an ETF)."""
    days = sorted(sessions)
    return [(a, b) for a, b in zip(days, days[1:])
            if a == prev_session(b) and sessions[a]["inst"] == sessions[b]["inst"]]


# ---------------------------------------------------------------- profile

def tick_hist(H: np.ndarray, L: np.ndarray, V: np.ndarray) -> tuple[np.ndarray, int]:
    """Volume per 0.25 tick, each bar's volume spread evenly over [low, high]; returns (vols, base tick)."""
    lo, hi = np.rint(L / TICK).astype(np.int64), np.rint(H / TICK).astype(np.int64)
    base = int(lo.min())
    vols = np.zeros(int(hi.max()) - base + 1)
    for a, b, v in zip(lo - base, hi - base, V):
        vols[a:b + 1] += v / (b - a + 1)
    return vols, base


def value_area(vols: np.ndarray) -> tuple[int, int, int]:
    """(val, poc, vah) as bin indices; amt_lucid_study.value_area's rule."""
    n = len(vols)
    cands = np.flatnonzero(vols == vols.max())
    poc = int(cands[np.argmin(np.abs(cands - (n - 1) / 2))])
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
    return lo, poc, hi


def nodes(vols: np.ndarray, base: int, poc_tick: int, close: float) -> dict:
    """HVN / LVN prices (bin centres on the tick grid) and the bin width in ticks."""
    w = max(1, int(round(NODE_BIN_PCT * close / TICK)))
    nb = -(-len(vols) // w)
    b = np.zeros(nb * w)
    b[:len(vols)] = vols
    b = b.reshape(nb, w).sum(1)
    s = np.convolve(np.pad(b, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    med = float(np.median(s))
    poc_bin = (poc_tick - base) // w
    keep = lambda i: min(i, nb - 1 - i, abs(i - poc_bin)) > NODE_GAP
    centre = lambda i: (base + i * w + (w - 1) / 2) * TICK
    hvn = [centre(i) for i in range(1, nb - 1) if s[i] > s[i - 1] and s[i] >= s[i + 1] and s[i] >= HVN_MULT * med and keep(i)]
    lvn = [centre(i) for i in range(1, nb - 1) if s[i] < s[i - 1] and s[i] <= s[i + 1] and s[i] <= LVN_MULT * med
           and s[:i].max() > med and s[i + 1:].max() > med and keep(i)]
    return dict(hvn=hvn, lvn=lvn, width=w, nbins=nb, poc_bin=poc_bin)


def prior_levels(p: dict) -> dict:
    vols, base = tick_hist(p["H"], p["L"], p["V"])
    lo, poc, hi = value_area(vols)
    tp = (p["H"] + p["L"] + p["C"]) / 3
    lv = dict(poc=(base + poc) * TICK, val=(base + lo) * TICK, vah=(base + hi) * TICK, high=p["H"].max(),
              low=p["L"].min(), vwap=float((tp * p["V"]).sum() / p["V"].sum()) if p["V"].sum() else float(p["C"][-1]),
              close=float(p["C"][-1]), base=base)
    lv["range"] = lv["high"] - lv["low"]
    lv["mid"] = (lv["high"] + lv["low"]) / 2
    lv.update(nodes(vols, base, base + poc, float(p["C"][-1])))
    return lv


# ---------------------------------------------------------------- T1

def t1_session(lv: dict, s: dict) -> tuple[np.ndarray, np.ndarray, dict] | None:
    """One session's T1 inputs: the control's (hits, weight) per cell, and per level (cell, touch, mirror touch).

    Control prices are the prior-range ticks more than NODE_GAP node bins from the POC. Each tick weighs
    TICK / (T1_BUCKET x range), so a session adds at most ~1 to a cell however wide its range was."""
    o, rng = s["O"][0], lv["range"]
    if rng <= 0:
        return None
    win = (s["m"] >= T1_START) & (s["m"] <= T1_END)
    lo, hi = s["L"][win].min(), s["H"][win].max()
    loc = 0 if lv["val"] <= o <= lv["vah"] else 1 if lv["low"] <= o <= lv["high"] else 2

    def cells(x: np.ndarray) -> np.ndarray:
        b = np.minimum((np.abs(x - o) / rng / T1_BUCKET).astype(int), T1_NBUCKET - 1)
        return ((x > o).astype(int) * 3 + loc) * T1_NBUCKET + b

    xs = np.arange(round(lv["low"] / TICK), round(lv["high"] / TICK) + 1) * TICK
    xs = xs[(np.abs(xs - lv["poc"]) > NODE_GAP * lv["width"] * TICK) & (xs != o)]
    c, w = cells(xs), TICK / (T1_BUCKET * rng)
    hits = np.bincount(c, weights=((xs >= lo) & (xs <= hi)) * w, minlength=T1_NCELL)
    weight = np.bincount(c, minlength=T1_NCELL) * w
    levels = {}
    for key in T1_LEVELS:
        x = lv[key]
        if abs(x - o) >= T1_MIN_DIST * rng and x != o:
            levels[key] = (int(cells(np.array([x]))[0]), int(lo <= x <= hi), int(lo <= 2 * o - x <= hi))
    return hits, weight, levels


def t1(sessions: dict) -> dict:
    rows = [(d, r) for a, d in pairs(sessions) if (r := t1_session(prior_levels(sessions[a]), sessions[d]))]
    if not rows:
        return {key: dict(sessions=0, mean=None, ci95=None, lower_alpha=None) for key in T1_LEVELS}
    hits = np.array([r[0] for _, r in rows])
    weight = np.array([r[1] for _, r in rows])
    W = boot_weights(len(rows))
    hits_b, weight_b = W @ hits, W @ weight
    curve = hits.sum(0) / np.maximum(weight.sum(0), 1e-12)
    out = {}
    for key in T1_LEVELS:
        sel = np.array([i for i, (_, r) in enumerate(rows) if key in r[2] and weight[:, r[2][key][0]].sum() > 0], int)
        if not len(sel):
            out[key] = dict(sessions=0, mean=None, ci95=None, lower_alpha=None)
            continue
        cell = np.array([rows[i][1][2][key][0] for i in sel])
        touch = np.array([rows[i][1][2][key][1] for i in sel], float)
        mirror = np.array([rows[i][1][2][key][2] for i in sel], float)
        excess = touch - curve[cell]
        ok = weight_b[:, cell] > 0
        w = W[:, sel] * ok
        draws = (w * (touch - hits_b[:, cell] / np.maximum(weight_b[:, cell], 1e-12))).sum(1) / np.maximum(w.sum(1), 1e-12)
        days = [rows[i][0] for i in sel]
        out[key] = dict(sessions=len(sel), touch=float(touch.mean()), control=float(curve[cell].mean()),
                        mean=float(excess.mean()), **ci(draws), by_year=by_year(days, excess),
                        mirror=float(mirror.mean()), minus_mirror=boot_mean(touch - mirror))
    return out


# ---------------------------------------------------------------- T2

def first_passage(price: float, D: float, s: dict) -> str | None:
    """'through' | 'back' | 'ambiguous' | 'open' for the first one-sided approach from 09:45, or None (no approach)."""
    O, H, L, m = s["O"], s["H"], s["L"], s["m"]
    touch = (L <= price) & (H >= price)
    for i in range(1, len(m)):
        if m[i] < T2_START:
            continue
        if m[i] > T2_END:
            return None
        if touch[i] and not touch[i - 1]:
            up = H[i - 1] < price           # came from below: through = up
            for k in range(i, len(m)):
                if m[k] > T2_END:
                    return "open"
                thr = H[k] >= price + D if up else L[k] <= price - D
                # the approach bar's far side printed on the way to the price, before the touch
                bck = k > i and (L[k] <= price - D if up else H[k] >= price + D)
                if thr and bck:
                    return "ambiguous"
                if thr:
                    return "through"
                if bck:
                    return "back"
            return "open"
    return None


def placebos(lv: dict, day: date) -> list[float]:
    w, nb = lv["width"], lv["nbins"]
    centre = lambda i: (lv["base"] + i * w + (w - 1) / 2) * TICK
    taken = [lv["poc_bin"]] + [round((x / TICK - lv["base"] - (w - 1) / 2) / w) for x in lv["hvn"] + lv["lvn"]]
    ok = [i for i in range(nb) if min(i, nb - 1 - i) > NODE_GAP and all(abs(i - t) > NODE_GAP for t in taken)]
    if not ok:
        return []
    rng = np.random.default_rng(day.toordinal())
    return [centre(int(i)) for i in rng.choice(ok, size=min(N_PLACEBO, len(ok)), replace=False)]


def t2_stratum(price: float, lv: dict, o: float) -> int:
    """(inside the prior VA) x (distance from the open bucket)."""
    d = int(np.searchsorted(T2_DIST_EDGES, abs(price - o) / lv["range"], side="right")) if lv["range"] > 0 else 0
    return int(lv["val"] <= price <= lv["vah"]) * (len(T2_DIST_EDGES) + 1) + d


def t2_session(lv: dict, s: dict, day: date) -> dict:
    """Outcome counts per kind, and through / resolved counts per kind x stratum."""
    D = max(2 * TICK, round(T2_D * lv["range"] / TICK) * TICK)
    o = s["O"][0]
    counts, thr, tot = {}, np.zeros((len(T2_KINDS), T2_NSTRATA)), np.zeros((len(T2_KINDS), T2_NSTRATA))
    for j, (kind, prices) in enumerate(zip(T2_KINDS, (lv["hvn"], lv["lvn"], placebos(lv, day)))):
        res = [(p, r) for p in prices if (r := first_passage(p, D, s))]
        counts[kind] = {k: sum(r == k for _, r in res) for k in ("through", "back", "ambiguous", "open")}
        for p, r in res:
            if r in ("through", "back"):
                st = t2_stratum(p, lv, o)
                thr[j, st] += r == "through"
                tot[j, st] += 1
    return dict(counts=counts, thr=thr, tot=tot)


def strat_diff(thr: np.ndarray, tot: np.ndarray, a: int, b: int) -> np.ndarray:
    """Rate(a) - rate(b), per-stratum differences weighted by the two kinds' events; leading axes broadcast."""
    na, nb = tot[..., a, :], tot[..., b, :]
    ra, rb = thr[..., a, :] / np.maximum(na, 1), thr[..., b, :] / np.maximum(nb, 1)
    w = np.where((na > 0) & (nb > 0), na + nb, 0.0)
    return (w * (ra - rb)).sum(-1) / np.maximum(w.sum(-1), 1e-12)


def t2(sessions: dict) -> dict:
    per = [t2_session(prior_levels(sessions[a]), sessions[d], d) for a, d in pairs(sessions)]
    n, shape = len(per), (len(T2_KINDS), T2_NSTRATA)
    thr = np.array([p["thr"] for p in per]).reshape(n, *shape)
    tot = np.array([p["tot"] for p in per]).reshape(n, *shape)
    W = boot_weights(n)
    thr_b = (W @ thr.reshape(n, -1)).reshape(-1, *shape)
    tot_b = (W @ tot.reshape(n, -1)).reshape(-1, *shape)
    T, N = thr.sum(0), tot.sum(0)
    raw = T.sum(1) / np.maximum(N.sum(1), 1)
    h, l, pl = 0, 1, 2                           # T2_KINDS order
    counts = {k: {c: int(sum(p["counts"][k][c] for p in per)) for c in ("through", "back", "ambiguous", "open")}
              for k in T2_KINDS}
    return dict(sessions=n, counts=counts, rate={k: float(v) for k, v in zip(T2_KINDS, raw)},
                strata=dict(through=T.tolist(), resolved=N.tolist()),
                raw_lvn_minus_hvn=float(raw[l] - raw[h]),
                lvn_minus_hvn=dict(mean=float(strat_diff(T, N, l, h)), **ci(strat_diff(thr_b, tot_b, l, h))),
                placebo_minus_hvn=dict(mean=float(strat_diff(T, N, pl, h)), **ci(strat_diff(thr_b, tot_b, pl, h))))


# ---------------------------------------------------------------- T3

def decisions(s: dict) -> list[dict]:
    """Per 5m decision bar (end 11:00-14:30): gate inputs, developing VA and any signal side."""
    O, H, L, C, V, m = s["O"], s["H"], s["L"], s["C"], s["V"], s["m"]
    tp = (H + L + C) / 3
    cv = np.cumsum(V)
    vwap = np.where(cv > 0, np.cumsum(tp * V) / np.maximum(cv, 1e-12), C)
    bucket = (m - OPEN) // 5
    ends = np.r_[np.flatnonzero(np.diff(bucket)), len(m) - 1]
    starts = np.r_[0, ends[:-1] + 1]
    end_min = OPEN + 5 * (bucket[ends] + 1)
    sign5 = np.sign(C[ends] - vwap[ends])
    lo_t, hi_t = np.rint(L / TICK).astype(np.int64), np.rint(H / TICK).astype(np.int64)
    base = int(lo_t.min())
    hist = np.zeros(int(hi_t.max()) - base + 1)
    added = 0
    out = []
    for b, (a, e) in enumerate(zip(starts, ends)):
        for i in range(added, e + 1):
            hist[lo_t[i] - base:hi_t[i] - base + 1] += V[i] / (hi_t[i] - lo_t[i] + 1)
        added = e + 1
        if not (T3_FIRST <= end_min[b] <= T3_LAST) or e + 1 >= len(m) or m[e + 1] >= FLAT:
            continue
        lo_i, hi_i = int(lo_t[:e + 1].min()) - base, int(hi_t[:e + 1].max()) - base
        va_lo, poc, va_hi = value_area(hist[lo_i:hi_i + 1])
        val, pocp, vah = ((base + lo_i + x) * TICK for x in (va_lo, poc, va_hi))
        past = np.searchsorted(m, end_min[b] - T3_LOOKBACK, side="left") - 1   # bars before t - 60
        win = (end_min > end_min[b] - T3_CROSS_WIN) & (end_min <= end_min[b])
        sg = sign5[win][sign5[win] != 0]
        h5, l5, c5 = H[a:e + 1].max(), L[a:e + 1].min(), C[e]
        up, dn = h5 >= vah + TICK, l5 <= val - TICK
        side = 0
        if up != dn and val <= c5 <= vah:
            side = -1 if up else 1
        out.append(dict(e=e, side=side, h5=h5, l5=l5, val=val, poc=pocp, vah=vah,
                        drift=abs(vwap[e] - vwap[past]), rng=H[:e + 1].max() - L[:e + 1].min(),
                        cross=int((sg[1:] != sg[:-1]).sum())))
    return out


def balanced(dp: dict, s_mult: float) -> bool:
    return dp["drift"] <= s_mult * dp["rng"] and dp["cross"] >= T3_MIN_CROSS


def bracket2(s: dict, d: int, j: int, stop_d: float, t1_d: float, t2_d: float, be: bool, cost_pts: float,
             slip: int = 1) -> float:
    """Net R of a two-half bracket entered at bar j's open (`slip` ticks adverse, as are stop and time exits).

    Stop and targets sit at their planned prices (t3_plan measures them from the open + 1 tick), whatever `slip`."""
    O, H, L, C, m = s["O"], s["H"], s["L"], s["C"], s["m"]
    sl = slip * TICK
    plan = O[j] + d * TICK
    entry = O[j] + d * sl
    stop = plan - d * stop_d
    left = [plan + d * t1_d, plan + d * t2_d]
    exits: list[float] = []
    for i in range(j, len(m)):
        adv, fav = (L[i], H[i]) if d > 0 else (H[i], L[i])
        if i > j and (O[i] - stop) * d <= 0:
            exits += [O[i] - d * sl] * len(left)
            break
        if (adv - stop) * d <= 0:
            exits += [stop - d * sl] * len(left)
            break
        filled = []
        for t in left:
            if i > j and (O[i] - t) * d >= 0:
                filled.append((t, O[i]))
            elif (fav - t) * d >= TICK:
                filled.append((t, t))
        for t, px in filled:
            left.remove(t)
            exits.append(px)
        if filled and be:
            stop = entry
        if not left:
            break
        if m[i] >= FLAT or i == len(m) - 1:
            exits += [C[i] - d * sl] * len(left)
            break
    return (float(np.mean([(x - entry) * d for x in exits])) - cost_pts) / stop_d


def t3_plan(dp: dict, s: dict, k: int):
    """(dir, entry bar, stop distance, POC distance, far-edge distance) or None."""
    d, j = dp["side"], dp["e"] + 1
    entry = s["O"][j] + d * TICK
    stop = dp["h5"] + k * TICK if d < 0 else dp["l5"] - k * TICK
    if (stop - entry) * -d <= 0:              # opened through the stop
        return None
    stop_d = max((stop - entry) * -d, T3_MIN_STOP_TICKS * TICK)
    t1_d = (dp["poc"] - entry) * d
    t2_d = ((dp["val"] if d < 0 else dp["vah"]) - entry) * d
    if t1_d < TICK or dp["vah"] - dp["val"] < 2 * stop_d:
        return None
    return d, j, stop_d, t1_d, t2_d


def t3_rows(sessions: dict, symbol: str) -> dict:
    """{cell: {"bal": [trade], "twin": [trade]}}, trade = dict(day, dir, r, r_flip, r_2x, friction_r, stop_ticks)."""
    cost = COMMISSION_RT / INSTRUMENTS[symbol]["pv"]
    rows = {cell_name(p): dict(bal=[], twin=[]) for p in T3_GRID}
    for _, day in pairs(sessions):
        s = sessions[day]
        dps = [dp for dp in decisions(s) if dp["side"]]
        for p in T3_GRID:
            seen = set()
            for dp in dps:
                group = "bal" if balanced(dp, p["s"]) else "twin"
                if (group, dp["side"]) in seen:
                    continue
                plan = t3_plan(dp, s, p["k"])
                if plan is None:
                    continue
                seen.add((group, dp["side"]))
                d, j, sd, a, b = plan
                r = bracket2(s, d, j, sd, a, b, p["be"], cost)
                gross = bracket2(s, d, j, sd, a, b, p["be"], 0.0, slip=0)
                rows[cell_name(p)][group].append(dict(
                    day=day, dir=d, r=r, r_flip=bracket2(s, -d, j, sd, a, b, p["be"], cost),
                    r_2x=bracket2(s, d, j, sd, a, b, p["be"], 2 * cost, slip=2), friction_r=gross - r,
                    stop_ticks=sd / TICK))
    return rows


def t3_score(cell: dict, controls: bool) -> dict:
    bal, twin = cell["bal"], cell["twin"]
    r = np.array([t["r"] for t in bal])
    edge = lambda ts: float(np.mean([(t["r"] - t["r_flip"]) / 2 for t in ts])) if ts else None
    stat = lambda key, f=np.mean: float(f([t[key] for t in bal])) if bal else None
    out = dict(trades=len(r), twin_trades=len(twin), **boot_mean(r), mean_2x=stat("r_2x"),
               friction_r=stat("friction_r"), stop_ticks_median=stat("stop_ticks", np.median),
               twin_mean=float(np.mean([t["r"] for t in twin])) if twin else None,
               edge=edge(bal), twin_edge=edge(twin), by_year=by_year([t["day"] for t in bal], r))
    if controls and len(r):
        rng = np.random.default_rng(SEED + 1)
        flip = np.array([t["r_flip"] for t in bal])
        rand = np.array([np.where(rng.random(len(r)) < .5, r, flip).mean() for _ in range(N_RANDOM)])
        out["coin"] = dict(mean=float(rand.mean()), p=float((1 + (rand >= r.mean()).sum()) / (1 + N_RANDOM)))
    return out


def select_t3(explore: dict) -> dict | None:
    best = None
    for p in T3_GRID:
        name = cell_name(p)
        per = {sym: explore[sym]["t3"][name] for sym in ("SPY", "QQQ")}
        if any(c["trades"] < T3_MIN_TRADES or c["mean"] <= 0 or c["mean_2x"] is None or c["mean_2x"] <= 0
               or c["twin_edge"] is None or c["edge"] <= c["twin_edge"] for c in per.values()):
            continue
        pooled = sum(c["mean"] * c["trades"] for c in per.values()) / sum(c["trades"] for c in per.values())
        if best is None or pooled > best["pooled_mean_r"]:
            best = dict(cell=name, params=p, pooled_mean_r=pooled)
    return best


# ---------------------------------------------------------------- inference

def block_idx(n: int, n_boot: int = N_BOOT, block: int = BLOCK, seed: int = SEED) -> np.ndarray:
    b = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - b + 1, (n_boot, -(-n // b)))
    return (starts[:, :, None] + np.arange(b)).reshape(n_boot, -1)[:, :n].astype(np.int32)


def boot_weights(n: int) -> np.ndarray:
    """(N_BOOT, n) counts of each row in each block-bootstrap draw (block_idx's draws), for ratio statistics."""
    idx = block_idx(n)
    flat = (idx + np.arange(len(idx))[:, None] * n).ravel()
    return np.bincount(flat, minlength=len(idx) * n).reshape(len(idx), n).astype(float)


def ci(draws: np.ndarray) -> dict:
    return dict(ci95=[float(np.quantile(draws, .025)), float(np.quantile(draws, .975))],
                lower_alpha=float(np.quantile(draws, ALPHA)))


def boot_mean(x: np.ndarray) -> dict:
    if not len(x):
        return dict(mean=None, ci95=None, lower_alpha=None)
    return dict(mean=float(x.mean()), **ci(x[block_idx(len(x))].mean(1)))


def by_year(days: list[date], x: np.ndarray) -> dict:
    out: dict[int, list[float]] = {}
    for d, v in zip(days, x):
        out.setdefault(d.year, []).append(float(v))
    return {y: dict(n=len(v), mean=float(np.mean(v))) for y, v in sorted(out.items())}


def passes(stat: dict) -> bool:
    return stat["lower_alpha"] is not None and stat["lower_alpha"] > 0


def verdicts(res: dict) -> dict:
    t1 = res["t1"]
    simpler = [t1[k]["mean"] for k in T1_LEVELS[1:] if t1[k]["mean"] is not None]
    t1_ok = passes(t1["poc"]) and all(t1["poc"]["mean"] > m for m in simpler)
    out = dict(T1="PASS" if t1_ok else "FAIL",
               T2="PASS" if passes(res["t2"]["lvn_minus_hvn"]) and res["t2"]["placebo_minus_hvn"]["mean"] > 0 else "FAIL")
    t3 = res.get("t3")
    if t3 is None:
        out["T3"] = "DROPPED (no cell qualified in exploration)"
    else:
        ok = (t3["trades"] and passes(t3) and t3["coin"]["p"] < ALPHA and t3["twin_edge"] is not None
              and t3["edge"] > t3["twin_edge"])
        out["T3"] = "PASS" if ok else "FAIL"
    return out


# ---------------------------------------------------------------- profile check

def profile_check(trades_dir: Path) -> dict:
    """Exact (prints) vs 1m-bar profile on NQ RTH sessions before VERIFY_START: POC gap in node bins (and ticks), HVN
    agreement within one bin."""
    rows = []
    for f in sorted(trades_dir.glob("*.parquet")):
        if date.fromisoformat(f.name[:10]) >= VERIFY_START.date():
            continue
        df = pd.read_parquet(f)
        ts = pd.to_datetime(df["ts_event"] if "ts_event" in df else df.index, utc=True)
        df = df.assign(ts=ts.tz_convert(ET))
        df = df[df.instrument_id == df.instrument_id.mode().iloc[0]]
        mins = df.ts.dt.hour * 60 + df.ts.dt.minute
        df = df[(mins >= OPEN) & (mins < CLOSE)]
        if df.empty:
            continue
        tick = np.rint(df.price.to_numpy(float) / TICK).astype(np.int64)
        base = int(tick.min())
        exact = np.bincount(tick - base, weights=df["size"].to_numpy(float))
        bars = df.set_index("ts").price.resample("1min").ohlc().dropna()
        vol = df.set_index("ts")["size"].resample("1min").sum().reindex(bars.index)
        smear, sbase = tick_hist(bars.high.to_numpy(), bars.low.to_numpy(), vol.to_numpy(float))
        _, ep, _ = value_area(exact)
        _, sp, _ = value_area(smear)
        close = float(df.price.iloc[-1])
        en, sn = nodes(exact, base, base + ep, close), nodes(smear, sbase, sbase + sp, close)
        w = en["width"] * TICK
        near = lambda xs, ys: sum(any(abs(x - y) <= w for y in ys) for x in xs)
        gap = abs((base + ep) - (sbase + sp))
        rows.append(dict(day=str(df.ts.iloc[0].date()), poc_gap_ticks=gap, poc_gap_bins=gap / en["width"],
                         bin_ticks=en["width"], hvn_exact=len(en["hvn"]), hvn_bars=len(sn["hvn"]),
                         hvn_recall=near(en["hvn"], sn["hvn"]), hvn_precision=near(sn["hvn"], en["hvn"])))
    if not rows:
        return dict(sessions=0)
    g = np.array([r["poc_gap_bins"] for r in rows])
    he, hb = sum(r["hvn_exact"] for r in rows), sum(r["hvn_bars"] for r in rows)
    return dict(sessions=len(rows), bin_ticks_median=float(np.median([r["bin_ticks"] for r in rows])),
                poc_gap_bins_median=float(np.median(g)), poc_gap_over_1_bin=float((g > 1).mean()),
                poc_gap_ticks_median=float(np.median([r["poc_gap_ticks"] for r in rows])),
                hvn_recall=sum(r["hvn_recall"] for r in rows) / max(he, 1),
                hvn_precision=sum(r["hvn_precision"] for r in rows) / max(hb, 1), rows=rows)


# ---------------------------------------------------------------- main

def script_sha() -> str:
    """Hash of the spec: this file and amt_lucid_study.py, whose constants and loader it uses."""
    h = hashlib.sha256()
    for f in SPEC_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def coverage_problems(sessions: dict) -> list[str]:
    """Years of the confirmation window with too few ES sessions (a partial download must not spend the look)."""
    per = {y: 0 for y in range(CONFIRM_START.year, CONFIRM_END.year + 1)}
    for d in sessions:
        per[d.year] = per.get(d.year, 0) + 1
    return [f"{y}: {n} sessions" for y, n in per.items() if n < ES_MIN_SESSIONS_PER_YEAR]


def looks() -> list[str]:
    return [l for l in LOOKS.read_text().splitlines() if l.strip()] if LOOKS.exists() else []


def run_all(sessions: dict, symbol: str, cells: list[dict] | None) -> dict:
    res = dict(sessions=len(sessions), first=str(min(sessions)), last=str(max(sessions)),
               pairs=len(pairs(sessions)), t1=t1(sessions), t2=t2(sessions))
    if cells:
        rows = t3_rows(sessions, symbol)
        res["t3"] = {cell_name(p): t3_score(rows[cell_name(p)], True) for p in cells}
    return res


def fmt(x, spec="+.3f") -> str:
    return "  n/a" if x is None else format(x, spec)


def report(sym: str, res: dict) -> None:
    print(f"\n{sym}  {res['sessions']} sessions {res['first']} -> {res['last']} ({res['pairs']} with a usable prior)")
    for key in T1_LEVELS:
        t = res["t1"][key]
        if not t["sessions"]:
            print(f"  T1 {key:<5} n=0")
            continue
        print(f"  T1 {key:<5} n={t['sessions']:<5} touch {t['touch']:.3f} control {t['control']:.3f} "
              f"excess {fmt(t['mean'])} 95% {[round(v, 3) for v in t['ci95']]} lower@alpha {fmt(t['lower_alpha'])} "
              f"| mirror {t['mirror']:.3f} (touch-mirror {fmt(t['minus_mirror']['mean'])})")
    t = res["t2"]
    print(f"  T2 pass-through (raw): HVN {t['rate']['hvn']:.3f}  LVN {t['rate']['lvn']:.3f}  "
          f"placebo {t['rate']['placebo']:.3f}  counts {t['counts']}")
    print(f"     stratified LVN-HVN {t['lvn_minus_hvn']['mean']:+.3f} lower@alpha {t['lvn_minus_hvn']['lower_alpha']:+.3f} "
          f"(raw {t['raw_lvn_minus_hvn']:+.3f}); stratified placebo-HVN {t['placebo_minus_hvn']['mean']:+.3f}")
    for name, c in res.get("t3", {}).items():
        print(f"  T3 {name:<20} n={c['trades']:<4} meanR {fmt(c['mean'])} lower@alpha {fmt(c['lower_alpha'])} "
              f"2x-cost {fmt(c['mean_2x'])} friction {fmt(c['friction_r'], '.3f')}R stop {fmt(c['stop_ticks_median'], '.0f')}t "
              f"edge {fmt(c['edge'])} | twin n={c['twin_trades']} {fmt(c['twin_mean'])} edge {fmt(c['twin_edge'])} | "
              f"coin {fmt(c.get('coin', {}).get('mean'))} "
              f"p={fmt(c.get('coin', {}).get('p'), '.4f')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--explore", action="store_true", help="T1-T3 on XNAS SPY + QQQ <= 2025-03-26 (repeatable)")
    mode.add_argument("--profile-check", action="store_true", help="1m-bar vs exact profile on the held NQ prints")
    mode.add_argument("--freeze", action="store_true", help="pick the T3 cell from explore.json, pin the script hash")
    mode.add_argument("--confirm", action="store_true", help="score the frozen tests once on ES 2012-2021")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sha = script_sha()

    if args.profile_check:
        res = profile_check(amt.DATA / "databento" / "nq-trades" / "NQ")
        (OUT / "profile_check.json").write_text(json.dumps(res, indent=1))
        print({k: v for k, v in res.items() if k != "rows"})
        return 0

    if args.explore:
        res = dict(script_sha=sha)
        for sym in ("SPY", "QQQ"):
            res[sym] = run_all(load_xnas(sym), sym, T3_GRID)
            report(sym, res[sym])
        res["selected_t3"] = select_t3(res)
        print(f"\nT3 selection: {res['selected_t3'] or 'none qualified; T3 will be dropped'}  (script {sha})")
        (OUT / "explore.json").write_text(json.dumps(res, indent=1, default=str))
        return 0

    if args.freeze:
        if PREREG.exists() or looks():
            print(f"already frozen ({PREREG}) or already scored ({LOOKS}); refusing")
            return 1
        explore = json.loads((OUT / "explore.json").read_text())
        if explore.get("script_sha") != sha:
            print(f"explore.json is from script {explore.get('script_sha')}, this is {sha}: re-run --explore")
            return 1
        chosen = select_t3(explore)
        PREREG.write_text(json.dumps(dict(script_sha=sha, t3=chosen, alpha=ALPHA,
                                          frozen_at=pd.Timestamp.now(tz="UTC").isoformat()), indent=1) + "\n")
        print(f"frozen script {sha}, T3 cell {chosen and chosen['cell']}. Commit {PREREG.name} now.")
        return 0

    if looks() or (OUT / "results.json").exists():
        print(f"already scored ({'; '.join(looks()) or OUT / 'results.json'}); refusing a second look")
        return 1
    if not PREREG.exists():
        print("run --explore and --freeze first")
        return 1
    pin = json.loads(PREREG.read_text())
    if pin["script_sha"] != sha:
        print(f"spec changed since --freeze ({pin['script_sha']} -> {sha}); refusing")
        return 1
    sessions = load_es()
    if gaps := coverage_problems(sessions):
        print(f"ES download incomplete ({', '.join(gaps)}; need >= {ES_MIN_SESSIONS_PER_YEAR} a year); "
              "nothing scored, the look is not spent")
        return 1
    with LOOKS.open("a") as f:
        f.write(f"script={sha} sessions={len(sessions)} at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    print(f"look logged in {LOOKS.name}: commit it with the results")
    t3_cell = pin["t3"]
    res = run_all(sessions, "ES", [t3_cell["params"]] if t3_cell else None)
    report("ES (one look)", res)
    res["t3"] = res["t3"][t3_cell["cell"]] if t3_cell else None
    res["verdicts"] = verdicts(res)
    print(f"\nVERDICTS (alpha {ALPHA:.4f}): {res['verdicts']}")
    (OUT / "results.json").write_text(json.dumps(dict(prereg=pin, result=res), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
