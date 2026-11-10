"""Scheduled-news blackout flags. Port of frontend/lib/backtest/news.js.

The calendar itself is functions/ml/econ_calendar.py, which also generates the JS copy
(frontend/lib/backtest/newsCalendar.js), so both engines read identical events. Bars past the calendar's
coverage are NaN ("unknown"), never 0: a run on fresh data must not silently read as "no news".
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

from .clock import INTERVAL_SECONDS

try:
    import econ_calendar as ec
except ModuleNotFoundError:  # imported from outside functions/ml: the calendar module sits next to the package
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import econ_calendar as ec

IMPACT_RANK = ec.IMPACT_RANK


@lru_cache(maxsize=None)
def _calendar(min_impact: str):
    """(sorted event epochs, coverage end) for event types at or above `min_impact`."""
    types = ec._selected(min_impact, None)
    ev = np.array(sorted(e.ts for e in ec.events(min_impact)), dtype=np.float64)
    return ev, float(min(ec._cover_end(k) for k in types))


def bar_seconds(ds) -> float:
    """Bar length: the interval label, else the median spacing of the first 200 bars."""
    known = INTERVAL_SECONDS.get(ds.interval)
    if known:
        return known
    gaps = np.sort(np.diff(ds.time[:200]))
    return float(gaps[len(gaps) >> 1]) if len(gaps) else 300.0


def news_window_flags(ds, min_impact: str = "high", before_min: float = 5, after_min: float = 15) -> np.ndarray:
    """1 where bar [t, t + bar) overlaps an event window [event - before, event + after), 0 where it does not,
    NaN past coverage."""
    ev, cover_end = _calendar(min_impact)
    t = ds.time
    bar = bar_seconds(ds)
    before = before_min * 60
    after = max(after_min * 60, 1)   # a release is an instant; a 0/0 window still marks the bar it prints in
    j = np.searchsorted(ev, t - after, side="right")   # first window ending after the bar starts
    ok = j < len(ev)
    out = np.zeros(len(t))
    out[ok] = (ev[j[ok]] - before < t[ok] + bar).astype(np.float64)
    out[t >= cover_end] = np.nan
    return out


def news_blackout_flags(flags: np.ndarray, start: int = 0, stop: int | None = None):
    """Engine flags from `news_window_flags`. `blocked[i]`: the next bar is in a window, so an order placed at
    bar i's close would be held through news. `end[i]`: the first such bar, where an open position is closed.
    `no_entry[i]`: the bar before `end`, where a new position would be opened only to be closed one bar later.
    Returns (end, blocked, no_entry, uncovered bars in [start, stop])."""
    n = len(flags)
    stop = n - 1 if stop is None else stop
    nxt = np.r_[flags[1:], 0.0] == 1
    blocked = nxt.copy()
    end = blocked & (flags != 1)
    no_entry = np.zeros(n, dtype=bool)
    no_entry[:-1] = end[1:]
    uncovered = int(np.isnan(flags[start:stop + 1]).sum())
    return end, blocked, no_entry, uncovered
