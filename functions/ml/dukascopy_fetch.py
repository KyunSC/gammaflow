"""Free spot 1-minute bars from Dukascopy's public datafeed (proxy for GC / 6E futures).

    .venv/bin/python -I functions/ml/dukascopy_fetch.py                     # fetch (resumes)
    .venv/bin/python -I functions/ml/dukascopy_fetch.py --to-parquet        # build monthly parquet

One request per (symbol, side, UTC weekday): datafeed/<SYM>/<YYYY>/<MM-1>/<DD>/<SIDE>_candles_min_1.bi5,
an LZMA blob of 1440 big-endian rows (t_sec, open, close, low, high: int32 price*scale; volume: float32).
Raw files are kept under data/dukascopy/<SYM>/<SIDE>/<YYYY>/<date>.bi5 (an empty file = no data that
day). Existing files are skipped, so a killed run resumes. 503/timeouts back off and retry; a day that
keeps failing is logged in fetch_log.jsonl and retried on the next run. Spot is not the futures
contract: the basis drifts slowly, but GC/6E levels and tick values must come from the futures spec.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "data" / "dukascopy"
LOG = ROOT / "fetch_log.jsonl"
URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y:04d}/{m:02d}/{d:02d}/{side}_candles_min_1.bi5"
SCALE = {"EURUSD": 1e5, "XAUUSD": 1e3}
ROW = struct.Struct(">5if")


def weekdays(start: date, end: date):
    d = start
    while d < end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def raw_path(sym: str, side: str, d: date) -> Path:
    return ROOT / sym / side / f"{d.year}" / f"{d.isoformat()}.bi5"


def decode(blob: bytes, scale: float, day: date) -> list[tuple]:
    """Rows (ts_utc, open, high, low, close, volume); validates OHLC ordering."""
    if not blob:
        return []
    raw = lzma.decompress(blob)
    if len(raw) % ROW.size:
        raise ValueError(f"{day}: {len(raw)} bytes is not a multiple of {ROW.size}")
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    out = []
    for t, o, c, lo, hi, v in ROW.iter_unpack(raw):
        if not lo <= min(o, c) <= max(o, c) <= hi:
            raise ValueError(f"{day} t={t}: bad OHLC {o} {hi} {lo} {c}")
        out.append((base + timedelta(seconds=t), o / scale, hi / scale, lo / scale, c / scale, float(v)))
    return out


def fetch_one(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research script)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def log(row: dict) -> None:
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")


def fetch(symbols, sides, start, end, pause, timeout, retries) -> int:
    todo = [(side, sym, d) for side in sides for sym in symbols for d in weekdays(start, end)
            if not raw_path(sym, side, d).exists()]
    print(f"{len(todo)} files to fetch", flush=True)
    failed, t0 = 0, time.time()
    for i, (side, sym, d) in enumerate(todo, 1):
        url = URL.format(sym=sym, y=d.year, m=d.month - 1, d=d.day, side=side)
        blob, err = None, None
        for attempt in range(retries):
            try:
                blob = fetch_one(url, timeout)
                break
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code == 404:
                    blob = b""
                    break
            except Exception as e:  # timeout / reset
                err = type(e).__name__
            time.sleep(min(300, pause * 4 ** (attempt + 1)))
        if blob is None:
            failed += 1
            log({"sym": sym, "side": side, "date": d.isoformat(), "status": "failed", "err": err})
            continue
        decode(blob, SCALE[sym], d)  # refuse to keep a corrupt file
        p = raw_path(sym, side, d)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(p)
        log({"sym": sym, "side": side, "date": d.isoformat(), "status": "ok", "bytes": len(blob),
             "sha256": hashlib.sha256(blob).hexdigest()})
        if i % 100 == 0:
            rate = i / (time.time() - t0)
            print(f"{i}/{len(todo)} {sym} {side} {d}  {rate:.2f}/s  eta {(len(todo) - i) / rate / 3600:.1f}h"
                  f"  failed {failed}", flush=True)
        time.sleep(pause)
    print(f"done: {len(todo) - failed} ok, {failed} failed (re-run to retry)", flush=True)
    return 1 if failed else 0


def to_parquet(symbols, sides, start, end) -> int:
    import pandas as pd
    for side in sides:
        for sym in symbols:
            by_month: dict[str, list] = {}
            missing = 0
            for d in weekdays(start, end):
                p = raw_path(sym, side, d)
                if not p.exists():
                    missing += 1
                    continue
                by_month.setdefault(d.strftime("%Y-%m"), []).extend(decode(p.read_bytes(), SCALE[sym], d))
            out = ROOT / "parquet" / sym / side
            out.mkdir(parents=True, exist_ok=True)
            for month, rows in by_month.items():
                df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
                df.to_parquet(out / f"{month}.parquet", index=False)
            print(f"{sym} {side}: {len(by_month)} months, {missing} weekdays missing", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="EURUSD,XAUUSD")
    ap.add_argument("--sides", default="BID,ASK")
    ap.add_argument("--start", default="2011-01-03")
    ap.add_argument("--end", default="2026-08-15", help="exclusive")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--to-parquet", action="store_true")
    a = ap.parse_args()
    syms, sides = a.symbols.upper().split(","), a.sides.upper().split(",")
    if not set(syms) <= set(SCALE) or not set(sides) <= {"BID", "ASK"}:
        ap.error(f"symbols must be in {sorted(SCALE)}, sides in BID,ASK")
    s, e = date.fromisoformat(a.start), date.fromisoformat(a.end)
    ROOT.mkdir(parents=True, exist_ok=True)
    if a.to_parquet:
        return to_parquet(syms, sides, s, e)
    return fetch(syms, sides, s, e, a.pause, a.timeout, a.retries)


if __name__ == "__main__":
    sys.exit(main())
