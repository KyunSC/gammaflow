"""V2_skew_shock: fade a 30-minute QQQ 25-delta skew shock that NQ's own 30-minute move does not explain
(|z| >= K, same-slot scaled), holding 90 minutes (prereg/V2_skew_shock.json)."""
import math


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.ranges = []        # RTH range of completed full sessions (ADR20)
        self.hist = []          # per eligible session: {slot: (dK, dP)}
        self.cur = None

    def _close_day(self):
        s = self.cur
        if s is None:
            return
        if not s["half"]:
            self.ranges.append(s["hi"] - s["lo"])
        if not s["half"] and not s["exdiv"] and s["any_opt"]:
            self.hist.append(s["pairs"])

    def _start_day(self, bar):
        p, n = self.p, self.p["n_hist"]
        self.cur = {"hi": bar["h"], "lo": bar["l"], "half": bar["half_day"], "exdiv": False, "any_opt": False,
                    "sk": {}, "c": {}, "pairs": {}, "done": False, "beta": None, "rms": {}}
        if len(self.hist) < n:
            return
        win = self.hist[-n:]
        sxy = sum(dk * dp for d in win for dk, dp in d.values())
        sxx = sum(dp * dp for d in win for _, dp in d.values())
        if sxx <= 0:
            return
        beta = sxy / sxx
        self.cur["beta"] = beta
        for k in range(p["first_slot"], p["last_slot"] + 1):
            e = [d[k][0] - beta * d[k][1] for d in win if k in d]
            if len(e) >= p["min_slot_hist"]:
                r = math.sqrt(sum(x * x for x in e) / len(e))
                if r > 0:
                    self.cur["rms"][k] = r

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self._close_day()
            self.day = bar["day"]
            self._start_day(bar)
        s, k, opt = self.cur, bar["slot"], bar["opt"]
        s["hi"], s["lo"] = max(s["hi"], bar["h"]), min(s["lo"], bar["l"])
        if opt is not None:
            s["any_opt"] = True
            if opt["exdiv"]:
                s["exdiv"] = True
            s["sk"][k] = opt["skew25"]
        s["c"][k] = bar["c"]
        # time exit: decided on the close of the 18th bar held (bars_held 17), fills at the next open
        if pos is not None:
            if pos["bars_held"] >= p["hold_bars"] - 1:
                return {"op": "exit"}
            return None
        lag = p["lag"]
        if not (p["first_slot"] <= k <= p["last_slot"]):
            return None
        sk0, sk1, c0 = s["sk"].get(k - lag), s["sk"].get(k), s["c"].get(k - lag)
        if sk0 is None or sk1 is None or c0 is None:
            return None
        dK, dP = sk1 - sk0, math.log(bar["c"] / c0)
        s["pairs"][k] = (dK, dP)
        if s["half"] or s["exdiv"] or s["done"] or s["beta"] is None or k not in s["rms"]:
            return None
        if len(self.ranges) < p["n_hist"]:
            return None
        z = (dK - s["beta"] * dP) / s["rms"][k]
        if abs(z) < p["k"]:
            return None
        dec = bar["mod"] + 5
        if any(dec - p["news_before"] <= m <= dec + p["news_after"] for m in bar["news"]):
            return None
        s["done"] = True
        side = 1 if z > 0 else -1
        adr = sum(self.ranges[-p["n_hist"]:]) / p["n_hist"]
        return {"op": "enter", "side": side, "type": "market", "stop": bar["c"] - side * p["stop_adr"] * adr,
                "target": None}
