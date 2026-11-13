"""D2_monthend_rebalance: on the last N scheduled sessions of the month, trade ES 09:35 -> 15:55 AGAINST the
month-to-date equity-minus-bond return X = mtd.ret + duration x mtd.dy10 / 100 (prereg/D2_monthend_rebalance.json):
X > 0 (equities ahead -> rebalancers sell) -> short; X < 0 -> long. Optional scale-free size cut |z| >= zmin with
z = X / (sd20 x sqrt(n)). 1:1 bracket of k x ATR20 around the 09:30 close.

Stateless: computed on slot 0 from bar['mtd'], bar['sessions_left_in_month'] and bar['hist'] only."""
import math


def _sd(xs):
    n = len(xs)
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def signal_x(mtd, duration):
    if mtd is None or mtd["dy10"] is None:
        return None
    return mtd["ret"] + duration * mtd["dy10"] / 100.0


def zscore(x, mtd, hist, n_sd, min_sd):
    win = [r["ret"] for r in hist[-n_sd:] if r["ret"] is not None and r["nyse_skipped"] == 0]
    if len(win) < min_sd:
        return None
    sd = _sd(win)
    n = sum(1 for r in hist if r["day"] > mtd["base_day"])
    if not sd > 0 or n < 1:
        return None
    return x / (sd * math.sqrt(n))


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
        self.N = params["cfg"]["N"]
        self.zmin = params["cfg"]["zmin"]

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None or bar["half_day"]:
            return None
        left = bar["sessions_left_in_month"]
        if left is None or left > self.N - 1:
            return None
        p = self.p
        x = signal_x(bar["mtd"], p["bond_duration"])
        if x is None or x == 0:
            return None
        if self.zmin > 0:
            z = zscore(x, bar["mtd"], bar["hist"], p["n_sd"], p["min_sd"])
            if z is None or abs(z) < self.zmin:
                return None
        atr = atr20(bar["hist"], p["atr_def"])
        if atr is None:
            return None
        side = -1 if x > 0 else 1
        risk = p["k"] * atr
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
