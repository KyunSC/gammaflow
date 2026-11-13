"""F3_yield_shock: trade ES 09:35 -> 15:55 against the prior session's z-scored 10y yield change
(prereg/F3_yield_shock.json). Stateless: computed on slot 0 from bar['hist'] only."""
import math


def deltas(hist):
    out = []
    for a, b in zip(hist[:-1], hist[1:]):
        if a["ust10y"] is not None and b["ust10y"] is not None:
            out.append(b["ust10y"] - a["ust10y"])
    return out


def zscore(hist, min_deltas):
    if len(hist) < 2 or hist[-1]["ust10y"] is None or hist[-2]["ust10y"] is None:
        return None
    d = deltas(hist[-60:])
    if len(d) < min_deltas:
        return None
    m = sum(d) / len(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))
    if not sd > 0:
        return None
    return (hist[-1]["ust10y"] - hist[-2]["ust10y"]) / sd


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

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None:
            return None
        p = self.p
        z = zscore(bar["hist"], p["min_deltas"])
        if z is None or z == 0 or abs(z) < p["Z"]:
            return None
        atr = atr20(bar["hist"], p["atr_def"])
        if atr is None:
            return None
        side = -1 if z > 0 else 1
        risk = p["k"] * atr
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
