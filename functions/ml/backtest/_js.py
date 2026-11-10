"""JavaScript number semantics the port has to reproduce exactly."""
from __future__ import annotations

import math


def js_round(x: float) -> int:
    """Math.round: halves go up. Python's round() goes to even (round(2.5) == 2), and floor(x + 0.5) is wrong
    for 0.49999999999999994, where the addition itself rounds up to 1."""
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r
