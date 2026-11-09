"""Columnar bar data: the one shape the engine accepts.

The JS engine works on parallel Float64Arrays; this is the same idea with numpy arrays. Times are epoch
seconds (bar open, UTC). `features` holds exported research columns (GEX and baseline features), `ml` the
walk-forward model predictions. Both are optional; strategies that need them read NaN when they are absent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .clock import INTERVAL_SECONDS


def _f64(values) -> np.ndarray:
    """Float64 array with JSON nulls as NaN (the export writes NaN as null)."""
    return np.array([np.nan if v is None else v for v in values], dtype=np.float64)


@dataclass(eq=False)
class Dataset:
    time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    interval: str = "5m"
    symbol: str = ""
    id: str = ""
    features: dict = field(default_factory=dict)
    ml: dict = field(default_factory=dict)
    synthetic: bool = False
    # Memoised derived series (see series.get_series). Not part of equality or repr.
    cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for k in ("time", "open", "high", "low", "close", "volume"):
            setattr(self, k, np.ascontiguousarray(getattr(self, k), dtype=np.float64))
        n = len(self.close)
        if n < 2:
            raise ValueError("dataset needs at least two bars")
        for k in ("time", "open", "high", "low", "volume"):
            if len(getattr(self, k)) != n:
                raise ValueError(f"column {k} has {len(getattr(self, k))} rows, close has {n}")
        if np.any(np.diff(self.time) <= 0):
            raise ValueError("timestamps must be strictly increasing")

    def __len__(self) -> int:
        return len(self.close)

    @classmethod
    def from_json(cls, path) -> "Dataset":
        """Load a research artifact in the format of frontend/public/backtest/*.json (export_backtest_data.py)."""
        j = json.loads(Path(path).read_text())
        ml = {}
        if j.get("ml"):
            ml = {"pred": _f64(j["ml"]["pred"]), "target": _f64(j["ml"]["target_return"])}
        return cls(time=_f64(j["time"]), open=_f64(j["open"]), high=_f64(j["high"]), low=_f64(j["low"]),
                   close=_f64(j["close"]), volume=_f64(j["volume"]), interval=j["interval"], symbol=j["symbol"],
                   id=f"{j['symbol']}:{j['interval']}:{j.get('generatedAt', '')}",
                   features={k: _f64(v) for k, v in (j.get("features") or {}).items()},
                   ml=ml, synthetic=bool(j.get("synthetic")))

    @classmethod
    def from_frame(cls, df: pd.DataFrame, interval: str, symbol: str = "", **kw) -> "Dataset":
        """From a DataFrame with open/high/low/close/volume columns and either a tz-aware DatetimeIndex or a
        `time` column (tz-aware timestamps or epoch seconds). Extra numeric columns become `features`."""
        if interval not in INTERVAL_SECONDS and interval not in ("1wk", "1mo"):
            raise ValueError(f"unknown interval {interval!r}")
        t = df["time"] if "time" in df.columns else df.index
        if isinstance(t, (pd.DatetimeIndex, pd.Series)) and pd.api.types.is_datetime64_any_dtype(t):
            idx = pd.DatetimeIndex(t)
            if idx.tz is None:
                raise ValueError("naive timestamps: tz_localize them first (UTC vs ET is otherwise a guess)")
            time = idx.as_unit("s").asi8.astype(np.float64)
        else:
            time = np.asarray(t, dtype=np.float64)
        ohlcv = ["open", "high", "low", "close", "volume"]
        extra = [c for c in df.columns if c not in ohlcv and c != "time" and pd.api.types.is_numeric_dtype(df[c])]
        return cls(time=time, **{c: df[c].to_numpy(np.float64) for c in ohlcv}, interval=interval, symbol=symbol,
                   features={c: df[c].to_numpy(np.float64) for c in extra}, **kw)
