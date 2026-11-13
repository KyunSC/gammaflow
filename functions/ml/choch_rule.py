"""Change-of-character (CHoCH) swing logic, copied unchanged from PR #16 functions/ml/choch_crypto_study.py
(commit cfb9294, spec hash a680817f1496890a) so the ES/NQ studies use the exact rule the crypto train study used.
Do not edit: test_choch_rule.py checks the copy against PR #16's code when that worktree is present.
"""
from __future__ import annotations

import numpy as np


def swing_points(high: np.ndarray, low: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Boolean swing-high and swing-low flags, levels.js semantics: strictly beyond the k bars before, at least the
    k bars after. Bar j's flag is only knowable at the close of bar j + k."""
    n = len(high)
    is_h, is_l = np.zeros(n, bool), np.zeros(n, bool)
    for j in range(k, n - k):
        before, after = slice(j - k, j), slice(j + 1, j + k + 1)
        is_h[j] = (high[j] > high[before]).all() and (high[j] >= high[after]).all()
        is_l[j] = (low[j] < low[before]).all() and (low[j] <= low[after]).all()
    return is_h, is_l


def choch_events(high: np.ndarray, low: np.ndarray, close: np.ndarray, k: int) -> list[tuple[int, int, float]]:
    """(signal bar, side, stop level before the pad) for every CHoCH, using only swings known at the signal close."""
    is_h, is_l = swing_points(high, low, k)
    hs: list[tuple[int, float]] = []
    ls: list[tuple[int, float]] = []
    fired_h = fired_l = -1
    out = []
    for t in range(len(close)):
        j = t - k  # the swing at bar j becomes known at this bar's close
        if j >= 0:
            if is_h[j]:
                hs.append((j, high[j]))
            if is_l[j]:
                ls.append((j, low[j]))
        if len(hs) < 2 or len(ls) < 2:
            continue
        up = hs[-1][1] > hs[-2][1] and ls[-1][1] > ls[-2][1]
        down = hs[-1][1] < hs[-2][1] and ls[-1][1] < ls[-2][1]
        if up and close[t] < ls[-1][1] and fired_l != ls[-1][0]:
            fired_l = ls[-1][0]
            out.append((t, -1, float(max(hs[-1][1], high[ls[-1][0]: t + 1].max()))))
        elif down and close[t] > hs[-1][1] and fired_h != hs[-1][0]:
            fired_h = hs[-1][0]
            out.append((t, 1, float(min(ls[-1][1], low[hs[-1][0]: t + 1].min()))))
    return out
