"""F1_news_gap: follow the overnight gap at 09:35 on sessions whose only high-impact release was pre-open
(prereg/F1_news_gap.json)."""
from collections import deque


class Strategy:
    def __init__(self, params):
        self.p = params
        self.trs = deque(maxlen=params["atr_n"])   # completed sessions' RTH true ranges
        self.day = None
        self.h = self.l = None
        self.pc = None          # today's bar['prev_close']
        self.gap = None
        self.done = False

    def _close_day(self):
        if self.h is None:
            return
        if self.pc is None:
            tr = self.h - self.l
        else:
            tr = max(self.h, self.pc) - min(self.l, self.pc)
        self.trs.append(tr)

    def _day_ok(self, bar):
        f = self.p["day_filter"]
        if f == "pre_rth_news":
            return bar["news_day"] is True and len(bar["news"]) == 0
        if f == "quiet":   # report-only control (prereg against_the_mechanism)
            return bar["news_day"] is False and len(bar["news"]) == 0
        raise ValueError("unknown day_filter")

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._close_day()
            self.day = bar["day"]
            self.h, self.l = bar["h"], bar["l"]
            self.pc = bar["prev_close"]
            self.done = False
            self.gap = None if self.pc is None or bar["slot"] != 0 else bar["o"] - self.pc
        else:
            self.h, self.l = max(self.h, bar["h"]), min(self.l, bar["l"])
        if self.done or pos is not None or bar["slot"] != 0:
            return None
        self.done = True
        p = self.p
        if self.gap is None or self.gap == 0 or len(self.trs) < p["atr_n"] or not self._day_ok(bar):
            return None
        atr = sum(self.trs) / len(self.trs)
        if abs(self.gap) < p["g"] * atr:
            return None
        side = 1 if self.gap > 0 else -1
        c = bar["c"]
        stop = bar["l"] - p["stop_pad_atr"] * atr if side == 1 else bar["h"] + p["stop_pad_atr"] * atr
        return {"op": "enter", "side": side, "type": "market", "stop": stop, "target": c + side * abs(c - stop)}
