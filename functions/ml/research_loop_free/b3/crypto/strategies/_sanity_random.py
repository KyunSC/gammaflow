"""Sanity only: one random-side market entry per UTC day at a random minute, stop = target = stop_pct of price,
held at most 24h. Accounting check: mean net R ~ -cost, gross R ~ 0."""
import numpy as np

from eval.engine import Signal, end_by_time, run_starts


def signals(m, feats, params):
    rng = np.random.default_rng(params["seed"])
    out = []
    first = run_starts(m.t // 86400)
    for a, b in zip(first, np.r_[first[1:], m.n]):
        s = a + int(rng.integers(0, max(1, b - a - 1)))
        side = 1 if rng.random() < 0.5 else -1
        if s + 1 >= m.n:
            continue
        d = params["stop_pct"] / 100 * m.c[s]
        out.append(Signal(s, side, d, d, end_by_time(m, s, 86400)))
    return out
