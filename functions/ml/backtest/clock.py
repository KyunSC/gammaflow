"""Session clock. Port of frontend/lib/backtest/time.js.

Named `clock` rather than `time` so it can never shadow the standard library module.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def trading_day(t):
    """Trading-day number for epoch seconds (scalar or array).

    The day rolls at 22:00 UTC, not midnight. That lands inside CME's daily halt in both EDT and EST,
    so an 18:00-17:00 ET Globex session is one day, and it sits after the equity close, so RTH days
    are unchanged.
    """
    return np.floor((np.asarray(t, dtype=np.float64) + 7200) / 86400).astype(np.int64)


def et_minute_of_day(t) -> np.ndarray:
    """Minute of the New York wall-clock day (0-1439) for each epoch-second time."""
    ts = pd.to_datetime(np.asarray(t, dtype=np.float64), unit="s", utc=True).tz_convert("America/New_York")
    return np.asarray(ts.hour * 60 + ts.minute, dtype=np.int64)
