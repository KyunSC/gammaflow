"""F2_friday_squaring: fade a large week-to-date move at Friday 14:00 (prereg/F2_friday_squaring.json)."""
from collections import deque

import numpy as np


def week_index(day: str) -> int:
    """Monday-start week number (1970-01-01 was a Thursday)."""
    return (int(np.datetime64(day, "D").astype(np.int64)) + 3) // 7


class Strategy:
    def __init__(self, params):
        self.p = params
        self.trs = deque(maxlen=params["atr_n"])
        self.day = None
        self.h = self.l = None
        self.pc = None
        self.week = None
        self.week_open = None
        self.week_rolled = False
        self.done = False

    def _close_day(self):
        if self.h is None:
            return
        self.trs.append(self.h - self.l if self.pc is None else max(self.h, self.pc) - min(self.l, self.pc))

    def _day_ok(self, bar):
        f = self.p["day_filter"]
        if bar["half_day"] or bar["roll"]:
            return False
        if f == "friday":
            return bar["dow"] == 4
        if f == "mon_thu":   # report-only control (prereg against_the_mechanism)
            return bar["dow"] <= 3
        raise ValueError("unknown day_filter")

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._close_day()
            self.day = bar["day"]
            self.h, self.l = bar["h"], bar["l"]
            self.pc = bar["prev_close"]
            self.done = False
            wk = week_index(bar["day"])
            if wk != self.week:
                self.week = wk
                self.week_open = bar["o"] if bar["slot"] == 0 else None
                self.week_rolled = False
            elif bar["roll"]:
                self.week_rolled = True
        else:
            self.h, self.l = max(self.h, bar["h"]), min(self.l, bar["l"])
        p = self.p
        if self.done or pos is not None or bar["mod"] != p["decide_mod"]:
            return None
        self.done = True
        if self.week_open is None or self.week_rolled or len(self.trs) < p["atr_n"] or not self._day_ok(bar):
            return None
        atr = sum(self.trs) / len(self.trs)
        wtd = bar["c"] - self.week_open
        if wtd == 0 or abs(wtd) < p["w"] * atr:
            return None
        side = -1 if wtd > 0 else 1
        c, risk = bar["c"], p["stop_atr"] * atr
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
