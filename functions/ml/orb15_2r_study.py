"""15-minute opening-range breakout, close confirmation, stop at the far side of the range, 2R target,
with a high-impact news blackout. A frozen one-rule test on NQ and ES proxies, scored for LucidFlex 50K.

Idea (Sunny, 2026-10-25): wait for price to close above the 15-minute opening range, buy, stop at the very
bottom of the range, target 2R (mirror for shorts); no trading during or before high-impact news.

Rules (written down before any number was computed; nothing below is tuned):
  - data: Databento XNAS.ITCH ohlcv-1m QQQ / SPY via open_ema_trail_study.load_bars (RTH 09:30-15:59 ET,
    sessions with >= 380 bars, QQQ x 41.2 -> NQ, SPY x 10.05 -> ES, tick 0.25, 1 MNQ $2/pt, 1 MES $5/pt).
    Window 2022-01-03 .. 2026-08-14 (last research session; the sealed verify block is never loaded).
  - opening range (OR): high / low of the 09:30-09:44 1m bars; all 15 must exist.
  - confirmation: candles of CONF minutes anchored at 09:30 (primary CONF = 5: 09:45, 09:50, ...). The first
    candle from 09:45 whose close is > OR high -> long, < OR low -> short. One trade a session, no re-entry.
    Entry at the open of the next 1m bar + 1 tick adverse; no entry at or after 15:00 ET.
  - stop: long at OR low, short at OR high. R = |entry - stop|. Target = entry + 2R.
  - exits on 1m bars from the entry bar: open through the stop (after the entry bar) -> open - 1 tick;
    low through the stop -> stop - 1 tick; high a tick through the target -> target (stop first when one
    bar touches both). Otherwise flat at the 15:59 close - 1 tick.
  - costs: the slippage above plus $0.50 per contract per side.
  - news (econ_calendar high impact: CPI, NFP, FOMC + presser + minutes, PPI, retail sales, PCE, GDP
    advance, ISM mfg / services):
      none       no filter (reference)
      blackout   (PRIMARY) no entry with its entry minute in [event - 30, event + 15]; a candle confirming
                 there is skipped and the scan continues with the next candle. An open trade is flattened at
                 the close of the last 1m bar ending <= event - 5 min.
      skip_day   no trade on any session with a high-impact event (08:30 releases included)
  - sensitivity (reported, never selected): CONF in {1, 15} with the primary news rule.
  - controls: random direction (2,000 seeds) on the same entries with the same R and 2R target in the
    other direction; p = (1 + #seeds with mean net R >= the rule's) / 2,001.
  - Lucid: LucidFlex 50K (no DLL, $90.20 fee) replayed by flybrain.prop.simulate_account on iid session draws
    (every session, no-trade days included), micros = floor(risk / (R x $/pt)) capped at 40, trade skipped
    when that is 0. Risk $780 (2 net 2R wins clear the $3,000 target, per lucid_structure's sizing rule)
    and $520 (3 wins). EV compared with the random-direction twin (10 seeds) on the same days and sizing.
  - verdict (primary: CONF 5, blackout, NQ+ES day-pooled, full window): PASS if pooled mean net R > 0 with
    its 95% 5-session block-bootstrap CI above 0, mean > 0 on both symbols and in both 2022-2024 and
    2025-2026, and random-direction p < 0.05. WEAK if pooled mean > 0 but a condition fails. FAIL otherwise.

Prior data use: 2022-2024 was the discovery side of several ORB studies; QQQ 2025-03 -> 2026-08 was the
holdout of lucid_orb_study (5m ORB, 1:1, %-stop: STRUCTURE-ONLY) and SPY's same window was scored by the
write-up 15m ORB. This rule (close confirmation, range stop, 2R, news blackout) was never run, and it has
no fitted parameter, but neither window is pristine for opening-range ideas.

    python orb15_2r_study.py           # one run, writes data/orb15_2r/results.json and run.lock
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from open_ema_trail_study import ET, block_ci, high_impact_events, load_bars, max_dd  # noqa: E402

OUT = HERE / "data" / "orb15_2r"
WINDOW = (date(2022, 1, 3), date(2026, 8, 14))
SPLIT = date(2025, 1, 1)
PRODUCTS = ("NQ", "ES")
PT_USD = {"NQ": 2.0, "ES": 5.0}
TICK = 0.25
COMM_SIDE = 0.50
OPEN_M, OR_END_M, LAST_ENTRY_M, CLOSE_M = 570, 585, 900, 960
RR = 2.0
PRE_NEWS, POST_NEWS, FLAT_BEFORE = 30, 15, 5
CONF_PRIMARY, CONF_SENS = 5, (1, 15)
NEWS_MODES = ("none", "blackout", "skip_day")
RISKS = (780, 520)
MAX_MICROS = 40
N_RANDOM = 2000
TWIN_SEEDS = 10
SEED = 20261025


@dataclass
class Day:
    d: date
    m: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    orh: float
    orl: float


def build_days(bars) -> list[Day]:
    et = bars.index.tz_convert(ET)
    minute = np.asarray(et.hour * 60 + et.minute)
    day = np.asarray(et.date)
    out = []
    for d in sorted(set(day)):
        if not (WINDOW[0] <= d <= WINDOW[1]):
            continue
        k = day == d
        m = minute[k]
        orb = (m >= OPEN_M) & (m < OR_END_M)
        if orb.sum() != OR_END_M - OPEN_M:
            continue
        g = bars[k]
        H, L = g.high.to_numpy(float), g.low.to_numpy(float)
        out.append(Day(d, m, g.open.to_numpy(float), H, L, g.close.to_numpy(float),
                       float(H[orb].max()), float(L[orb].min())))
    return out


# ---------------------------------------------------------------- rule

def find_entry(day: Day, conf: int, blocked) -> tuple[int, int] | None:
    """(entry bar index, direction) of the first confirming candle whose entry is allowed, else None."""
    m = day.m
    cid = (m - OPEN_M) // conf
    for i in range(len(m) - 1):
        if m[i] < OR_END_M or cid[i + 1] == cid[i]:
            continue  # not the last bar of a post-range candle
        c = day.C[i]
        s = 1 if c > day.orh else -1 if c < day.orl else 0
        if not s:
            continue
        j = i + 1
        if m[j] >= LAST_ENTRY_M:
            return None
        if blocked(m[j]):
            continue
        return j, s
    return None


def trade(day: Day, j: int, s: int, R: float | None, last: int) -> dict:
    """One bracket from bar j's open. R None -> stop at the far side of the range. Short = mirrored long."""
    if s > 0:
        O, H, L, C, far = day.O, day.H, day.L, day.C, day.orl
    else:
        O, H, L, C, far = -day.O, -day.L, -day.H, -day.C, -day.orh
    entry = O[j] + TICK
    if R is None:
        R = entry - far
    if R < TICK:
        return dict(ok=False)
    stop, target = entry - R, entry + RR * R
    mae = mfe = 0.0
    for i in range(j, last + 1):
        if i > j and O[i] <= stop:
            px, why = O[i] - TICK, "stop"
        elif L[i] <= stop:
            px, why = stop - TICK, "stop"
        elif H[i] >= target + TICK:
            px, why = target, "target"
        else:
            mae, mfe = min(mae, L[i] - entry), max(mfe, H[i] - entry)
            continue
        return dict(ok=True, pts=px - entry, R=R, why=why, mae=min(mae, px - entry), mfe=max(mfe, px - entry),
                    held=i - j + 1)
    px = C[last] - TICK
    return dict(ok=True, pts=px - entry, R=R, why="time", mae=min(mae, px - entry), mfe=max(mfe, px - entry),
                held=last - j + 1)


def run_day(day: Day, conf: int, mode: str, events: list) -> dict | None:
    """The rule's trade and the opposite-direction twin (same entry and R), or None for no trade."""
    if mode == "skip_day" and events:
        return None
    ev = sorted(e for e in events if OPEN_M <= e < CLOSE_M) if mode == "blackout" else []
    blocked = (lambda mm: any(e - PRE_NEWS <= mm <= e + POST_NEWS for e in ev)) if ev else (lambda mm: False)
    hit = find_entry(day, conf, blocked)
    if hit is None:
        return None
    j, s = hit
    last = len(day.m) - 1
    nxt = next((e for e in ev if e > day.m[j]), None)
    reason_flat = "time"
    if nxt is not None:
        keep = np.nonzero(day.m + 1 <= nxt - FLAT_BEFORE)[0]
        if len(keep) and keep[-1] >= j:
            last, reason_flat = int(keep[-1]), "news"
    t = trade(day, j, s, None, last)
    if not t["ok"]:
        return None
    if t["why"] == "time":
        t["why"] = reason_flat
    t["twin"] = trade(day, j, -s, t["R"], last)
    t.update(dir=s, entry_m=int(day.m[j]))
    return t


# ---------------------------------------------------------------- scoring

def net_r(t: dict, pt: float) -> float:
    """Net R for 1 micro: costs scale with contracts, so 1 contract is the conservative case."""
    return (t["pts"] * pt - 2 * COMM_SIDE) / (t["R"] * pt)


def summarize(rows: list[dict | None], pt: float, rng) -> dict:
    tr = [r for r in rows if r]
    if not tr:
        return dict(trades=0)
    nr = np.array([net_r(t, pt) for t in tr])
    usd = np.array([t["pts"] * pt - 2 * COMM_SIDE for t in tr])
    twin = np.array([net_r(t["twin"], pt) for t in tr])
    lo, hi = block_ci(nr, rng)
    coins = rng.integers(0, 2, size=(N_RANDOM, len(tr))).astype(bool)
    rand = np.where(coins, nr, twin).mean(axis=1)
    wins, losses = usd[usd > 0].sum(), -usd[usd < 0].sum()
    why = {k: float(np.mean([t["why"] == k for t in tr])) for k in ("target", "stop", "time", "news")}
    return dict(trades=len(tr), sessions=len(rows), trade_rate=len(tr) / len(rows), long_share=float(np.mean([t["dir"] > 0 for t in tr])),
                mean_net_R=float(nr.mean()), ci95=[lo, hi], win_rate=float((nr > 0).mean()),
                profit_factor=float(wins / losses) if losses else math.inf, exits=why,
                median_R_pts=float(np.median([t["R"] for t in tr])), median_entry_m=float(np.median([t["entry_m"] for t in tr])),
                total_usd_1ct=float(usd.sum()), max_dd_usd_1ct=max_dd(usd),
                random_p=float((1 + (rand >= nr.mean()).sum()) / (N_RANDOM + 1)), random_mean=float(rand.mean()),
                reversed_mean_R=float(twin.mean()), _nr=nr)


def pooled(by_prod: dict, days_by: dict, rng) -> dict:
    """Day-pooled NQ+ES: average the two symbols' net R on days both traded, else the one that did."""
    acc: dict = {}
    for p in PRODUCTS:
        for day, r in zip(days_by[p], by_prod[p]):
            if r:
                acc.setdefault(day.d, []).append(net_r(r, PT_USD[p]))
    x = np.array([np.mean(acc[d]) for d in sorted(acc)])
    lo, hi = block_ci(x, rng)
    return dict(days=len(x), mean_net_R=float(x.mean()), ci95=[lo, hi])


def lucid_days(rows: list[dict | None], pt: float, risk: float, twin_seed: int | None = None) -> dict:
    rng = np.random.default_rng(twin_seed) if twin_seed is not None else None
    pnl, lo, hi, nt = [], [], [], []
    for r in rows:
        t = r
        if r and rng is not None and rng.random() < 0.5:
            t = r["twin"]
        if not t or not t.get("ok"):
            pnl.append(0.0); lo.append(0.0); hi.append(0.0); nt.append(0)
            continue
        n = int(min(MAX_MICROS, math.floor(risk / (t["R"] * pt))))
        if n < 1:
            pnl.append(0.0); lo.append(0.0); hi.append(0.0); nt.append(0)
            continue
        c = 2 * COMM_SIDE * n
        pnl.append(t["pts"] * pt * n - c)
        lo.append(min(0.0, t["mae"] * pt * n - c / 2, pnl[-1]))
        hi.append(max(0.0, t["mfe"] * pt * n, pnl[-1]))
        nt.append(1)
    return dict(pnl=np.array(pnl), lo=np.array(lo), hi=np.array(hi), trades=np.array(nt))


def lucid_ev(d: dict, paths: int = 20000, seed: int = 1) -> dict:
    from lucid_structure import FLEX50_FEE, replay
    from flybrain.prop import resolve_plan
    takes, used, paid, passed, _ = replay(d, resolve_plan("flex", "50k", True), paths, seed=seed)
    ev = takes.mean() - FLEX50_FEE
    se = takes.std(ddof=1) / math.sqrt(len(takes))
    return dict(ev=float(ev), ev_lo=float(ev - 1.96 * se), ev_hi=float(ev + 1.96 * se), pass_rate=float(passed.mean()),
                paid=float(paid.mean()), days_used=float(used.mean()), trade_days=float(d["trades"].mean()))


def verdict(pool: dict, per: dict, halves: dict) -> str:
    if pool["mean_net_R"] <= 0:
        return "FAIL"
    ok = (pool["ci95"][0] > 0 and all(per[p]["mean_net_R"] > 0 and per[p]["random_p"] < 0.05 for p in PRODUCTS)
          and all(h["mean_net_R"] > 0 for h in halves.values()))
    return "PASS" if ok else "WEAK"


def strip(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ---------------------------------------------------------------- 2011-2021 CME confirmation
#
# Rules written 2026-10-25 BEFORE any 2011-2021 futures bar was downloaded (Sunny approved buying them after
# the 2022-2026 PASS above). One look (--confirm writes confirm.lock just before the first trade is simulated).
#   - data: Databento GLBX.MDP3 ohlcv-1m, continuous front month by volume (NQ.v.0 / ES.v.0;
#     data/databento/fut-ohlcv-1m-cont), native index points, no ETF ratios. Sessions 2011-01-03 -> 2021-12-31,
#     RTH 09:30-15:59 ET, >= 380 RTH bars, one contract all session (roll days with mixed contracts skipped).
#     Every month must be present or the run refuses before the lock.
#   - rule, costs, sizing, controls, Lucid replay, variants and verdict: exactly as above, with the halves
#     2011-2015 and 2016-2021. Traded as micros ($2 / $5 per point, $1 RT) as if they had existed.
#   - news: econ_calendar.py starts in 2022, so this file carries the pre-2022 HIGH-impact events that land
#     in RTH, which are the only ones the primary blackout can act on (08:30 releases end their window at
#     08:45, before the opening range):
#       FOMC statement (federalreserve.gov/monetarypolicy/fomchistorical<year>.htm, 2021 from
#       fomccalendars.htm): 14:15 ET in 2011-2012 except 12:30 on press-conference days; 14:00 from 2013.
#       Press conference: 14:15 in 2011-2012, 14:30 from 2013. 2020-03-03 emergency cut: 10:00, presser 11:00.
#       Minutes: 14:00. ISM manufacturing / services: 10:00 on the 1st / 3rd business day (the same unverified
#       rule econ_calendar uses). Sessions were not public-holiday checked beyond econ_calendar's holidays.
#     skip_day needs the 08:30 releases (CPI, NFP, PPI, ...), which are not compiled for 2011-2021, so it is
#     NOT run in the confirmation.

CONF_WINDOW = (date(2011, 1, 3), date(2021, 12, 31))
CONF_SPLIT = date(2016, 1, 1)
FUT_BARS = HERE / "data" / "databento" / "fut-ohlcv-1m-cont"
MIN_PRICE = {"NQ": 1000.0, "ES": 500.0}  # native points; lower means ETF prices slipped in


def _days(s: str) -> list[date]:
    return [date.fromisoformat(x) for x in s.split()]


FOMC_DECISION = _days("""
2011-01-26 2011-03-15 2011-04-27 2011-06-22 2011-08-09 2011-09-21 2011-11-02 2011-12-13
2012-01-25 2012-03-13 2012-04-25 2012-06-20 2012-08-01 2012-09-13 2012-10-24 2012-12-12
2013-01-30 2013-03-20 2013-05-01 2013-06-19 2013-07-31 2013-09-18 2013-10-30 2013-12-18
2014-01-29 2014-03-19 2014-04-30 2014-06-18 2014-07-30 2014-09-17 2014-10-29 2014-12-17
2015-01-28 2015-03-18 2015-04-29 2015-06-17 2015-07-29 2015-09-17 2015-10-28 2015-12-16
2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16 2021-01-27
2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
""")
FOMC_PRESSER = _days("""
2011-04-27 2011-06-22 2011-11-02 2012-01-25 2012-04-25 2012-06-20 2012-09-13 2012-12-12
2013-03-20 2013-06-19 2013-09-18 2013-12-18 2014-03-19 2014-06-18 2014-09-17 2014-12-17
2015-03-18 2015-06-17 2015-09-17 2015-12-16 2016-03-16 2016-06-15 2016-09-21 2016-12-14
2017-03-15 2017-06-14 2017-09-20 2017-12-13 2018-03-21 2018-06-13 2018-09-26 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16 2021-01-27
2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
""")
FOMC_MINUTES = _days("""
2011-02-16 2011-04-05 2011-05-18 2011-07-12 2011-08-30 2011-10-12 2011-11-22 2012-01-03
2012-02-15 2012-04-03 2012-05-16 2012-07-11 2012-08-22 2012-10-04 2012-11-14 2013-01-03
2013-02-20 2013-04-10 2013-05-22 2013-07-10 2013-08-21 2013-10-09 2013-11-20 2014-01-08
2014-02-19 2014-04-09 2014-05-21 2014-07-09 2014-08-20 2014-10-08 2014-11-19 2015-01-07
2015-02-18 2015-04-08 2015-05-20 2015-07-08 2015-08-19 2015-10-08 2015-11-18 2016-01-06
2016-02-17 2016-04-06 2016-05-18 2016-07-06 2016-08-17 2016-10-12 2016-11-23 2017-01-04
2017-02-22 2017-04-05 2017-05-24 2017-07-05 2017-08-16 2017-10-11 2017-11-22 2018-01-03
2018-02-21 2018-04-11 2018-05-23 2018-07-05 2018-08-22 2018-10-17 2018-11-29 2019-01-09
2019-02-20 2019-04-10 2019-05-22 2019-07-10 2019-08-21 2019-10-09 2019-11-20 2020-01-03
2020-02-19 2020-04-08 2020-05-20 2020-07-01 2020-08-19 2020-10-07 2020-11-25 2021-01-06
2021-02-17 2021-04-07 2021-05-19 2021-07-07 2021-08-18 2021-10-13 2021-11-24
""")


def pre2022_rth_events() -> dict:
    """{session date: [ET minutes]} of high-impact events in RTH, 2011-2021."""
    import econ_calendar as ec
    out: dict = {}

    def add(d, hh, mm):
        out.setdefault(d, []).append(hh * 60 + mm)

    pres = set(FOMC_PRESSER)
    for d in FOMC_DECISION:
        if d.year <= 2012:
            add(d, 12, 30) if d in pres else add(d, 14, 15)
            if d in pres:
                add(d, 14, 15)
        else:
            add(d, 14, 0)
            if d in pres:
                add(d, 14, 30)
    add(date(2020, 3, 3), 10, 0); add(date(2020, 3, 3), 11, 0)
    for d in FOMC_MINUTES:
        add(d, 14, 0)
    years = range(2011, 2022)
    hol = ec._observed_set(years)
    for y in years:
        for m in range(1, 13):
            bd = ec.business_days(y, m, hol)
            add(bd[0], 10, 0); add(bd[2], 10, 0)
    return {d: sorted(set(v)) for d, v in out.items()}


def missing_months(product: str) -> list[str]:
    from open_ema_trail_study import file_span, months_between
    covered = set()
    for f in (FUT_BARS / product).glob("*.parquet"):
        sp = file_span(f)
        if sp:
            covered.update(months_between(*sp))
    return [m for m in months_between(CONF_WINDOW[0], date(2022, 1, 1)) if m not in covered]


def load_fut(product: str):
    """RTH 1m bars of the continuous front month in native points; sessions mixing contracts dropped."""
    import pandas as pd
    from open_ema_trail_study import file_span
    lo, end_excl = CONF_WINDOW[0], date(2022, 1, 1)
    files = [f for f in sorted((FUT_BARS / product).glob("*.parquet")) if (sp := file_span(f)) and sp[0] < end_excl and sp[1] > lo]
    bars = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume", "instrument_id"]) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    et = bars.index.tz_convert(ET)
    m = np.asarray(et.hour * 60 + et.minute)
    bars = bars[(m >= OPEN_M) & (m < CLOSE_M)]
    bars = bars[(bars.index >= pd.Timestamp(lo, tz=ET)) & (bars.index < pd.Timestamp(end_excl, tz=ET))]
    assert bars.low.min() > MIN_PRICE[product], f"{product}: prices below {MIN_PRICE[product]}"
    day = bars.index.tz_convert(ET).date
    g = bars.groupby(day)
    ok = (g.size() >= 380) & (g.instrument_id.nunique() == 1)
    return bars[np.isin(day, list(ok.index[ok]))]


def evaluate(days_by: dict, news: dict, split: date, modes, halves_names) -> tuple[dict, dict]:
    rng = np.random.default_rng(SEED)
    variants = [(CONF_PRIMARY, m) for m in modes] + [(c, "blackout") for c in CONF_SENS]
    res, rows_by = {}, {}
    print(f"\n{'variant':<22}{'sym':<4}{'trades':>7}{'meanR':>8}{'CI95':>18}{'win':>7}{'PF':>6}{'rand p':>8}{'tgt/stop/time/news':>22}")
    for conf, mode in variants:
        key = f"conf{conf}/{mode}"
        by = {p: [run_day(day, conf, mode, news.get(day.d, [])) for day in days_by[p]] for p in PRODUCTS}
        rows_by[key] = by
        entry = {"per": {}, "halves": {}, "years": {}}
        for p in PRODUCTS:
            s = summarize(by[p], PT_USD[p], rng)
            entry["per"][p] = s
            ex = s["exits"]
            print(f"{key:<22}{p:<4}{s['trades']:>7}{s['mean_net_R']:>+8.3f}  [{s['ci95'][0]:+.3f},{s['ci95'][1]:+.3f}]"
                  f"{s['win_rate']:>7.1%}{s['profit_factor']:>6.2f}{s['random_p']:>8.3f}"
                  f"   {ex['target']:.0%}/{ex['stop']:.0%}/{ex['time']:.0%}/{ex['news']:.0%}")
            yrs = sorted({day.d.year for day in days_by[p]})
            entry["years"][p] = {y: float(np.mean([net_r(r, PT_USD[p]) for day, r in zip(days_by[p], by[p]) if r and day.d.year == y]))
                                 for y in yrs}
        entry["pooled"] = pooled(by, days_by, rng)
        for name, keep in ((halves_names[0], lambda d: d < split), (halves_names[1], lambda d: d >= split)):
            sub_by = {p: [r for day, r in zip(days_by[p], by[p]) if keep(day.d)] for p in PRODUCTS}
            sub_days = {p: [day for day in days_by[p] if keep(day.d)] for p in PRODUCTS}
            entry["halves"][name] = pooled(sub_by, sub_days, rng)
        pl = entry["pooled"]
        print(f"{key:<22}{'all':<4}{pl['days']:>7}{pl['mean_net_R']:>+8.3f}  [{pl['ci95'][0]:+.3f},{pl['ci95'][1]:+.3f}]"
              + "".join(f"   {n} {h['mean_net_R']:+.3f}" for n, h in entry["halves"].items()))
        res[key] = entry
    return res, rows_by


def lucid_block(rows_by: dict, keys) -> dict:
    print("\nLucidFlex 50K EV per account (rule vs random-direction twin, same days and sizing)")
    lucid = {}
    for key in keys:
        for p in PRODUCTS:
            for risk in RISKS:
                rows = rows_by[key][p]
                rule = lucid_ev(lucid_days(rows, PT_USD[p], risk))
                tw = np.array([lucid_ev(lucid_days(rows, PT_USD[p], risk, twin_seed=s), paths=4000, seed=s + 3)["ev"]
                               for s in range(TWIN_SEEDS)])
                row = dict(**rule, twin_ev=float(tw.mean()), twin_min=float(tw.min()), twin_max=float(tw.max()),
                           twin_rank=float((tw >= rule["ev"]).mean()))
                lucid[f"{key}/{p}/{risk}"] = row
                print(f"{key:<22}{p:<4}${risk:<5} EV {rule['ev']:+7.1f} [{rule['ev_lo']:+.0f},{rule['ev_hi']:+.0f}] "
                      f"pass {rule['pass_rate']:.1%} paid {rule['paid']:.1%} | twin {tw.mean():+7.1f} "
                      f"({tw.min():+.0f}..{tw.max():+.0f}), twins >= rule {row['twin_rank']:.0%}")
    return lucid


def confirm(check_only: bool) -> int:
    import pandas as pd
    missing = {p: missing_months(p) for p in PRODUCTS}
    if any(missing.values()):
        print(f"missing months, refusing: { {p: m[:6] + (['...'] if len(m) > 6 else []) for p, m in missing.items() if m} }")
        return 1
    news = pre2022_rth_events()
    days_by = {p: build_days_window(load_fut(p), CONF_WINDOW) for p in PRODUCTS}
    for p, ds in days_by.items():
        print(f"{p}: {len(ds)} sessions {ds[0].d} -> {ds[-1].d}, median OR width {np.median([d.orh - d.orl for d in ds]):.2f} pts")
    print(f"news: {sum(len(v) for v in news.values())} RTH high-impact events on {len(news)} sessions")
    if check_only:
        return 0
    lock = OUT / "confirm.lock"
    if lock.exists():
        print(f"confirmation already run ({lock.read_text().strip()}); refusing a second look")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"started {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    res, rows_by = evaluate(days_by, news, CONF_SPLIT, ("none", "blackout"), ("2011-2015", "2016-2021"))
    prim = f"conf{CONF_PRIMARY}/blackout"
    v = verdict(res[prim]["pooled"], res[prim]["per"], res[prim]["halves"])
    print(f"\nCONFIRMATION {prim}: {v}")
    for p in PRODUCTS:
        print(f"  {p} by year: " + " ".join(f"{y}:{r:+.3f}" for y, r in res[prim]["years"][p].items()))
    lucid = lucid_block(rows_by, (prim,))
    out = {"verdict": v, "primary": prim,
           "variants": {k: {"per": {p: strip(s) for p, s in e["per"].items()}, "pooled": e["pooled"], "halves": e["halves"],
                            "years": e["years"]} for k, e in res.items()},
           "lucid": lucid}
    (OUT / "confirm.json").write_text(json.dumps(out, indent=1, default=float))
    lock.write_text(lock.read_text() + f"finished {pd.Timestamp.now(tz='UTC').isoformat()} verdict {v}\n")
    print(f"\nwrote {OUT / 'confirm.json'}")
    return 0


def build_days_window(bars, window) -> list[Day]:
    global WINDOW
    saved, WINDOW = WINDOW, window
    try:
        return build_days(bars)
    finally:
        WINDOW = saved


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--again", action="store_true", help="rerun after a code bug fix only (the rule stays frozen)")
    ap.add_argument("--confirm", action="store_true", help="ONE look at 2011-2021 CME futures")
    ap.add_argument("--confirm-check", action="store_true", help="2011-2021 coverage and counts only, no trades")
    args = ap.parse_args()
    if args.confirm or args.confirm_check:
        return confirm(args.confirm_check)
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "run.lock"
    if lock.exists() and not args.again:
        print(f"already run ({lock.read_text().strip()}); pass --again only after a bug fix")
        return 1

    news: dict = {}
    for d, minute, _ in high_impact_events(*WINDOW):
        news.setdefault(d, []).append(minute)
    days_by = {p: build_days(load_bars(p, date(2026, 8, 15))) for p in PRODUCTS}
    for p, ds in days_by.items():
        print(f"{p}: {len(ds)} sessions {ds[0].d} -> {ds[-1].d}")

    rng = np.random.default_rng(SEED)
    variants = [(CONF_PRIMARY, m) for m in NEWS_MODES] + [(c, "blackout") for c in CONF_SENS]
    res, rows_by = {}, {}
    print(f"\n{'variant':<22}{'sym':<4}{'trades':>7}{'meanR':>8}{'CI95':>18}{'win':>7}{'PF':>6}{'rand p':>8}{'tgt/stop/time/news':>22}")
    for conf, mode in variants:
        key = f"conf{conf}/{mode}"
        by = {p: [run_day(day, conf, mode, news.get(day.d, [])) for day in days_by[p]] for p in PRODUCTS}
        rows_by[key] = by
        entry = {"per": {}, "halves": {}}
        for p in PRODUCTS:
            s = summarize(by[p], PT_USD[p], rng)
            entry["per"][p] = s
            ex = s["exits"]
            print(f"{key:<22}{p:<4}{s['trades']:>7}{s['mean_net_R']:>+8.3f}  [{s['ci95'][0]:+.3f},{s['ci95'][1]:+.3f}]"
                  f"{s['win_rate']:>7.1%}{s['profit_factor']:>6.2f}{s['random_p']:>8.3f}"
                  f"   {ex['target']:.0%}/{ex['stop']:.0%}/{ex['time']:.0%}/{ex['news']:.0%}")
        entry["pooled"] = pooled(by, days_by, rng)
        for name, keep in (("2022-2024", lambda d: d < SPLIT), ("2025-2026", lambda d: d >= SPLIT)):
            sub_by = {p: [r for day, r in zip(days_by[p], by[p]) if keep(day.d)] for p in PRODUCTS}
            sub_days = {p: [day for day in days_by[p] if keep(day.d)] for p in PRODUCTS}
            entry["halves"][name] = pooled(sub_by, sub_days, rng)
        pl = entry["pooled"]
        print(f"{key:<22}{'all':<4}{pl['days']:>7}{pl['mean_net_R']:>+8.3f}  [{pl['ci95'][0]:+.3f},{pl['ci95'][1]:+.3f}]"
              + "".join(f"   {n} {h['mean_net_R']:+.3f}" for n, h in entry["halves"].items()))
        res[key] = entry

    prim = f"conf{CONF_PRIMARY}/blackout"
    v = verdict(res[prim]["pooled"], res[prim]["per"], res[prim]["halves"])
    print(f"\nPRIMARY {prim}: {v}")

    print("\nLucidFlex 50K EV per account (rule vs random-direction twin, same days and sizing)")
    lucid = {}
    for key in (prim, f"conf{CONF_PRIMARY}/none"):
        for p in PRODUCTS:
            for risk in RISKS:
                rows = rows_by[key][p]
                rule = lucid_ev(lucid_days(rows, PT_USD[p], risk))
                tw = np.array([lucid_ev(lucid_days(rows, PT_USD[p], risk, twin_seed=s), paths=4000, seed=s + 3)["ev"]
                               for s in range(TWIN_SEEDS)])
                row = dict(**rule, twin_ev=float(tw.mean()), twin_min=float(tw.min()), twin_max=float(tw.max()),
                           twin_rank=float((tw >= rule["ev"]).mean()))
                lucid[f"{key}/{p}/{risk}"] = row
                print(f"{key:<22}{p:<4}${risk:<5} EV {rule['ev']:+7.1f} [{rule['ev_lo']:+.0f},{rule['ev_hi']:+.0f}] "
                      f"pass {rule['pass_rate']:.1%} paid {rule['paid']:.1%} | twin {tw.mean():+7.1f} "
                      f"({tw.min():+.0f}..{tw.max():+.0f}), twins >= rule {row['twin_rank']:.0%}")

    out = {"verdict": v, "primary": prim,
           "variants": {k: {"per": {p: strip(s) for p, s in e["per"].items()}, "pooled": e["pooled"], "halves": e["halves"]}
                        for k, e in res.items()},
           "lucid": lucid}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))
    import pandas as pd
    lock.write_text(f"run at {pd.Timestamp.now(tz='UTC').isoformat()} verdict {v}\n")
    print(f"\nwrote {OUT / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
