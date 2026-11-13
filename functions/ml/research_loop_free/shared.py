"""Shared-file writes for the free-data loop (plan rule 3), all under research_loop/.shared.lock.

* mirror_run: every ledger row (sanity and candidate) also goes to research_loop/ledger.jsonl, wrapped as
  {"kind": "external_run", "loop": ..., "row": {...}} so the ES loop's own controller (which counts only
  kind == "candidate" / "sanity") never mistakes it for one of its configurations.
* append_spend / append_closed_row: same pattern as research_loop_daily.controller (re-read under the lock, append
  only, atomic replace, keep the file's own final newline).
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
SHARED = ML / "research_loop"
LOCK = SHARED / ".shared.lock"
LEDGER = SHARED / "ledger.jsonl"
SPEND = SHARED / "data_spend_ledger.json"
CLOSED = SHARED / "CLOSED_IDEAS.md"


class _Lock:
    def __init__(self, lock: Path = LOCK):
        self.lock = lock

    def __enter__(self):
        self.f = open(self.lock, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def mirror_run(row: dict, loop: str, path: Path = LEDGER, lock: Path = LOCK) -> None:
    line = json.dumps({"kind": "external_run", "loop": loop, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "row": row},
                      sort_keys=True, default=float) + "\n"
    with _Lock(lock):
        with open(path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def append_spend(rows: list[dict], path: Path = SPEND, lock: Path = LOCK) -> None:
    with _Lock(lock):
        cur = path.read_text()
        d = json.loads(cur)
        d["rows"] = list(d["rows"]) + list(rows)
        _atomic_write(path, json.dumps(d, indent=1, ensure_ascii=False) + ("\n" if cur.endswith("\n") else ""))


def append_closed_row(row: str, path: Path = CLOSED, lock: Path = LOCK) -> None:
    """Append one markdown table row to CLOSED_IDEAS.md's last table (file must end with a table row)."""
    row = row.strip()
    if not (row.startswith("|") and row.endswith("|")):
        raise ValueError("not a markdown table row")
    with _Lock(lock):
        cur = path.read_text()
        last = cur.rstrip("\n").rsplit("\n", 1)[-1]
        if not last.startswith("|"):
            raise RuntimeError("CLOSED_IDEAS.md does not end with a table row; another loop may be mid-edit")
        _atomic_write(path, cur.rstrip("\n") + "\n" + row + "\n")
