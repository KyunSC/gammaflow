"""Feature series joined as of their publish time.

A signal on 1m bar i is decided at that bar's close, t_dec = m.t[i] + 60. A feature row is visible to it only when the
row's `avail` <= t_dec. `avail` per source (plan, Evaluator section):

    metrics (5m OI, ratios)          stamp + 300     (row stamped t counts only after t + 5m)
    premium / mark / index 1m        open + 60       (bar close)
    Coinbase 5m candles              open + 300
    Deribit DVOL hourly              open + 3600     (counts at the hour's end)
    funding                          print time      (the rate is fixed at the print)
    kline taker flow, hourly sums    hour + 3600     (completed UTC hours only)

Every loader stays inside [block.start - warmup, block.end) and refuses anything at or after TEST_START.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .blocks import Block, HoldoutError, months

sys.path.insert(0, str(C.LOOP))
import fetch_free as FF  # noqa: E402  (its readers carry the test-start guard)

PMI = {'premium': 'premiumIndexKlines', 'mark': 'markPriceKlines', 'index': 'indexPriceKlines'}
METRIC_COLS = ('sum_open_interest', 'sum_open_interest_value', 'count_toptrader_long_short_ratio',
               'sum_toptrader_long_short_ratio', 'count_long_short_ratio', 'sum_taker_long_short_vol_ratio')
TEST_S = int(C.TEST_START.timestamp())


@dataclass
class Series:
    stamp: np.ndarray            # int64 epoch seconds, as published
    avail: np.ndarray            # int64 epoch seconds when the row becomes usable; sorted
    values: dict[str, np.ndarray]

    def __post_init__(self):
        o = np.argsort(self.avail, kind='stable')
        self.stamp, self.avail = self.stamp[o], self.avail[o]
        self.values = {k: np.asarray(v, float)[o] for k, v in self.values.items()}
        if len(self.stamp) and self.stamp.max() >= TEST_S:
            raise HoldoutError('feature row on or after the test start')

    def __len__(self):
        return len(self.avail)

    def asof(self, t_dec: np.ndarray, *, max_age: float) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Latest row with avail <= t_dec, per decision time, if it is at most `max_age` seconds old (required: pass
        np.inf only on purpose). Returns values (NaN where no row qualifies) and the row index used (-1 where none)."""
        t_dec = np.asarray(t_dec, np.int64)
        if len(self.avail) == 0:
            return {k: np.full(len(t_dec), np.nan) for k in self.values}, np.full(len(t_dec), -1)
        j = np.searchsorted(self.avail, t_dec, side='right') - 1
        jj = np.maximum(j, 0)
        ok = (j >= 0) & ((t_dec - self.avail[jj]) <= max_age)
        out = {k: np.where(ok, v[jj], np.nan) for k, v in self.values.items()}
        return out, np.where(ok, j, -1)


def decision_times(t_open: np.ndarray) -> np.ndarray:
    """Close of each 1m bar: when a signal on that bar is decided."""
    return np.asarray(t_open, np.int64) + 60


class Features:
    def __init__(self, block: Block, warmup_days: int = 0, raw: Path = C.RAW):
        self.lo = block.start - pd.Timedelta(days=warmup_days)
        self.hi = block.end
        if self.hi > C.TEST_START:
            raise HoldoutError('feature window ends after the test start')
        self.block, self.warmup_days, self.raw = block, warmup_days, raw
        self.lo_s, self.hi_s = int(self.lo.timestamp()), int(self.hi.timestamp())

    def _clip(self, stamp: np.ndarray) -> np.ndarray:
        return (stamp >= self.lo_s) & (stamp < self.hi_s)

    def metrics(self, symbol: str) -> Series:
        d0, d1 = self.lo.date(), (self.hi - pd.Timedelta(seconds=1)).date()
        rows = {}
        for k in range((d1 - d0).days + 1):
            day = d0 + dt.timedelta(k)
            f = self.raw / 'metrics' / symbol / f'{symbol}-metrics-{day.isoformat()}.zip'
            if not f.exists():
                continue
            for r in FF.read_metrics(f.read_bytes(), day):
                t = int(pd.Timestamp(r['create_time'], tz='UTC').timestamp())
                rows.setdefault(t, r)
        ts = np.array(sorted(rows), np.int64)
        ts = ts[self._clip(ts)]
        vals = {}
        for c in METRIC_COLS:
            v = np.array([float(rows[t][c]) if rows[t][c].strip() else np.nan for t in ts])
            if c.startswith('sum_open_interest'):
                v[v == 0] = np.nan  # zero OI is a publishing gap, not a value
            vals[c] = v
        return Series(ts, ts + 300, vals)

    def pmi(self, kind: str, symbol: str) -> Series:
        """premium / mark / index 1m klines: monthly files merged with the daily backfill, deduped on open time."""
        src = PMI[kind]
        rows = {}
        for m in months(f'{self.lo:%Y-%m}', f'{self.hi - pd.Timedelta(seconds=1):%Y-%m}'):
            f = self.raw / src / symbol / f'{symbol}-1m-{m}.zip'
            if f.exists():
                for r in FF.read_kline_month(f.read_bytes(), dt.date.fromisoformat(m + '-01')):
                    rows.setdefault(r[0] // 1000, r)
        ddir = self.raw / src / symbol / 'daily'
        for f in sorted(ddir.glob(f'{symbol}-1m-*.zip')) if ddir.exists() else []:
            day = dt.date.fromisoformat(f.name[-14:-4])
            if not (self.lo.date() <= day < self.hi.date()):
                continue
            pre, post = FF.split_kline_month(f.read_bytes())
            if post:
                raise HoldoutError(f'{f.name}: rows at/after the test start')
            for r in pre:
                rows.setdefault(r[0] // 1000, r)
        ts = np.array(sorted(rows), np.int64)
        ts = ts[self._clip(ts)]
        a = np.array([rows[t][1:] for t in ts]).reshape(-1, 4)
        return Series(ts, ts + 60, dict(open=a[:, 0], high=a[:, 1], low=a[:, 2], close=a[:, 3]))

    def coinbase(self, product: str) -> Series:
        frames = []
        for m in months(f'{self.lo:%Y-%m}', f'{self.hi - pd.Timedelta(seconds=1):%Y-%m}'):
            f = self.raw / 'coinbase' / product / f'{m}.csv.gz'
            if f.exists():
                frames.append(pd.read_csv(io.BytesIO(gzip.decompress(f.read_bytes()))))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['t', 'open', 'high', 'low', 'close', 'volume'])
        df = df.drop_duplicates('t').sort_values('t')
        ts = df['t'].to_numpy(np.int64)
        keep = self._clip(ts)
        return Series(ts[keep], ts[keep] + 300, {c: df[c].to_numpy(float)[keep] for c in ('open', 'high', 'low', 'close', 'volume')})

    def dvol(self, currency: str) -> Series:
        df = pd.read_csv(io.BytesIO(gzip.decompress((self.raw / 'dvol' / f'{currency}.csv.gz').read_bytes())))
        ts = (df['t_ms'].to_numpy(np.int64) // 1000)
        keep = self._clip(ts)
        return Series(ts[keep], ts[keep] + 3600, {c: df[c].to_numpy(float)[keep] for c in ('open', 'high', 'low', 'close')})

    def funding(self, symbol: str) -> Series:
        df = self.block.funding(symbol, self.warmup_days)
        ts = df['time'].to_numpy(np.int64) if len(df) else np.zeros(0, np.int64)
        return Series(ts, ts.copy(), dict(rate=df['funding_rate'].to_numpy(float) if len(df) else np.zeros(0)))


def hourly_from_bars(t_open: np.ndarray, cols: dict[str, np.ndarray], stale: np.ndarray | None = None) -> Series:
    """UTC-hour sums of 1m columns (e.g. volume, taker_buy_volume), usable only once the hour is complete.
    `bars` counts the 1m bars present and `stale_bars` those inside zero-volume padded outages (pass Market.stale), so
    a strategy can skip hours with holes: a clean hour has bars == 60 and stale_bars == 0."""
    t_open = np.asarray(t_open, np.int64)
    if len(t_open) == 0:
        z = np.zeros(0, np.int64)
        return Series(z, z.copy(), {**{k: np.zeros(0) for k in cols}, 'bars': np.zeros(0), 'stale_bars': np.zeros(0)})
    hr = t_open // 3600
    first = np.r_[0, np.flatnonzero(np.diff(hr)) + 1]
    start = hr[first] * 3600
    vals = {k: np.add.reduceat(np.asarray(v, float), first) for k, v in cols.items()}
    vals['bars'] = np.diff(np.r_[first, len(t_open)]).astype(float)
    st = np.zeros(len(t_open)) if stale is None else np.asarray(stale, float)
    vals['stale_bars'] = np.add.reduceat(st, first)
    return Series(start, start + 3600, vals)
