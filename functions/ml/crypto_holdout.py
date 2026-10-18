"""Train / validation / test blocks for the MyFundedPerps crypto study, and the guard every crypto study loads through.

    [ train 2020-01-01 → 2024-06-30 ][ 7d ][ validation 2024-07-08 → 2025-06-30 ][ 7d ][ test 2025-07-08 → 2026-09-30 ]

Plan: /mnt/project-files/studies/myfundedperps/PLAN.md, section 6. Nobody in this project has backtested crypto bars
over these dates, which is why crypto gets a historical test at all (the index history is spent or reserved).

    train       explore freely; every open is logged
    validation  cut the candidates to at most 3 frozen specs; at most MAX_VALIDATION_LOOKS opens, ever
    test        one open, ever, scoring every frozen spec together; needs the specs' hashes, which are logged

The embargoes cover the longest planned hold (72h) plus slack. Blocks end at fixed dates, so data ingested later never
leaks in. A block refuses to load if a month it needs is missing or below the downloader's coverage bar.

    with open_block("train", purpose="C1 daily trend grid") as b:
        bars = b.bars("BTCUSDT")
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from binance_fetch import OUT_ROOT, months

BLOCKS = {
    "train": ("2020-01-01", "2024-07-01"),
    "validation": ("2024-07-08", "2025-07-01"),
    "test": ("2025-07-08", "2026-10-01"),
}
EMBARGO_DAYS = 7
MAX_VALIDATION_LOOKS = 5
LOOKS = OUT_ROOT.parent / "looks.jsonl"


class HoldoutError(RuntimeError):
    pass


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def looks(log: Path = LOOKS) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


@dataclass
class Block:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    root: Path

    def _months(self) -> list[str]:
        last = self.end - pd.Timedelta(seconds=1)
        return months(f"{self.start:%Y-%m}", f"{last:%Y-%m}")

    def _read(self, kind: str, symbol: str, warmup_days: int = 0) -> pd.DataFrame:
        lo = self.start - pd.Timedelta(days=warmup_days)
        frames = []
        for m in months(f"{lo:%Y-%m}", f"{self.end - pd.Timedelta(seconds=1):%Y-%m}"):
            f = self.root / kind / symbol / f"{m}.parquet"
            if not f.exists():
                gappy = f.with_suffix(".gappy.parquet")
                why = "below the coverage bar" if gappy.exists() else "not downloaded"
                if kind == "funding" and not gappy.exists():
                    continue  # funding history starts later than klines for some symbols
                raise HoldoutError(f"{symbol} {kind} {m} is {why}; run binance_fetch.py")
            frames.append(pd.read_parquet(f))
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        t = df["time"]
        return df[(t >= int(lo.timestamp())) & (t < int(self.end.timestamp()))].reset_index(drop=True)

    def bars(self, symbol: str, warmup_days: int = 0) -> pd.DataFrame:
        """1m bars inside the block. `warmup_days` prepends earlier bars for indicators; a study must not trade them."""
        return self._read("klines-1m", symbol, warmup_days)

    def funding(self, symbol: str, warmup_days: int = 0) -> pd.DataFrame:
        return self._read("funding", symbol, warmup_days)


@contextmanager
def open_block(name: str, *, purpose: str, spec_hashes: list[str] | None = None, root: Path = OUT_ROOT, log: Path = LOOKS):
    """Open a block for one run. Validation and test opens are counted against their limits and logged first."""
    if name not in BLOCKS:
        raise HoldoutError(f"unknown block {name!r}")
    if not purpose:
        raise HoldoutError("say what the run is for; it goes in the looks log")
    prior = [x for x in looks(log) if x["block"] == name]
    if name == "validation" and len(prior) >= MAX_VALIDATION_LOOKS:
        raise HoldoutError(f"validation already opened {len(prior)} times (limit {MAX_VALIDATION_LOOKS}); freeze the specs")
    if name == "test":
        if prior:
            raise HoldoutError(f"the test block was already scored on {prior[0]['at']} ({prior[0]['purpose']}); it gets one look")
        if not spec_hashes:
            raise HoldoutError("the test block needs the frozen specs' hashes")
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "block": name, "purpose": purpose,
             "specs": list(spec_hashes or [])}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    start, end = BLOCKS[name]
    yield Block(name, _ts(start), _ts(end), root)
