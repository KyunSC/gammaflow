"""D1_daily_reversal: trade ES 09:35 -> 15:55 against a large prior L-day same-contract close-to-close return
(prereg/D1_daily_reversal.json). z = R_L / (sd20 * sqrt(L)); |z| >= Z -> side = -sign(z); 1:1 bracket of
k x ATR20 (mean of the last 20 hist true ranges) around the 09:30 bar close.

Stateless: everything is computed on slot 0 from bar['hist'] (sessions strictly before today), so it never depends
on past trades or on any intraday bar except the 09:30 close used as the bracket centre."""
import math


def _sd(xs):
    n = len(xs)
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _usable(r):
    return r["ret"] is not None and r["nyse_skipped"] == 0


def zscore(hist, L, n_sd, min_sd):
    """z of the last L hist returns vs the sd of the usable returns in hist[-n_sd:]; None when not computable."""
    last = hist[-L:]
    if len(last) < L or not all(_usable(r) for r in last):
        return None
    win = [r["ret"] for r in hist[-n_sd:] if _usable(r)]
    if len(win) < min_sd:
        return None
    sd = _sd(win)
    if not sd > 0:
        return None
    R = 1.0
    for r in last:
        R *= 1.0 + r["ret"]
    return (R - 1.0) / (sd * math.sqrt(L))


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
        self.L = params["cfg"]["L"]
        self.Z = params["cfg"]["Z"]

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None or bar["half_day"]:
            return None
        p = self.p
        z = zscore(bar["hist"], self.L, p["n_sd"], p["min_sd"])
        if z is None or z == 0 or abs(z) < self.Z:
            return None
        atr = atr20(bar["hist"], p["atr_def"])
        if atr is None:
            return None
        side = -1 if z > 0 else 1
        risk = p["k"] * atr
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
