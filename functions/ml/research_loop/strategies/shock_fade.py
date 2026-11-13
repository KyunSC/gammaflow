"""shock_fade: fade an unusually large mid-session 5m move that no scheduled release explains (prereg/shock_fade.json)."""
from collections import defaultdict, deque


class Strategy:
    def __init__(self, params):
        self.p = params
        self.hist = defaultdict(lambda: deque(maxlen=params["lookback"]))  # slot -> |move| of prior sessions
        self.day = None
        self.prev_c = None
        self.today = []

    def news_near(self, bar):
        end = bar["mod"] + 5
        lo, hi = end - self.p["news_after"], end + self.p["news_before"]
        return any(lo <= m <= hi for m in bar["news"])

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            for slot, a in self.today:  # yesterday's moves join the history only now (causal)
                self.hist[slot].append(a)
            self.today = []
            self.day = bar["day"]
            self.prev_c = None
        slot = bar["slot"]
        r = None if self.prev_c is None else bar["c"] - self.prev_c
        act = None
        if pos is not None:
            if pos["bars_held"] + 1 >= p["hold_bars"]:  # entry bar + 5 more completed = 30 minutes
                act = {"op": "exit"}
        elif r is not None and p["first_slot"] <= slot <= p["last_slot"]:
            h = self.hist[slot]
            if len(h) >= p["min_obs"]:
                sigma = sum(h) / len(h)
                if abs(r) >= p["K"] * sigma and abs(r) >= p["min_points"] and not self.news_near(bar):
                    side = -1 if r > 0 else 1
                    c, risk = bar["c"], abs(r)
                    act = {"op": "enter", "side": side, "type": "market", "stop": c - side * risk,
                           "target": c + side * risk}
        if r is not None:
            self.today.append((slot, abs(r)))
        self.prev_c = bar["c"]
        return act
