"""Compact 5-minute options features from the ThetaData iv_5m backfill (QQQ -> MNQ, SPY -> MES).

Run once per symbol from functions/ml:
    .venv/bin/python -m research_loop_volsig.build_features --symbol QQQ
    .venv/bin/python -m research_loop_volsig.build_features --symbol SPY

Timestamp semantics (verified in LOG iteration 1): an iv_5m row stamped T is a SNAPSHOT at T
(underlying_price at T matches futures as-of T, corr ~1.0 at lag 0). So the features stamped
`slot_end = T` are built ONLY from rows whose timestamp == T, and belong to the futures 5m slot
that ENDS at T (slot start T-5m). Nothing is forward-filled: a snapshot with too few quotes gives
NaN for that slot only. The 09:30 snapshot is skipped (empty from 2019, pre-open/stale before),
so the first slot_end is 09:35.

Per (date, slot_end), for ONE expiry per day (the nearest with calendar DTE >= 7, fixed for the
whole day so the series never jumps intraday on an expiry switch):
  S            median underlying_price of the snapshot
  atm_call_iv  call implied_vol linearly interpolated in strike at K = S (quoted calls only)
  atm_put_iv   same for puts
  atm_iv       mean of the two
  iv_spread    atm_call_iv - atm_put_iv (Cremers & Weinbaum call-minus-put spread; its LEVEL
               carries dividend/early-exercise/rate bias of an American ETF chain, so ideas should
               use changes or trailing-normalised values)
  put25_iv     put IV interpolated at Black-Scholes delta -0.25 (OTM puts, K <= S)
  call25_iv    call IV interpolated at delta +0.25 (OTM calls, K >= S)
  skew25       put25_iv - call25_iv
  n_call, n_put  quoted options (bid > 0, ask >= bid, implied_vol > 0) in the chosen expiry

Delta uses each option's own implied_vol, r = q = 0 (spot, not a parity forward), and tau = calendar
time from slot_end to the expiry's 16:00 ET close (years of 365 days). In high-rate years the parity
forward is up to ~11 bp from spot; recomputing on it moved skew25 by ~0.0003 typically, 0.0077 at
most (an ex-dividend day; review 3b).

ThetaData's implied_vol ignores dividends: when an ex-dividend date falls between the trade date and
the expiry, call IVs read low and put IVs high (iv_spread -2..-8 vol pts, skew25 ~2x). The evaluator
flags those days (bar['opt']['exdiv']); these features are not corrected for it.

Outputs (data/research_loop_volsig/features/): <SYM>.parquet and <SYM>_coverage.json.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import norm

ML = Path(__file__).resolve().parent.parent
IV_DIR = ML / "data" / "thetadata" / "iv_5m"
OUT_DIR = ML / "data" / "research_loop_volsig" / "features"
ET = "America/New_York"
MIN_DTE = 7
MAX_ATM_GAP = 0.05          # bracketing strikes around S must lie within 5% of S
COLS = ["expiration", "strike", "right", "timestamp", "bid", "ask", "implied_vol", "underlying_price"]
FEATURES = ["S", "atm_call_iv", "atm_put_iv", "atm_iv", "iv_spread", "put25_iv", "call25_iv", "skew25"]
YEAR_S = 365.0 * 86400.0


def pick_expiry(expirations, day: date) -> str | None:
    """Nearest expiry with calendar DTE >= MIN_DTE, or None."""
    ok = sorted(e for e in set(expirations) if (date.fromisoformat(e) - day).days >= MIN_DTE)
    return ok[0] if ok else None


def interp_at(x: np.ndarray, y: np.ndarray, x0: float, max_gap: float | None = None) -> float:
    """Linear interpolation of y at x0 between the two bracketing points; NaN if x0 is not bracketed
    (no extrapolation) or the bracket is wider than max_gap."""
    if len(x) == 0:
        return np.nan
    o = np.argsort(x, kind="stable")
    x, y = x[o], y[o]
    if x0 < x[0] or x0 > x[-1]:
        return np.nan
    j = int(np.searchsorted(x, x0, side="left"))
    if x[j] == x0:
        return float(y[j])
    lo, hi = j - 1, j
    if max_gap is not None and x[hi] - x[lo] > max_gap:
        return np.nan
    w = (x0 - x[lo]) / (x[hi] - x[lo])
    return float(y[lo] + w * (y[hi] - y[lo]))


def bs_delta(S: float, K: np.ndarray, iv: np.ndarray, tau: float, call: bool) -> np.ndarray:
    d1 = (np.log(S / K) + 0.5 * iv * iv * tau) / (iv * np.sqrt(tau))
    return norm.cdf(d1) if call else norm.cdf(d1) - 1.0


def snapshot_features(snap: pd.DataFrame, tau: float) -> dict:
    """Features from ONE snapshot (rows of one timestamp, one expiry)."""
    q = snap[(snap.bid > 0) & (snap.ask >= snap.bid) & (snap.implied_vol > 0)]
    out = dict.fromkeys(FEATURES, np.nan)
    calls, puts = q[q.right == "CALL"], q[q.right == "PUT"]
    out["n_call"], out["n_put"] = len(calls), len(puts)
    if q.empty or tau <= 0:
        return out
    S = float(snap.underlying_price.median())
    out["S"] = S
    gap = MAX_ATM_GAP * S
    c_atm = interp_at(calls.strike.to_numpy(float), calls.implied_vol.to_numpy(float), S, gap)
    p_atm = interp_at(puts.strike.to_numpy(float), puts.implied_vol.to_numpy(float), S, gap)
    out["atm_call_iv"], out["atm_put_iv"] = c_atm, p_atm
    out["atm_iv"] = 0.5 * (c_atm + p_atm)
    out["iv_spread"] = c_atm - p_atm
    otm_p = puts[puts.strike <= S]
    otm_c = calls[calls.strike >= S]
    if len(otm_p):
        d = bs_delta(S, otm_p.strike.to_numpy(float), otm_p.implied_vol.to_numpy(float), tau, call=False)
        out["put25_iv"] = interp_at(d, otm_p.implied_vol.to_numpy(float), -0.25)
    if len(otm_c):
        d = bs_delta(S, otm_c.strike.to_numpy(float), otm_c.implied_vol.to_numpy(float), tau, call=True)
        out["call25_iv"] = interp_at(d, otm_c.implied_vol.to_numpy(float), 0.25)
    out["skew25"] = out["put25_iv"] - out["call25_iv"]
    return out


def day_features(df: pd.DataFrame, day: date) -> tuple[pd.DataFrame, dict]:
    """All slot features for one day's iv_5m rows. Returns (frame, day-coverage dict)."""
    exp = pick_expiry(df.expiration.unique(), day)
    info = {"date": day.isoformat(), "expiry": exp, "slots": 0, "atm_missing": 0, "skew_missing": 0}
    if exp is None:
        return pd.DataFrame(), info
    ts = df.timestamp.dt.tz_convert(ET)
    df = df.assign(timestamp=ts)
    df = df[(df.expiration == exp) & (ts.dt.strftime("%H:%M") > "09:30")]
    close = pd.Timestamp(f"{exp} 16:00", tz=ET)
    rows = []
    for t, snap in df.groupby("timestamp", sort=True):
        f = snapshot_features(snap, (close - t).total_seconds() / YEAR_S)
        f.update(date=day, slot_end=t, expiry=exp, dte=(date.fromisoformat(exp) - day).days)
        rows.append(f)
    out = pd.DataFrame(rows)
    if not out.empty:
        info["slots"] = len(out)
        info["atm_missing"] = int(out.atm_iv.isna().sum())
        info["skew_missing"] = int(out.skew25.isna().sum())
    return out, info


def _one(path: str) -> tuple[pd.DataFrame, dict]:
    day = date.fromisoformat(Path(path).parent.name[5:])
    df = pq.ParquetFile(path).read(columns=COLS).to_pandas()
    return day_features(df, day)


def build(symbol: str, workers: int = 3, limit: int | None = None) -> None:
    root = IV_DIR / f"symbol={symbol}"
    paths = sorted(str(p / "part.parquet") for p in root.iterdir() if (p / "part.parquet").exists())
    if limit:
        paths = paths[:limit]
    frames, infos = [], []
    with ProcessPoolExecutor(max_workers=min(workers, 3)) as ex:
        for i, (f, info) in enumerate(ex.map(_one, paths, chunksize=8)):
            frames.append(f)
            infos.append(info)
            if i % 250 == 0:
                print(f"{symbol} {i}/{len(paths)} {info['date']}", flush=True)
    feat = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    cols = ["date", "slot_end", "expiry", "dte", *FEATURES, "n_call", "n_put"]
    feat = feat[cols].sort_values("slot_end").reset_index(drop=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_DIR / f".{symbol}.parquet.tmp"
    feat.to_parquet(tmp, index=False)
    os.replace(tmp, OUT_DIR / f"{symbol}.parquet")
    no_exp = [x["date"] for x in infos if x["expiry"] is None]
    cov = {
        "symbol": symbol,
        "days": len(infos),
        "days_without_expiry_ge_7dte": no_exp,
        "slots": int(len(feat)),
        "slots_atm_missing": int(feat.atm_iv.isna().sum()),
        "slots_skew_missing": int(feat.skew25.isna().sum()),
        "slots_per_day": feat.groupby("date").size().value_counts().sort_index().to_dict(),
        "worst_days_atm_missing": sorted(infos, key=lambda x: -x["atm_missing"])[:15],
        "dte_quantiles": feat.groupby("date").dte.first().quantile([0, 0.5, 1]).to_dict(),
    }
    cov["slots_per_day"] = {str(k): int(v) for k, v in cov["slots_per_day"].items()}
    cov["dte_quantiles"] = {str(k): float(v) for k, v in cov["dte_quantiles"].items()}
    (OUT_DIR / f"{symbol}_coverage.json").write_text(json.dumps(cov, indent=1, default=str))
    print(json.dumps({k: v for k, v in cov.items() if k != "worst_days_atm_missing"}, default=str)[:2000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["QQQ", "SPY"])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="first N days only (smoke test)")
    a = ap.parse_args()
    build(a.symbol, a.workers, a.limit)
