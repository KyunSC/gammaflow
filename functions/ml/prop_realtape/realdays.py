"""Real ES/NQ day paths for the coin-flip prop replay (plan: prop_realtape/PLAN.md, step 2).

One file per product x entry time x stop scheme: `data/prop_realtape/paths/<product>_<HHMM>_<scheme>.parquet`.
A file holds, for every tradeable session, the 1m bars from the entry bar to the session's last bar before 17:00 ET,
as integer ticks relative to the entry bar's open, long side. The short side is the exact mirror
(`side_bars(..., side=-1)`: o,c -> -o,-c and h,l -> -l,-h), so any direction rule is a lookup on the same rows.
Brackets, flat-by, costs and contracts are applied later by replay.py, per plan, because they depend on the plan's
$ risk, commission and flat-by time, none of which belong to the tape.

Session handling copied from vwap_ema_3m_study.build (not imported):
  * sessions run 18:00 ET (D-1) -> 17:00 ET (D), labelled D; weekends dropped;
  * roll sessions dropped: two contracts inside the session, or a contract different from the previous session's
    (`.v.0` rolls at 00:00 UTC), so a day's path is one unadjusted contract;
  * sessions with < 900 1m bars dropped (thin / holiday);
  * early-halt sessions dropped (CME holiday sessions: last bar before 16:00 ET, or before 13:10 ET on a NYSE half day);
  * NYSE half days (CME equity halt 13:15 ET): no entry at or after 12:45 ET; replay flattens by 13:10.
Entry: the open of the 1m bar stamped exactly at the entry minute (ET). A session without that bar has no trade
(counted in `meta.json`).

Stop schemes carry two per-day measures, both from values known at the prior session's close only; replay picks
the stop rule (same $ risk, contracts re-rounded):
  * `vol_ticks` (absolute): atr = ATR20 in ticks; vix = the VIX-implied 1-day sd in ticks,
    VIX/100/sqrt(252) x prior session close / tick. Stop = k x vol_ticks with a declared constant k.
  * `scale` (regime-relative): the measure over its own 250-session rolling median; stop = plan ticks x scale.
    Over long spans this keeps stops near the plan's ticks, so it only adjusts for the vol regime.
Details:
  * fixed: 1.
  * atr:   ATR20 / median(ATR20 over the 250 prior sessions, min 20), where ATR20 = mean session range (high - low,
           18:00-17:00) of the 20 non-roll sessions ending before D (a roll session spans two contracts).
  * vix:   VIX close of the last Cboe date before D / median(that series over the 250 prior Cboe dates, min 20).
           Cboe VIX_History.csv, copied from data/research_loop_volsig/cboe/ (sha256 in meta.json).
Days whose atr or vix scale is undefined (warm-up, early 2011) carry NaN; replay compares schemes on the common set.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import multiprocessing as mp
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
BARS = HERE / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT = HERE / "data" / "prop_realtape"
PATHS = OUT / "paths"
VIX_CSV = OUT / "vix" / "VIX_History.csv"
TZ = "America/New_York"
TICK = 0.25
SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")
SESSION_START_MOD = 18 * 60
SESSION_END_MOD = 17 * 60                 # last bar kept is < 17:00 ET
HALF_NOENTRY_MOD = 12 * 60 + 45
HALF_FLAT_MOD = 13 * 60 + 10
RTH_CLOSE_MOD = 16 * 60
MIN_1M_BARS = 900
ATR_N, MED_N, MED_MIN = 20, 250, 20

PRODUCTS = ("ES", "NQ")
ENTRIES = ("0935", "1000", "1100", "1300")
SCHEMES = ("fixed", "atr", "vix")
ERAS = (("2011-18", date(2011, 1, 3), date(2018, 12, 31)), ("2019-21", date(2019, 1, 1), date(2021, 12, 31)),
        ("2022-26", date(2022, 1, 1), date(2026, 8, 14)), ("2026-ext", date(2026, 8, 15), date(2026, 11, 3)))


def era_of(d: date):
    return next((k for k, lo, hi in ERAS if lo <= d <= hi), None)


def nyse_half_day(d: date) -> bool:
    """Copied from vwap_ema_3m_study: day after Thanksgiving; Jul 3 and Dec 24 on Mon-Thu."""
    if d.month == 11 and d.weekday() == 4:
        thanksgiving = date(d.year, 11, 1 + (3 - date(d.year, 11, 1).weekday()) % 7 + 21)
        return d == thanksgiving + timedelta(days=1)
    return (d.month, d.day) in ((7, 3), (12, 24)) and d.weekday() <= 3


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_bars(product: str) -> pd.DataFrame:
    files = sorted(f for f in (BARS / product).glob("*.parquet") if SPAN.search(f.name))
    cols = ["open", "high", "low", "close", "instrument_id"]
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in files]).sort_index()
    return df[~df.index.duplicated()]


def sessions(df: pd.DataFrame) -> pd.DataFrame:
    """One row per session: bar index span, contract, range, tradeable flag (same rules as vwap_ema_3m_study)."""
    et = df.index.tz_convert(TZ)
    mod = np.asarray(et.hour * 60 + et.minute, dtype=np.int64)
    wall = np.asarray(et.date)
    sday = np.where(mod >= SESSION_START_MOD, wall + timedelta(days=1), wall)
    g = pd.DataFrame({"d": sday, "i": np.arange(len(df)), "inst": df["instrument_id"].to_numpy(),
                      "h": df["high"].to_numpy(), "l": df["low"].to_numpy(), "c": df["close"].to_numpy()})
    s = g.groupby("d", sort=True).agg(i0=("i", "first"), i1=("i", "last"), n=("i", "size"), first=("inst", "first"),
                                      last=("inst", "last"), nuniq=("inst", "nunique"), hi=("h", "max"), lo=("l", "min"),
                                      close=("c", "last"))
    prev_last = s["last"].shift(1)
    s["roll"] = (s["nuniq"] > 1) | (prev_last.notna() & (s["first"] != prev_last))
    s["weekend"] = [d.weekday() >= 5 for d in s.index]
    s["thin"] = s["n"] < MIN_1M_BARS
    s["range"] = s["hi"] - s["lo"]
    return s, mod


def atr_scale(s: pd.DataFrame) -> pd.DataFrame:
    """Per session date, from the prior session's close only: rel = ATR20 / rolling median, ticks = ATR20 / TICK,
    prev_close = the prior session's last close. Roll sessions are left out of the ATR (their range spans two
    contracts, review finding 6): a date reads the ATR of the last non-roll session before it."""
    w = s[~s["weekend"]]
    nr = w[~w["roll"]] if "roll" in w else w
    atr = nr["range"].rolling(ATR_N, min_periods=ATR_N).mean()           # ATR20 known at close of that session
    med = atr.rolling(MED_N, min_periods=MED_MIN).median()                 # median of ATR20 values up to that close
    pos = np.searchsorted(np.array(nr.index), np.array(w.index), side="left") - 1   # last non-roll session < D
    take = lambda x: np.where(pos >= 0, x.to_numpy()[np.clip(pos, 0, None)], np.nan)
    return pd.DataFrame({"rel": take(atr / med), "ticks": take(atr / TICK),
                         "prev_close": w["close"].shift(1).to_numpy()}, index=w.index)


def vix_scale(dates) -> tuple[pd.DataFrame, str]:
    """rel = prior Cboe VIX close / its rolling median; level = that VIX close."""
    v = pd.read_csv(VIX_CSV)
    v["DATE"] = pd.to_datetime(v["DATE"], format="%m/%d/%Y").dt.date
    v = v.set_index("DATE")["CLOSE"].astype(float).sort_index()
    ratio = v / v.rolling(MED_N, min_periods=MED_MIN).median()            # known at that Cboe close
    idx = pd.Index(sorted(dates))
    pos = np.searchsorted(np.array(ratio.index), np.array(idx), side="left") - 1    # last Cboe date strictly before D
    take = lambda x: np.where(pos >= 0, x.to_numpy()[np.clip(pos, 0, None)], np.nan)
    return pd.DataFrame({"rel": take(ratio), "level": take(v)}, index=idx), sha256(VIX_CSV)


def build(product: str, entry: str) -> dict:
    df = load_bars(product)
    s, mod = sessions(df)
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    emod = int(entry[:2]) * 60 + int(entry[2:])
    asc = atr_scale(s)
    keep = s[~s["weekend"] & ~s["roll"] & ~s["thin"]]
    keep = keep[[era_of(d) is not None for d in keep.index]]
    vsc, vix_hash = vix_scale(keep.index)
    rows, segs, skipped = [], [], {"no_entry_bar": 0, "half_day_late": 0, "early_halt": 0}
    for d, r in keep.iterrows():
        half = nyse_half_day(d)
        if half and emod >= HALF_NOENTRY_MOD:
            skipped["half_day_late"] += 1
            continue
        i0, i1 = int(r.i0), int(r.i1)
        if mod[i1] < (HALF_FLAT_MOD if half else RTH_CLOSE_MOD) or mod[i1] >= SESSION_START_MOD:
            skipped["early_halt"] += 1
            continue
        m = mod[i0:i1 + 1]
        hit = np.flatnonzero(m == emod)           # sessions start 18:00 ET, so an entry minute appears once
        if not len(hit):
            skipped["no_entry_bar"] += 1
            continue
        a = i0 + int(hit[0])
        tail = np.flatnonzero((mod[a:i1 + 1] >= emod) & (mod[a:i1 + 1] < SESSION_END_MOD))
        b = a + int(tail[-1])
        px0 = o[a]
        tk = lambda x: np.rint((x[a:b + 1] - px0) / TICK).astype(np.int32)
        segs.append((tk(o), tk(h), tk(l), tk(c), mod[a:b + 1].astype(np.int16)))
        pc = float(asc.at[d, "prev_close"])
        vix = float(vsc.at[d, "level"])
        rows.append(dict(date=d, era=era_of(d), half=half, entry_px=px0, contract=int(r["first"]), n_bars=b - a + 1,
                         scale_atr=float(asc.at[d, "rel"]), scale_vix=float(vsc.at[d, "rel"]),
                         atr_ticks=float(asc.at[d, "ticks"]), prev_close=pc, vix_prev=vix,
                         vixsd_ticks=vix / 100 / np.sqrt(252) * pc / TICK))
    days = pd.DataFrame(rows)
    start = np.r_[0, np.cumsum(days["n_bars"].to_numpy())[:-1]]
    days["start"] = start
    bars = {k: np.concatenate([sg[j] for sg in segs]) for j, k in enumerate(("o", "h", "l", "c", "et_min"))}
    return dict(days=days, bars=bars, skipped=skipped, vix_sha256=vix_hash)


def write(product: str, entry: str) -> dict:
    out = build(product, entry)
    days, bars = out["days"], out["bars"]
    meta = {}
    for scheme in SCHEMES:
        dd = days.copy()
        dd["scale"] = 1.0 if scheme == "fixed" else dd[f"scale_{scheme}"]
        dd["vol_ticks"] = np.nan if scheme == "fixed" else dd["atr_ticks" if scheme == "atr" else "vixsd_ticks"]
        idx = np.repeat(np.arange(len(dd)), dd["n_bars"].to_numpy())
        tbl = pd.DataFrame({"day": idx.astype(np.int32), **bars})
        # The day table rides in the parquet schema metadata (JSON), so one file holds bars + days.
        p = PATHS / f"{product}_{entry}_{scheme}.parquet"
        import pyarrow as pa
        import pyarrow.parquet as pq
        t = pa.Table.from_pandas(tbl, preserve_index=False)
        dj = dd.assign(date=dd["date"].astype(str)).to_json(orient="split", index=False)
        t = t.replace_schema_metadata({b"days": dj.encode(), b"product": product.encode(), b"entry": entry.encode(),
                                       b"scheme": scheme.encode()})
        pq.write_table(t, p, compression="zstd")
        meta[scheme] = dict(file=p.name, sha256=sha256(p), days=int(len(dd)), scale_nan=int(dd["scale"].isna().sum()),
                            bars=int(len(tbl)))
    per_era = days.groupby("era").size().to_dict()
    return dict(product=product, entry=entry, skipped=out["skipped"], days_per_era=per_era,
                vix_sha256=out["vix_sha256"], files=meta)


def load_day_paths(product: str, entry_et: str, stop_scheme: str) -> dict:
    """Read-only accessor (also used by the policy loop).

    Returns {"days": DataFrame(date, era, half, entry_px, contract, n_bars, start, scale, scale_atr, scale_vix),
             "o","h","l","c": int32 ticks vs the entry bar open (long side), "et_min": int16 ET minute of day}.
    Day i's bars are [start[i], start[i] + n_bars[i]). Bar 0 is the entry bar; its open is 0.
    """
    import pyarrow.parquet as pq
    entry_et = entry_et.replace(":", "")
    t = pq.read_table(PATHS / f"{product}_{entry_et}_{stop_scheme}.parquet")
    days = pd.read_json(io.StringIO(t.schema.metadata[b"days"].decode()), orient="split")
    days["date"] = pd.to_datetime(days["date"]).dt.date
    cols = {k: t.column(k).to_numpy() for k in ("o", "h", "l", "c", "et_min")}
    return dict(days=days, **cols)


def side_bars(o, h, l, c, side: int):
    """Long (+1) bars unchanged; short (-1) = mirror. Ticks are symmetric, so this is exact."""
    return (o, h, l, c) if side > 0 else (-o, -l, -h, -c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    PATHS.mkdir(parents=True, exist_ok=True)
    jobs = [(p, e) for p in PRODUCTS for e in ENTRIES]
    with mp.Pool(min(3, a.workers)) as pool:
        res = pool.starmap(write, jobs)
    meta = dict(vix_csv=str(VIX_CSV.relative_to(HERE)), vix_sha256=res[0]["vix_sha256"],
                realdays_sha256=sha256(Path(__file__)), runs=res)
    (PATHS / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    for r in res:
        print(r["product"], r["entry"], r["skipped"], r["days_per_era"],
              {k: (v["days"], v["scale_nan"], v["bars"]) for k, v in r["files"].items()})


if __name__ == "__main__":
    main()
