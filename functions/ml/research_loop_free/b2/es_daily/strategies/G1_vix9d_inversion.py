"""G1_vix9d_inversion: trade ES 09:35 -> 15:55 long when ln(VIX9D/VIX) at the prior close is in its upper tail
(short-term panic), short when in its lower tail (prereg/G1_vix9d_inversion.json). series='vix_level' is the
report-only control (x = ln VIX)."""
import math
from collections import deque

import numpy as np


def feature(daily, series):
    if daily is None:
        return None
    v, v9 = daily.get("VIX"), daily.get("VIX9D")
    if series == "inversion":
        if v is None or v9 is None or not v > 0 or not v9 > 0:
            return None
        return math.log(v9 / v)
    if series == "vix_level":
        return math.log(v) if v is not None and v > 0 else None
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
        x = feature(bar["daily"], p.get("series", "inversion"))
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
