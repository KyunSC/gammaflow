"""Costs: slippage in ticks by fill kind and commission per side, in base and stress scenarios. Results in R and $."""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from . import config as C


@lru_cache(maxsize=1)
def _pmf() -> list[tuple[int, int, np.ndarray, np.ndarray]]:
    buckets = json.loads((C.EVAL_DIR / "stop_slip_pmf.json").read_text())["buckets"]
    out = []
    for key, pm in buckets.items():
        a, b = key.split("-")
        lo = int(a[:2]) * 60 + int(a[3:])
        hi = int(b[:2]) * 60 + int(b[3:])
        ks = np.array(sorted(int(x) for x in pm))
        ps = np.array([pm[str(x)] for x in ks], dtype=float)
        out.append((lo, hi, ks, ps / ps.sum()))
    return sorted(out)


def stop_slip_draw(mods: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Extra stop slip in ticks drawn from the bucket of each fill's ET minute (outside buckets: the last one)."""
    pm = _pmf()
    out = np.zeros(len(mods), dtype=float)
    u = rng.random(len(mods))
    for i, m in enumerate(mods):
        ks, ps = next(((k, p) for lo, hi, k, p in pm if lo <= m < hi), (pm[-1][2], pm[-1][3]))
        out[i] = ks[min(np.searchsorted(np.cumsum(ps), u[i], side="right"), len(ks) - 1)]
    return out


def apply(trades: list[dict], scenario: str = "base", seed: int = C.SEED) -> dict[str, np.ndarray]:
    """Net R and $ per trade (1 MES) for `trades` from engine.run. R uses the base-fill risk for both scenarios."""
    if scenario not in ("base", "stress"):
        raise ValueError(scenario)
    n = len(trades)
    if n == 0:
        return {"r": np.zeros(0), "usd": np.zeros(0), "gross_pts": np.zeros(0)}
    slip = C.SLIP_BASE if scenario == "base" else C.SLIP_STRESS
    comm = C.COMMISSION_PER_SIDE if scenario == "base" else C.STRESS_COMMISSION_PER_SIDE
    side = np.array([t["side"] for t in trades], dtype=float)
    ent = np.array([t["entry_ref"] for t in trades])
    ext = np.array([t["exit_ref"] for t in trades])
    risk = np.array([t["risk_pts"] for t in trades])
    s_in = np.array([slip[t["entry_kind"]] for t in trades], dtype=float)
    s_out = np.array([slip[t["exit_kind"]] for t in trades], dtype=float)
    if scenario == "stress" and C.STRESS_STOP_PMF:
        rng = np.random.default_rng(seed)
        ein = np.array([t["entry_kind"] == "stop" for t in trades])
        eout = np.array([t["exit_kind"] == "stop" for t in trades])
        if ein.any():
            s_in[ein] += stop_slip_draw(np.array([t["entry_mod"] for t in trades])[ein], rng)
        if eout.any():
            s_out[eout] += stop_slip_draw(np.array([t["exit_mod"] for t in trades])[eout], rng)
    gross = side * (ext - ent)
    net_pts = gross - (s_in + s_out) * C.TICK
    usd = net_pts * C.POINT_VALUE - 2 * comm
    return {"r": usd / (risk * C.POINT_VALUE), "usd": usd, "gross_pts": gross}
