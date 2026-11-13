"""V1_flow_divergence: at 12:00 ET trade NQ in the sign of the residual of QQQ's morning change in ATM
call-minus-put IV spread, after regressing out NQ's own 09:30 -> 12:00 return over the prior 20 eligible
sessions, when |z| >= Z (prereg/V1_flow_divergence.json)."""
import math


def _mean_spread(vals, need=3):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if len(v) >= need else None


def _ols(hist):
    """Intercept, slope and residual sd (n-2 dof) of y on x; None if degenerate."""
    n = len(hist)
    mx = sum(x for x, _ in hist) / n
    my = sum(y for _, y in hist) / n
    sxx = sum((x - mx) ** 2 for x, _ in hist)
    if sxx <= 0 or n < 3:
        return None
    b = sum((x - mx) * (y - my) for x, y in hist) / sxx
    a = my - b * mx
    sse = sum((y - a - b * x) ** 2 for x, y in hist)
    s = math.sqrt(sse / (n - 2))
    return (a, b, s) if s > 0 else None


class Strategy:
    def __init__(self, params):
        self.p = params
        self.day = None
        self.ranges = []        # RTH range of completed full sessions (ADR20)
        self.hist = []          # (r, dS) of every eligible session, traded or not
        self.cur = None

    def _close_day(self):
        s = self.cur
        if s is not None and not s["half"]:
            self.ranges.append(s["hi"] - s["lo"])

    def on_bar(self, bar, pos):
        p = self.p
        if bar["day"] != self.day:
            self._close_day()
            self.day = bar["day"]
            self.cur = {"hi": bar["h"], "lo": bar["l"], "half": bar["half_day"], "o0": None,
                        "open_sp": [], "noon_sp": [], "opt0": False}
        s, k, opt = self.cur, bar["slot"], bar["opt"]
        s["hi"], s["lo"] = max(s["hi"], bar["h"]), min(s["lo"], bar["l"])
        o_lo, o_hi = p["open_slots"]
        n_lo, n_hi = p["noon_slots"]
        if k == 0:
            s["o0"] = bar["o"]
            s["opt0"] = opt is not None
        if o_lo <= k <= o_hi:
            s["open_sp"].append(None if opt is None else opt["iv_spread"])
        if n_lo <= k <= n_hi:
            s["noon_sp"].append(None if opt is None else opt["iv_spread"])
        if k != p["decision_slot"]:
            return None
        # eligibility (also decides whether the session enters the history)
        if s["half"] or s["o0"] is None or not s["opt0"] or opt is None or opt["exdiv"] is not False:
            return None
        a_sp, n_sp = _mean_spread(s["open_sp"]), _mean_spread(s["noon_sp"])
        if a_sp is None or n_sp is None:
            return None
        r = math.log(bar["c"] / s["o0"])
        dS = n_sp - a_sp
        n = p["n_hist"]
        fit = _ols(self.hist[-n:]) if len(self.hist) >= n else None
        self.hist.append((r, dS))
        if fit is None or len(self.ranges) < n:
            return None
        a, b, sd = fit
        z = (dS - a - b * r) / sd
        if any(p["news_from"] <= m < p["news_to"] for m in bar["news"]):
            return None
        if abs(z) < p["z"] or pos is not None:
            return None
        side = 1 if z > 0 else -1
        adr = sum(self.ranges[-n:]) / n
        return {"op": "enter", "side": side, "type": "market", "stop": bar["c"] - side * p["stop_adr"] * adr,
                "target": None}
