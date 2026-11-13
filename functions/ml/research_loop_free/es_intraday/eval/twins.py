"""Random-direction twins and the always-long baseline.

A twin keeps each real trade's entry minute, entry price and entry kind (same costs), its initial risk and target
distance, and reassigns the directions at random while keeping the strategy's number of longs (a side-matched
permutation): a long-biased strategy with no timing skill cannot beat it on market drift alone. The 50/50 coin-flip
p is reported for information. It exits on its own stop/target (fixed: trailing moves of
the real trade are not copied) or, failing that, where the real trade exited:
  * real exit at a bar open (market / flat): the twin exits at that same open;
  * real exit inside a bar (stop / target): the twin exits at the next 1m open, or at the session's last close.
Each trade's long and short outcome is computed once, so N twins are N sign draws.
"""
from __future__ import annotations

import numpy as np

from . import config as C
from .costs import apply
from .data import Session
from .engine import check_bar


def _one(s: Session, t: dict, d: int) -> dict:
    ref, risk = t["entry_ref"], t["risk_pts"]
    stop = ref - d * risk
    target = None if t["target"] is None else ref + d * abs(t["target"] - ref)
    j0, j1 = t["j_entry"], t["j_exit"]
    intrabar = t["exit_kind"] in ("stop", "target")
    last = j1 if intrabar else j1 - 1
    kind, xref, jx = None, None, None
    for j in range(j0, last + 1):
        first = j == j0
        o = ref if (first and not t["at_open"]) else s.o[j]
        r = check_bar(o, s.h[j], s.l[j], d, stop, target, allow_target=(not first) or t["at_open"])
        if r is not None:
            kind, xref, jx = r[0], r[1], j
            break
    if kind is None:
        if not intrabar:
            kind, xref, jx = t["exit_kind"], t["exit_ref"], j1  # the open of bar j1 (or the data-gap close)
        elif j1 + 1 < len(s.o):
            kind, xref, jx = "market", s.o[j1 + 1], j1 + 1
        else:
            kind, xref, jx = "flat", s.c[-1], j1
    return {**t, "side": d, "stop_init": stop, "target": target, "exit_kind": kind, "exit_ref": float(xref),
            "j_exit": jx, "exit_mod": int(s.mod[jx])}


def long_short_r(sessions: list[Session], trades: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Base-cost net R of every trade taken long and taken short by its twin."""
    longs = [_one(sessions[t["si"]], t, 1) for t in trades]
    shorts = [_one(sessions[t["si"]], t, -1) for t in trades]
    return apply(longs, "base")["r"], apply(shorts, "base")["r"]


def twin_test(real_r: np.ndarray, r_long: np.ndarray, r_short: np.ndarray, sides, n: int = C.N_TWINS,
              seed: int = C.SEED, chunk: int = 2000) -> dict:
    """One-sided p that a side-matched random-direction twin's mean net R is >= the real mean (the gate), plus
    the 50/50 coin-flip p (information)."""
    if len(real_r) == 0:
        return {"p": 1.0, "p_coin": 1.0, "twin_mean": 0.0, "twin_sd": 0.0, "always_long": 0.0,
                "always_short": 0.0, "long_share": float("nan"), "n_twins": n}
    is_long = np.asarray(sides) > 0
    real = float(real_r.mean())
    rng = np.random.default_rng(seed)
    ge = ge_coin = 0
    means = []
    for start in range(0, n, chunk):
        k = min(chunk, n - start)
        perm = rng.permuted(np.tile(is_long, (k, 1)), axis=1)
        m = np.where(perm, r_long, r_short).mean(axis=1)
        means.append(m)
        ge += int((m >= real - 1e-12).sum())
        coin = rng.random((k, len(real_r))) < 0.5
        ge_coin += int((np.where(coin, r_long, r_short).mean(axis=1) >= real - 1e-12).sum())
    means = np.concatenate(means)
    return {"p": (1 + ge) / (1 + n), "p_coin": (1 + ge_coin) / (1 + n), "twin_mean": float(means.mean()),
            "twin_sd": float(means.std()), "always_long": float(r_long.mean()), "always_short": float(r_short.mean()),
            "long_share": float(is_long.mean()), "n_twins": n}
