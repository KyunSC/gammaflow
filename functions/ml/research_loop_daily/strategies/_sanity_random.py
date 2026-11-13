"""Accounting check only: a random-direction market entry decided on the 09:30 bar (fills at the 09:35 open),
1:1 bracket of k x ATR20 (mean of the last 20 bar['hist'] true ranges) around the 09:30 close, flat 15:55: the plan's
trade shape. Expected mean R ~ -cost. With need_all, it trades only when bar['mtd'], bar['daily']['UST10Y'] and
bar['sessions_left_in_month'] are present too, which shows the new keys reach the strategy process."""
import numpy as np


class Strategy:
    def __init__(self, params):
        self.rng = np.random.default_rng(params["seed"])
        self.k = params["k"]
        self.need_all = params.get("need_all", False)

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None:
            return None
        side = 1 if self.rng.random() < 0.5 else -1
        h = bar["hist"][-20:]
        if len(h) < 20 or any(r["tr"] is None for r in h):
            return None
        if self.need_all and (bar["mtd"] is None or bar["daily"] is None or bar["daily"]["UST10Y"] is None
                              or bar["sessions_left_in_month"] is None):
            return None
        risk = self.k * float(np.mean([r["tr"] for r in h]))
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
