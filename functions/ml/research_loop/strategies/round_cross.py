"""round_cross: trade in the direction of a decisive 5m close through a round number (prereg/round_cross.json)."""
import math


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.prev_c = None
        self.used = set()

    def news_due(self, bar):
        end = bar["mod"] + 5
        return any(end <= m <= end + self.p["news_before"] for m in bar["news"])

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self.day = bar["day"]
            self.prev_c = None
            self.used = set()
        c, pc = bar["c"], self.prev_c
        act = None
        if pos is not None:
            if pos["bars_held"] + 1 >= p["hold_bars"]:  # entry bar + 11 more completed = 60 minutes
                act = {"op": "exit"}
        if pc is not None and p["first_slot"] <= bar["slot"] <= p["last_slot"]:
            step, thr = p["step"], p["through"]
            up = math.floor((c - thr) / step) * step     # farthest level with c >= L + thr
            dn = math.ceil((c + thr) / step) * step      # farthest level with c <= L - thr
            side, level = 0, None
            if c > pc and up > pc:
                side, level = 1, up
            elif c < pc and dn < pc:
                side, level = -1, dn
            if side and level not in self.used:
                self.used.add(level)  # first qualifying cross of this level today, traded or not
                if pos is None and act is None and not self.news_due(bar):
                    stop = level - side * p["stop_beyond"]
                    risk = side * (c - stop)
                    act = {"op": "enter", "side": side, "type": "market", "stop": stop, "target": c + side * risk}
        self.prev_c = c
        return act
