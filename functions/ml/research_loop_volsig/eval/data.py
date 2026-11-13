"""RTH sessions of the traded product (C.PRODUCT, NQ or ES) for the evaluator: 1m bars (fills) and the 5m bars
strategies decide on.

Each session also carries the companion session's 5m bars (ES for NQ, NQ for ES), built by the same session builder
from the companion's own 1m bars: slot k of the companion covers the same ET minutes as slot k and closes at the
same time, so it holds nothing the traded bar does not already know. Missing companion session or slot -> None.

Options features (C.OPTIONS: QQQ for NQ, SPY for ES) ride on each slot as opt5[slot]: the frozen features row whose
slot_end equals the slot's END (bar start + 5 min), i.e. the snapshot taken at the bar's close. Cboe daily closes
ride on each session as `daily`, dated the previous session of this product's own session list.

Only dev / val1 / val2 can be loaded. Each split returns (warmup, trade) session lists: the strategy sees the
warmup sessions first (no orders), then trades the rest.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from . import config as C

SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")


@dataclass
class Session:
    day: date
    half: bool
    close_mod: int                 # RTH close, ET minutes (960 or 780)
    inst: int
    roll: bool                     # front contract differs from the previous loaded session's
    prev_close: float | None       # previous session's last RTH close; None on a roll day or first session
    overnight: dict | None         # same-contract Globex o/h/l/c/v between the previous RTH close and 09:30
    news: list[int]                # ET minutes of high-impact releases inside RTH
    news_day: bool | None          # any high-impact release that ET date; None if the calendar does not cover it
    # 1m arrays (RTH, < close_mod)
    t: np.ndarray                  # epoch seconds UTC of the bar start
    mod: np.ndarray                # ET minutes after midnight
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    # 5m bars: slot = (mod - 570) // 5; a = first, b = last (inclusive) 1m index
    b5: dict = field(default_factory=dict)
    # Companion (ES) for the same ET date: {slot: {o,h,l,c,v}} or None if ES has no matching session
    comp5: dict | None = None
    comp_prev_close: float | None = None   # ES's own previous-session close (None on an ES roll day / first)
    comp_roll: bool = False                 # ES front contract differs from ES's previous session (reset ES history)
    # Options features by slot ({slot: {field: value|None}}); a slot without a features row is absent
    opt5: dict = field(default_factory=dict)
    # Cboe closes dated the previous session: {"date": iso, "VIX": x|None, ...}; None before the first session
    daily: dict | None = None

    @property
    def flat_slot(self) -> int:
        """Slot of the last 5m bar; any position is closed at its open."""
        return (self.close_mod - C.BAR_MINUTES - C.RTH_OPEN) // C.BAR_MINUTES


def _files(lo: date, hi: date, product: str = C.PRODUCT) -> list:
    out = []
    for f in sorted((C.BARS_DIR / product).glob("*.parquet")):
        m = SPAN.search(f.name)
        if m and date.fromisoformat(m[1]) < hi and date.fromisoformat(m[2]) > lo:
            out.append(f)
    return out


def nyse_half_day(d: date) -> bool:
    """NYSE 13:00 early close (published in advance): day after Thanksgiving; Jul 3 and Dec 24 on Mon-Thu."""
    if d.month == 11 and d.weekday() == 4:
        thanksgiving = date(d.year, 11, 1 + (3 - date(d.year, 11, 1).weekday()) % 7 + 21)
        return d == thanksgiving + timedelta(days=1)
    return (d.month, d.day) in ((7, 3), (12, 24)) and d.weekday() <= 3


@lru_cache(maxsize=1)
def _news() -> dict:
    n = json.loads((C.EVAL_DIR / "news.json").read_text())
    cov = tuple(date.fromisoformat(x) for x in n["news_days_coverage"])
    return {"rth": n["rth"], "days": set(n["news_days"]), "cov": cov}


def build_sessions(raw: pd.DataFrame) -> list[Session]:
    """raw: all-hours 1m bars (UTC index; open/high/low/close/volume/instrument_id), sorted, unique."""
    raw = raw[~raw.index.duplicated()].sort_index()
    et = raw.index.tz_convert(C.TZ)
    mod_all = np.asarray(et.hour * 60 + et.minute)
    day_all = np.asarray(et.date)
    t_all = (raw.index.asi8 // 1_000_000_000).astype(np.int64)
    inst_all = raw["instrument_id"].to_numpy()
    o_all, h_all, l_all, c_all = (raw[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    v_all = raw["volume"].to_numpy(dtype=float)
    rth = (mod_all >= C.RTH_OPEN) & (mod_all < C.RTH_CLOSE)
    idx = np.flatnonzero(rth)
    news = _news()

    out: list[Session] = []
    prev: Session | None = None
    prev_close_t: int | None = None
    days, starts = np.unique(day_all[idx], return_index=True)
    bounds = list(starts) + [len(idx)]
    for k, d in enumerate(days):
        ii = idx[bounds[k]:bounds[k + 1]]
        if d.weekday() >= 5 or d in C.NYSE_ADHOC_CLOSURES:
            continue
        last = int(mod_all[ii[-1]])
        if last <= C.CME_HOLIDAY_LAST_MOD:
            continue
        half = nyse_half_day(d)
        if half != (last in C.HALF_DAY_LAST_MODS):
            raise ValueError(f"{d}: NYSE half-day rule says {half} but the last RTH-hour bar is at {last // 60}:{last % 60:02d}")
        close_mod = C.HALF_CLOSE if half else C.RTH_CLOSE
        ii = ii[mod_all[ii] < close_mod]
        if len(ii) < C.MIN_RTH_BARS or len(np.unique(inst_all[ii])) != 1:
            continue
        inst = int(inst_all[ii[0]])
        roll = prev is not None and prev.inst != inst
        on = None
        if prev_close_t is not None:
            lo_i = np.searchsorted(t_all, prev_close_t, side="left")
            w = np.arange(lo_i, ii[0])
            w = w[(inst_all[w] == inst) & ~rth[w]]  # Globex hours only, same contract as today's RTH
            if len(w):
                on = {"o": float(o_all[w[0]]), "h": float(h_all[w].max()), "l": float(l_all[w].min()),
                      "c": float(c_all[w[-1]]), "v": float(v_all[w].sum())}
        ds = d.isoformat()
        cov = news["cov"]
        s = Session(
            day=d, half=half, close_mod=close_mod, inst=inst, roll=roll,
            prev_close=None if (prev is None or roll) else float(prev.c[-1]),
            overnight=on, news=list(news["rth"].get(ds, [])),
            news_day=(ds in news["days"] or ds in news["rth"]) if cov[0] <= d <= cov[1] else None,
            t=t_all[ii], mod=mod_all[ii].astype(np.int32), o=o_all[ii], h=h_all[ii], l=l_all[ii], c=c_all[ii], v=v_all[ii],
        )
        s.b5 = five_minute(s)
        out.append(s)
        prev = s
        prev_close_t = int(s.t[-1]) + 60
    return out


def five_minute(s: Session) -> dict:
    slot = (s.mod - C.RTH_OPEN) // C.BAR_MINUTES
    u, a = np.unique(slot, return_index=True)
    b = np.append(a[1:], len(slot)) - 1
    return {
        "slot": u.astype(int), "a": a.astype(int), "b": b.astype(int),
        "t": s.t[a] - (s.mod[a] - (C.RTH_OPEN + u * C.BAR_MINUTES)) * 60,  # nominal bar start
        "o": s.o[a], "h": np.maximum.reduceat(s.h, a), "l": np.minimum.reduceat(s.l, a), "c": s.c[b],
        "v": np.add.reduceat(s.v, a),
    }


def attach_companion(ses: list[Session], comp: list[Session]) -> None:
    """Give each session the same-date companion session's 5m bars by slot. Both sides come from build_sessions,
    so they share the RTH window, the half-day rule and the holiday drops; a close mismatch means no companion."""
    by = {c.day: c for c in comp}
    for s in ses:
        c = by.get(s.day)
        if c is None or c.close_mod != s.close_mod:
            s.comp5, s.comp_prev_close, s.comp_roll = None, None, False
            continue
        b = c.b5
        s.comp5 = {int(b["slot"][k]): {"o": float(b["o"][k]), "h": float(b["h"][k]), "l": float(b["l"][k]),
                                     "c": float(b["c"][k]), "v": float(b["v"][k])} for k in range(len(b["slot"]))}
        s.comp_prev_close, s.comp_roll = c.prev_close, c.roll


def _raw(lo: date, hi: date, product: str) -> pd.DataFrame:
    files = _files(lo - timedelta(days=7), hi, product)
    raw = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "volume", "instrument_id"]) for f in files])
    return raw.sort_index()


@lru_cache(maxsize=1)
def _features() -> dict:
    """{slot_end epoch seconds UTC: row dict} from the frozen features parquet of C.OPTIONS."""
    f = pd.read_parquet(C.FEATURES_DIR / f"{C.OPTIONS}.parquet", columns=["slot_end", *C.OPT_FIELDS])
    # unit-safe (the parquet stores microseconds): seconds since the epoch
    t = ((f["slot_end"].dt.tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()
    cols = {k: f[k].tolist() for k in C.OPT_FIELDS}
    out = {}
    for i, ts in enumerate(t):
        row = {}
        for k in C.OPT_FIELDS:
            v = cols[k][i]
            if isinstance(v, float) and not np.isfinite(v):
                v = None
            elif k in ("dte", "n_call", "n_put") and v is not None:
                v = int(v)
            elif isinstance(v, (np.floating, float)):
                v = float(v)
            row[k] = v
        out[int(ts)] = row
    return out


@lru_cache(maxsize=1)
def _exdiv() -> tuple[date, ...]:
    df = pd.read_csv(C.EXDIV_DIR / f"{C.OPTIONS}.csv")
    return tuple(sorted(date.fromisoformat(x) for x in df["ex_date"]))


def exdiv_in_window(day: date, expiry: str | None, ex: tuple[date, ...]) -> bool | None:
    """True if an ex-dividend date lies in (day, expiry]; None without an expiry."""
    if expiry is None:
        return None
    e = date.fromisoformat(expiry)
    return any(day < x <= e for x in ex)


def attach_options(ses: list[Session], feats: dict | None = None, exdiv: tuple | None = None) -> None:
    """opt5[slot] = features row whose slot_end is the slot's END (nominal start + 5 min). Only exact matches.
    Each row also gets 'exdiv' (ex-dividend date in (day, expiry])."""
    feats = _features() if feats is None else feats
    ex = _exdiv() if exdiv is None else exdiv
    for s in ses:
        b = s.b5
        s.opt5 = {}
        for k in range(len(b["slot"])):
            row = feats.get(int(b["t"][k]) + C.BAR_MINUTES * 60)
            if row is not None:
                s.opt5[int(b["slot"][k])] = {**row, "exdiv": exdiv_in_window(s.day, row.get("expiry"), ex)}


@lru_cache(maxsize=1)
def _cboe() -> dict:
    """{series: {date: close}} from the frozen Cboe CSVs (close column; VVIX/SKEW have a single value column)."""
    out = {}
    for n in C.DAILY_SERIES:
        df = pd.read_csv(C.CBOE_DIR / f"{n}_History.csv")
        col = "CLOSE" if "CLOSE" in df.columns else n
        df = df[pd.to_numeric(df[col], errors="coerce") > 0]
        days = pd.to_datetime(df["DATE"], format="%m/%d/%Y").dt.date
        out[n] = dict(zip(days, df[col].astype(float)))
    return out


def attach_daily(ses: list[Session], cboe: dict | None = None) -> None:
    """daily = Cboe closes dated the previous session in `ses` (this product's own list, before any date filter)."""
    cboe = _cboe() if cboe is None else cboe
    for i, s in enumerate(ses):
        if i == 0:
            s.daily = None
            continue
        p = ses[i - 1].day
        s.daily = {"date": p.isoformat(), **{n: cboe[n].get(p) for n in C.DAILY_SERIES}}


def load_window(lo: date, hi: date) -> list[Session]:
    ses = build_sessions(_raw(lo, hi, C.PRODUCT))
    attach_companion(ses, build_sessions(_raw(lo, hi, C.COMPANION)))
    attach_options(ses)
    attach_daily(ses)
    return [s for s in ses if lo <= s.day < hi]


def load_split(split: str) -> tuple[list[Session], list[Session]]:
    if split == "dev_opt" and C.PRODUCT in C.DEV_OPT_REFUSED:
        raise ValueError(f"dev_opt refused for {C.PRODUCT}: {C.DEV_OPT_REFUSED[C.PRODUCT]}")
    if split not in C.SPLITS:
        raise ValueError(f"unknown split {split!r}; the evaluator only loads {sorted(C.SPLITS)}")
    lo, hi = C.SPLITS[split]
    if hi > C.LAST_ON_DISK + timedelta(days=1):
        raise ValueError("split reaches past LAST_ON_DISK")
    ses = load_window(lo - timedelta(days=60), hi)
    ses = [s for s in ses if s.day <= C.LAST_ON_DISK]
    first = next(i for i, s in enumerate(ses) if s.day >= lo)
    skip = C.WARMUP_SESSIONS if split in C.DEV_SPLITS else C.GAP_SESSIONS
    start = first + skip
    trade = ses[start:]
    warm = ses[max(0, start - C.WARMUP_SESSIONS):start]
    return warm, trade
