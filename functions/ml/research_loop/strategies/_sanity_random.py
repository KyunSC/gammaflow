"""Accounting check only: one random-direction market entry per session at a random slot, 1:1 bracket of
`risk` points, flat by the close. Expected mean R ~ -cost."""
import numpy as np


class Strategy:
    def __init__(self, params):
        self.rng = np.random.default_rng(params["seed"])
        self.risk = params["risk"]
        self.day = None

    def on_bar(self, bar, pos):
        if bar["day"] != self.day:
            self.day = bar["day"]
            self.at = int(self.rng.integers(0, bar["flat_slot"] - 1))
            self.side = 1 if self.rng.random() < 0.5 else -1
        if pos is None and bar["slot"] == self.at:
            c, d = bar["c"], self.side
            return {"op": "enter", "side": d, "type": "market", "stop": c - d * self.risk, "target": c + d * self.risk}
        return None
