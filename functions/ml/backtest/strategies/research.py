"""Strategies that need research-plane columns (GEX features, OOS model predictions). Ports of
gexRegime.js, gexWallFade.js and mlSignal.js."""
from __future__ import annotations

import math

import numpy as np

from .._js import js_round as _js_round
from ..series import get_series
from .base import Param, Strategy


class GexRegime(Strategy):
    """Above zero gamma dealers hedge against price (mean-revert); below it they hedge with it (trend-follow)."""
    id, label, family, plane = "gexRegime", "GEX Regime Switch", "gex", "research"
    requires = ("f:above_zero_gamma", "f:gamma_regime_strength")
    params = (Param("lookback", 6, min=1, max=60), Param("revertZ", 0.15, min=0.01, max=2),
              Param("momentumBp", 8, min=0, max=100), Param("minStrength", 0, min=0, max=1),
              Param("shortSide", True, "boolean"))

    def warmup(self, p, ds):
        return _js_round(p["lookback"]) + 20

    def prepare(self, ds, p):
        lb = _js_round(p["lookback"])
        mom = np.full(len(ds.close), np.nan)
        mom[lb:] = ds.close[lb:] / ds.close[:-lb] - 1 if lb > 0 else 0.0
        return dict(mom=mom.tolist(), regime=get_series(ds, "f:above_zero_gamma").tolist(),
                    strength=get_series(ds, "f:gamma_regime_strength").tolist(),
                    vs_sma=get_series(ds, "f:close_vs_sma20").tolist(), sma20=get_series(ds, "sma:20").tolist(),
                    close=ds.close.tolist())

    def signal(self, i, s, ds, p, prev):
        regime = s["regime"][i]
        if math.isnan(regime):
            return 0
        if abs(s["strength"][i]) < p["minStrength"]:
            return 0
        short = (lambda v: v) if p["shortSide"] else (lambda v: 0)
        if regime > 0:
            stretch = s["vs_sma"][i]
            if math.isnan(stretch):
                m = s["sma20"][i]
                if math.isnan(m):
                    return 0
                stretch = s["close"][i] / m - 1
            trig = p["revertZ"] / 100
            if stretch <= -trig:
                return 1
            if stretch >= trig:
                return short(-1)
            return 0
        m = s["mom"][i]
        if math.isnan(m):
            return 0
        trig = p["momentumBp"] / 10000
        if m >= trig:
            return 1
        if m <= -trig:
            return short(-1)
        return 0


class GexWallFade(Strategy):
    """Short into the call wall, buy the put wall, only while price sits above zero gamma."""
    id, label, family, plane = "gexWallFade", "GEX Wall Fade", "gex", "research"
    requires = ("f:dist_call_wall_atr", "f:dist_put_wall_atr", "f:above_zero_gamma", "f:call_wall_strength",
                "f:put_wall_strength")
    params = (Param("band", 0.5, min=0.05, max=3), Param("exitBand", 1.5, min=0.1, max=6),
              Param("minWallStrength", 0.1, min=0, max=0.9), Param("regimeGate", True, "boolean"),
              Param("shortSide", True, "boolean"))

    def warmup(self, p, ds):
        return 1

    def prepare(self, ds, p):
        cols = dict(call="dist_call_wall_atr", put="dist_put_wall_atr", regime="above_zero_gamma",
                    call_strength="call_wall_strength", put_strength="put_wall_strength")
        return {k: get_series(ds, f"f:{v}").tolist() for k, v in cols.items()}

    def signal(self, i, s, ds, p, prev):
        d_call, d_put = s["call"][i], s["put"][i]
        if math.isnan(d_call) or math.isnan(d_put):
            return 0
        if prev > 0:
            return 0 if d_put >= p["exitBand"] else 1
        if prev < 0:
            return 0 if d_call <= -p["exitBand"] else -1
        if p["regimeGate"] and not s["regime"][i] > 0:
            return 0
        near_call = abs(d_call) <= p["band"] and s["call_strength"][i] >= p["minWallStrength"]
        near_put = abs(d_put) <= p["band"] and s["put_strength"][i] >= p["minWallStrength"]
        if near_put and not near_call:
            return 1
        if near_call and not near_put:
            return -1 if p["shortSide"] else 0
        return 0


class MlSignal(Strategy):
    """Trade the walk-forward OOS forest prediction past +-threshold; exit after `holdBars` (or follow sign).
    `ml:pred` is NaN on every bar a fold was still training on, so this can only trade out of sample."""
    id, label, family, plane = "mlSignal", "ML Signal (RF)", "ml", "research"
    requires = ("ml:pred",)
    params = (Param("thresholdBp", 3, min=0, max=50), Param("holdBars", 3, min=1, max=60),
              Param("mode", "hold", "select", options=("hold", "follow")), Param("shortSide", True, "boolean"))

    def warmup(self, p, ds):
        return 1

    def prepare(self, ds, p):
        return dict(pred=get_series(ds, "ml:pred").tolist(), entry_bar=-1)

    def signal(self, i, s, ds, p, prev):
        v = s["pred"][i]
        theta = p["thresholdBp"] / 10000
        if p["mode"] == "follow":
            if math.isnan(v):
                return 0
            if v > theta:
                return 1
            if v < -theta:
                return -1 if p["shortSide"] else 0
            return 0
        if prev != 0:
            if i - s["entry_bar"] >= _js_round(p["holdBars"]):
                s["entry_bar"] = -1
                return 0
            return prev
        if math.isnan(v):
            return 0
        if v > theta:
            s["entry_bar"] = i
            return 1
        if v < -theta and p["shortSide"]:
            s["entry_bar"] = i
            return -1
        return 0
