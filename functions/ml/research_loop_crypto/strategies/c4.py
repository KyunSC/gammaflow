"""C4, US-open range breakout (MFP spec, hash 422d4919183d40e8). Verbatim port of mfp_crypto_study.signals_c4,
used for evaluator parity only. The loop never re-runs C4 on train for research or changes its spec."""
from __future__ import annotations

import numpy as np

from eval.engine import Market, Signal, run_starts


def signals_c4(mk: Market, stop: str, m: float) -> list[Signal]:
    out = []
    first = run_starts(mk.ny_date)
    for a, b in zip(first, np.r_[first[1:], mk.n]):
        if mk.ny_dow[a] >= 5:
            continue
        mins = mk.ny_min[a:b]
        rng = np.flatnonzero((mins >= 570) & (mins < 600)) + a
        if len(rng) != 30:
            continue
        hi, lo = mk.h[rng].max(), mk.l[rng].min()
        win = np.flatnonzero((mins >= 600) & (mins < 900)) + a
        out_side = np.sign((mk.c[win] > hi).astype(int) - (mk.c[win] < lo).astype(int))
        hit = np.flatnonzero(out_side)
        flat = np.flatnonzero(mins < 960)
        if not len(hit) or not len(flat):
            continue
        s, side = int(win[hit[0]]), int(out_side[hit[0]])
        ref = lo if side > 0 else hi
        level = ref if stop == "opposite" else (hi + lo) / 2
        dist = abs(mk.c[s] - level)
        if dist > 0:
            out.append(Signal(s, side, dist, m * dist, int(flat[-1] + a)))
    return out
