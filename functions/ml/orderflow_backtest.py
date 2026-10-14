"""Backtest the Flow Zone Trader "delta bubble at a key level" setup on NQ tick data.

Rules, transcribed from the channel's "Delta Volume Bubbles orderflow trading strategy"
video (youtube.com/watch?v=NMoT47nml_k):

  * No key level, no trade. Levels: prior-session low-volume nodes (volume profile),
    prior-session high/low, and the session VWAP +-1/2 sd bands.
  * Short: price comes up into a level from below, a *buy* delta bubble (one aggressor
    order of >= bubble_size contracts) prints at the level, then price trades back below
    the bubble with acceptance (the next full minute closes below its lowest fill): buyers are
    underwater / absorbed. Long is the mirror image with a sell bubble.
  * Stop above structure (the extreme since the bubble). Target the next key level or
    VWAP; skip the trade if that is less than 1R away, and use 2R when nothing is in
    the way.
  * Optional footprint confirmation: the accepting minute's delta must agree with the
    trade (aggressive sellers stepping in for a short).

Not modelled: the video's discretionary footprint read beyond minute delta, the Globex
"daily open" level (the data starts at 09:25 ET), and sizing down on wide stops (trades
wider than max_stop are skipped; results are in R, so size does not matter).

Everything is causal: levels come from the prior session or from prints before the
trigger, and entries fill at the first print after the confirming minute closes, one
tick worse. Stops fill one tick worse too; targets need a print one tick through.

Evaluation: an 8-cell grid chosen on the first 70% of sessions (discovery) and
reported on the rest (holdout), next to controls with identical levels, stops and
targets: "touch" (any print at the level, no bubble), "with_flow" (the bubble is on
the trade's side, so no absorption story) and random entries (noise floor).

Data: data/databento/nq-trades/NQ/*.parquet (databento_fetch.py nq-trades), all of it
before the sealed verify block.

    .venv/bin/python functions/ml/orderflow_backtest.py

--study absorb replaces the single big order with measured absorption: within one tick of
the high of the last W seconds, aggressive buying >= absorb_mult x the prior session's
median minute volume, while that high sits within `leak` ticks of the high of the W
seconds before (a short; the long mirrors it with sellers at the low). The "push" control
is the same effort that did move price more than `leak` ticks; acceptance, stops and
targets are shared. Points scale with the prior session's range ("range" units, quoted
at NQ's REF_RANGE) so a rule frozen on NQ transfers to ES. NQ picks the cell; ES is then
read once, after preregistered.json is written (a second ES run is refused):

    .venv/bin/python functions/ml/orderflow_backtest.py --study absorb --product NQ
    .venv/bin/python functions/ml/orderflow_backtest.py --study absorb --product ES

--study gex is the pre-registered test in ORDERFLOW_GEX_PREREG.md: GEX_RULE (the frozen
absorption cell plus QQQ call wall / put wall / zero gamma converted to NQ as levels, taken
only while QQQ net GEX < 0) on NQ sessions TEST_START..TEST_END, which no other study
reads. --smoke counts trades on research sessions, --freeze records the code hash before
the test prints exist, and the plain run reads them once:

    .venv/bin/python functions/ml/orderflow_backtest.py --study gex --smoke
    .venv/bin/python functions/ml/orderflow_backtest.py --study gex --freeze
    .venv/bin/python functions/ml/orderflow_backtest.py --study gex
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from holdout import VERIFY_START

ET = "America/New_York"
TICK = 0.25
POINT_VALUE = 20.0  # NQ $ per point
COMMISSION_USD = 4.5  # round trip
COMMISSION_PTS = COMMISSION_USD / POINT_VALUE
POINT_VALUES = {"NQ": 20.0, "ES": 50.0}
SLIP = TICK  # adverse slippage on market entries, stops and the end-of-day exit
MIN_NS = 60_000_000_000
SEC_NS = 1_000_000_000
PRE_OPEN_S = 300  # prints start at 09:25 ET
HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "databento" / "nq-trades" / "NQ"
OUT = HERE / "data" / "orderflow"
DISCOVERY_FRAC = 0.7
# "range" units quote points as on an NQ day whose prior RTH range was REF_RANGE: the
# median over the NQ research sessions, so a 3-pt tolerance means the same on ES.
REF_RANGE = 418.25  # --calibrate, 79 NQ sessions to 2026-08-14
# ~90th / 95th percentile (0.033 / 0.066) of the effort ratio at NQ level touches (--calibrate).
# Round 2: the 99th (0.35) fired <= 2 times in 81 sessions, since every second at a level counts.
ABSORB_MULTS = (0.03, 0.07)
PASS_RULE = "ES mean R > 0, above ES touch and push, n >= 30"
RESEARCH_START = "2026-04-24"  # bubble / absorb studies; earlier NQ prints are the GEX test set
TEST_START, TEST_END = "2025-10-24", "2026-04-24"  # --study gex, end exclusive
GEX = HERE / "data" / "thetadata_gex" / "qqq_gex_snapshots.parquet"
GEX_NAMES = ("call_wall", "put_wall", "zero_gamma")
GEX_LAG_NS = 60 * SEC_NS  # a snapshot is usable a minute after computed_at
GEX_STALE_NS = 20 * MIN_NS
PREREG_DOC = HERE / "ORDERFLOW_GEX_PREREG.md"


@dataclass(frozen=True)
class Params:
    trigger: str = "absorb"  # "absorb" | "with_flow" | "touch" | "random" | "absorb_vol" | "push"
    bubble_size: int = 60  # contracts in one aggressor order (the video uses 60-100)
    level_tol: float = 3.0  # points between the bubble and the level
    footprint: bool = False
    approach_min: int = 5  # price this long before the trigger must be on the approach side
    confirm_min: int = 10  # acceptance must come within this many minutes
    min_stop: float = 4.0
    max_stop: float = 30.0
    min_rr: float = 1.0
    fallback_rr: float = 2.0
    stop_buffer: float = 2 * TICK
    band_after_min: int = 15  # VWAP bands are degenerate right after the open
    last_entry_min: int = 360  # 15:30 ET
    flatten_min: int = 385  # 15:55 ET
    seed: int = 0
    units: str = "pts"  # "pts" | "range" (scaled by the prior session's range / REF_RANGE)
    window_s: int = 30  # absorb_vol / push: seconds of aggression measured
    absorb_mult: float = 0.0  # effort per minute of window, x the prior session's median minute volume
    leak: int = 1  # ticks the window high may gain on the one before and still count as absorbed
    point_value: float = POINT_VALUE
    gex_levels: bool = False  # add QQQ call wall / put wall / zero gamma, converted to NQ
    regime: str = "any"  # "any" | "neg" | "pos": trade only while QQQ net GEX has that sign

    @property
    def name(self) -> str:
        gex = ("/gexL" if self.gex_levels else "") + ("" if self.regime == "any" else f"/{self.regime}")
        if self.trigger == "random":
            return f"random/s{self.seed}{gex}"
        if self.trigger in ("absorb_vol", "push"):
            return f"{self.trigger}/w{self.window_s}/m{self.absorb_mult:g}/l{self.leak}{gex}"
        size = "" if self.trigger == "touch" else f"/b{self.bubble_size}"
        return f"{self.trigger}{size}/tol{self.level_tol:g}/{'fp' if self.footprint else 'nofp'}{gex}"


# The pre-registered rule (ORDERFLOW_GEX_PREREG.md): the frozen absorb cell, GEX levels, short gamma.
GEX_RULE = Params("absorb_vol", level_tol=3.0, units="range", window_s=30, absorb_mult=0.03, leak=2,
                  gex_levels=True, regime="neg")


@dataclass
class Session:
    """Prior-session reference levels; only valid on the same contract (no roll gap)."""
    instrument: int
    high: float
    low: float
    lvns: list[float]
    vol_per_min: float = 0.0  # median RTH minute volume


@dataclass
class Day:
    date: str
    instrument: int
    open_ns: int
    ts: np.ndarray  # int64 ns UTC, 09:25-16:00 ET prints
    px: np.ndarray
    sz: np.ndarray
    side: np.ndarray  # +1 buy aggressor, -1 sell aggressor, 0 unknown
    rth0: int  # first print at/after 09:30
    vwap: np.ndarray  # after print i (NaN before rth0)
    sd: np.ndarray
    bounds: np.ndarray  # print index at each minute boundary 09:30 + k min, k = 0..390
    close: np.ndarray  # per minute, carried forward over empty minutes
    delta: np.ndarray
    o_start: np.ndarray  # aggregated aggressor orders
    o_end: np.ndarray
    o_size: np.ndarray
    o_lo: np.ndarray
    o_hi: np.ndarray
    o_side: np.ndarray
    sec0: int  # ns of the 1-second grid start (09:25 ET)
    s_bounds: np.ndarray  # print index at each second boundary
    s_hi: np.ndarray  # per-second high (-inf when empty)
    s_lo: np.ndarray  # per-second low (+inf when empty)
    cache: dict = field(default_factory=dict, repr=False)
    gex: dict = field(default_factory=dict, repr=False)  # see attach_gex


def aggregate_orders(ts, px, sz, side):
    """One aggressor order sweeping several prices prints as several trades with the same
    match timestamp; group consecutive prints with equal (ts, side) back into orders."""
    new = np.ones(len(ts), bool)
    new[1:] = (ts[1:] != ts[:-1]) | (side[1:] != side[:-1])
    start = np.flatnonzero(new)
    end = np.r_[start[1:], len(ts)] - 1
    size = np.add.reduceat(sz, start)
    return start, end, size, np.minimum.reduceat(px, start), np.maximum.reduceat(px, start), side[start]


def low_volume_nodes(px, sz, bin_pts=5.0, win=3, reach=10, ratio=0.5) -> list[float]:
    """Valleys of the session volume profile: the local minimum of a smoothed histogram
    over +-win bins, at most `ratio` of the smaller peak within `reach` bins either side."""
    if len(px) == 0:
        return []
    b = np.floor(px / bin_pts).astype(np.int64)
    b0 = b.min()
    hist = np.bincount(b - b0, weights=sz)
    sm = np.convolve(np.pad(hist, 1, mode="edge"), [0.25, 0.5, 0.25], "valid")
    out: list[float] = []
    for i in range(win, len(sm) - win):
        if sm[i] > sm[i - win:i + win + 1].min():
            continue
        left, right = sm[max(0, i - reach):i].max(), sm[i + 1:i + 1 + reach].max()
        if sm[i] <= ratio * min(left, right) and (not out or (b0 + i + 0.5) * bin_pts - out[-1] > win * bin_pts):
            out.append(float((b0 + i + 0.5) * bin_pts))
    return out


def load_day(path: Path) -> Day | None:
    df = pd.read_parquet(path)
    if "action" in df:
        df = df[df["action"] == "T"]
    if df.empty:
        return None
    ts = (df["ts_event"] if "ts_event" in df else df.index.to_series()).astype("int64").to_numpy()
    order = np.argsort(ts, kind="stable")
    ts = ts[order]
    px = df["price"].to_numpy(float)[order]
    sz = df["size"].to_numpy(float)[order]
    side = np.select([df["side"].to_numpy() == "B", df["side"].to_numpy() == "A"], [1, -1], 0)[order].astype(np.int8)
    date = path.name[:10]
    return build_day(date, int(df["instrument_id"].mode().iloc[0]), ts, px, sz, side)


def build_day(date: str, instrument: int, ts, px, sz, side) -> Day:
    open_ns = pd.Timestamp(f"{date} 09:30", tz=ET).value
    close_ns = open_ns + 390 * MIN_NS
    keep = ts < close_ns
    ts, px, sz, side = ts[keep], px[keep], sz[keep], side[keep]
    rth0 = int(np.searchsorted(ts, open_ns))

    vwap = np.full(len(ts), np.nan)
    sd = np.full(len(ts), np.nan)
    v = np.cumsum(sz[rth0:])
    m1 = np.cumsum(px[rth0:] * sz[rth0:]) / v
    m2 = np.cumsum(px[rth0:] ** 2 * sz[rth0:]) / v
    vwap[rth0:] = m1
    sd[rth0:] = np.sqrt(np.maximum(m2 - m1 ** 2, 0.0))

    bounds = np.searchsorted(ts, open_ns + np.arange(391) * MIN_NS)
    last = bounds[1:] - 1
    close = np.where(bounds[1:] > bounds[:-1], px[np.maximum(last, 0)], np.nan)
    close = pd.Series(close).ffill().to_numpy()
    cd = np.r_[0.0, np.cumsum(side * sz)]
    delta = cd[bounds[1:]] - cd[bounds[:-1]]
    o = aggregate_orders(ts, px, sz, side)
    sec0 = open_ns - PRE_OPEN_S * SEC_NS
    s_bounds = np.searchsorted(ts, sec0 + np.arange(PRE_OPEN_S + 390 * 60 + 1) * SEC_NS)
    s_hi, s_lo = np.full(len(s_bounds) - 1, -np.inf), np.full(len(s_bounds) - 1, np.inf)
    full = s_bounds[1:] > s_bounds[:-1]
    if full.any():  # empty seconds have no prints, so consecutive non-empty starts tile them
        starts = s_bounds[:-1][full]
        s_hi[full], s_lo[full] = np.maximum.reduceat(px, starts), np.minimum.reduceat(px, starts)
    return Day(date, instrument, open_ns, ts, px, sz, side, rth0, vwap, sd, bounds, close, delta, *o,
               sec0, s_bounds, s_hi, s_lo)


def session_summary(day: Day) -> Session:
    px, sz = day.px[day.rth0:], day.sz[day.rth0:]
    cv = np.r_[0.0, np.cumsum(day.sz)]
    vpm = float(np.median(cv[day.bounds[1:]] - cv[day.bounds[:-1]]))
    return Session(day.instrument, float(px.max()), float(px.min()), low_volume_nodes(px, sz), vpm)


def static_levels(prev: Session | None, day: Day) -> list[tuple[str, float]]:
    if prev is None or prev.instrument != day.instrument:  # first day or contract roll
        return []
    return [("pdh", prev.high), ("pdl", prev.low)] + [("lvn", x) for x in prev.lvns]


def load_gex(path: Path = GEX) -> pd.DataFrame:
    g = pd.read_parquet(path, columns=["computed_at", "spot", *GEX_NAMES, "net_gex"])
    g["date"] = g["computed_at"].dt.tz_convert(ET).dt.strftime("%Y-%m-%d")
    return g.sort_values("computed_at")


def attach_gex(day: Day, snaps: pd.DataFrame) -> None:
    """QQQ snapshots of the day as NQ levels: strike x (last NQ print at or before
    computed_at / QQQ spot then). Rows with no NQ print yet are dropped."""
    snaps = snaps[snaps["date"] == day.date]
    comp = snaps["computed_at"].dt.as_unit("ns").astype("int64").to_numpy()  # the parquet is in us
    i = np.searchsorted(day.ts, comp, side="right") - 1
    keep = i >= 0
    ratio = day.px[i[keep]] / snaps["spot"].to_numpy(float)[keep]
    day.gex = dict(comp=comp[keep], avail=comp[keep] + GEX_LAG_NS, net=snaps["net_gex"].to_numpy(float)[keep],
                   lv=snaps[list(GEX_NAMES)].to_numpy(float)[keep] * ratio[:, None])


def gex_at(day: Day, t) -> tuple[np.ndarray, np.ndarray]:
    """(levels [n, 3], net GEX [n]) of the latest usable snapshot at each time; NaN if none."""
    t = np.atleast_1d(np.asarray(t, dtype=np.int64))
    nan_lv, nan_net = np.full((len(t), len(GEX_NAMES)), np.nan), np.full(len(t), np.nan)
    g = day.gex
    if not g or not len(g["comp"]):
        return nan_lv, nan_net
    j = np.searchsorted(g["avail"], t, side="right") - 1
    jj = np.maximum(j, 0)
    ok = (j >= 0) & (t - g["comp"][jj] <= GEX_STALE_NS)
    return np.where(ok[:, None], g["lv"][jj], nan_lv), np.where(ok, g["net"][jj], nan_net)


def regime_ok(day: Day, t: int, p: Params) -> bool:
    if p.regime == "any":
        return True
    net = gex_at(day, t)[1][0]
    return bool(net < 0) if p.regime == "neg" else bool(net > 0)


def dynamic_levels(day: Day, i: int, p: Params, with_vwap: bool) -> list[tuple[str, float]]:
    """VWAP-band (and, with gex_levels, GEX) levels known after print i."""
    if i < day.rth0 or np.isnan(day.vwap[i]):
        return []
    out = [("vwap", day.vwap[i])] if with_vwap else []
    if day.ts[i] >= day.open_ns + p.band_after_min * MIN_NS and day.sd[i] > 0:
        out += [(f"vwap{k:+d}sd", day.vwap[i] + k * day.sd[i]) for k in (-2, -1, 1, 2)]
    if p.gex_levels:
        out += [(k, float(x)) for k, x in zip(GEX_NAMES, gex_at(day, day.ts[i])[0][0]) if not np.isnan(x)]
    return out


def gex_columns(day: Day, i: np.ndarray, p: Params) -> list[np.ndarray]:
    """GEX levels after prints i, as prefilter columns (NaN before the open or when stale)."""
    if not p.gex_levels:
        return []
    lv = gex_at(day, day.ts[np.maximum(i, 0)])[0]
    lv[i < day.rth0] = np.nan
    return list(lv.T)


def price_before(day: Day, t: int) -> float:
    i = int(np.searchsorted(day.ts, t, side="right")) - 1
    return float(day.px[max(i, 0)])


def simulate(day: Day, direction: int, entry_i: int, stop: float, p: Params,
             levels: list[tuple[str, float]], trig: dict, cell: str) -> dict | None:
    """Enter at print entry_i, pick the target, and walk prints to stop/target/flatten."""
    flat_i = int(np.searchsorted(day.ts, day.open_ns + p.flatten_min * MIN_NS))
    if entry_i >= flat_i - 1:
        return None
    entry = day.px[entry_i] + direction * SLIP
    risk = direction * (entry - stop)
    if risk > p.max_stop:
        return None
    if risk < p.min_stop:
        stop, risk = entry - direction * p.min_stop, p.min_stop

    lv = levels + dynamic_levels(day, entry_i - 1, p, with_vwap=True)
    ahead = [(k, x) for k, x in lv if direction * (x - entry) >= TICK]
    if ahead:
        tkind, target = min(ahead, key=lambda kx: direction * (kx[1] - entry))
        if direction * (target - entry) < p.min_rr * risk:
            return None
    else:
        tkind, target = f"{p.fallback_rr:g}R", entry + direction * p.fallback_rr * risk

    path = day.px[entry_i + 1:flat_i]
    hit_stop = direction * (path - stop) <= 0
    hit_tgt = direction * (path - target) >= TICK
    si = int(hit_stop.argmax()) if hit_stop.any() else len(path)
    ti = int(hit_tgt.argmax()) if hit_tgt.any() else len(path)
    if si < ti:
        j, reason = si, "stop"
        exit_px = (min(stop, path[j]) if direction > 0 else max(stop, path[j])) - direction * SLIP
    elif ti < len(path):
        j, reason, exit_px = ti, "target", target
    else:
        j, reason, exit_px = len(path) - 1, "eod", path[-1] - direction * SLIP
    exit_i = entry_i + 1 + j
    pnl = direction * (exit_px - entry) - COMMISSION_USD / p.point_value
    # Excursions while open (points from the entry fill), for prop-account drawdown replay.
    held = direction * (day.px[entry_i:exit_i + 1] - entry)
    mae, mfe = min(float(held.min()), direction * (exit_px - entry)), max(float(held.max()), 0.0)
    return dict(
        date=day.date, cell=cell, direction=direction, **trig,
        entry_time=pd.Timestamp(day.ts[entry_i], tz="UTC").tz_convert(ET).strftime("%H:%M:%S"),
        entry=entry, stop=stop, target=target, target_kind=tkind, risk=risk,
        exit=exit_px, exit_reason=reason, exit_ns=int(day.ts[exit_i]),
        bars_held=int((day.ts[exit_i] - day.ts[entry_i]) // MIN_NS), pnl_pts=pnl, r=pnl / risk,
        mae_pts=mae, mfe_pts=mfe,
    )


def candidates(day: Day, statics: list[tuple[str, float]], p: Params):
    """Yield (order index, direction, level kind, level price) in time order."""
    t = day.ts[day.o_start]
    live = (t >= day.open_ns) & (t < day.open_ns + p.last_entry_min * MIN_NS)
    if p.trigger in ("absorb", "with_flow"):
        live &= (day.o_size >= p.bubble_size) & (day.o_side != 0)
    js = np.flatnonzero(live)
    # Vectorized prefilter (same levels as the exact check below): orders near any level.
    prev_i = day.o_start[js] - 1
    bands_ok = ((prev_i >= day.rth0) & (t[js] >= day.open_ns + p.band_after_min * MIN_NS)
                & (day.sd[np.maximum(prev_i, 0)] > 0))
    vw, sd = day.vwap[np.maximum(prev_i, 0)], day.sd[np.maximum(prev_i, 0)]
    lv = np.column_stack([np.full(len(js), x) for _, x in statics]
                         + [np.where(bands_ok, vw + k * sd, np.nan) for k in (-2, -1, 1, 2)]
                         + gex_columns(day, prev_i, p))
    dist = np.maximum(np.maximum(day.o_lo[js, None] - lv, lv - day.o_hi[js, None]), 0.0)
    js = js[(dist <= p.level_tol).any(axis=1)]
    last_touch: dict[tuple[str, int], int] = {}
    for j in js:
        s = int(day.o_start[j])
        lv = statics + dynamic_levels(day, s - 1, p, with_vwap=False)
        if not lv:
            continue
        lo, hi = day.o_lo[j], day.o_hi[j]
        ap = price_before(day, int(t[j]) - p.approach_min * MIN_NS)
        best = None
        for kind, x in lv:
            dist = max(lo - x, x - hi, 0.0)
            if dist > p.level_tol:
                continue
            came_from = -1 if ap < x else 1 if ap > x else 0  # -1: from below -> short
            if came_from == 0:
                continue
            if p.trigger == "absorb":
                ok = day.o_side[j] == -came_from  # buyers into resistance / sellers into support
            elif p.trigger == "with_flow":
                ok = day.o_side[j] == came_from
            else:
                ok = True
            if ok and (best is None or dist < best[0]):
                best = (dist, came_from, kind, x)
        if best is None:
            continue
        _, direction, kind, x = best
        if p.trigger == "touch":  # one touch per level per minute, or it's every print
            key, minute = (kind, direction), int((t[j] - day.open_ns) // MIN_NS)
            if last_touch.get(key) == minute:
                continue
            last_touch[key] = minute
        yield j, direction, kind, x


def bubble_events(day: Day, statics: list[tuple[str, float]], p: Params):
    """Yield (time, first print, first confirm minute, direction, trigger price, trig) per bubble."""
    for j, direction, kind, x in candidates(day, statics, p):
        s = int(day.o_start[j])
        trig_px = day.o_lo[j] if direction < 0 else day.o_hi[j]  # far edge of the bubble
        m0 = int((day.ts[s] - day.open_ns) // MIN_NS) + 1  # a whole minute that starts after it
        trig = dict(level_kind=kind, level=x, trigger_size=float(day.o_size[j]),
                    trigger_time=pd.Timestamp(day.ts[s], tz="UTC").tz_convert(ET).strftime("%H:%M:%S"))
        yield int(day.ts[s]), s, m0, direction, trig_px, trig


def absorb_profile(day: Day, w: int) -> dict:
    """Per grid second k (window = the w seconds ending with k): the window high/low and the
    one over the w seconds before it. Effort is filled in lazily (see effort())."""
    if w not in day.cache:
        win = np.lib.stride_tricks.sliding_window_view
        hi = win(np.r_[np.full(w - 1, -np.inf), day.s_hi], w).max(1)
        lo = win(np.r_[np.full(w - 1, np.inf), day.s_lo], w).min(1)
        day.cache[w] = dict(hi=hi, lo=lo, hi_prev=np.r_[np.full(w, -np.inf), hi[:-w]],
                            lo_prev=np.r_[np.full(w, np.inf), lo[:-w]],
                            buy=np.full(len(hi), np.nan), sell=np.full(len(hi), np.nan))
    return day.cache[w]


def effort(day: Day, w: int, k: int, direction: int) -> float:
    """Aggressive volume in the window within one tick of its extreme: buyers at the high for
    a short (direction -1), sellers at the low for a long."""
    pr = absorb_profile(day, w)
    arr = pr["buy" if direction < 0 else "sell"]
    if np.isnan(arr[k]):
        a, b = day.s_bounds[max(k - w + 1, 0)], day.s_bounds[k + 1]
        px, sz, side = day.px[a:b], day.sz[a:b], day.side[a:b]
        if direction < 0:
            arr[k] = sz[(side == 1) & (px >= pr["hi"][k] - TICK)].sum()
        else:
            arr[k] = sz[(side == -1) & (px <= pr["lo"][k] + TICK)].sum()
    return float(arr[k])


def level_dist(day: Day, ks: np.ndarray, zlo: np.ndarray, zhi: np.ndarray,
               statics: list[tuple[str, float]], p: Params) -> np.ndarray:
    """Distance from the zone [zlo, zhi] at the end of second k to the nearest level (statics,
    VWAP bands and GEX levels known then)."""
    t = day.sec0 + (ks + 1) * SEC_NS
    i = day.s_bounds[ks + 1] - 1
    ok = (i >= day.rth0) & (t >= day.open_ns + p.band_after_min * MIN_NS) & (day.sd[np.maximum(i, 0)] > 0)
    vw, sd = day.vwap[np.maximum(i, 0)], day.sd[np.maximum(i, 0)]
    lv = np.column_stack([np.full(len(ks), x) for _, x in statics]
                         + [np.where(ok, vw + k * sd, np.nan) for k in (-2, -1, 1, 2)]
                         + gex_columns(day, i, p))
    d = np.maximum(np.maximum(zlo[:, None] - lv, lv - zhi[:, None]), 0.0)
    return np.nanmin(np.where(np.isnan(d), np.inf, d), axis=1)


def absorb_events(day: Day, statics: list[tuple[str, float]], p: Params, prev: Session):
    """Yield absorption ("absorb_vol") or effort-that-moved-price ("push") events at levels,
    in time order, as bubble_events does. One event per side per window."""
    w, leak = p.window_s, p.leak * TICK
    need = p.absorb_mult * prev.vol_per_min * w / 60  # same intensity for either window
    pr = absorb_profile(day, w)
    k0 = PRE_OPEN_S - 1  # second ending at 09:30
    ks = np.arange(k0, PRE_OPEN_S - 1 + p.last_entry_min * 60)
    sides = []
    for direction, ext, prv in ((-1, pr["hi"], pr["hi_prev"]), (1, pr["lo"], pr["lo_prev"])):
        with np.errstate(invalid="ignore"):  # inf - inf on empty windows; dropped by isfinite below
            gain = -direction * (ext[ks] - prv[ks])  # how far the aggression moved its extreme
        moved = (gain > leak) if p.trigger == "push" else (np.abs(gain) <= leak)
        zlo, zhi = (ext[ks] - TICK, ext[ks]) if direction < 0 else (ext[ks], ext[ks] + TICK)
        near = level_dist(day, ks, zlo, zhi, statics, p) <= p.level_tol
        sides += [(int(k), direction) for k in ks[moved & near & np.isfinite(ext[ks])]]
    last = {-1: -10**9, 1: -10**9}
    for k, direction in sorted(sides):
        if k - last[direction] < w or effort(day, w, k, direction) < need:
            continue
        t = day.sec0 + (k + 1) * SEC_NS
        z = pr["hi"][k] if direction < 0 else pr["lo"][k]
        zlo, zhi = (z - TICK, z) if direction < 0 else (z, z + TICK)
        i = int(day.s_bounds[k + 1]) - 1
        ap = price_before(day, t - p.approach_min * MIN_NS)
        best = None
        for kind, x in statics + dynamic_levels(day, i, p, with_vwap=False):
            dist = max(zlo - x, x - zhi, 0.0)
            # Buyers absorbed under resistance approached from below, sellers above support.
            if dist <= p.level_tol and direction * (ap - x) > 0 and (best is None or dist < best[0]):
                best = (dist, kind, x)
        if best is None:
            continue
        last[direction] = k
        trig = dict(level_kind=best[1], level=best[2], trigger_size=effort(day, w, k, direction),
                    trigger_time=pd.Timestamp(t, tz="UTC").tz_convert(ET).strftime("%H:%M:%S"))
        m0 = -(-(t - day.open_ns) // MIN_NS)  # first whole minute starting at or after t
        yield t, int(day.s_bounds[max(k - w + 1, 0)]), int(m0), direction, z + direction * TICK, trig


def scale(p: Params, prev: Session | None, day: Day) -> tuple[Params | None, float]:
    """Points in "range" units are quoted at REF_RANGE; rescale them to the prior session."""
    if p.units == "pts":
        return p, 1.0
    if prev is None or prev.instrument != day.instrument:
        return None, 0.0
    k = (prev.high - prev.low) / REF_RANGE
    return replace(p, level_tol=p.level_tol * k, min_stop=p.min_stop * k, max_stop=p.max_stop * k), k


def run_day(day: Day, statics: list[tuple[str, float]], p: Params, prev: Session | None = None) -> list[dict]:
    cell = p.name
    p, k = scale(p, prev, day)
    if p is None:
        return []
    if p.trigger == "random":
        return run_random(day, statics, p, cell, k)
    if p.trigger in ("absorb_vol", "push"):
        events = absorb_events(day, statics, p, prev)
    else:
        events = bubble_events(day, statics, p)
    trades, busy_until = [], -1
    for t, s, m0, direction, trig_px, trig in events:
        if t <= busy_until or not regime_ok(day, t, p):
            continue
        # Acceptance: a whole minute that starts after the trigger closes beyond it.
        for m in range(m0, min(m0 + p.confirm_min, p.last_entry_min)):
            if direction * (day.close[m] - trig_px) > 0 and (not p.footprint or direction * day.delta[m] > 0):
                break
        else:
            continue
        seg = day.px[s:day.bounds[m + 1]]
        stop = (seg.max() if direction < 0 else seg.min()) - direction * p.stop_buffer
        tr = simulate(day, direction, int(day.bounds[m + 1]), stop, p, statics, trig, cell)
        if tr:
            trades.append(tr)
            busy_until = tr["exit_ns"]
    return trades


def run_random(day: Day, statics, p: Params, cell: str, k: float = 1.0) -> list[dict]:
    """Noise floor: ~3 random-minute entries a session, random side, a 6/10/15-pt stop,
    and the same target rule."""
    rng = np.random.default_rng([p.seed, int(day.date.replace("-", ""))])
    trades, busy_until = [], -1
    for m in np.sort(rng.choice(p.last_entry_min, size=rng.poisson(3), replace=False)):
        i = int(day.bounds[m + 1])
        if i >= len(day.ts) or day.ts[i] <= busy_until or not regime_ok(day, int(day.ts[i]), p):
            continue
        direction = int(rng.choice([-1, 1]))
        stop = day.px[i] + direction * SLIP - direction * float(rng.choice([6.0, 10.0, 15.0])) * k
        tr = simulate(day, direction, i, stop, p, statics,
                      dict(level_kind="random", level=np.nan, trigger_size=0.0, trigger_time=""), cell)
        if tr:
            trades.append(tr)
            busy_until = tr["exit_ns"]
    return trades


def grid() -> list[Params]:
    cells = []
    for b in (60, 100):
        for tol in (3.0, 6.0):
            for fp in (False, True):
                cells += [Params("absorb", b, tol, fp), Params("with_flow", b, tol, fp)]
    for tol in (3.0, 6.0):
        for fp in (False, True):
            cells.append(Params("touch", 0, tol, fp))
    return cells + [Params("random", seed=s) for s in range(20)]


def absorb_grid(point_value: float) -> list[Params]:
    """8 absorption cells, each with its push twin, plus touch and random in the same units."""
    base = dict(level_tol=3.0, units="range", point_value=point_value)
    cells = []
    for w in (30, 60):
        for m in ABSORB_MULTS:
            for leak in (1, 2):
                cells += [Params(t, window_s=w, absorb_mult=m, leak=leak, **base) for t in ("absorb_vol", "push")]
    cells.append(Params("touch", 0, **base))
    return cells + [Params("random", seed=s, **base) for s in range(20)]


def summarize(tr: pd.DataFrame, sessions: list[str], n_boot=2000, seed=0,
              point_value: float = POINT_VALUE, usd_key: str = "usd_per_nq") -> dict:
    """Trade stats; the CI resamples whole sessions so intraday clustering is kept."""
    if tr.empty:
        return dict(n=0)
    r = tr["r"].to_numpy()
    by = tr.groupby("date")["r"].agg(["sum", "count"]).reindex(sessions, fill_value=0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(by), size=(n_boot, len(by)))
    s, c = by["sum"].to_numpy()[idx].sum(1), by["count"].to_numpy()[idx].sum(1)
    boot = s[c > 0] / c[c > 0]
    eq = np.cumsum(r)
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return dict(
        n=len(r), per_session=round(len(r) / len(sessions), 2), win_rate=round(float((r > 0).mean()), 3),
        mean_r=round(float(r.mean()), 3), ci95=[round(float(q), 3) for q in np.percentile(boot, [2.5, 97.5])],
        total_r=round(float(r.sum()), 1), profit_factor=round(float(wins / losses), 2) if losses else None,
        max_dd_r=round(float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()), 1),
        mean_pts=round(float(tr["pnl_pts"].mean()), 2), **{usd_key: round(float(tr["pnl_pts"].sum() * point_value))},
        median_risk_pts=round(float(tr["risk"].median()), 2),
        exits={k: int(v) for k, v in tr["exit_reason"].value_counts().items()},
    )


def research_files(data: Path) -> list[Path]:
    # Research data only: nothing from the verify block or the gap week before it.
    cutoff = (VERIFY_START - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    return [f for f in sorted(data.glob("*.parquet")) if RESEARCH_START <= f.name[:10] < cutoff]


def test_files(data: Path) -> list[Path]:
    return [f for f in sorted(data.glob("*.parquet")) if TEST_START <= f.name[:10] < TEST_END]


def days(files: list[Path], gex: pd.DataFrame | None = None):
    """Yield (day, prior session) in date order, with GEX snapshots attached when given."""
    prev: Session | None = None
    for f in files:
        day = load_day(f)
        if day is None or day.rth0 >= len(day.ts):
            continue
        if gex is not None:
            attach_gex(day, gex)
        yield day, prev
        prev = session_summary(day)


def run_study(files: list[Path], cells: list[Params],
              gex: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    trades: list[dict] = []
    sessions: list[str] = []
    for day, prev in days(files, gex):
        sessions.append(day.date)
        statics = static_levels(prev, day)
        for p in cells:
            trades += run_day(day, statics, p, prev)
        print(f"{day.date}  prints={len(day.ts):>7}  levels={len(statics):>2}  "
              f"bubbles>=60={int((day.o_size >= 60).sum()):>4}  trades so far={len(trades)}")
    return pd.DataFrame(trades), sessions


def code_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def print_table(rows: dict, splits: tuple[str, ...]) -> None:
    print(f"{'cell':<32}" + "  |".join(f"{'n':>5}{'win':>7}{'meanR':>8}{'CI95':>18}{'totR':>8}" for _ in splits))
    for name, row in rows.items():
        cols = []
        for split in splits:
            s = row[split]
            cols.append(f"{s.get('n', 0):>5}{s.get('win_rate', 0):>7.2f}{s.get('mean_r', 0):>8.3f}"
                        f"{str(s.get('ci95', '')):>18}{s.get('total_r', 0):>8.1f}")
        print(f"{name:<32}" + "  |".join(cols))


def bubble_main(args) -> int:
    files = research_files(args.data)
    if not files:
        print(f"no data under {args.data}")
        return 1
    cells = grid()
    tr, sessions = run_study(files, cells)
    cut = sessions[int(len(sessions) * DISCOVERY_FRAC)]
    disc_s, hold_s = [s for s in sessions if s < cut], [s for s in sessions if s >= cut]
    disc, hold = tr[tr["date"] < cut], tr[tr["date"] >= cut]

    table = {}
    for p in cells:
        table[p.name] = dict(discovery=summarize(disc[disc["cell"] == p.name], disc_s),
                             holdout=summarize(hold[hold["cell"] == p.name], hold_s))
    # Pick the strategy cell on discovery only (>= 30 trades), then read its holdout once.
    eligible = [p for p in cells if p.trigger == "absorb" and table[p.name]["discovery"].get("n", 0) >= 30]
    best = max(eligible, key=lambda p: table[p.name]["discovery"]["mean_r"]) if eligible else None
    controls = {}
    if best:
        controls = {
            "with_flow": replace(best, trigger="with_flow").name,
            "touch": replace(best, trigger="touch", bubble_size=0).name,
        }
    rnd = tr[tr["cell"].str.startswith("random")]
    random_floor = {
        split: summarize(rnd[(rnd["date"] < cut) == (split == "discovery")], ss)
        for split, ss in (("discovery", disc_s), ("holdout", hold_s))
    }

    args.out.mkdir(parents=True, exist_ok=True)
    tr.drop(columns=["exit_ns"]).to_csv(args.out / "trades.csv", index=False)
    report = dict(
        sessions=dict(all=len(sessions), discovery=[disc_s[0], disc_s[-1], len(disc_s)],
                      holdout=[hold_s[0], hold_s[-1], len(hold_s)]),
        costs=dict(commission_pts=COMMISSION_PTS, slippage_ticks=1),
        defaults=asdict(Params()), selected=best.name if best else None, controls=controls,
        random_floor=random_floor, cells={k: v for k, v in table.items() if not k.startswith("random")},
    )
    (args.out / "report.json").write_text(json.dumps(report, indent=2))

    print(f"\nsessions: discovery {disc_s[0]}..{disc_s[-1]} ({len(disc_s)}), "
          f"holdout {hold_s[0]}..{hold_s[-1]} ({len(hold_s)})")
    rows = {k: v for k, v in table.items() if not k.startswith("random/")}
    print_table({**rows, "random (20 seeds pooled)": random_floor}, ("discovery", "holdout"))
    print(f"\nselected on discovery: {report['selected']}   controls: {controls}")
    print(f"wrote {args.out / 'report.json'} and trades.csv")
    return 0


def calibrate(files: list[Path], tol: float = 3.0) -> None:
    """Print REF_RANGE and the effort distribution (per minute of window, x the prior session's
    median minute volume) at every level-touching second, both sides, both windows."""
    ranges, ratios = [], []
    for day, prev in days(files):
        if prev is None or prev.instrument != day.instrument:
            continue
        ranges.append(prev.high - prev.low)
        statics = static_levels(prev, day)
        p = Params(level_tol=tol)
        ks = np.arange(PRE_OPEN_S - 1, PRE_OPEN_S - 1 + p.last_entry_min * 60)
        for w in (30, 60):
            pr = absorb_profile(day, w)
            for direction, ext in ((-1, pr["hi"]), (1, pr["lo"])):
                ok = np.isfinite(ext[ks])
                kk = ks[ok]
                zlo, zhi = (ext[kk] - TICK, ext[kk]) if direction < 0 else (ext[kk], ext[kk] + TICK)
                near = kk[level_dist(day, kk, zlo, zhi, statics, p) <= tol]
                ratios += [effort(day, w, int(k), direction) / (prev.vol_per_min * w / 60) for k in near]
        print(f"{day.date}  prior range={ranges[-1]:.2f}  touches so far={len(ratios)}")
    q = np.percentile(ratios, [50, 90, 95, 99, 99.5])
    print(f"\nREF_RANGE (median prior RTH range) = {np.median(ranges):.2f} over {len(ranges)} sessions")
    print("effort ratio percentiles 50/90/95/99/99.5:", np.round(q, 3))


def absorb_main(args) -> int:
    pv = POINT_VALUES[args.product]
    out = args.out / f"absorb_{args.product}"
    files = research_files(args.data)
    if not files:
        print(f"no data under {args.data}")
        return 1
    if args.product == "NQ":
        return absorb_select(files, out, pv)
    return absorb_verify(files, out, args.out / "absorb_NQ" / "report.json", pv)


def absorb_select(files: list[Path], out: Path, pv: float) -> int:
    """Run the grid on NQ and freeze the best absorption cell, if it beats its controls."""
    cells = absorb_grid(pv)
    tr, sessions = run_study(files, cells)
    cut = sessions[int(len(sessions) * DISCOVERY_FRAC)]
    splits = {"all": sessions, "discovery": [s for s in sessions if s < cut],
              "holdout": [s for s in sessions if s >= cut]}
    summ = lambda df, ss: summarize(df[df["date"].isin(ss)], ss, point_value=pv, usd_key="usd_per_contract")
    table = {p.name: {k: summ(tr[tr["cell"] == p.name], ss) for k, ss in splits.items()}
             for p in cells if p.trigger != "random"}
    rnd = tr[tr["cell"].str.startswith("random")]
    table["random (20 seeds pooled)"] = {k: summ(rnd, ss) for k, ss in splits.items()}

    eligible = [p for p in cells if p.trigger == "absorb_vol" and table[p.name]["all"].get("n", 0) >= 40]
    best = max(eligible, key=lambda p: table[p.name]["all"]["mean_r"]) if eligible else None
    controls, selected = {}, None
    if best:
        controls = {"push": replace(best, trigger="push").name, "touch": Params("touch", 0, 3.0).name}
        mean = lambda name: table[name]["all"].get("mean_r", -np.inf)
        if all(mean(best.name) > mean(c) for c in controls.values()):
            selected = best
    out.mkdir(parents=True, exist_ok=True)
    tr.drop(columns=["exit_ns"]).to_csv(out / "trades.csv", index=False)
    report = dict(
        product="NQ", code_sha=code_sha(), ref_range=REF_RANGE, absorb_mults=list(ABSORB_MULTS),
        sessions={k: [ss[0], ss[-1], len(ss)] for k, ss in splits.items()},
        costs=dict(commission_usd=COMMISSION_USD, point_value=pv, slippage_ticks=1),
        best=best.name if best else None, controls=controls,
        selected=selected.name if selected else None,
        selected_params=asdict(selected) if selected else None, cells=table,
    )
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print_table(table, tuple(splits))
    print(f"\nbest on all NQ sessions: {report['best']}  controls: {controls}")
    print(f"selected (beats both controls): {report['selected']}")
    print(f"wrote {out / 'report.json'} and trades.csv")
    return 0


def absorb_verify(files: list[Path], out: Path, nq_report: Path, pv: float) -> int:
    """One look at ES: preregister the frozen NQ cell durably, then score it and its controls."""
    if not nq_report.exists():
        print(f"no NQ selection at {nq_report}; run --study absorb --product NQ first")
        return 1
    nq = json.loads(nq_report.read_text())
    if not nq.get("selected"):
        print("NQ selected no cell (none beat its controls); ES stays unread")
        return 1
    if nq["code_sha"] != code_sha():
        print("orderflow_backtest.py changed since the NQ selection; rerun NQ before reading ES")
        return 1
    frozen = replace(Params(**nq["selected_params"]), point_value=pv)
    out.mkdir(parents=True, exist_ok=True)
    prereg = dict(created_at=datetime.now(timezone.utc).isoformat(), frozen=asdict(frozen),
                  code_sha=nq["code_sha"], nq_report_sha=hashlib.sha256(nq_report.read_bytes()).hexdigest(),
                  pass_rule=PASS_RULE)
    try:  # exclusive create: the record exists before any ES print is loaded, and blocks a second look
        fd = os.open(out / "preregistered.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        print(f"{out / 'preregistered.json'} exists: ES was already read once; no second look")
        return 1
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(prereg, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    base = dict(level_tol=3.0, units="range", point_value=pv)
    push = replace(frozen, trigger="push")
    cells = [frozen, push, Params("touch", 0, **base)] + [Params("random", seed=s, **base) for s in range(20)]
    tr, sessions = run_study(files, cells)
    summ = lambda df: summarize(df, sessions, point_value=pv, usd_key="usd_per_contract")
    table = {p.name: {"all": summ(tr[tr["cell"] == p.name])} for p in cells if p.trigger != "random"}
    table["random (20 seeds pooled)"] = {"all": summ(tr[tr["cell"].str.startswith("random")])}
    res, mean = table[frozen.name]["all"], lambda name: table[name]["all"].get("mean_r", -np.inf)
    passed = bool(res.get("n", 0) >= 30 and res["mean_r"] > 0
                  and res["mean_r"] > mean(push.name) and res["mean_r"] > mean(cells[2].name))
    tr.drop(columns=["exit_ns"]).to_csv(out / "trades.csv", index=False)
    report = dict(product="ES", preregistered=prereg, sessions=[sessions[0], sessions[-1], len(sessions)],
                  costs=dict(commission_usd=COMMISSION_USD, point_value=pv, slippage_ticks=1),
                  passed=passed, cells=table)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print_table(table, ("all",))
    print(f"\nfrozen {frozen.name}: {'PASS' if passed else 'FAIL'} ({PASS_RULE})")
    print(f"wrote {out / 'report.json'} and trades.csv")
    return 0


def gex_cells() -> list[Params]:
    """GEX_RULE first, then its controls, then the two secondary variants."""
    base = dict(level_tol=3.0, units="range", gex_levels=True, regime="neg")
    return ([GEX_RULE, replace(GEX_RULE, trigger="push"), Params("touch", 0, **base)]
            + [Params("random", seed=s, **base) for s in range(20)]
            + [replace(GEX_RULE, regime="pos"), replace(GEX_RULE, gex_levels=False)])


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def durable_create(path: Path, payload: dict) -> bool:
    """Write JSON with exclusive create and fsync; False if the file already exists."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(payload, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return True


def test_window_artifacts(data: Path) -> list[Path]:
    """Any file (parquet, DBN, request, intent) whose name starts with a test-window date."""
    return [f for f in data.glob("*") if TEST_START <= f.name[:10] < TEST_END]


def robustness(r: np.ndarray, dates: pd.Series) -> dict:
    if not len(r):
        return {}
    top = np.sort(r)[::-1]
    k = max(1, int(np.ceil(0.05 * len(r))))
    q = pd.PeriodIndex(pd.to_datetime(dates), freq="Q").astype(str)
    return dict(median_r=round(float(np.median(r)), 3),
                mean_r_without_top2=round(float(top[2:].mean()), 3) if len(r) > 2 else None,
                top5pct_share_of_total_r=round(float(top[:k].sum() / r.sum()), 2) if r.sum() else None,
                by_quarter={k_: dict(n=int(len(v)), mean_r=round(float(v.mean()), 3))
                            for k_, v in pd.Series(r).groupby(q.to_numpy())})


def gex_main(args, out: Path) -> int:
    if args.smoke:  # research sessions only; counts, never R
        tr, sessions = run_study(research_files(args.data), gex_cells(), load_gex())
        counts = tr["cell"].value_counts() if len(tr) else pd.Series(dtype=int)
        print(f"\nsmoke on {len(sessions)} research sessions: trades per cell (R not shown)")
        for p in gex_cells():
            print(f"  {p.name:<45}{int(counts.get(p.name, 0)):>6}")
        return 0
    freeze = out / "freeze.json"
    if args.freeze:
        if test_window_artifacts(args.data):
            print("test-window prints already exist; the freeze must come before the data")
            return 1
        out.mkdir(parents=True, exist_ok=True)
        freeze.write_text(json.dumps(dict(
            created_at=datetime.now(timezone.utc).isoformat(), code_sha=code_sha(), prereg_sha=file_sha(PREREG_DOC),
            window=[TEST_START, TEST_END], rule=asdict(GEX_RULE), cells=[p.name for p in gex_cells()]), indent=2) + "\n")
        print(f"froze {GEX_RULE.name}: code {code_sha()[:12]}, doc {file_sha(PREREG_DOC)[:12]} -> {freeze}")
        return 0
    if not freeze.exists():
        print("no freeze record; run --study gex --freeze before buying the test prints")
        return 1
    fz = json.loads(freeze.read_text())
    if fz["code_sha"] != code_sha() or fz["prereg_sha"] != file_sha(PREREG_DOC):
        print("orderflow_backtest.py or ORDERFLOW_GEX_PREREG.md changed since the freeze; refusing")
        return 1
    files = test_files(args.data)
    if not files:
        print(f"no test prints {TEST_START}..{TEST_END} under {args.data}")
        return 1
    prereg = dict(created_at=datetime.now(timezone.utc).isoformat(), freeze=fz,
                  files=[f.name for f in files])
    if not durable_create(out / "preregistered.json", prereg):
        print(f"{out / 'preregistered.json'} exists: the test set was already read once; no second look")
        return 1

    cells = gex_cells()
    tr, sessions = run_study(files, cells, load_gex())
    summ = lambda df: summarize(df, sessions)
    table = {p.name: summ(tr[tr["cell"] == p.name]) for p in cells if p.trigger != "random"}
    table["random (20 seeds pooled)"] = summ(tr[tr["cell"].str.startswith("random")])
    rule, push, touch = (table[p.name] for p in cells[:3])
    beats = rule.get("n", 0) >= 30 and rule["mean_r"] > 0 and all(
        rule["mean_r"] > c.get("mean_r", -np.inf) for c in (push, touch))
    verdict = "PASS" if beats and rule["ci95"][0] > 0 else "WEAK" if beats else "FAIL"
    mine = tr[tr["cell"] == GEX_RULE.name] if len(tr) else tr
    rob = robustness(mine["r"].to_numpy(), mine["date"]) if len(mine) else {}
    tr.drop(columns=["exit_ns"]).to_csv(out / "trades.csv", index=False)
    (out / "report.json").write_text(json.dumps(dict(
        sessions=[sessions[0], sessions[-1], len(sessions)], verdict=verdict, rule=GEX_RULE.name,
        robustness=rob, cells=table, preregistered=prereg), indent=2))
    print_table({k: {"all": v} for k, v in table.items()}, ("all",))
    print(f"\n{GEX_RULE.name}: {verdict}\nrobustness: {json.dumps(rob)}")
    print(f"wrote {out / 'report.json'} and trades.csv")
    return 0


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", choices=("bubble", "absorb", "gex"), default="bubble")
    ap.add_argument("--product", choices=tuple(POINT_VALUES), default="NQ")
    ap.add_argument("--calibrate", action="store_true", help="NQ only: print REF_RANGE and effort percentiles")
    ap.add_argument("--smoke", action="store_true", help="gex: trade counts on research sessions only")
    ap.add_argument("--freeze", action="store_true", help="gex: record code/doc hashes before the test prints exist")
    ap.add_argument("--data", type=Path, help="default data/databento/<product>-trades/<PRODUCT>")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.data = args.data or HERE / "data" / "databento" / f"{args.product.lower()}-trades" / args.product
    if args.product != "NQ" and (args.study != "absorb" or args.calibrate):
        print("ES is the one-look test set: only the preregistered --study absorb run may read it")
        return 1
    if args.calibrate:
        calibrate(research_files(args.data))
        return 0
    if args.study == "gex":
        return gex_main(args, args.out / "gex_NQ")
    return absorb_main(args) if args.study == "absorb" else bubble_main(args)


if __name__ == "__main__":
    sys.exit(main())
