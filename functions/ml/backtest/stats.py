"""Sharpe inference: standard error, PSR, deflated Sharpe, holdout split. Port of frontend/lib/backtest/stats.js.

The normal CDF and its inverse are the same closed-form approximations the JS uses (A&S 7.1.26 and Acklam),
not scipy's, on purpose: the point is that both engines print the same digits, and scipy's exact CDF differs
from the approximation around the 7th decimal.
"""
from __future__ import annotations

import math

from .clock import trading_day

EULER_GAMMA = 0.5772156649015329


def norm_cdf(x: float) -> float:
    if x == math.inf:
        return 1.0
    if x == -math.inf:
        return 0.0
    t = 1 / (1 + 0.3275911 * abs(x) / math.sqrt(2))
    y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-(x * x) / 2)
    return 0.5 * (1 + y) if x >= 0 else 0.5 * (1 - y)


def norm_inv(p: float) -> float:
    if p <= 0:
        return -math.inf
    if p >= 1:
        return math.inf
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416]
    lo = 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - lo:
        return -norm_inv(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def moments(returns) -> dict:
    """Mean, sample sd, skew and raw (non-excess) kurtosis, summed left to right like the JS."""
    n = len(returns)
    if n < 2:
        return dict(n=n, mean=0.0, sd=0.0, skew=0.0, kurt=3.0)
    xs = [float(x) for x in returns]
    m = 0.0
    for x in xs:
        m += x
    m /= n
    m2 = m3 = m4 = 0.0
    for x in xs:
        dv = x - m
        d2 = dv * dv
        m2 += d2
        m3 += d2 * dv
        m4 += d2 * d2
    m2 /= n
    m3 /= n
    m4 /= n
    sd = math.sqrt(m2)
    return dict(n=n, mean=m, sd=math.sqrt((m2 * n) / (n - 1)),
                skew=m3 / sd ** 3 if sd > 0 else 0.0, kurt=m4 / m2 ** 2 if sd > 0 else 3.0)


def _sharpe_se(sr, n, skew, kurt):
    """Per-bar Sharpe standard error, Mertens (2002)."""
    if n < 2:
        return math.nan
    v = 1 - skew * sr + ((kurt - 1) / 4) * sr * sr
    return math.sqrt(max(v, 0) / (n - 1))


def sharpe_inference(returns, ppy: float, z: float = 1.959963984540054) -> dict:
    mo = moments(returns)
    sr = mo["mean"] / mo["sd"] if mo["sd"] > 0 else 0.0
    se = _sharpe_se(sr, mo["n"], mo["skew"], mo["kurt"])
    ann = math.sqrt(ppy)
    ok = math.isfinite(se)
    return dict(n=mo["n"], sr=sr, se=se, skew=mo["skew"], kurt=mo["kurt"], sharpe=sr * ann,
                ci=[(sr - z * se) * ann, (sr + z * se) * ann] if ok else [math.nan, math.nan],
                psr=norm_cdf(sr / se) if ok and se > 0 else math.nan)


def expected_max_sharpe(trials: int, trial_var: float) -> float:
    """Expected best per-bar Sharpe among `trials` zero-edge strategies whose Sharpes have variance `trial_var`."""
    if not trials > 1 or not trial_var > 0:
        return 0.0
    e = (1 - EULER_GAMMA) * norm_inv(1 - 1 / trials) + EULER_GAMMA * norm_inv(1 - 1 / (trials * math.e))
    return math.sqrt(trial_var) * e


def deflated_sharpe(inference: dict, trial_srs) -> dict:
    """P(true SR > best-of-N noise), Bailey & Lopez de Prado (2014). `trial_srs` are per-bar Sharpes of every
    configuration tried on the same data, this one included."""
    srs = [float(x) for x in trial_srs]
    trials = len(srs)
    var = 0.0
    if trials > 1:
        m = 0.0
        for x in srs:
            m += x
        m /= trials
        for x in srs:
            var += (x - m) ** 2
        var /= trials - 1
    sr0 = expected_max_sharpe(trials, var)
    se = _sharpe_se(inference["sr"], inference["n"], inference["skew"], inference["kurt"])
    dsr = norm_cdf((inference["sr"] - sr0) / se) if math.isfinite(se) and se > 0 else math.nan
    return dict(trials=trials, sr0=sr0, dsr=dsr)


def holdout_split(time, pct: float) -> dict:
    """Where a locked holdout of the last `pct`% starts, snapped to a trading-day boundary."""
    n = len(time)
    none = dict(cut=n, research_end=n - 1, holdout_bars=0)
    if not pct > 0 or n < 4:
        return none
    day = trading_day(time)
    target = min(n - 1, max(1, math.floor(n * (1 - pct / 100))))
    cut = target
    while cut < n and day[cut] == day[cut - 1]:
        cut += 1
    if cut >= n - 1:
        cut = target
        while cut > 0 and day[cut] == day[cut - 1]:
            cut -= 1
        if cut < 1:
            return none
    return dict(cut=cut, research_end=cut - 1, holdout_bars=n - cut)
