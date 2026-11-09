"""Price-only strategies. Ports of smaCross.js, bbReversion.js and vwapReversion.js."""
from __future__ import annotations

import math

from .._js import js_round as _js_round
from ..series import get_series
from .base import Param, Strategy


class SmaCross(Strategy):
    """Long while the fast average is above the slow one; short (optionally) below. Stateless."""
    id, label = "smaCross", "MA Cross"
    params = (Param("fast", 10, min=2, max=200), Param("slow", 50, min=3, max=400),
              Param("maType", "ema", "select", options=("sma", "ema")), Param("shortSide", True, "boolean"))

    def warmup(self, p, ds):
        return max(p["fast"], p["slow"]) + 1

    def prepare(self, ds, p):
        return (get_series(ds, f"{p['maType']}:{_js_round(p['fast'])}").tolist(),
                get_series(ds, f"{p['maType']}:{_js_round(p['slow'])}").tolist())

    def signal(self, i, s, ds, p, prev):
        f, sl = s[0][i], s[1][i]
        if math.isnan(f) or math.isnan(sl):
            return 0
        if f > sl:
            return 1
        if f < sl:
            return -1 if p["shortSide"] else 0
        return prev


class BbReversion(Strategy):
    """Buy the lower Bollinger band, sell the upper, flatten at the mid. Stateful: holds through the band,
    so it reads `prev`."""
    id, label = "bbReversion", "BB Reversion"
    params = (Param("period", 20, min=5, max=200), Param("stdDev", 2, min=0.5, max=4),
              Param("shortSide", True, "boolean"))

    def warmup(self, p, ds):
        return _js_round(p["period"]) + 1

    def prepare(self, ds, p):
        period, mult = _js_round(p["period"]), p["stdDev"]
        return dict(upper=get_series(ds, f"bbUpper:{period}:{mult}").tolist(),
                    lower=get_series(ds, f"bbLower:{period}:{mult}").tolist(),
                    mid=get_series(ds, f"bbMid:{period}").tolist(), close=ds.close.tolist())

    def signal(self, i, s, ds, p, prev):
        close, mid = s["close"][i], s["mid"][i]
        if math.isnan(mid):
            return 0
        if prev > 0:
            return 0 if close >= mid else 1
        if prev < 0:
            return 0 if close <= mid else -1
        if close <= s["lower"][i]:
            return 1
        if close >= s["upper"][i]:
            return -1 if p["shortSide"] else 0
        return 0


class VwapReversion(Strategy):
    """Fade price back to session VWAP once it stretches `entryAtr` ATRs away; exit within `exitAtr`."""
    id, label = "vwapReversion", "VWAP Fade"
    params = (Param("entryAtr", 1.2, min=0.1, max=5), Param("exitAtr", 0.2, min=0, max=3),
              Param("atrPeriod", 14, min=2, max=100), Param("shortSide", True, "boolean"))

    def warmup(self, p, ds):
        return _js_round(p["atrPeriod"]) + 1

    def prepare(self, ds, p):
        return dict(vwap=get_series(ds, "vwap").tolist(), atr=get_series(ds, f"atr:{_js_round(p['atrPeriod'])}").tolist(),
                    close=ds.close.tolist())

    def signal(self, i, s, ds, p, prev):
        a = s["atr"][i]
        if not a > 0:
            return 0
        dev = (s["close"][i] - s["vwap"][i]) / a
        if prev > 0:
            return 0 if dev >= -p["exitAtr"] else 1
        if prev < 0:
            return 0 if dev <= p["exitAtr"] else -1
        if dev <= -p["entryAtr"]:
            return 1
        if dev >= p["entryAtr"]:
            return -1 if p["shortSide"] else 0
        return 0
