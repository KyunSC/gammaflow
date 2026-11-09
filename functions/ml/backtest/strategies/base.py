"""The strategy contract, identical to the JS one (frontend/lib/backtest/strategies/index.js):

    prepare(ds, params) -> state                 precompute series once per run
    warmup(params, ds)  -> int                   first bar the strategy may speak on
    signal(i, state, ds, params, prev) -> -1|0|1 target position after bar i's close

`signal` sees bar i and earlier only by convention, but it cannot act on bar i: the engine fills its answer at
bar i+1's open. `prev` is the target it returned last time, which lets a stateful strategy (hold until the
mid) work without keeping its own position copy.

Keep per-run state in the object `prepare` returns, never on `self`: strategy instances are shared singletons
in the registry, so state on `self` would leak from one run into the next.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    key: str
    default: object
    kind: str = "number"   # number | boolean | select
    min: float | None = None
    max: float | None = None
    options: tuple = ()


class Strategy:
    id: str = ""
    label: str = ""
    family: str = "ta"
    plane: str = "live"        # 'research' strategies need GEX / ML columns
    requires: tuple[str, ...] = ()   # series keys that must not be all NaN (a warning, not an error)
    params: tuple[Param, ...] = ()

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def warmup(self, p: dict, ds) -> int:
        return 0

    def prepare(self, ds, p: dict):
        return None

    def signal(self, i: int, s, ds, p: dict, prev: int) -> int:
        raise NotImplementedError
