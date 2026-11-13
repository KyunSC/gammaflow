"""G4_vrp_direction: long ES 09:35 -> 15:55 when VRP = VIX - RV20 is in its upper tail, short in its lower tail
(prereg/G4_vrp_direction.json). series 'vix_level' / 'neg_rv' are the report-only controls."""
import math
from collections import deque

import numpy as np


def rv(hist, n):
    r = [h["ret"] for h in hist if h["ret"] is not None and h["nyse_skipped"] == 0][-n:]
    if len(r) < n:
        return None
    m = sum(r) / n
    return math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1)) * math.sqrt(252) * 100


def feature(bar, p):
    d = bar["daily"]
    vix = None if d is None else d.get("VIX")
    s = p.get("series", "vrp")
    if s == "vix_level":
        return vix
    r = rv(bar["hist"], p["rv_n"])
    if r is None:
        return None
    if s == "neg_rv":
        return -r
    if s == "vrp":
        return None if vix is None else vix - r
    raise ValueError("unknown series")


def atr20(hist, atr_def):
    rows = hist[-20:]
    if len(rows) < 20:
        return None
    v = [r["tr"] if atr_def == "tr" else r["h"] - r["l"] for r in rows]
    if any(x is None for x in v):
        return None
    return sum(v) / 20.0


class Strategy:
    def __init__(self, params):
        self.p = params
        self.xs = deque(maxlen=params["max_hist"])
        self.day = None

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or bar["day"] == self.day:
            return None
        self.day = bar["day"]
        p = self.p
        x = feature(bar, p)
        if x is None:
            return None
        act = None
        if pos is None and len(self.xs) >= p["min_hist"]:
            h = np.asarray(self.xs)
            hi, lo = float(np.quantile(h, p["q"])), float(np.quantile(h, 1 - p["q"]))
            side = 1 if x >= hi else (-1 if x <= lo else 0)
            atr = atr20(bar["hist"], p["atr_def"])
            if side and atr is not None:
                risk = p["k"] * atr
                c = bar["c"]
                act = {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
        self.xs.append(x)
        return act
