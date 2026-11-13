"""Overnight volume-profile node study: fade or break the POC / HVN / LVN of the prior day, week or month on ES and
NQ during Globex hours.

Question: is a profile node a better overnight entry price than a random price inside the same profile's range?
The prior-RTH-session tick version (profile_nodes_study.py) found no edge vs random levels; this one changes the
session (overnight), the profile horizon (day / week / month) and the data (1m bars 2011 -> 2026).

Data: Databento ES.v.0 / NQ.v.0 1m bars (`fut-ohlcv-1m-cont`), back-adjusted additively at each roll minute (rolls
  happen inside a Globex session at a single minute, so the jump is the calendar spread). Distances, R and costs do
  not depend on the additive offset.
Trading day D: Globex bars from (D-1) 18:00 ET. Weekdays with a normal RTH session (>= 200 RTH 1m bars, last RTH-hour
  bar after 13:00, not an NYSE ad-hoc closure). A day whose bars change contract before the flat is skipped.
Profiles (all complete before (D-1) 18:00 ET, so no look-ahead), built like the chart:
  d_full: previous trading day's full session (tdate == D'), d_rth: its 09:30-16:00 (13:00 half days),
  week: previous Mon-Fri trading-date week, month: previous calendar month.
  Volume per tick from 1m OHLCV with frontend/lib/volumeProfile.js computeVolumeProfile's body/wick split, then
  nodes with the profileNodesFromTicks port (80 rows, Gaussian 1.5, 10% prominence, <= 3 HVN).
Events (per level, levels snapped to the tick grid): armed from above when a whole 1m bar is >= A above it (below:
  <= A below); the first later bar trading a tick through it is the touch. Touches count only 18:30 -> 08:15 ET;
  a touch before 18:30 disarms. After a trade closes the level can re-arm. Each level trades on its own.
  fade  - limit at the level (fills at the level on the touch bar), direction back toward the armed side.
  break - stop one tick through (fills at max/min(open, stop price)), direction of the cross.
  Stop S = 0.5 x ADR20 (mean full-session range of the 20 prior trading days), >= 4 ticks, target 1 x S, both
  measured from the order price. A = 0.25 x ADR20.
Exits: open variant flat at the 09:25 ET bar's open; close variant flat at 15:55 (12:55 half days).
Fills / costs: research_loop eval engine.check_bar / entry_fill (stop first inside a bar, targets need a tick
  through, the entry bar's target only for at-open stop fills), costs.apply base and stress (MES / MNQ, $0.50/side).
Controls:
  random direction: the side-matched permutation twin of the research loop (each trade's opposite side run on its
    own bracket to the same flat), p from twins.twin_test.
  random levels: for each (day, profile, kind) the same number of uniform prices in the profile's [low, high],
    10 seeds, same rules; excess = real mean R - random mean R, one-sided session-bootstrap p.
Gate: see overnight_nodes_prereg.json (frozen before the first run).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from profile_nodes_study import profile_nodes  # noqa: E402
from research_loop.eval import config as C_ES  # noqa: E402
from research_loop.eval import costs as costs_es  # noqa: E402
from research_loop.eval import criteria as crit  # noqa: E402
from research_loop.eval.data import nyse_half_day  # noqa: E402
from research_loop.eval.engine import check_bar, entry_fill, snap  # noqa: E402
from research_loop.eval.twins import twin_test  # noqa: E402
from research_loop_nq.eval import costs as costs_nq  # noqa: E402

TZ = "America/New_York"
TICK = 0.25
BARS = HERE / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT = HERE / "data" / "overnight_nodes"
PREREG = HERE / "overnight_nodes_prereg.json"
COSTS = {"ES": costs_es, "NQ": costs_nq}

WINDOWS = ("d_full", "d_rth", "week", "month")
KINDS = ("poc", "hvn", "lvn")
SIDES = ("fade", "break")
EXITS = ("open", "close")
CELLS = [(w, k, s, e) for w in WINDOWS for k in KINDS for s in SIDES for e in EXITS]  # 48 per product

P = dict(arm_adr=0.25, stop_adr=0.5, rr=1.0, adr_n=20, min_stop_ticks=4,
         entry_start=18 * 60 + 30, entry_end=8 * 60 + 15, flat_open=9 * 60 + 25, flat_close=15 * 60 + 55,
         flat_close_half=12 * 60 + 55, n_rnd_seeds=10, min_week_days=2, min_month_days=10)
SPLITS = {"dev": (date(2011, 1, 1), date(2019, 1, 1)), "val1": (date(2019, 1, 1), date(2022, 1, 1)),
          "val2": (date(2022, 1, 1), date(2026, 8, 15))}
GAP_SESSIONS = 5
N_BOOT = 20000
SEED = 20261103


def cell_id(c) -> str:
    return "/".join(c)


# --- data --------------------------------------------------------------------------------------------------------

def load_bars(product: str, lo: date, hi: date) -> pd.DataFrame:
    """1m bars with tdate (Globex trading date), ET minute and back-adjusted prices, for tdates in [lo, hi)."""
    fs = []
    for f in sorted((BARS / product).glob("*.parquet")):
        a, b = f.name[:10], f.name[11:21]
        if date.fromisoformat(a) < hi + timedelta(days=2) and date.fromisoformat(b) > lo - timedelta(days=2):
            fs.append(f)
    raw = pd.concat([pd.read_parquet(f, columns=["instrument_id", "open", "high", "low", "close", "volume"])
                     for f in fs])
    raw = raw[~raw.index.duplicated()].sort_index()
    et = raw.index.tz_convert(TZ)
    df = pd.DataFrame({
        "t": raw.index.asi8 // 1_000_000_000,
        "mod": np.asarray(et.hour * 60 + et.minute, dtype=np.int32),
        "tdate": np.asarray((et + pd.Timedelta(hours=6)).date),
        "inst": raw["instrument_id"].to_numpy(),
        "o": raw["open"].to_numpy(float), "h": raw["high"].to_numpy(float),
        "l": raw["low"].to_numpy(float), "c": raw["close"].to_numpy(float),
        "v": raw["volume"].to_numpy(float),
    })
    df = df[(df.tdate >= lo) & (df.tdate < hi)].reset_index(drop=True)
    back_adjust(df)
    return df


def back_adjust(df: pd.DataFrame) -> None:
    """Additive back-adjustment in place: bars before each contract change shift by (new open - old close)."""
    inst = df["inst"].to_numpy()
    ch = np.flatnonzero(inst[1:] != inst[:-1]) + 1
    off = np.zeros(len(df))
    for i in ch:
        off[:i] += df["o"].iat[i] - df["c"].iat[i - 1]
    for k in ("o", "h", "l", "c"):
        df[k] = df[k].to_numpy() + off


def trading_days(df: pd.DataFrame) -> dict:
    """{tdate: (start, end, close_mod)} for tradeable weekdays; start/end index the tdate's bars in df."""
    td = df["tdate"].to_numpy()
    mod = df["mod"].to_numpy()
    u, s = np.unique(td, return_index=True)
    e = np.append(s[1:], len(td))
    out = {}
    for d, a, b in zip(u, s, e):
        if d.weekday() >= 5 or d in C_ES.NYSE_ADHOC_CLOSURES:
            continue
        m = mod[a:b]
        rth = (m >= 570) & (m < 960)
        if not rth.any() or m[rth].max() <= C_ES.CME_HOLIDAY_LAST_MOD:
            continue
        close_mod = C_ES.HALF_CLOSE if nyse_half_day(d) else C_ES.RTH_CLOSE
        if int(((m >= 570) & (m < close_mod)).sum()) < C_ES.MIN_RTH_BARS:
            continue
        out[d] = (int(a), int(b), close_mod)
    return out


# --- profile -------------------------------------------------------------------------------------------------------

def wilder_atr(h, l, c, n=14) -> np.ndarray:
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    a = 1.0 / n
    out = np.empty(len(h))
    out[0] = tr[0]
    if len(h) > 1:
        out[1:], _ = lfilter([a], [1, -(1 - a)], tr[1:], zi=[(1 - a) * tr[0]])
    return out


def tick_volume(o, h, l, c, v) -> tuple[np.ndarray, np.ndarray]:
    """(tick index, volume) per tick: computeVolumeProfile's OHLCV approximation, before row bucketing."""
    m = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (v > 0)
    o, h, l, c, v = o[m], h[m], l[m], c[m], v[m]
    if len(v) == 0:
        return np.zeros(0, np.int64), np.zeros(0)
    atr = wilder_atr(h, l, c)
    oi, hi, li, ci = (np.floor(x / TICK + 0.5).astype(np.int64) for x in (o, h, l, c))
    rng = hi - li
    segs_a, segs_b, segs_v = [], [], []

    def add(mask, a, b, vol):
        segs_a.append(a[mask]); segs_b.append(b[mask]); segs_v.append(vol[mask])

    single = rng <= 0
    extreme = ~single & (atr > 0) & (rng * TICK > 3.0 * atr)
    normal = ~single & ~extreme
    add(single, hi, hi, v)
    add(extreme, li, hi, v)
    blo, bhi = np.minimum(oi, ci), np.maximum(oi, ci)
    bt = bhi - blo
    with np.errstate(divide="ignore", invalid="ignore"):
        wick = np.where(rng > 0, (rng - bt) / np.maximum(rng, 1), 0)
    bw = np.clip(0.7 + (0.5 - wick) * 0.3, 0.5, 0.8)
    up, lo_ = hi - bhi, blo - li
    tw = up + lo_
    add(normal, blo, bhi, v * bw)                                  # body (doji: one tick)
    add(normal & (tw == 0), blo, bhi, v * (1 - bw))               # marubozu: wick share back on the body
    with np.errstate(divide="ignore", invalid="ignore"):
        add(normal & (up > 0), bhi + 1, hi, v * (1 - bw) * up / np.maximum(tw, 1))
        add(normal & (lo_ > 0), li, blo - 1, v * (1 - bw) * lo_ / np.maximum(tw, 1))
    a, b, w = np.concatenate(segs_a), np.concatenate(segs_b), np.concatenate(segs_v)
    base = int(a.min())
    n = int(b.max()) - base + 2
    diff = np.zeros(n)
    share = w / (b - a + 1)
    np.add.at(diff, a - base, share)
    np.add.at(diff, b - base + 1, -share)
    vol = np.cumsum(diff)[:-1]
    idx = np.arange(base, base + n - 1)
    keep = vol > 1e-12
    return idx[keep], vol[keep]


def window_levels(df: pd.DataFrame, a: int, b: int, mask: np.ndarray | None = None) -> dict | None:
    sl = slice(a, b)
    o, h, l, c, v = (df[k].to_numpy()[sl] for k in ("o", "h", "l", "c", "v"))
    if mask is not None:
        o, h, l, c, v = o[mask], h[mask], l[mask], c[mask], v[mask]
    if len(o) < 30:
        return None
    ti, tv = tick_volume(o, h, l, c, v)
    if len(ti) < 3:
        return None
    nd = profile_nodes(ti * TICK, tv)
    rnd = lambda x: round(x / TICK) * TICK  # noqa: E731
    return {"poc": [rnd(nd["poc"])], "hvn": [rnd(x) for x in nd["hvn"]], "lvn": [rnd(x) for x in nd["lvn"]],
            "lo": float(l.min()), "hi": float(h.max())}


def build_profiles(df: pd.DataFrame, days: dict, targets: list[date]) -> dict:
    """{(day, window): levels} for each trading day in targets."""
    td_list = sorted(days)
    pos = {d: i for i, d in enumerate(td_list)}
    mod = df["mod"].to_numpy()
    cache: dict = {}
    out = {}
    for d in targets:
        i = pos[d]
        if i == 0:
            continue
        dp = td_list[i - 1]
        a, b, cm = days[dp]
        out[(d, "d_full")] = cache.setdefault(("d", dp), window_levels(df, a, b))
        m = (mod[a:b] >= 570) & (mod[a:b] < cm)
        out[(d, "d_rth")] = cache.setdefault(("r", dp), window_levels(df, a, b, m))
        wk0 = d - timedelta(days=d.weekday() + 7)
        wds = [x for x in td_list if wk0 <= x < wk0 + timedelta(days=5)]
        if ("w", wk0) not in cache:
            cache[("w", wk0)] = (window_levels(df, days[wds[0]][0], days[wds[-1]][1])
                                 if len(wds) >= P["min_week_days"] else None)
        out[(d, "week")] = cache[("w", wk0)]
        m1 = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
        mds = [x for x in td_list if (x.year, x.month) == (m1.year, m1.month)]
        if ("m", m1) not in cache:
            cache[("m", m1)] = (window_levels(df, days[mds[0]][0], days[mds[-1]][1])
                                if len(mds) >= P["min_month_days"] else None)
        out[(d, "month")] = cache[("m", m1)]
    return out


# --- simulation ----------------------------------------------------------------------------------------------------

def run_exit(d, f, j, at_open, stop, target, o, h, l, fx) -> tuple[str, float, int]:
    """Exit of a position entered on bar j at f (engine semantics), or the flat at bar fx's open."""
    r = check_bar(f, h[j], l[j], d, stop, target, allow_target=at_open)
    if r is not None:
        return r[0], r[1], j
    a = j + 1
    if a < fx:
        oo, hh, ll = o[a:fx], h[a:fx], l[a:fx]
        if d > 0:
            hit = (oo <= stop) | (ll <= stop) | (hh >= target + TICK)
        else:
            hit = (oo >= stop) | (hh >= stop) | (ll <= target - TICK)
        k = np.flatnonzero(hit)
        if len(k):
            m = a + int(k[0])
            r = check_bar(o[m], h[m], l[m], d, stop, target, allow_target=True)
            return r[0], r[1], m
    if fx < len(o):
        return "flat", float(o[fx]), fx
    return "flat", float(o[-1] if len(o) else f), len(o) - 1  # no bar at the flat time (not expected)


def sim_level(L: float, day: dict, side: str, fx: int, A: float, S: float, rr: float) -> list[dict]:
    """All trades one level produces on one night for one side rule and one flat index."""
    o, h, l, mod = day["o"], day["h"], day["l"], day["mod"]
    e0, e1 = day["e0"], day["e1"]
    arm_a, arm_b = l >= L + A, h <= L - A
    arm = arm_a | arm_b
    tch_a, tch_b = l <= L - TICK, h >= L + TICK
    out = []
    i = 0
    while i < e1:
        ks = np.flatnonzero(arm[i:e1])
        if not len(ks):
            break
        k = i + int(ks[0])
        above = bool(arm_a[k])
        tj = np.flatnonzero((tch_a if above else tch_b)[k + 1:e1])
        if not len(tj):
            break
        j = k + 1 + int(tj[0])
        if j < e0:
            i = j + 1
            continue
        if side == "fade":
            d, typ, px = (1 if above else -1), "limit", L
        else:
            d, typ = (-1 if above else 1), "stop"
            px = L - TICK if above else L + TICK
        f = entry_fill(o[j], h[j], l[j], d, typ, px)
        assert f is not None
        at_open = typ == "stop" and f == o[j]
        stop = px - d * S
        target = px + d * rr * S
        kind, xp, x = run_exit(d, f, j, at_open, stop, target, o, h, l, fx)
        risk = max(abs(f - stop), TICK)
        # opposite side on its own bracket from the same fill (random-direction twin)
        tstop, ttgt = f + d * risk, f - d * abs(target - f)
        tk, txp, tx = run_exit(-d, f, j, at_open, tstop, ttgt, o, h, l, fx)
        out.append({"side": d, "entry_kind": typ, "entry_ref": float(f), "risk_pts": float(risk),
                    "entry_mod": int(mod[j]), "exit_kind": kind, "exit_ref": float(xp), "exit_mod": int(mod[x]),
                    "o_exit_kind": tk, "o_exit_ref": float(txp), "o_exit_mod": int(mod[tx]), "level": L})
        if kind == "flat":
            break
        i = x + 1
    return out


def sim_day(task: dict) -> list[dict]:
    """Every (cell, real/random seed) trade of one trading day."""
    day = task["day"]
    S, A, rr = task["S"], task["A"], task["rr"]
    out = []
    for (w, kind, seed), levels in task["levels"].items():
        for L in levels:
            for side in SIDES:
                for ex in EXITS:
                    fx = day["fx_open"] if ex == "open" else day["fx_close"]
                    for t in sim_level(L, day, side, fx, A, S, rr):
                        out.append({**t, "cell": cell_id((w, kind, side, ex)), "seed": seed, "day": task["date"]})
    return out


def sim_chunk(tasks: list[dict]) -> list[dict]:
    out = []
    for t in tasks:
        out.extend(sim_day(t))
    return out


def et_ts(d: date, mod: int) -> int:
    """UTC epoch seconds of ET wall-clock minute `mod` on date d (DST-aware)."""
    return int(pd.Timestamp(f"{d.isoformat()} {mod // 60:02d}:{mod % 60:02d}", tz=TZ).value // 1_000_000_000)


def day_tasks(product: str, lo: date, hi: date, stop_adr: float, windows=WINDOWS, with_random=True) -> tuple[list, list]:
    """(tasks, trade-day list) for trading days in [lo, hi). The first GAP_SESSIONS days of a val split are skipped."""
    df = load_bars(product, lo - timedelta(days=75), hi)
    days = trading_days(df)
    td_list = sorted(days)
    targets = [d for d in td_list if lo <= d < hi]
    if lo != SPLITS["dev"][0]:
        targets = targets[GAP_SESSIONS:]
    prof = build_profiles(df, days, targets)
    pos = {d: i for i, d in enumerate(td_list)}
    rngs = np.array([df["h"].to_numpy()[a:b].max() - df["l"].to_numpy()[a:b].min() for a, b, _ in
                     (days[d] for d in td_list)])
    t_all, mod_all, inst = df["t"].to_numpy(), df["mod"].to_numpy(), df["inst"].to_numpy()
    tasks, used = [], []
    for d in targets:
        i = pos[d]
        if i < P["adr_n"]:
            continue
        a, b, cm = days[d]
        m = mod_all[a:b]
        tt = t_all[a:b]
        prev = d - timedelta(days=1)
        t_e0, t_e1 = et_ts(prev, P["entry_start"]), et_ts(d, P["entry_end"])
        t_fo = et_ts(d, P["flat_open"])
        t_fc = et_ts(d, P["flat_close_half"] if cm == C_ES.HALF_CLOSE else P["flat_close"])
        fc = int(np.searchsorted(tt, t_fc))
        if fc >= len(tt) or len(np.unique(inst[a:a + fc + 1])) != 1:
            continue  # roll inside the trading window, or no bar at the flat
        adr = float(rngs[i - P["adr_n"]:i].mean())
        S = max(snap(stop_adr * adr, up=True), P["min_stop_ticks"] * TICK)
        A = snap(P["arm_adr"] * adr, up=True)
        day = {"o": df["o"].to_numpy()[a:a + fc + 1], "h": df["h"].to_numpy()[a:a + fc + 1],
               "l": df["l"].to_numpy()[a:a + fc + 1], "mod": m[:fc + 1],
               "e0": int(np.searchsorted(tt, t_e0)), "e1": int(np.searchsorted(tt, t_e1)),
               "fx_open": int(np.searchsorted(tt, t_fo)), "fx_close": fc}
        levels = {}
        for wi, w in enumerate(windows):
            pr = prof.get((d, w))
            if pr is None:
                continue
            for ki, kind in enumerate(KINDS):
                lv = pr[kind]
                levels[(w, kind, -1)] = lv
                if with_random and lv:
                    for s in range(P["n_rnd_seeds"]):
                        g = np.random.default_rng([SEED, d.toordinal(), wi, ki, s])
                        levels[(w, kind, s)] = [round(x / TICK) * TICK for x in g.uniform(pr["lo"], pr["hi"], len(lv))]
        tasks.append({"date": d.isoformat(), "day": day, "S": S, "A": A, "rr": P["rr"], "levels": levels})
        used.append(d.isoformat())
    return tasks, used


def simulate(product: str, split: str, stop_adr: float = P["stop_adr"], with_random=True, workers=8) -> tuple[pd.DataFrame, list]:
    lo, hi = SPLITS[split]
    tasks, used = day_tasks(product, lo, hi, stop_adr, with_random=with_random)
    chunks = [tasks[i:i + 40] for i in range(0, len(tasks), 40)]
    rows = []
    with ProcessPoolExecutor(workers) as ex:
        for r in ex.map(sim_chunk, chunks):
            rows.extend(r)
    return pd.DataFrame(rows), used


# --- statistics -----------------------------------------------------------------------------------------------------

def net_r(product: str, tr: pd.DataFrame, scenario="base", opposite=False) -> tuple[np.ndarray, np.ndarray]:
    if len(tr) == 0:
        return np.zeros(0), np.zeros(0)
    recs = tr.to_dict("records")
    if opposite:
        recs = [{**t, "side": -t["side"], "exit_kind": t["o_exit_kind"], "exit_ref": t["o_exit_ref"],
                 "exit_mod": t["o_exit_mod"]} for t in recs]
    res = COSTS[product].apply(recs, scenario)
    return res["r"], res["usd"]


def excess_p(real: pd.DataFrame, rnd: pd.DataFrame, r_real, r_rnd, days: list[str], n=N_BOOT, seed=SEED) -> dict:
    """Real minus random-level mean R, one-sided p from a whole-session bootstrap (both resampled together)."""
    pos = {d: i for i, d in enumerate(days)}
    nd = len(days)
    def agg(df, r):
        ii = np.array([pos[x] for x in df["day"]], dtype=int) if len(df) else np.zeros(0, int)
        return np.bincount(ii, weights=r, minlength=nd), np.bincount(ii, minlength=nd).astype(float)
    rs, rc = agg(real, r_real)
    qs, qc = agg(rnd, r_rnd)
    if rc.sum() == 0 or qc.sum() == 0:
        return {"excess": float("nan"), "p": 1.0, "ci": [float("nan")] * 2, "rnd_mean": float("nan")}
    ex = rs.sum() / rc.sum() - qs.sum() / qc.sum()
    rng = np.random.default_rng(seed)
    le, diffs = 0, []
    for start in range(0, n, 1000):
        k = min(1000, n - start)
        idx = rng.integers(0, nd, size=(k, nd))
        a = rs[idx].sum(1) / np.maximum(rc[idx].sum(1), 1)
        b = qs[idx].sum(1) / np.maximum(qc[idx].sum(1), 1)
        dd = a - b
        le += int((dd <= 0).sum())
        diffs.append(dd)
    diffs = np.concatenate(diffs)
    return {"excess": float(ex), "p": (1 + le) / (1 + n), "ci": [float(np.percentile(diffs, 2.5)),
            float(np.percentile(diffs, 97.5))], "rnd_mean": float(qs.sum() / qc.sum())}


def evaluate_cell(product: str, trades: pd.DataFrame, cell: str, days: list[str], n_trials: int) -> dict:
    real = trades[(trades.cell == cell) & (trades.seed == -1)].sort_values(["day", "entry_mod"], kind="stable")
    rnd = trades[(trades.cell == cell) & (trades.seed >= 0)]
    r, usd = net_r(product, real)
    r_st, _ = net_r(product, real, "stress")
    r_op, _ = net_r(product, real, opposite=True)
    sides = real["side"].to_numpy() if len(real) else np.zeros(0)
    r_long = np.where(sides > 0, r, r_op)
    r_short = np.where(sides > 0, r_op, r)
    tw = twin_test(r, r_long, r_short, sides)
    dd = real["day"].to_numpy().astype(str)
    m = crit.summarize(r, usd, r_st, dd, days, tw, n_trials) if len(real) else {"trades": 0, "twin": tw}
    rr_, _ = net_r(product, rnd)
    m["random_levels"] = excess_p(real, rnd, r, rr_, days)
    if len(real):
        gross = (real["side"] * (real["exit_ref"] - real["entry_ref"])).to_numpy() / real["risk_pts"].to_numpy()
        m["mean_r_gross"] = float(gross.mean())
        m["cost_r"] = float(gross.mean() - r.mean())
        m["exit_mix"] = real["exit_kind"].value_counts(normalize=True).round(3).to_dict()
        m["median_risk_pts"] = float(real["risk_pts"].median())
    return m


def gate(m: dict, split: str, alpha: float) -> list[str]:
    c = PREREG_CRITERIA["dev" if split == "dev" else "val"]
    f = []
    if m["trades"] < c["min_trades"]:
        return [f"trades {m['trades']} < {c['min_trades']}"]
    if not m["twin"]["p"] < alpha:
        f.append(f"dir-twin p {m['twin']['p']:.4f}")
    if not m["random_levels"]["p"] < alpha:
        f.append(f"rnd-level p {m['random_levels']['p']:.4f}")
    if not m["mean_r_base"] > 0:
        f.append(f"mean R {m['mean_r_base']:+.3f}")
    if not m["ci_base"][0] > 0:
        f.append(f"CI low {m['ci_base'][0]:+.3f}")
    if not m["mean_r_stress"] > 0:
        f.append(f"stress {m['mean_r_stress']:+.3f}")
    if not m["max_year_share"] <= c["max_year_share"]:
        f.append(f"year share {m['max_year_share']:.2f}")
    if not m["ex_top5_mean"] > 0:
        f.append("ex-top5 <= 0")
    if sum(1 for x in m["folds"] if x > 0) < c["min_folds_positive"]:
        f.append("folds")
    return f


PREREG_CRITERIA = {
    "dev": {"min_trades": 200, "alpha": 0.05 / len(CELLS), "max_year_share": 0.40, "min_folds_positive": 2},
    "val": {"min_trades": 100, "alpha": 0.05, "max_year_share": 0.40, "min_folds_positive": 2},
}


# --- prereg guard ---------------------------------------------------------------------------------------------------

def file_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def check_prereg() -> dict:
    pr = json.loads(PREREG.read_text())
    if pr["study_sha256"] != file_sha():
        raise SystemExit("overnight_nodes_study.py changed after preregistration; refusing to run")
    return pr


def write_prereg() -> None:
    if PREREG.exists():
        raise SystemExit(f"{PREREG.name} exists; preregistration is one-shot")
    PREREG.write_text(json.dumps({
        "frozen": date.today().isoformat(), "study_sha256": file_sha(), "params": P, "cells": [cell_id(c) for c in CELLS],
        "splits": {k: [a.isoformat(), b.isoformat()] for k, (a, b) in SPLITS.items()}, "criteria": PREREG_CRITERIA,
        "rules": [
            "dev: a cell passes only if it passes every dev criterion on BOTH ES and NQ, with dir-twin p and "
            "random-level p < 0.05/48, and the neighbour stops (0.4, 0.6 x ADR20) have mean net R > 0 on both",
            "val1 and val2 are run only for cells that passed dev; a shortlist needs every val criterion on both "
            "products in both windows (p < 0.05)",
            "no parameter is changed after the first dev run; the holdout (after 2026-08-14) is not on disk",
        ],
    }, indent=1))


# --- main -----------------------------------------------------------------------------------------------------------

def run_split(split: str, cells: list[str] | None = None) -> dict:
    pr = check_prereg()
    OUT.mkdir(parents=True, exist_ok=True)
    if split != "dev":
        devf = OUT / "dev_results.json"
        if not devf.exists():
            raise SystemExit("run dev first")
        passed = json.loads(devf.read_text())["passed"]
        cells = [c for c in (cells or passed) if c in passed]
        if not cells:
            raise SystemExit("no cell passed dev; validation stays unopened")
        if (OUT / f"{split}_results.json").exists():
            raise SystemExit(f"{split} already run (one look)")
    cells = cells or [cell_id(c) for c in CELLS]
    alpha = PREREG_CRITERIA["dev" if split == "dev" else "val"]["alpha"]
    res = {"split": split, "prereg_sha": pr["study_sha256"], "products": {}}
    for product in ("ES", "NQ"):
        trades, days = simulate(product, split)
        trades.to_parquet(OUT / f"{split}_{product}_trades.parquet")
        out = {}
        for c in cells:
            m = evaluate_cell(product, trades, c, days, n_trials=len(CELLS) * 2)
            m["fails"] = gate(m, split, alpha)
            out[c] = m
            print(f"{split} {product} {c:28s} n={m['trades']:5d} R={m.get('mean_r_base', float('nan')):+.3f} "
                  f"gross={m.get('mean_r_gross', float('nan')):+.3f} twin p={m['twin']['p']:.3f} "
                  f"rnd ex={m['random_levels']['excess']:+.3f} p={m['random_levels']['p']:.3f} "
                  f"{'PASS' if not m['fails'] else ';'.join(m['fails'][:3])}", flush=True)
        res["products"][product] = {"sessions": len(days), "cells": out}
    both = [c for c in cells if all(not res["products"][p]["cells"][c]["fails"] for p in ("ES", "NQ"))]
    if split == "dev" and both:
        res["neighbours"] = {}
        for sa in (0.4, 0.6):
            for product in ("ES", "NQ"):
                tr, days = simulate(product, split, stop_adr=sa, with_random=False)
                for c in both:
                    r, _ = net_r(product, tr[(tr.cell == c) & (tr.seed == -1)])
                    res["neighbours"][f"{product}/{sa}/{c}"] = float(r.mean()) if len(r) else float("nan")
        both = [c for c in both if all(res["neighbours"][f"{p}/{sa}/{c}"] > 0 for p in ("ES", "NQ") for sa in (0.4, 0.6))]
    res["passed"] = both
    (OUT / f"{split}_results.json").write_text(json.dumps(res, indent=1, default=float))
    print(f"{split}: passed {both}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg", action="store_true")
    ap.add_argument("--split", choices=list(SPLITS))
    a = ap.parse_args()
    if a.prereg:
        write_prereg()
    elif a.split:
        run_split(a.split)


if __name__ == "__main__":
    main()
