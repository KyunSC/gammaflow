"""H1_es_hour_periodicity: follow the mean same-RTH-hour ES return of the previous N full sessions
(prereg/H1_es_hour_periodicity.json). series='prev_hour' is the report-only control (the hour just ended)."""
import math
from collections import deque

HOURS = (600, 660, 720, 780, 840, 900)


class Strategy:
    def __init__(self, params):
        self.p = params
        self.ret = {H: deque(maxlen=params["N"]) for H in HOURS}
        self.rng = {H: deque(maxlen=params["range_n"]) for H in HOURS}
        self.day = None
        self.half = self.roll = False
        self.cur = {}

    def _finish(self):
        if self.day is None or self.half:
            return
        b = self.cur
        for H in HOURS:
            a, z = b.get(H - 5), b.get(H + 55)
            self.ret[H].append(math.log(z[3] / a[3]) if a and z else None)
            bars = [b.get(m) for m in range(H, H + 60, 5)]
            self.rng[H].append(max(x[1] for x in bars) - min(x[2] for x in bars) if all(bars) else None)

    @staticmethod
    def _mean(dq, need):
        v = [x for x in dq if x is not None]
        return sum(v) / len(v) if len(v) >= need else None

    def _signal(self, H):
        p = self.p
        if p.get("series", "periodicity") == "prev_hour":
            a = self.cur.get(H - 5)
            if H == 600:
                b = self.cur.get(570)
                ref = None if b is None else b[0]
            else:
                b = self.cur.get(H - 65)
                ref = None if b is None else b[3]
            return None if a is None or ref is None else math.log(a[3] / ref)
        if len(self.ret[H]) < p["N"]:
            return None
        return self._mean(self.ret[H], math.ceil(p["valid_frac"] * p["N"]))

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self._finish()
            self.day, self.half, self.roll, self.cur = bar["day"], bar["half_day"], bar["roll"], {}
        m = bar["mod"]
        self.cur[m] = (bar["o"], bar["h"], bar["l"], bar["c"])
        if pos is not None:
            return {"op": "exit"} if m - 50 in HOURS else None
        H = m + 5
        if H not in HOURS or self.half or self.roll:
            return None
        x = self._signal(H)
        if x is None or x == 0:
            return None
        if len(self.rng[H]) < self.p["range_n"]:
            return None
        R = self._mean(self.rng[H], math.ceil(self.p["valid_frac"] * self.p["range_n"]))
        if R is None or R <= 0:
            return None
        side = 1 if x > 0 else -1
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * R, "target": c + side * R}
