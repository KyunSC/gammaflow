"""smt_divergence: fade NQ when exactly one of NQ / ES takes out an established RTH session extreme
(prereg/smt_divergence.json)."""

TICK = 0.25


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.ranges = []            # completed sessions' NQ RTH ranges (causal)
        self.cur_hi = self.cur_lo = None

    def news_due(self, bar):
        end = bar["mod"] + 5
        return any(end <= m <= end + self.p["news_before"] for m in bar["news"])

    def _new_day(self, bar):
        if self.cur_hi is not None:
            self.ranges.append(self.cur_hi - self.cur_lo)
        self.day = bar["day"]
        self.cur_hi = self.cur_lo = None
        # per market: [HI, slot of HI, LO, slot of LO] over slots before the current bar
        self.ext = {"nq": None, "es": None}
        self.done = {1: False, -1: False}

    def _signal(self, k, nq, es):
        """+1 long / -1 short / 0. nq, es: this bar's dicts; extremes are over earlier slots only."""
        if es is None or self.ext["nq"] is None or self.ext["es"] is None:
            return 0
        est = self.p["est_slots"]
        HN, tHN, LN, tLN = self.ext["nq"]
        HE, tHE, LE, tLE = self.ext["es"]
        nq_hi = nq["h"] >= HN + TICK and k - tHN >= est
        es_hi = es["h"] >= HE + TICK and k - tHE >= est
        bear = (nq_hi and es["h"] < HE) or (es_hi and nq["h"] < HN)
        nq_lo = nq["l"] <= LN - TICK and k - tLN >= est
        es_lo = es["l"] <= LE - TICK and k - tLE >= est
        bull = (nq_lo and es["l"] > LE) or (es_lo and nq["l"] > LN)
        if bear and bull:
            return 0
        return -1 if bear else (1 if bull else 0)

    @staticmethod
    def _update(ext, k, h, l):
        if ext is None:
            return [h, k, l, k]
        if h > ext[0]:
            ext[0], ext[1] = h, k
        if l < ext[2]:
            ext[2], ext[3] = l, k
        return ext

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self._new_day(bar)
        k, c = bar["slot"], bar["c"]
        nq = {"h": bar["h"], "l": bar["l"]}
        es = bar["es"]
        act = None
        if pos is not None and pos["bars_held"] + 1 >= p["hold_bars"]:  # entry bar + 11 more = 60 minutes
            act = {"op": "exit"}
        last = min(p["last_slot"], bar["flat_slot"] - 15)
        side = self._signal(k, nq, es) if p["first_slot"] <= k <= last else 0
        if (side and not self.done[side] and pos is None and act is None and not self.news_due(bar)
                and len(self.ranges) >= p["adr_n"]):
            adr = sum(self.ranges[-p["adr_n"]:]) / p["adr_n"]
            hi_incl = max(self.ext["nq"][0], bar["h"])
            lo_incl = min(self.ext["nq"][2], bar["l"])
            beyond = (hi_incl - c + TICK) if side < 0 else (c - lo_incl + TICK)
            risk = max(beyond, p["m"] * adr)
            stop = c - side * risk
            act = {"op": "enter", "side": side, "type": "market", "stop": stop, "target": c + side * risk}
            self.done[side] = True
        # extremes include this bar only after the signal check (strictly earlier slots)
        self.ext["nq"] = self._update(self.ext["nq"], k, bar["h"], bar["l"])
        if es is not None:
            self.ext["es"] = self._update(self.ext["es"], k, es["h"], es["l"])
        self.cur_hi = bar["h"] if self.cur_hi is None else max(self.cur_hi, bar["h"])
        self.cur_lo = bar["l"] if self.cur_lo is None else min(self.cur_lo, bar["l"])
        return act
