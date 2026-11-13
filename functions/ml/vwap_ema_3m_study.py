"""VWAP close-through entries with an EMA exit on 3m bars, NQ + ES (spec: vwap_ema_3m_spec.md).

Standalone. It copies the research_loop evaluator's fill and cost rules (eval/config.py, eval/costs.py,
eval/engine.py `check_bar`, eval/twins.py) and does not import or edit the frozen evaluator.

Timing:
  * Indicators and cues are read on 3m closes. Every order decided on a close fills at the next 3m bar's open
    (the open of its first 1m bar). Nothing fills at the decision bar's close.
  * Hard stops are checked on the 1m bars inside each 3m bar before that bar's close is read (stop-first). A stop
    hit at a 1m open (gap) fills at the open, otherwise at the stop. Stop prices snap to the 0.25 grid, away from
    the entry.
  * Sessions run 18:00 ET (day D-1) -> 17:00 ET (day D) and are labelled D. 3m bars are anchored at 18:00 ET.
  * Flat at the open of the first 1m bar at or after 16:55 ET (13:10 ET on NYSE half days, when CME halts at
    13:15). No entry may fill at or after 16:30 ET (12:45 on half days). An opposite cue after the cutoff still
    closes the position (the flip's exit leg) without opening the other side.
  * Sessions that close at 16:15 ET (2011-12 Fridays): flat 16:10, no entries from 15:45 (user, 2026-11-03).
  * 2011-2018 data has a CME halt 16:15-16:30 ET every day. Per the user (2026-11-03), the spec is kept as
    written: positions can be held through that halt.
  * Skipped sessions: roll sessions (two contracts in the session, or a contract different from the previous
    session's; `.v.0` rolls at 00:00 UTC), sessions that stop before their flat time (CME holiday / halted
    sessions), weekends, sessions with < 900 1m bars. EMA and ATR restart on each new contract.

Costs (1 MNQ / 1 MES): $0.50 commission per side; 1 tick slippage on market fills (entries, EMA exits, flips,
flat); stops get the measured NQ stop slip, the mean of `research_loop/eval/stop_slip_pmf.json` for the fill's
ET bucket (outside the measured RTH buckets: the last bucket, as the evaluator does). Stress: market/flat
2 ticks, stops 1 tick + that mean, commission $1/side.

Run discovery (2011-01-03 -> 2018-12-31 only):   ../../.venv/bin/python vwap_ema_3m_study.py
Any window touching 2022+ raises unless --confirm is given AND vwap_ema_3m_prereg.json exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
BARS_DIR = HERE / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT = HERE / "data" / "vwap_ema_3m"
SPEC = HERE / "vwap_ema_3m_spec.md"
SPEC2 = HERE / "vwap_ema_3m_v2_spec.md"           # v2 addendum (user request, 2026-11-03)
PREREG = HERE / "vwap_ema_3m_prereg.json"
LOCK = OUT / "confirm.lock"

# --- Windows ---------------------------------------------------------------------------------------------------
DISC_LO, DISC_HI = date(2011, 1, 3), date(2018, 12, 31)        # inclusive session dates
CONF_LO, CONF_HI = date(2022, 1, 3), date(2026, 8, 14)
VAL1_LO, VAL1_HI = date(2019, 1, 2), date(2021, 12, 31)       # newer, unseen by this family; also needs the prereg
NEWER = ((VAL1_LO, VAL1_HI), (CONF_LO, CONF_HI))
FORBIDDEN_FROM = date(2022, 1, 1)                                # needs --confirm + prereg

# --- Contract and costs (copied from research_loop/eval/config.py + costs.py) ----------------------------------
TZ = "America/New_York"
TICK = 0.25
POINT_VALUE = {"ES": 5.0, "NQ": 2.0}       # MES, MNQ
COMM = {"base": 0.50, "stress": 1.00}       # per side
SLIP = {"base": {"market": 1.0, "flat": 1.0}, "stress": {"market": 2.0, "flat": 2.0}}
STRESS_STOP_EXTRA = 1.0                     # stress stop = 1 tick + the measured mean
# Mean stop slip in ticks by ET bucket [lo, hi) minutes, from eval/stop_slip_pmf.json (NQ fill_study).
STOP_SLIP_BUCKETS = [
    (9 * 60 + 30, 10 * 60, 1.7583),
    (10 * 60, 10 * 60 + 5, 2.2573),
    (10 * 60 + 5, 14 * 60, 1.1888),
    (14 * 60, 14 * 60 + 5, 1.5442),
    (14 * 60 + 5, 15 * 60 + 55, 1.1856),
]
STOP_SLIP_OUTSIDE = STOP_SLIP_BUCKETS[-1][2]

# --- Session clock (session minutes: 0 = 18:00 ET) -------------------------------------------------------------
SESSION_START_MOD = 18 * 60
SM_FLAT, SM_NOENTRY = 22 * 60 + 55, 22 * 60 + 30              # 16:55, 16:30 ET
SM_FLAT_HALF, SM_NOENTRY_HALF = 19 * 60 + 10, 18 * 60 + 45    # 13:10, 12:45 ET
# 2011-12 Friday sessions closed at 16:15 ET (no 16:30 reopen). User (2026-11-03): flat 16:10, no entries from 15:45.
SM_FLAT_1615, SM_NOENTRY_1615 = 22 * 60 + 10, 21 * 60 + 45    # 16:10, 15:45 ET
# v2 RTH session: VWAP anchored 09:30, entries fill 09:30-15:29, flat 15:55 (half days: 12:30 / 12:55)
SM_RTH_OPEN = 15 * 60 + 30                                      # 09:30 ET
SM_RTH_FLAT, SM_RTH_NOENTRY = 21 * 60 + 55, 21 * 60 + 30        # 15:55, 15:30 ET
SM_RTH_FLAT_HALF, SM_RTH_NOENTRY_HALF = 18 * 60 + 55, 18 * 60 + 30   # 12:55, 12:30 ET
MIN_1M_BARS = 900
BAR_MIN = 3

# --- Grid ------------------------------------------------------------------------------------------------------
MODES = ("none", "arm_exit", "filter_entry")
EMAS = (9, 13, 21, 34)
STOPS = ("vwap_close", "atr1", "entry_bar")   # vwap_close == no hard stop (flip on), see spec
WARMUPS = (0, 30)                              # first allowed fill, session minutes
ATR_N = 14
SEED = 20261103
N_MC = 20000

# --- Pass gate (spec) ------------------------------------------------------------------------------------------
GATE = {"p_max": 0.005, "min_years_pos": 5, "max_top5_share": 0.5}


def variant_id(mode: str, ema: int, stop: str, warm: int) -> str:
    return f"{mode}|ema{ema}|{stop}|w{warm}"


GRID = [dict(mode=m, ema=e, stop=s, warm=w, id=variant_id(m, e, s, w))
        for m in MODES for e in EMAS for s in STOPS for w in WARMUPS]
assert len(GRID) == 72

# v2 (vwap_ema_3m_v2_spec.md): entry trigger x flip x session x EMA x stop
ENTRIES = ("price", "ema")
FLIPS = (True, False)
SESSIONS = ("globex", "rth")
V2_STOPS = ("none", "atr1")


def v2_id(entry: str, flip: bool, session: str, ema: int, stop: str) -> str:
    return f"v2|{entry}|{'flip' if flip else 'noflip'}|{session}|ema{ema}|{stop}"


GRID2 = [dict(mode="none", ema=e, stop=st, warm=0, entry=en, flip=f, session=se, id=v2_id(en, f, se, e, st))
         for en in ENTRIES for f in FLIPS for se in SESSIONS for e in EMAS for st in V2_STOPS]
assert len(GRID2) == 64
GRIDS = {"v1": GRID, "v2": GRID2}


# --- Guard -----------------------------------------------------------------------------------------------------

_CONFIRM_ARMED = False   # set only by run_confirm, after it has created the lock file


def assert_window(lo: date, hi: date, confirm: bool = False, prereg: Path | None = None) -> None:
    """Discovery only, unless --confirm with a prereg JSON on disk. Called by the loader itself."""
    prereg = PREREG if prereg is None else prereg
    if lo > hi:
        raise ValueError(f"empty window {lo}..{hi}")
    if confirm:
        if not prereg.exists():
            raise PermissionError(f"--confirm needs {prereg.name}; none on disk")
        if (lo, hi) not in NEWER:
            raise ValueError(f"--confirm runs only {NEWER}")
        return
    if lo >= FORBIDDEN_FROM or hi >= FORBIDDEN_FROM:
        raise PermissionError("2022+ data needs --confirm and a prereg JSON (one look, explicit approval)")
    if hi > DISC_HI:
        raise PermissionError("2019+ data is read only through --confirm with the prereg (frozen variants)")
    if lo < DISC_LO or hi > DISC_HI:
        raise ValueError(f"discovery window is {DISC_LO}..{DISC_HI}; got {lo}..{hi}")


# --- Data ------------------------------------------------------------------------------------------------------

SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")


def load_1m(sym: str, lo: date, hi: date, confirm: bool = False, pad_days: int = 10) -> pd.DataFrame:
    """1m bars covering sessions lo..hi plus `pad_days` of earlier bars (EMA/ATR warmup)."""
    assert_window(lo, hi, confirm)
    if confirm and not (_CONFIRM_ARMED and LOCK.exists()):
        raise PermissionError("confirm data is read only through run_confirm (lock + hash checks)")
    first = lo - timedelta(days=pad_days)
    end = hi + timedelta(days=1)                      # session hi ends 17:30 ET on hi at the latest
    files = []
    for f in sorted((BARS_DIR / sym).glob("*.parquet")):
        m = SPAN.search(f.name)
        if m and date.fromisoformat(m[1]) < end and date.fromisoformat(m[2]) > first:
            files.append(f)
    if not files:
        raise FileNotFoundError(f"no {sym} bars for {lo}..{hi}")
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in files]).sort_index()
    df = df[(df.index >= pd.Timestamp(first, tz="UTC")) & (df.index < pd.Timestamp(end, tz="UTC"))]
    return df


def nyse_half_day(d: date) -> bool:
    """NYSE 13:00 early close (CME equity halt 13:15 ET): day after Thanksgiving; Jul 3 and Dec 24 on Mon-Thu."""
    if d.month == 11 and d.weekday() == 4:
        thanksgiving = date(d.year, 11, 1 + (3 - date(d.year, 11, 1).weekday()) % 7 + 21)
        return d == thanksgiving + timedelta(days=1)
    return (d.month, d.day) in ((7, 3), (12, 24)) and d.weekday() <= 3


@dataclass
class Data:
    sym: str
    # 1m
    o1: np.ndarray
    h1: np.ndarray
    l1: np.ndarray
    c1: np.ndarray
    sm1: np.ndarray        # session minute (0 = 18:00 ET)
    mod1: np.ndarray       # ET minute of day
    # 3m
    a1: np.ndarray         # first 1m index
    b1: np.ndarray         # last 1m index
    sm3: np.ndarray        # nominal bar start, session minutes
    o3: np.ndarray
    h3: np.ndarray
    l3: np.ndarray
    c3: np.ndarray
    vw: np.ndarray         # session VWAP at the bar's close (NaN before any volume)
    vwr: np.ndarray        # RTH VWAP from 09:30 ET at the bar's close (NaN before 09:30)
    ema: dict              # N -> EMA at the bar's close (NaN until N bars of the contract)
    atr: np.ndarray        # Wilder ATR(14) at the bar's close (NaN until 14 bars of the contract)
    sessions: list         # tradeable sessions (dicts)
    skipped: dict = field(default_factory=dict)
    _lists: dict = field(default_factory=dict, repr=False)

    def L(self, name: str):
        """Plain-list copy of an array (fast scalar access in the bar loop)."""
        if name not in self._lists:
            v = getattr(self, name) if not name.startswith("ema") else self.ema[int(name[3:])]
            self._lists[name] = v.tolist()
        return self._lists[name]


def ema_restart(c: np.ndarray, seg: np.ndarray, n: int) -> np.ndarray:
    """EMA(n) of closes, seeded by the SMA of the first n closes of each contract segment."""
    out = np.full(len(c), np.nan)
    a = 2.0 / (n + 1)
    cl = c.tolist()
    sl = seg.tolist()
    e = None
    cnt = 0
    acc = 0.0
    prev = None
    for i in range(len(cl)):
        if sl[i] != prev:
            prev, e, cnt, acc = sl[i], None, 0, 0.0
        cnt += 1
        if e is None:
            acc += cl[i]
            if cnt == n:
                e = acc / n
                out[i] = e
        else:
            e = e + a * (cl[i] - e)
            out[i] = e
    return out


def atr_restart(h: np.ndarray, l: np.ndarray, c: np.ndarray, seg: np.ndarray, n: int = ATR_N) -> np.ndarray:
    """Wilder ATR(n), seeded by the mean of the first n true ranges of each contract segment."""
    out = np.full(len(c), np.nan)
    hl, ll, cl, sl = h.tolist(), l.tolist(), c.tolist(), seg.tolist()
    prev = None
    a = None
    cnt = 0
    acc = 0.0
    for i in range(len(cl)):
        if sl[i] != prev:
            prev, a, cnt, acc = sl[i], None, 0, 0.0
            tr = hl[i] - ll[i]
        else:
            pc = cl[i - 1]
            tr = max(hl[i] - ll[i], abs(hl[i] - pc), abs(ll[i] - pc))
        cnt += 1
        if a is None:
            acc += tr
            if cnt == n:
                a = acc / n
                out[i] = a
        else:
            a = (a * (n - 1) + tr) / n
            out[i] = a
    return out


def build(df: pd.DataFrame, sym: str, lo: date, hi: date) -> Data:
    """1m bars (UTC index; open/high/low/close/volume/instrument_id) -> 3m bars, indicators, tradeable sessions."""
    df = df[~df.index.duplicated()].sort_index()
    et = df.index.tz_convert(TZ)
    mod = np.asarray(et.hour * 60 + et.minute, dtype=np.int64)
    sm = (mod - SESSION_START_MOD) % 1440
    wall = np.asarray(et.date)
    sday = np.where(mod >= SESSION_START_MOD, wall + timedelta(days=1), wall)
    inst = df["instrument_id"].to_numpy()
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy(dtype=float)
    n1 = len(df)

    # 3m bars: new bar when the session, the 3m bucket or the contract changes
    bucket = sm // BAR_MIN
    new = np.ones(n1, dtype=bool)
    if n1 > 1:
        new[1:] = (sday[1:] != sday[:-1]) | (bucket[1:] != bucket[:-1]) | (inst[1:] != inst[:-1])
    a1 = np.flatnonzero(new)
    b1 = np.append(a1[1:], n1) - 1
    o3, c3 = o[a1], c[b1]
    h3, l3 = np.maximum.reduceat(h, a1), np.minimum.reduceat(l, a1)
    v3 = np.add.reduceat(v, a1)
    sm3 = bucket[a1] * BAR_MIN
    sday3 = sday[a1]
    inst3 = inst[a1]

    # session VWAP from 18:00 ET, typical = (H+L+C)/3 of the 3m bar
    typ = (h3 + l3 + c3) / 3.0
    snew = np.ones(len(a1), dtype=bool)
    snew[1:] = sday3[1:] != sday3[:-1]
    sid = np.cumsum(snew) - 1
    cpv = pd.Series(typ * v3).groupby(sid).cumsum().to_numpy()
    cv = pd.Series(v3).groupby(sid).cumsum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(cv > 0, cpv / np.where(cv > 0, cv, 1.0), np.nan)

    rth3 = sm3 >= SM_RTH_OPEN
    cpvr = pd.Series(np.where(rth3, typ * v3, 0.0)).groupby(sid).cumsum().to_numpy()
    cvr = pd.Series(np.where(rth3, v3, 0.0)).groupby(sid).cumsum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vwr = np.where(rth3 & (cvr > 0), cpvr / np.where(cvr > 0, cvr, 1.0), np.nan)

    seg = np.cumsum(np.r_[True, inst3[1:] != inst3[:-1]])
    emas = {n: ema_restart(c3, seg, n) for n in EMAS}
    atr = atr_restart(h3, l3, c3, seg)

    sessions, skipped = [], {"weekend": 0, "thin": 0, "roll": 0, "early_halt": 0}
    close_1615: dict[int, int] = {}      # weekday -> sessions that closed at 16:15 (traded to 16:10)
    starts = np.flatnonzero(snew)
    ends = np.append(starts[1:], len(a1)) - 1
    prev_inst = None
    for k0, k1 in zip(starts.tolist(), ends.tolist()):
        d = sday3[k0]
        j0, jl = int(a1[k0]), int(b1[k1])
        first_inst, last_inst = int(inst3[k0]), int(inst3[k1])
        roll = (len(np.unique(inst3[k0:k1 + 1])) > 1
                or (prev_inst is not None and first_inst != prev_inst))
        prev_inst = last_inst
        if not (lo <= d <= hi):
            continue
        if d.weekday() >= 5:
            skipped["weekend"] += 1
            continue
        if roll:
            skipped["roll"] += 1
            continue
        if jl - j0 + 1 < MIN_1M_BARS:
            skipped["thin"] += 1
            continue
        half = nyse_half_day(d)
        flat_sm = SM_FLAT_HALF if half else SM_FLAT
        noentry_sm = SM_NOENTRY_HALF if half else SM_NOENTRY
        if not half and SM_FLAT_1615 <= sm[jl] <= SM_FLAT_1615 + 5:     # last bar 16:10..16:15
            flat_sm, noentry_sm = SM_FLAT_1615, SM_NOENTRY_1615
            close_1615[d.weekday()] = close_1615.get(d.weekday(), 0) + 1
        if sm[jl] < flat_sm:
            skipped["early_halt"] += 1
            continue
        j_flat = j0 + int(np.argmax(sm[j0:jl + 1] >= flat_sm))
        rth_flat = SM_RTH_FLAT_HALF if half else SM_RTH_FLAT
        j_flat_rth = j0 + int(np.argmax(sm[j0:jl + 1] >= rth_flat))      # exists: rth_flat < flat_sm <= sm[jl]
        sessions.append({"day": d, "k0": k0, "k1": k1, "j0": j0, "jl": jl, "j_flat": j_flat, "half": half,
                         "flat_sm": flat_sm, "noentry_sm": noentry_sm, "j_flat_rth": j_flat_rth,
                         "rth_noentry_sm": SM_RTH_NOENTRY_HALF if half else SM_RTH_NOENTRY})
    skipped["close_1615_by_weekday"] = close_1615
    return Data(sym=sym, o1=o, h1=h, l1=l, c1=c, sm1=sm, mod1=mod, a1=a1, b1=b1, sm3=sm3, o3=o3, h3=h3, l3=l3,
                c3=c3, vw=vw, vwr=vwr, ema=emas, atr=atr, sessions=sessions, skipped=skipped)


# --- Simulation ------------------------------------------------------------------------------------------------

def snap(px: float, up: bool) -> float:
    q = px / TICK
    return (math.ceil(q - 1e-9) if up else math.floor(q + 1e-9)) * TICK


def simulate(D: Data, v: dict) -> list[dict]:
    """Trades of one variant. Decisions on 3m closes, fills at the next 3m open, stops on 1m bars."""
    mode, n_ema, stop_kind, warm = v["mode"], v["ema"], v["stop"], v["warm"]
    entry, flip, rth = v.get("entry", "price"), v.get("flip", True), v.get("session", "globex") == "rth"
    o1, h1, l1, c1, sm1, mod1 = D.L("o1"), D.L("h1"), D.L("l1"), D.L("c1"), D.L("sm1"), D.L("mod1")
    a1, b1, o3, h3, l3, c3 = D.L("a1"), D.L("b1"), D.L("o3"), D.L("h3"), D.L("l3"), D.L("c3")
    vw, ema, atr = D.L("vwr" if rth else "vw"), D.L(f"ema{n_ema}"), D.L("atr")
    if rth:
        warm = SM_RTH_OPEN
    hard = stop_kind not in ("vwap_close", "none")
    trades: list[dict] = []

    for si, s in enumerate(D.sessions):
        k0, k1, jl, day = s["k0"], s["k1"], s["jl"], s["day"]
        j_flat = s["j_flat_rth"] if rth else s["j_flat"]
        noentry = s["rth_noentry_sm"] if rth else s["noentry_sm"]
        pos = 0
        tr = None            # open trade dict
        stop = None
        armed = False
        pend_exit = None     # exit kind ("ema" | "flip") to fill at the next open
        pend_enter = None    # (side, cue bar k)
        done = False

        def close(kind: str, px: float, j: int):
            nonlocal pos, tr, stop, armed
            tr.update(exit_kind=kind, exit_ref=px, j_exit=j, exit_mod=mod1[j])
            trades.append(tr)
            pos, tr, stop, armed = 0, None, None, False

        for k in range(k0, k1 + 1):
            ja, jb = a1[k], b1[k]
            # 0) the flat bar is at or before this bar's open (a gap before 16:55): flat there
            if ja >= j_flat:
                if pos:
                    close("flat", o1[j_flat], j_flat)
                done = True
                break
            # 1) orders from the previous close fill at this bar's open
            if pend_exit is not None and pos:
                close(pend_exit, o1[ja], ja)
            pend_exit = None
            if pend_enter is not None:
                side, kc = pend_enter
                fill = o1[ja]
                if stop_kind == "atr1":
                    stp = snap(fill - side * atr[kc], up=side < 0)
                elif stop_kind == "entry_bar":
                    stp = l3[kc] - TICK if side > 0 else h3[kc] + TICK
                else:
                    stp = None
                pend_enter = None
                # a fill already through its stop (gap) is not entered, as the frozen engine rejects such stops
                if stp is None or side * (fill - stp) > 0:
                    pos, stop = side, stp
                    armed = mode != "arm_exit" or (ema[kc] - vw[kc]) * side > 0
                    tr = {"si": si, "day": day, "side": side, "k_cue": kc, "k_entry": k, "j_entry": ja, "j_flat": j_flat,
                          "entry_ref": fill, "entry_mod": mod1[ja], "entry_sm": sm1[ja],
                          "risk_pts": (side * (fill - stp)) if stp is not None else float("nan"),
                          "stop_init": stp}
            # 2) inside the bar: stop-first on 1m bars, then flat at 16:55 (13:10)
            last_j = min(jb, j_flat - 1)
            if pos and hard and ((pos > 0 and l3[k] <= stop) or (pos < 0 and h3[k] >= stop)):
                for j in range(ja, last_j + 1):
                    if pos > 0:
                        if o1[j] <= stop:
                            close("stop", o1[j], j)
                            break
                        if l1[j] <= stop:
                            close("stop", stop, j)
                            break
                    else:
                        if o1[j] >= stop:
                            close("stop", o1[j], j)
                            break
                        if h1[j] >= stop:
                            close("stop", stop, j)
                            break
            if j_flat <= jb:
                if pos:
                    close("flat", o1[j_flat], j_flat)
                done = True
                break
            # 3) decision on this bar's close
            if k == k0 or vw[k] != vw[k] or vw[k - 1] != vw[k - 1]:
                continue
            cue = 0
            e = ema[k]
            if entry == "price":
                if c3[k - 1] <= vw[k - 1] and c3[k] > vw[k]:
                    cue = 1
                elif c3[k - 1] >= vw[k - 1] and c3[k] < vw[k]:
                    cue = -1
            else:   # "ema": the EMA crosses VWAP on this close, with the close on the same side of VWAP
                e1 = ema[k - 1]
                if e1 == e1 and e == e:
                    if e1 <= vw[k - 1] and e > vw[k] and c3[k] > vw[k]:
                        cue = 1
                    elif e1 >= vw[k - 1] and e < vw[k] and c3[k] < vw[k]:
                        cue = -1
            ema_ok = e == e
            nxt = k + 1 if k < k1 else None
            can_enter = (nxt is not None and ema_ok and warm <= sm1[a1[nxt]] < noentry
                         and (stop_kind != "atr1" or atr[k] == atr[k]))
            passes = cue != 0 and ema_ok and (mode != "filter_entry" or (e - vw[k]) * cue > 0)
            if pos == 0:
                if passes and can_enter:
                    pend_enter = (cue, k)
            elif cue == -pos and passes:
                pend_exit = "flip" if flip else "signal"
                if flip and can_enter:
                    pend_enter = (cue, k)
            elif ema_ok:
                if not armed and (e - vw[k]) * pos > 0:
                    armed = True
                if armed and (c3[k] - e) * pos < 0:
                    pend_exit = "ema"
        if not done and pos:
            close("end", c1[jl], jl)   # session data ran out before the flat time (cannot happen for kept sessions)
    return trades


# --- Costs -----------------------------------------------------------------------------------------------------

def stop_slip_mean(mod: int) -> float:
    for lo, hi, m in STOP_SLIP_BUCKETS:
        if lo <= mod < hi:
            return m
    return STOP_SLIP_OUTSIDE


def slip_ticks(kind: str, mod: int, scenario: str) -> float:
    if kind == "stop":
        m = stop_slip_mean(mod)
        return m + (STRESS_STOP_EXTRA if scenario == "stress" else 0.0)
    if kind in ("flat", "end"):
        return SLIP[scenario]["flat"]
    return SLIP[scenario]["market"]          # entries, ema exits, flips


def trade_usd(sym: str, side: int, ref: float, xref: float, exit_kind: str, exit_mod: int,
              scenario: str = "base") -> tuple[float, float]:
    """(net $, gross points) for 1 micro. Entries are market fills."""
    gross = side * (xref - ref)
    slip = slip_ticks("market", 0, scenario) + slip_ticks(exit_kind, exit_mod, scenario)
    usd = (gross - slip * TICK) * POINT_VALUE[sym] - 2 * COMM[scenario]
    return usd, gross


# --- Twins and baselines ---------------------------------------------------------------------------------------

def twin_exit(D: Data, t: dict, d: int) -> tuple[str, float, int]:
    """Exit of trade t taken on side d with its stop distance mirrored (eval/twins.py rule): its own stop, else
    where the real trade exited (open exits: that open; intrabar stop: the next 1m open; data end: last close)."""
    s = D.sessions[t["si"]]
    j0, j1, ref = t["j_entry"], t["j_exit"], t["entry_ref"]
    intrabar = t["exit_kind"] == "stop"
    last = j1 if intrabar or t["exit_kind"] == "end" else j1 - 1
    risk = t["risk_pts"]
    if risk == risk and last >= j0:
        stop = ref - d * risk
        if d > 0:
            seg = D.l1[j0:last + 1]
            hit = np.flatnonzero(seg <= stop)
        else:
            seg = D.h1[j0:last + 1]
            hit = np.flatnonzero(seg >= stop)
        if len(hit):
            j = j0 + int(hit[0])
            oj = D.o1[j]
            px = oj if (d > 0 and oj <= stop) or (d < 0 and oj >= stop) else stop
            return "stop", float(px), j
    if not intrabar:
        return t["exit_kind"], float(t["exit_ref"]), j1
    jn = j1 + 1
    jf = t.get("j_flat", s["j_flat"])
    if jn < jf and jn <= s["jl"]:
        return "market", float(D.o1[jn]), jn
    if jf <= s["jl"]:
        return "flat", float(D.o1[jf]), jf
    return "end", float(D.c1[s["jl"]]), s["jl"]


def long_short_usd(D: Data, trades: list[dict], scenario: str = "base") -> tuple[np.ndarray, np.ndarray]:
    """Net $ of every trade taken long and taken short (same entry, mirrored stop distance)."""
    rl = np.empty(len(trades))
    rs = np.empty(len(trades))
    for i, t in enumerate(trades):
        for d, arr in ((1, rl), (-1, rs)):
            if d == t["side"]:
                kind, px, j = t["exit_kind"], t["exit_ref"], t["j_exit"]
            else:
                kind, px, j = twin_exit(D, t, d)
            arr[i] = trade_usd(D.sym, d, t["entry_ref"], px, kind, int(D.mod1[j]), scenario)[0]
    return rl, rs


def twin_p_normal(real: np.ndarray, rl: np.ndarray, rs: np.ndarray, sides: np.ndarray) -> dict:
    """Side-matched permutation (same number of longs, sides reassigned at random): one-sided p that the twin
    mean is >= the real mean. Normal approximation to the exact finite-population distribution."""
    n = len(real)
    if n < 2:
        return {"p": 1.0, "twin_mean": 0.0, "twin_sd": 0.0}
    m = int((sides > 0).sum())
    dlt = rl - rs
    mu = (rs.sum() + m * dlt.mean()) / n
    var = m * (n - m) / (n - 1) * dlt.var() / n ** 2
    sd = math.sqrt(var) if var > 0 else 0.0
    z = (real.mean() - mu) / sd if sd > 0 else (math.inf if real.mean() > mu else -math.inf)
    return {"p": float(norm.sf(z)), "twin_mean": float(mu), "twin_sd": float(sd)}


def twin_p_mc(real: np.ndarray, rl: np.ndarray, rs: np.ndarray, sides: np.ndarray, n_mc: int = N_MC,
              seed: int = SEED, chunk: int = 200) -> float:
    is_long = sides > 0
    target = real.mean() - 1e-12
    rng = np.random.default_rng(seed)
    ge = 0
    for st in range(0, n_mc, chunk):
        k = min(chunk, n_mc - st)
        perm = rng.permuted(np.tile(is_long, (k, 1)), axis=1)
        ge += int((np.where(perm, rl, rs).mean(axis=1) >= target).sum())
    return (1 + ge) / (1 + n_mc)


# --- Stats -----------------------------------------------------------------------------------------------------

def stats(D: Data, v: dict, trades: list[dict], years: list[int]) -> dict:
    n_days = len(D.sessions)
    out = {"variant": v["id"], "n": len(trades), "sessions": n_days,
           "trades_per_day": len(trades) / n_days if n_days else 0.0}
    if not trades:
        return out | {"net_per_trade": 0.0, "net_per_day": 0.0, "p": 1.0}
    sides = np.array([t["side"] for t in trades])
    net, gross_pts = map(np.array, zip(*[trade_usd(D.sym, t["side"], t["entry_ref"], t["exit_ref"],
                                                   t["exit_kind"], t["exit_mod"]) for t in trades]))
    stress = np.array([trade_usd(D.sym, t["side"], t["entry_ref"], t["exit_ref"], t["exit_kind"], t["exit_mod"],
                                 "stress")[0] for t in trades])
    rl, rs = long_short_usd(D, trades)
    tw = twin_p_normal(net, rl, rs, sides)
    pv = POINT_VALUE[D.sym]
    days = pd.Series(net).groupby([t["day"] for t in trades]).sum().sort_index()
    yrs = pd.Series(net).groupby([t["day"].year for t in trades]).sum()
    yearly = {int(y): float(yrs.get(y, 0.0)) for y in years}
    total = float(net.sum())
    top5 = float(days.nlargest(5).sum())
    cum = days.cumsum()
    dd = float((cum.cummax().clip(lower=0) - cum).max())
    risk = np.array([t["risk_pts"] for t in trades])
    kinds = pd.Series([t["exit_kind"] for t in trades]).value_counts().to_dict()
    out |= {
        "long_share": float((sides > 0).mean()),
        "net_per_trade": float(net.mean()), "net_per_day": total / n_days, "net_total": total,
        "gross_per_trade": float(gross_pts.mean() * pv), "pts_per_trade": float(gross_pts.mean()),
        "cost_per_trade": float(gross_pts.mean() * pv - net.mean()),
        "stress_net_per_trade": float(stress.mean()),
        "r_per_trade": float(np.mean(net / (np.maximum(risk, TICK) * pv))) if v["stop"] not in ("vwap_close", "none") else None,
        "win_rate": float((net > 0).mean()),
        "yearly": yearly, "years_pos": int(sum(x > 0 for x in yearly.values())), "n_years": len(years),
        "top5_share": top5 / total if total > 0 else None,
        "max_dd": dd,
        "p": tw["p"], "p_method": "normal", "twin_mean": tw["twin_mean"], "twin_sd": tw["twin_sd"],
        "always_long": float(rl.mean()), "opposite_same_windows": float(np.where(sides > 0, rs, rl).mean()),
        "exit_kinds": {str(k): int(x) for k, x in kinds.items()},
        "_arrays": (net, rl, rs, sides),
    }
    return out


# --- Runner ----------------------------------------------------------------------------------------------------

_D: Data | None = None


def _run_one(v: dict) -> tuple[dict, list[dict]]:
    return v, simulate(_D, v)


def run_symbol(sym: str, lo: date, hi: date, variants: list[dict], confirm: bool = False, workers: int = 6,
               n_mc: int = N_MC) -> dict:
    global _D
    _D = build(load_1m(sym, lo, hi, confirm), sym, lo, hi)
    years = sorted({s["day"].year for s in _D.sessions})
    for name in ("o1", "h1", "l1", "c1", "sm1", "mod1", "a1", "b1", "o3", "h3", "l3", "c3", "vw", "vwr", "atr",
                 *(f"ema{n}" for n in EMAS)):
        _D.L(name)                     # build the list caches once, before the workers fork
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        sims = pool.map(_run_one, variants)
    res = {}
    for v, trades in sims:
        st = stats(_D, v, trades, years)
        arr = st.pop("_arrays", None)
        if arr is not None and st["net_per_trade"] > 0 and st["p"] < 0.05:
            st["p"] = twin_p_mc(*arr, n_mc=n_mc)
            st["p_method"] = f"mc{n_mc}"
        res[v["id"]] = st
        print(f"{sym} {v['id']:<36} n={st['n']:>7} tpd={st['trades_per_day']:5.1f} "
              f"net/tr={st['net_per_trade']:+7.3f} net/day={st['net_per_day']:+8.2f} p={st['p']:.4f}", flush=True)
    return {"sessions": len(_D.sessions), "skipped": _D.skipped, "years": years, "variants": res}


def neighbours(v: dict) -> list[str]:
    i = EMAS.index(v["ema"])
    if "entry" in v:
        mk = lambda e: v2_id(v["entry"], v["flip"], v["session"], e, v["stop"])
    else:
        mk = lambda e: variant_id(v["mode"], e, v["stop"], v["warm"])
    return [mk(EMAS[j]) for j in (i - 1, i + 1) if 0 <= j < len(EMAS)]


def gate(res: dict, syms=("ES", "NQ"), grid: list[dict] | None = None) -> dict:
    """Spec pass gate per variant, on both symbols."""
    out = {}
    for v in (GRID if grid is None else grid):
        fails = []
        for s in syms:
            st = res[s]["variants"][v["id"]]
            if not st["net_per_trade"] > 0:
                fails.append(f"{s}: net <= 0")
            if not st["p"] < GATE["p_max"]:
                fails.append(f"{s}: p {st['p']:.3g} >= {GATE['p_max']}")
            if st.get("years_pos", 0) < GATE["min_years_pos"]:
                fails.append(f"{s}: {st.get('years_pos', 0)}/{st.get('n_years', 0)} years positive")
            t5 = st.get("top5_share")
            if t5 is None or not t5 < GATE["max_top5_share"]:
                fails.append(f"{s}: top-5 share {t5}")
            for nb in neighbours(v):
                if not res[s]["variants"][nb]["net_per_trade"] > 0:
                    fails.append(f"{s}: neighbour {nb} net <= 0")
        out[v["id"]] = fails
    return out


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def draft_prereg(ids: list[str], discovery: Path) -> None:
    """Freeze at most 2 variants. Does not run anything."""
    if PREREG.exists():
        raise SystemExit(f"{PREREG.name} exists; preregistration is one-shot")
    if not 1 <= len(ids) <= 2 or any(i not in {v["id"] for v in GRID} for i in ids):
        raise SystemExit("freeze 1 or 2 grid variants")
    disc = json.loads(discovery.read_text())
    if disc.get("spec_sha256") != sha(SPEC) or disc.get("study_sha256") != sha(Path(__file__)):
        raise SystemExit("discovery.json was produced by a different spec or study; rerun discovery")
    not_passing = [i for i in ids if i not in disc.get("passing", [])]
    if not_passing:
        raise SystemExit(f"not gate-passing in discovery: {not_passing}")
    PREREG.write_text(json.dumps({
        "frozen": date.today().isoformat(), "variants": ids,
        "spec_sha256": sha(SPEC), "study_sha256": sha(Path(__file__)), "discovery_sha256": sha(discovery),
        "window": [CONF_LO.isoformat(), CONF_HI.isoformat()],
        "pass": "net > 0 on both ES and NQ with side-matched twin p < 0.05 on both, for a frozen variant",
        "one_look": "confirm.lock is created before any 2022+ bar is read; a second look is refused",
    }, indent=1))


def draft_prereg_user(approved: str) -> None:
    """Freeze every v1 + v2 variant for the user-approved newer-data looks (vwap_ema_3m_v2_spec.md)."""
    if PREREG.exists():
        raise SystemExit(f"{PREREG.name} exists; preregistration is one-shot")
    ids = [v["id"] for v in GRID + GRID2]
    PREREG.write_text(json.dumps({
        "frozen": date.today().isoformat(), "kind": "user_approved_newer_data", "approved": approved,
        "variants": ids, "n_variants": len(ids), "alpha_per_variant": 0.05 / len(ids),
        "spec_sha256": sha(SPEC), "spec2_sha256": sha(SPEC2), "study_sha256": sha(Path(__file__)),
        "windows": [[a.isoformat(), b.isoformat()] for a, b in NEWER],
        "pass": "per window: net > 0 on both ES and NQ with side-matched twin p < alpha_per_variant on both; "
                "robust = passes both windows",
        "one_look": "confirm.lock is created before any 2019+ bar is read; a second look is refused",
    }, indent=1))


def run_confirm(workers: int) -> dict:
    if not PREREG.exists():
        raise SystemExit("no prereg; --confirm refused")
    pr = json.loads(PREREG.read_text())
    if (pr["spec_sha256"] != sha(SPEC) or pr["study_sha256"] != sha(Path(__file__))
            or pr.get("spec2_sha256", sha(SPEC2)) != sha(SPEC2)):
        raise SystemExit("spec or study changed after preregistration; refusing")
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOCK, "x") as f:
            f.write(date.today().isoformat())
    except FileExistsError:
        raise SystemExit("confirm.lock exists: the one look is spent")
    global _CONFIRM_ARMED
    _CONFIRM_ARMED = True
    variants = [v for v in GRID + GRID2 if v["id"] in pr["variants"]]
    alpha = pr.get("alpha_per_variant", 0.05)
    windows = [tuple(date.fromisoformat(x) for x in w) for w in pr.get("windows", [[CONF_LO.isoformat(),
                                                                                    CONF_HI.isoformat()]])]
    res = {"alpha_per_variant": alpha, "windows": {}}
    for lo, hi in windows:
        w = {s: run_symbol(s, lo, hi, variants, confirm=True, workers=workers, n_mc=50000) for s in ("ES", "NQ")}
        w["verdict"] = {v["id"]: all(w[s]["variants"][v["id"]]["net_per_trade"] > 0
                                     and w[s]["variants"][v["id"]]["p"] < alpha for s in ("ES", "NQ"))
                        for v in variants}
        res["windows"][f"{lo}_{hi}"] = w
    res["robust"] = [v["id"] for v in variants if all(w["verdict"][v["id"]] for w in res["windows"].values())]
    return res


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(x) for k, x in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, date):
        return o.isoformat()
    return o


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=DISC_LO)
    ap.add_argument("--end", type=date.fromisoformat, default=DISC_HI)
    ap.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=OUT / "discovery.json")
    ap.add_argument("--confirm", action="store_true", help="one look at 2022-01-03..2026-08-14; needs the prereg")
    ap.add_argument("--draft-prereg", nargs="+", metavar="VARIANT")
    ap.add_argument("--grid", choices=sorted(GRIDS), default="v1")
    ap.add_argument("--prereg-user-approved", metavar="NOTE", help="freeze all v1+v2 variants for the newer-data looks")
    a = ap.parse_args(argv)
    if a.draft_prereg:
        draft_prereg(a.draft_prereg, a.out)
        return
    if a.prereg_user_approved:
        draft_prereg_user(a.prereg_user_approved)
        return
    if a.confirm:
        assert_window(CONF_LO, CONF_HI, confirm=True)
        res = run_confirm(a.workers)
        out = OUT / "confirm.json"
    else:
        assert_window(a.start, a.end)
        grid = GRIDS[a.grid]
        if a.grid != "v1" and a.out == OUT / "discovery.json":
            a.out = OUT / f"discovery_{a.grid}.json"
        res = {s: run_symbol(s, a.start, a.end, grid, workers=a.workers) for s in a.symbols}
        res["grid"] = a.grid
        if set(a.symbols) >= {"ES", "NQ"}:
            g = gate(res, grid=grid)
            res["gate"] = g
            res["passing"] = [k for k, f in g.items() if not f]
        res["window"] = [a.start, a.end]
        res["spec_sha256"] = sha(SPEC)
        res["spec2_sha256"] = sha(SPEC2)
        res["study_sha256"] = sha(Path(__file__))
        out = a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_jsonable(res), indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
