"""Pinned SHA-256 manifest of the frozen crypto evaluator, its tests, the out-of-package code it imports, and every
train/validation data file its loaders can read. Pattern of research_loop/eval/manifest.py.

The controller calls verify() before every run and refuses on any mismatch, missing or extra file.
Data files dated on or after the validation end (2025-07-01) are outside the set: no loader reads them.
"""
from __future__ import annotations

import hashlib
import platform
import re
from pathlib import Path

from . import config as C

MANIFEST = C.EVAL / 'MANIFEST.sha256'
LAST = '2025-07-01'           # validation end (exclusive); every tracked data file is dated before it
OUTSIDE = (C.LOOP / 'fetch_free.py', C.ML / 'flybrain' / '__init__.py', C.ML / 'flybrain' / 'config.py')


class HashMismatch(RuntimeError):
    pass


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


DATE = re.compile(r'(\d{4}-\d{2}(?:-\d{2})?)')


def _dated_before(p: Path, last: str = LAST) -> bool:
    m = DATE.findall(p.name)
    if not m:
        return False
    d = m[-1]
    return (d + '-01' if len(d) == 7 else d) < last


def data_files(binance: Path = C.BINANCE, raw: Path = C.RAW) -> list[Path]:
    out = []
    for kind in ('klines-1m', 'funding'):
        out += [p for p in sorted((binance / kind).glob('*/*.parquet')) if _dated_before(p)]
    out += [p for p in sorted((raw / 'metrics').glob('*/*.zip')) if _dated_before(p)]
    for src in ('premiumIndexKlines', 'markPriceKlines', 'indexPriceKlines'):
        out += [p for p in sorted((raw / src).glob('*/*.zip')) if _dated_before(p)]
        out += [p for p in sorted((raw / src).glob('*/daily/*.zip')) if _dated_before(p)]
    out += [p for p in sorted((raw / 'coinbase').glob('*/*.csv.gz')) if _dated_before(p)]
    out += sorted((raw / 'dvol').glob('*.csv.gz'))  # one file per currency, rows end 2025-07-07 23:00
    return out


def tracked(eval_dir: Path = C.EVAL, loop: Path = C.LOOP) -> list[Path]:
    files = sorted(p for p in eval_dir.rglob('*') if p.is_file() and p.suffix in ('.py', '.json')
                   and '__pycache__' not in p.parts)
    files += [f for f in OUTSIDE if f.exists()]
    files += sorted((loop / 'tests').glob('*.py'))
    return files + data_files()


def env_key() -> str:
    import numpy
    import pandas
    import pyarrow
    return f'env:python={platform.python_version()} numpy={numpy.__version__} pandas={pandas.__version__} pyarrow={pyarrow.__version__}'


def compute(files: list[Path], root: Path = C.ML, env: bool = True) -> dict[str, str]:
    out = {str(p.relative_to(root)): sha256(p) for p in files}
    if env:
        k = env_key()
        out[k] = hashlib.sha256(k.encode()).hexdigest()
    return out


def write(path: Path = MANIFEST, files: list[Path] | None = None, root: Path = C.ML, env: bool = True) -> str:
    entries = compute(files if files is not None else tracked(), root, env)
    text = ''.join(f'{h}  {k}\n' for k, h in sorted(entries.items()))
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def read(path: Path = MANIFEST) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        h, k = line.split('  ', 1)
        out[k] = h
    return out


def verify(path: Path = MANIFEST, files: list[Path] | None = None, root: Path = C.ML,
           expect_digest: str | None = None, env: bool = True) -> str:
    """Return the manifest digest; raise HashMismatch if anything differs from the pinned hashes."""
    if not path.exists():
        raise HashMismatch(f'{path} missing: evaluator not frozen')
    text = path.read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()
    if expect_digest is not None and digest != expect_digest:
        raise HashMismatch(f'manifest digest {digest[:16]} != pinned {expect_digest[:16]}')
    pinned = read(path)
    now = compute(files if files is not None else tracked(), root, env)
    problems = [f'changed {k}' for k in pinned if k in now and now[k] != pinned[k]]
    problems += [f'missing {k}' for k in pinned if k not in now]
    problems += [f'unpinned {k}' for k in now if k not in pinned]
    if problems:
        raise HashMismatch('; '.join(problems[:10]) + (f' (+{len(problems) - 10} more)' if len(problems) > 10 else ''))
    return digest
