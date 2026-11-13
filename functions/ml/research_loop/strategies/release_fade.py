"""release_fade: fade the first W-minute ES reaction to a scheduled in-session release (prereg/release_fade.json)."""


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.event = None
        self.ref = None
        self.done = True

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self.day = bar["day"]
            self.ref = None
            news = bar["news"]
            e = min(news) if news else None
            ok = e is not None and e >= p["first_event_mod"] and e + p["window"] <= p["last_entry_mod"]
            self.event = e if ok else None
            self.done = not ok
        act = None
        if pos is not None and pos["bars_held"] + 1 >= p["hold_bars"]:  # entry bar + 23 more = 120 minutes
            act = {"op": "exit"}
        if not self.done:
            end = bar["mod"] + 5
            c = bar["c"]
            if end == self.event:
                self.ref = c
            elif end == self.event + p["window"]:
                self.done = True
                if self.ref is not None and pos is None:
                    move = c - self.ref
                    if abs(move) >= p["min_move"]:
                        side = -1 if move > 0 else 1
                        risk = max(abs(move), p["min_risk"])
                        act = {"op": "enter", "side": side, "type": "market", "stop": c - side * risk,
                               "target": c + side * risk}
            elif end > self.event + p["window"]:
                self.done = True  # the reaction bar is missing (halt): no trade
        return act
