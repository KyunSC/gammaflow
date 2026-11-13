"""E1_tsmom_daily: trade ES 09:35 -> 15:55 in the direction of the past L-session same-contract return
(prereg/E1_tsmom_daily.json). S_L = sum of ret over hist[-L:]; side = sign(S_L), every eligible session; 1:1 bracket
of k x ATR20 (mean of the last 20 hist true ranges) around the 09:30 bar close.

Stateless: everything is computed on slot 0 from bar['hist'] (sessions strictly before today). Entries with
nyse_skipped > 0 count as recorded: their ret spans the missing sessions, so S_L still covers the whole price path."""


def trend_sum(hist, L):
    """Sum of ret over the last L hist entries; None if fewer than L entries or any ret is None."""
    last = hist[-L:]
    if len(last) < L or any(r["ret"] is None for r in last):
        return None
    return sum(r["ret"] for r in last)


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
        self.L = params["L"]

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None or bar["half_day"]:
            return None
        s = trend_sum(bar["hist"], self.L)
        if s is None or s == 0:
            return None
        atr = atr20(bar["hist"], self.p["atr_def"])
        if atr is None:
            return None
        side = 1 if s > 0 else -1
        risk = self.p["k"] * atr
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
