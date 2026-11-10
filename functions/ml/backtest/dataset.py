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


# Epoch seconds between 1973-03 and 2100: catches milliseconds (x1000) and a RangeIndex read as time (0, 1, 2...)
# while still taking long daily histories (SPY from 1993).
_EPOCH_RANGE = (1e8, 4.1e9)


def _frozen(a) -> np.ndarray:
    """A read-only float64 copy. Derived series are memoised per dataset, so the bars must not change under them."""
    out = np.array(a, dtype=np.float64)
    out.setflags(write=False)
    return out


@dataclass(eq=False)
class Dataset:
    """Bars as read-only numpy columns. To change prices, build a new Dataset: the memoised indicator cache
    belongs to one set of bars, which is why the columns are frozen and `dataclasses.replace` starts a fresh one."""
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
    # Memoised derived series (see series.get_series). Never passed in, so replace() cannot share it.
    cache: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        for k in ("time", "open", "high", "low", "close", "volume"):
            setattr(self, k, _frozen(getattr(self, k)))
        n = len(self.close)
        if n < 2:
            raise ValueError("dataset needs at least two bars")
        for k in ("time", "open", "high", "low", "volume"):
            if len(getattr(self, k)) != n:
                raise ValueError(f"column {k} has {len(getattr(self, k))} rows, close has {n}")
        t = self.time
        if not np.all(np.isfinite(t)) or t[0] < _EPOCH_RANGE[0] or t[-1] > _EPOCH_RANGE[1]:
            raise ValueError("time must be epoch seconds (UTC bar open); got values outside 1973-2100, "
                             "milliseconds or a row number?")
        if np.any(np.diff(t) <= 0):
            raise ValueError("timestamps must be strictly increasing")
        # Same rules as the JS validateDataset: a NaN price would be filled at 0 or silently poison every
        # running indicator after it, so it is refused here instead.
        o, h, l, c = self.open, self.high, self.low, self.close
        bad = ~(np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c))
        if bad.any():
            raise ValueError(f"{int(bad.sum())} bars have NaN/inf prices (first at row {int(np.argmax(bad))}); "
                             "drop or fill them first")
        bad = (l <= 0) | (l > np.minimum(o, c)) | (h < np.maximum(o, c))
        if bad.any():
            raise ValueError(f"invalid OHLC at row {int(np.argmax(bad))}: need 0 < low <= open, close <= high")
        if np.any(self.volume < 0) or np.any(np.isinf(self.volume)):
            # NaN is allowed (missing volume, counted as 0 by VWAP); inf would turn VWAP NaN for the rest of the day
            raise ValueError("negative or infinite volume")
        for group in (self.features, self.ml):
            for k, v in group.items():
                group[k] = _frozen(v)
                if len(group[k]) != n:
                    raise ValueError(f"column {k!r} has {len(group[k])} rows, the bars have {n}")

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
    def from_frame(cls, df: pd.DataFrame, interval: str, symbol: str = "", features: dict | None = None,
                   **kw) -> "Dataset":
        """From a DataFrame with open/high/low/close/volume columns (any case) and either a tz-aware
        DatetimeIndex or a `time` column (tz-aware timestamps or epoch seconds). Other numeric columns become
        `features`, plus any passed in `features`."""
        if interval not in INTERVAL_SECONDS and interval not in ("2m", "1wk", "1mo"):
            raise ValueError(f"unknown interval {interval!r}")
        df = df.rename(columns=str.lower)
        if "time" in df.columns:
            t = df["time"]
        elif isinstance(df.index, pd.DatetimeIndex):
            t = df.index
        else:
            raise ValueError("need a DatetimeIndex or a 'time' column")
        if pd.api.types.is_datetime64_any_dtype(t):
            idx = pd.DatetimeIndex(t)
            if idx.tz is None:
                raise ValueError("naive timestamps: tz_localize them first (UTC vs ET is otherwise a guess)")
            time = idx.as_unit("s").asi8.astype(np.float64)
        else:
            time = np.asarray(t, dtype=np.float64)   # epoch seconds; __post_init__ rejects ms or row numbers
        ohlcv = ["open", "high", "low", "close", "volume"]
        missing = [c for c in ohlcv if c not in df.columns]
        if missing:
            raise ValueError(f"missing columns {missing}")
        extra = [c for c in df.columns if c not in ohlcv and c != "time" and pd.api.types.is_numeric_dtype(df[c])]
        feats = {c: df[c].to_numpy(np.float64) for c in extra}
        feats.update(features or {})
        return cls(time=time, **{c: df[c].to_numpy(np.float64) for c in ohlcv}, interval=interval, symbol=symbol,
                   features=feats, **kw)
