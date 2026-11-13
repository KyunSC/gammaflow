"""nq_residual_momentum: at 12:00 ET trade NQ in the sign of its beta-adjusted residual vs ES since the open
when |z| >= Z (prereg/nq_residual_momentum.json)."""
import math


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.ranges = []        # NQ RTH range of every completed session (ADR)
        self.beta_hist = []     # (sum_xy, sum_xx) of every completed full session
        self.resid_hist = []    # 12:00 residual of completed full sessions, each with its own day's beta
        self.cur = None

    def _close_day(self):
        s = self.cur
        if s is None:
            return
        self.ranges.append(s["hi"] - s["lo"])
        if not s["half"]:
            self.beta_hist.append((s["sxy"], s["sxx"]))
            if s["resid"] is not None:
                self.resid_hist.append(s["resid"])

    def _beta(self):
        n = self.p["n_hist"]
        if len(self.beta_hist) < n:
            return None
        sxy = sum(a for a, _ in self.beta_hist[-n:])
        sxx = sum(b for _, b in self.beta_hist[-n:])
        return sxy / sxx if sxx > 0 else None

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self._close_day()
            self.day = bar["day"]
            self.cur = {"hi": bar["h"], "lo": bar["l"], "half": bar["half_day"], "sxy": 0.0, "sxx": 0.0,
                        "prev": None, "o_nq": None, "o_es": None, "es_ok": True, "seen": 0, "resid": None}
        s, k, es = self.cur, bar["slot"], bar["es"]
        s["hi"], s["lo"] = max(s["hi"], bar["h"]), min(s["lo"], bar["l"])
        # beta pairs: consecutive slots, both markets present
        if s["prev"] is not None and es is not None and s["prev"][0] == k - 1:
            x = math.log(es["c"] / s["prev"][2])
            y = math.log(bar["c"] / s["prev"][1])
            s["sxy"] += x * y
            s["sxx"] += x * x
        s["prev"] = (k, bar["c"], es["c"]) if es is not None else None
        d = p["decision_slot"]
        if k <= d:
            if es is None:
                s["es_ok"] = False
            s["seen"] += 1
            if k == 0 and es is not None:
                s["o_nq"], s["o_es"] = bar["o"], es["o"]
        if k != d or s["half"] or not s["es_ok"] or s["seen"] != d + 1 or s["o_nq"] is None:
            return None
        beta = self._beta()
        if beta is None:
            return None
        resid = math.log(bar["c"] / s["o_nq"]) - beta * math.log(es["c"] / s["o_es"])
        s["resid"] = resid
        n = p["n_hist"]
        if len(self.resid_hist) < n or len(self.ranges) < n:
            return None
        rms = math.sqrt(sum(r * r for r in self.resid_hist[-n:]) / n)
        if rms <= 0:
            return None
        z = resid / rms
        if abs(z) < p["z"] or pos is not None:
            return None
        if any(p["news_from"] <= m < p["news_to"] for m in bar["news"]):
            return None
        side = 1 if resid > 0 else -1
        adr = sum(self.ranges[-n:]) / n
        return {"op": "enter", "side": side, "type": "market", "stop": bar["c"] - side * p["stop_adr"] * adr, "target": None}
