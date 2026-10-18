"""Download Binance USD-M perpetual 1-minute klines and funding rates for the MyFundedPerps crypto study.

Source: data.binance.vision, Binance's free public archive (monthly zips with a SHA-256 .CHECKSUM beside each).
No key, no cost. The cloud sandbox cannot reach it, so this runs on a local machine.

    python functions/ml/binance_fetch.py                       # BTCUSDT ETHUSDT SOLUSDT, 2020-01 → last full month
    python functions/ml/binance_fetch.py --symbols BTCUSDT --start 2024-01 --end 2024-03
    python functions/ml/binance_fetch.py --check               # re-run coverage on what is on disk, download nothing

Layout: data/binance/um/klines-1m/<SYMBOL>/<YYYY-MM>.parquet and data/binance/um/funding/<SYMBOL>/<YYYY-MM>.parquet.
A month whose Parquet exists is skipped. The zip is kept next to it as the verified source.

Coverage: a month of 1m bars must hold >= 99.9% of its minutes, or it is written as <YYYY-MM>.gappy.parquet and
reported, so nothing loads it by accident. Two earlier studies here were distorted by trades held across holes in the
data (gamma-wall fade, the bundled QQQ sample), which is why this refuses instead of warning.

Downloading the test block is fine: what protects it is crypto_holdout.py, which every study loads through.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://data.binance.vision/data/futures/um/monthly"
OUT_ROOT = Path(__file__).resolve().parent / "data" / "binance" / "um"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
FIRST_MONTH = {"BTCUSDT": "2020-01", "ETHUSDT": "2020-01", "SOLUSDT": "2020-10"}
MIN_COVERAGE = 0.999
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
              "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def months(start: str, end: str) -> list[str]:
    """Inclusive list of YYYY-MM between start and end."""
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def last_full_month(today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{y:04d}-{m:02d}"


def month_bounds(month: str) -> tuple[int, int]:
    """[start, end) of a UTC calendar month in epoch seconds."""
    start = pd.Timestamp(f"{month}-01", tz="UTC")
    return int(start.timestamp()), int((start + pd.offsets.MonthBegin(1)).timestamp())


def kline_url(symbol: str, month: str) -> str:
    return f"{BASE_URL}/klines/{symbol}/1m/{symbol}-1m-{month}.zip"


def funding_url(symbol: str, month: str) -> str:
    return f"{BASE_URL}/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def get(url: str, tries: int = 4) -> bytes | None:
    """Bytes at url, None on 404 (a month Binance has not published), retrying other failures with backoff."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        time.sleep(2 ** (k + 1))
    raise RuntimeError(f"{url}: {err}")


def verify(blob: bytes, checksum: bytes | None, url: str) -> None:
    if checksum is None:
        raise RuntimeError(f"{url}: no .CHECKSUM published; refusing an unverified file")
    want = checksum.decode().split()[0].lower()
    got = hashlib.sha256(blob).hexdigest()
    if want != got:
        raise RuntimeError(f"{url}: sha256 {got} != published {want}")


def read_csv_zip(blob: bytes, names: list[str]) -> pd.DataFrame:
    """The one CSV inside a Binance zip, columns named `names`. Newer files carry a header row
    (klines call the trade count `count`); older ones do not."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    has_header = not raw.split(b"\n", 1)[0][:1].isdigit()
    df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=1 if has_header else 0)
    df.columns = names[: df.shape[1]]
    return df


def parse_klines(blob: bytes) -> pd.DataFrame:
    df = read_csv_zip(blob, KLINE_COLS)
    t = df["open_time"].astype("int64").to_numpy()
    # Milliseconds in the futures archive; microseconds if Binance ever switches it like spot (2025).
    scale = 1_000_000 if t.max() > 10 ** 14 else 1000
    out = pd.DataFrame({
        "time": t // scale,
        **{c: df[c].astype(float) for c in ("open", "high", "low", "close", "volume", "quote_volume")},
        "trades": df["trades"].astype("int64"),
        "taker_buy_volume": df["taker_buy_volume"].astype(float),
    })
    return out.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def parse_funding(blob: bytes) -> pd.DataFrame:
    df = read_csv_zip(blob, ["calc_time", "funding_interval_hours", "last_funding_rate"])
    t = df["calc_time"].astype("int64").to_numpy()
    scale = 1_000_000 if t.max() > 10 ** 14 else 1000
    return pd.DataFrame({"time": t // scale, "funding_rate": df["last_funding_rate"].astype(float)}).sort_values("time")


def coverage(times: np.ndarray, month: str, step: int = 60) -> dict:
    """Share of the month's minutes present, and every hole longer than one bar."""
    start, end = month_bounds(month)
    t = np.unique(np.asarray(times, dtype=np.int64))
    t = t[(t >= start) & (t < end)]
    expected = (end - start) // step
    edges = np.r_[start - step, t, end]
    gaps = np.diff(edges) // step - 1
    holes = [(int(edges[i] + step), int(gaps[i])) for i in np.flatnonzero(gaps > 0)]
    return {"month": month, "bars": int(t.size), "expected": int(expected), "share": t.size / expected,
            "holes": [{"from": datetime.fromtimestamp(a, timezone.utc).isoformat(), "missing_bars": n} for a, n in holes]}


def fetch_month(symbol: str, month: str, root: Path = OUT_ROOT, fetch=get) -> dict:
    """Download, verify and store one month of klines and funding; return its coverage report."""
    kdir, fdir = root / "klines-1m" / symbol, root / "funding" / symbol
    good, gappy = kdir / f"{month}.parquet", kdir / f"{month}.gappy.parquet"
    if good.exists():
        return {"month": month, "symbol": symbol, "status": "cached"}
    url = kline_url(symbol, month)
    blob = fetch(url)
    if blob is None:
        return {"month": month, "symbol": symbol, "status": "not-published"}
    verify(blob, fetch(url + ".CHECKSUM"), url)
    bars = parse_klines(blob)
    rep = coverage(bars["time"].to_numpy(), month)
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / f"{month}.zip").write_bytes(blob)
    ok = rep["share"] >= MIN_COVERAGE
    bars.to_parquet(good if ok else gappy, index=False)

    furl = funding_url(symbol, month)
    fblob = fetch(furl)
    if fblob is not None:
        verify(fblob, fetch(furl + ".CHECKSUM"), furl)
        fdir.mkdir(parents=True, exist_ok=True)
        parse_funding(fblob).to_parquet(fdir / f"{month}.parquet", index=False)
    # Reported, not fatal: funding is a signal for one hypothesis (C2), never a cost at MFP.
    return {**rep, "symbol": symbol, "status": "ok" if ok else "gappy", "funding": fblob is not None, "holes": rep["holes"][:20]}


def check_disk(root: Path = OUT_ROOT) -> list[dict]:
    out = []
    for f in sorted((root / "klines-1m").glob("*/*.parquet")):
        month = f.name.split(".")[0]
        rep = coverage(pd.read_parquet(f, columns=["time"])["time"].to_numpy(), month)
        out.append({"symbol": f.parent.name, "file": f.name, "share": round(rep["share"], 6), "holes": len(rep["holes"])})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    ap.add_argument("--start", default=None, help="YYYY-MM (default: each symbol's first month)")
    ap.add_argument("--end", default=last_full_month(), help="YYYY-MM inclusive (default: last full month)")
    ap.add_argument("--check", action="store_true", help="coverage of files already on disk; no downloads")
    a = ap.parse_args(argv)
    if a.check:
        for row in check_disk():
            print(json.dumps(row))
        return 0
    bad = 0
    for sym in a.symbols:
        for month in months(a.start or FIRST_MONTH.get(sym, "2020-01"), a.end):
            rep = fetch_month(sym, month)
            if rep["status"] == "gappy":
                bad += 1
            print(json.dumps({k: rep[k] for k in ("symbol", "month", "status", "share", "funding", "holes") if k in rep}))
    if bad:
        print(f"{bad} month(s) below {MIN_COVERAGE:.1%} coverage were written as *.gappy.parquet and will not load.", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
