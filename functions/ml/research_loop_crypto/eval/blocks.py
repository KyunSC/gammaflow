"""Block guard for the crypto perp loop: port of crypto_holdout.open_block (MFP branch 416dbd4) with three changes.

1. The test block does not exist here. Asking for it, or for any date on or after TEST_START, raises.
2. Validation opens are counted over every validation row in data/binance/looks.jsonl (shared with MFP), max 5.
3. Appends to looks.jsonl take the shared research_loop lock and are appended atomically (other loops run in parallel).
4. A Block whose window reaches into validation (or past TEST_START) can only be made by open_block, so every read
   of validation data is a logged look (review finding 1). Train-only windows may be built directly for data checks.

shared_lock is not re-entrant: do not call open_block while holding it (a second flock in one process blocks).
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config as C


class HoldoutError(RuntimeError):
    pass


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split('-'))
    ey, em = map(int, end.split('-'))
    out = []
    while (y, m) <= (ey, em):
        out.append(f'{y:04d}-{m:02d}')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def looks(log: Path = C.LOOKS) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text().splitlines() if x.strip()]


@contextmanager
def shared_lock(lock: Path = C.SHARED_LOCK):
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _append_atomic(path: Path, row: dict) -> None:
    """Caller holds the shared lock. Re-read, append our row only, write atomically (temp + fsync + os.replace)."""
    old = path.read_text() if path.exists() else ''
    if old and not old.endswith('\n'):
        old += '\n'
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with open(tmp, 'w') as f:
        f.write(old + json.dumps(row) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def append_jsonl_locked(path: Path, row: dict, lock: Path = C.SHARED_LOCK) -> None:
    with shared_lock(lock):
        _append_atomic(path, row)


def check_before_test(ts) -> None:
    t = pd.Timestamp(ts)
    t = t.tz_localize('UTC') if t.tzinfo is None else t
    if t >= C.TEST_START:
        raise HoldoutError(f'{ts} is on or after the test start {C.TEST_START.date()}')


_OPEN = object()  # only open_block holds this
VALIDATION_START = pd.Timestamp(C.BLOCKS['validation'][0], tz='UTC')


@dataclass
class Block:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    root: Path
    _token: object = None

    def __post_init__(self):
        if self.end > C.TEST_START:
            raise HoldoutError(f'block {self.name!r} ends after the test start')
        if self.end > VALIDATION_START and self._token is not _OPEN:
            raise HoldoutError(f'block {self.name!r} reaches into validation: open it with open_block so the look is logged')

    def _read(self, kind: str, symbol: str, warmup_days: int = 0) -> pd.DataFrame:
        lo = self.start - pd.Timedelta(days=warmup_days)
        frames = []
        for m in months(f'{lo:%Y-%m}', f'{self.end - pd.Timedelta(seconds=1):%Y-%m}'):
            f = self.root / kind / symbol / f'{m}.parquet'
            if not f.exists():
                gappy = f.with_suffix('.gappy.parquet')
                why = 'below the coverage bar' if gappy.exists() else 'not downloaded'
                if kind == 'funding' and not gappy.exists():
                    continue
                raise HoldoutError(f'{symbol} {kind} {m} is {why}')
            frames.append(pd.read_parquet(f))
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        t = df['time']
        df = df[(t >= int(lo.timestamp())) & (t < int(self.end.timestamp()))].reset_index(drop=True)
        if len(df) and df['time'].max() >= int(C.TEST_START.timestamp()):
            raise HoldoutError('loaded a row on or after the test start')
        return df

    def bars(self, symbol: str, warmup_days: int = 0) -> pd.DataFrame:
        return self._read('klines-1m', symbol, warmup_days)

    def funding(self, symbol: str, warmup_days: int = 0) -> pd.DataFrame:
        return self._read('funding', symbol, warmup_days)


@contextmanager
def open_block(name: str, *, purpose: str, spec_hashes: list[str] | None = None, root: Path = C.BINANCE,
               log: Path = C.LOOKS, lock: Path = C.SHARED_LOCK):
    if name == 'test':
        raise HoldoutError('the crypto perp loop never opens the test block')
    if name not in C.BLOCKS:
        raise HoldoutError(f'unknown block {name!r}')
    if not purpose:
        raise HoldoutError("say what the run is for; it goes in the looks log")
    start, end = (pd.Timestamp(x, tz='UTC') for x in C.BLOCKS[name])
    if end > C.TEST_START:
        raise HoldoutError(f'{name} block ends after the test start')
    entry = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'block': name, 'purpose': purpose,
             'specs': list(spec_hashes or []), 'loop': 'crypto_perp'}
    log.parent.mkdir(parents=True, exist_ok=True)
    with shared_lock(lock):  # count and append under one lock so parallel loops cannot both take the 5th look
        prior = [x for x in looks(log) if x['block'] == name]
        if name == 'validation' and len(prior) >= C.MAX_VALIDATION_LOOKS:
            raise HoldoutError(f'validation already opened {len(prior)} times (limit {C.MAX_VALIDATION_LOOKS})')
        _append_atomic(log, entry)
    yield Block(name, start, end, root, _OPEN)
