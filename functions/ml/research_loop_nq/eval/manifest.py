"""Pinned SHA-256 manifest of the frozen evaluator, its tests and the NQ + ES data files it reads.

The controller calls verify() before every run and refuses on any mismatch, missing or extra file.
"""
from __future__ import annotations

import hashlib
import platform
import re
from datetime import date
from pathlib import Path

from . import config as C

MANIFEST = C.EVAL_DIR / "MANIFEST.sha256"
TESTS = C.LOOP_DIR / "tests" / "test_eval.py"


class HashMismatch(RuntimeError):
    pass


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


SPAN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.parquet$")


def tracked(eval_dir: Path = C.EVAL_DIR, tests: Path = TESTS,
            bars: tuple[Path, ...] = (C.BARS_DIR / C.PRODUCT, C.BARS_DIR / C.COMPANION),
            root: Path = C.ML) -> list[Path]:
    """Evaluator code + snapshots, the package __init__ files on its import path, the tests, and the NQ and ES (companion) parquet
    files the splits can read (a later holdout purchase is outside this set by date)."""
    files = sorted(p for p in eval_dir.rglob("*") if p.is_file() and p.suffix in (".py", ".json")
                   and "__pycache__" not in p.parts)
    files += [f for f in (C.LOOP_DIR / "__init__.py", tests.parent / "__init__.py", tests) if f.exists()]
    for f in sorted(f for d in bars for f in d.glob("*.parquet")):
        m = SPAN.search(f.name)
        if m and date.fromisoformat(m[1]) <= C.LAST_ON_DISK:
            files.append(f)
    return files


def env_key() -> str:
    import numpy
    import pandas
    import pyarrow
    return f"env:python={platform.python_version()} numpy={numpy.__version__} pandas={pandas.__version__} pyarrow={pyarrow.__version__}"


def compute(files: list[Path], root: Path = C.ML, env: bool = True) -> dict[str, str]:
    out = {str(p.relative_to(root)): sha256(p) for p in files}
    if env:
        k = env_key()
        out[k] = hashlib.sha256(k.encode()).hexdigest()
    return out


def write(path: Path = MANIFEST, files: list[Path] | None = None, root: Path = C.ML, env: bool = True) -> str:
    entries = compute(files if files is not None else tracked(), root, env)
    text = "".join(f"{h}  {k}\n" for k, h in sorted(entries.items()))
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def read(path: Path = MANIFEST) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        h, k = line.split("  ", 1)
        out[k] = h
    return out


def verify(path: Path = MANIFEST, files: list[Path] | None = None, root: Path = C.ML,
           expect_digest: str | None = None, env: bool = True) -> str:
    """Return the manifest digest; raise HashMismatch if anything differs from the pinned hashes."""
    if not path.exists():
        raise HashMismatch(f"{path} missing: evaluator not frozen")
    text = path.read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()
    if expect_digest is not None and digest != expect_digest:
        raise HashMismatch(f"manifest digest {digest[:16]} != pinned {expect_digest[:16]}")
    pinned = read(path)
    now = compute(files if files is not None else tracked(), root, env)
    problems = [f"changed {k}" for k in pinned if k in now and now[k] != pinned[k]]
    problems += [f"missing {k}" for k in pinned if k not in now]
    problems += [f"unpinned {k}" for k in now if k not in pinned]
    if problems:
        raise HashMismatch("; ".join(problems[:10]) + (f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""))
    return digest
