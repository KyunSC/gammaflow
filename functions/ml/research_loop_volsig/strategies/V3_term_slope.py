"""V3_term_slope: trade ES 09:35 -> 15:55 against the weekday-adjusted 1-day change in VIX/VIX3M at the prior
close (ratio fell -> long, rose -> short) when |z| >= Z (prereg/V3_term_slope.json).

All history is updated on each session's first bar from bar['daily'] alone, before any position logic, so it
never depends on past trades."""
import math


def _sd(xs):
    n = len(xs)
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.prev_ratio = None
        self.by_dow = {k: [] for k in range(7)}   # raw D per weekday
        self.adj = []                             # weekday-adjusted A, all sessions
        self.ranges = []                          # RTH range of completed full sessions
        self.cur = None

    def _new_day(self, bar):
        p = self.p
        if self.cur is not None and not self.cur["half"]:
            self.ranges.append(self.cur["hi"] - self.cur["lo"])
        self.cur = {"hi": bar["h"], "lo": bar["l"], "half": bar["half_day"], "z": None}
        d = bar["daily"]
        r = d["VIX"] / d["VIX3M"] if d is not None and d["VIX"] and d["VIX3M"] else None
        if r is not None and self.prev_ratio is not None:
            D = r - self.prev_ratio
            hist = self.by_dow[bar["dow"]]
            if len(hist) >= p["min_dow"]:
                w = hist[-p["n_dow"]:]
                A = D - sum(w) / len(w)
                if len(self.adj) >= p["min_sd"]:
                    sd = _sd(self.adj[-p["n_sd"]:])
                    if sd > 0:
                        self.cur["z"] = A / sd
                self.adj.append(A)
            hist.append(D)
        self.prev_ratio = r

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self.day = bar["day"]
            self._new_day(bar)
        s = self.cur
        s["hi"], s["lo"] = max(s["hi"], bar["h"]), min(s["lo"], bar["l"])
        if bar["slot"] != 0 or s["half"] or s["z"] is None or pos is not None:
            return None
        z = s["z"]
        if z == 0 or abs(z) < p["z"] or len(self.ranges) < p["n_adr"]:
            return None
        side = -1 if z > 0 else 1
        adr = sum(self.ranges[-p["n_adr"]:]) / p["n_adr"]
        return {"op": "enter", "side": side, "type": "market", "stop": bar["c"] - side * p["stop_adr"] * adr,
                "target": None}
