"""Build exact per-minute volume-at-price partitions from Databento futures trades.

The chart's volume profile approximates intra-bar volume from OHLCV. Where real
prints exist, the API serves exact volume instead: it sums these partitions over
each bar the chart asks about (VolumeProfileController).

    python functions/ml/publish_tick_profiles.py                          # nq-trades -> API_Server/tick-profiles
    python functions/ml/publish_tick_profiles.py --product ES --source functions/ml/data/databento/es-trades/ES

Layout under --out:
    <PRODUCT>/index.json                    {"v":1,"symbol","tickSize","sessions":[{"date","start","end","file"}]}
    <PRODUCT>/<YYYY-MM-DD>.json.gz          {"v":1,"symbol","tickSize","date","start","end","volume",
                                             "minutes":[[t, lo, v_lo, v_lo+1, ...], ...],
                                             "delta":[[d_lo, d_lo+1, ...], ...]}
    <PRODUCT>/<YYYY-MM-DD>-<n>.json.gz      a further chunk on the same ET date (n = 2, 3, ...);
                                            the index entry keeps the plain date
t = UTC epoch seconds of the minute start, lo = price / tickSize of the first volume
slot; slots are contiguous ticks. delta[i] lines up with minutes[i]'s slots: buy-
aggressor minus sell-aggressor contracts (Databento side B / A; prints with no side
count toward volume only). [start, end) is the span that was *requested* from
Databento (its .request.json), so a minute with no prints inside it is a real zero,
not missing data. Partitions are rebuilt from scratch every run (cheap) and the
index is written last, so a reader never sees a session before its file exists.

Upload the folder to wherever `tickprofile.location` points (files first, index.json
last). This is CME-derived data; check your Databento licence before serving it publicly.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from publish_backtest_data import atomic_write, encode_json

HERE = Path(__file__).resolve().parent
TICK_SIZE = 0.25  # NQ and ES


def request_span(parquet: Path) -> tuple[int, int]:
    """UTC [start, end) epoch seconds actually requested for this chunk."""
    req = json.loads(parquet.with_name(parquet.name.replace(".parquet", ".request.json")).read_text())["request"]
    start, end = (int(pd.Timestamp(req[k]).timestamp()) for k in ("start", "end"))
    if start % 60 or end % 60 or end <= start:
        raise ValueError(f"{parquet.name}: request span must be whole minutes")
    return start, end


def build_session(parquet: Path, tick_size: float) -> dict | None:
    start, end = request_span(parquet)
    df = pd.read_parquet(parquet, columns=["ts_event", "price", "size", "side", "instrument_id"])
    if df.empty:
        return None
    # NQ.v.0 maps to one contract per day; anything else would mix roll prices.
    front = df["instrument_id"].mode().iloc[0]
    if (df["instrument_id"] != front).any():
        print(f"  {parquet.name}: dropping {(df['instrument_id'] != front).sum()} prints off the front contract")
        df = df[df["instrument_id"] == front]

    ticks = df["price"].to_numpy(float) / tick_size
    tick = np.rint(ticks).astype(np.int64)
    if np.abs(ticks - tick).max() > 1e-6:
        raise ValueError(f"{parquet.name}: prices off the {tick_size} grid")
    t = pd.to_datetime(df["ts_event"], utc=True).dt.as_unit("s").astype("int64").to_numpy()
    keep = (t >= start) & (t < end)
    minute = t[keep] // 60 * 60
    size = df["size"].to_numpy(np.int64)[keep]
    side = df["side"].to_numpy(str)[keep]
    sign = np.select([side == "B", side == "A"], [1, -1], 0)
    cells = (pd.DataFrame({"m": minute, "p": tick[keep], "v": size, "d": size * sign})
             .groupby(["m", "p"], sort=True)[["v", "d"]].sum())

    minutes, delta = [], []
    for m, row in cells.groupby(level=0, sort=True):
        prices = row.index.get_level_values(1).to_numpy()
        lo = int(prices.min())
        slots = np.zeros((2, int(prices.max()) - lo + 1), dtype=np.int64)
        slots[:, prices - lo] = row[["v", "d"]].to_numpy().T
        minutes.append([int(m), lo, *slots[0].tolist()])
        delta.append(slots[1].tolist())

    date = pd.Timestamp(start, unit="s", tz="UTC").tz_convert("America/New_York").strftime("%Y-%m-%d")
    return {"date": date, "start": start, "end": end, "volume": int(cells["v"].sum()),
            "minutes": minutes, "delta": delta}


def publish(source: Path, out: Path, product: str) -> list[dict]:
    tick_size = TICK_SIZE
    out = out / product
    out.mkdir(parents=True, exist_ok=True)
    sessions = []
    used = set()
    for parquet in sorted(source.glob("*.parquet")):
        session = build_session(parquet, tick_size)
        if session is None:
            continue
        if sessions and session["start"] < sessions[-1]["end"]:
            raise ValueError(f"{parquet.name}: overlaps the previous session")
        filename = f"{session['date']}.json.gz"
        n = 2
        while filename in used:  # two chunks on one ET date must not share a file
            filename = f"{session['date']}-{n}.json.gz"
            n += 1
        used.add(filename)
        body = {"v": 1, "symbol": product, "tickSize": tick_size, **session}
        atomic_write(out / filename, gzip.compress(encode_json(body), mtime=0))
        sessions.append({"date": session["date"], "start": session["start"], "end": session["end"], "file": filename})
        print(f"  {session['date']}  {len(session['minutes']):>4} min  {session['volume']:>9,} contracts")
    atomic_write(out / "index.json", encode_json({"v": 1, "symbol": product, "tickSize": tick_size, "sessions": sessions}))
    return sessions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--product", default="NQ", choices=["NQ", "ES"])
    ap.add_argument("--source", type=Path, help="folder of Databento trades parquet + .request.json "
                    "(default: functions/ml/data/databento/<product lower>-trades/<PRODUCT>)")
    ap.add_argument("--out", type=Path, default=HERE.parent.parent / "API_Server" / "tick-profiles")
    args = ap.parse_args()
    source = args.source or HERE / "data" / "databento" / f"{args.product.lower()}-trades" / args.product
    if not source.is_dir():
        print(f"no trades folder at {source}", file=sys.stderr)
        return 2
    sessions = publish(source, args.out, args.product)
    print(f"wrote {len(sessions)} sessions to {args.out / args.product}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
