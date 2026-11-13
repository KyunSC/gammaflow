"""Accounting check only: one random-direction market entry per session at a random slot, 1:1 bracket of
`risk_frac` x price (scale-free across NQ 2,300 -> 23,000), flat by the close. Expected mean R ~ -cost.
With need_opt, enters only on bars that carry bar['opt'] (atm_iv set) and bar['daily'] (VIX set): on dev_opt that
must still trade ~every session, which shows the new keys reach the strategy process."""
import numpy as np


class Strategy:
    def __init__(self, params):
        self.rng = np.random.default_rng(params["seed"])
        self.risk_frac = params["risk_frac"]
        self.need_opt = params.get("need_opt", False)
        self.day = None

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self.day = bar["day"]
            self.at = int(self.rng.integers(0, bar["flat_slot"] - 1))
            self.side = 1 if self.rng.random() < 0.5 else -1
        if self.need_opt and (bar["opt"] is None or bar["opt"]["atm_iv"] is None
                              or bar["daily"] is None or bar["daily"]["VIX"] is None):
            return None
        if pos is None and bar["slot"] == self.at:
            c, d = bar["c"], self.side
            risk = self.risk_frac * c
            return {"op": "enter", "side": d, "type": "market", "stop": c - d * risk, "target": c + d * risk}
        return None
