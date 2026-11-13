"""Frozen metrics for the 2026-11-04 study re-score (rubric: data/rescore/RUBRIC.md).

One function per metric. Subagents must call these, never their own formulas.
Pure standard library + numpy, so it runs under any interpreter in this repo.

Typical use:

    import rescore_metrics as rm
    row = rm.score_symbol(daily_pnl, dates=dates, N=40, oos=True, trades=120,
                          gross_per_trade=12.0, cost_per_trade=4.0,
                          twin_p=0.03, twin_kind="side_matched",
                          slippage_total=300.0)
    verdict = rm.study_verdict([row["verdict"] for row in rows])
"""

from __future__ import annotations

import hashlib
import math
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()

VERDICT_RANK = {"DEAD": 0, "PROMISING": 1, "STRONG": 2}
DEAD_REASONS = ("net_negative", "gross_le_costs", "worse_than_random",
                "oos_reversal", "few_days", "weak_stats")


def _arr(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        raise ValueError("expected a 1-D series of daily P&L")
    return a


# ---------------------------------------------------------------- Sharpe & moments

def daily_sharpe(pnl) -> float | None:
    """Non-annualized per-day Sharpe: mean / sample std (ddof=1). None if undefined."""
    a = _arr(pnl)
    if a.size < 2:
        return None
    sd = a.std(ddof=1)
    if sd == 0 or not np.isfinite(sd):
        return None
    return float(a.mean() / sd)


def skew_kurtosis(pnl) -> tuple[float | None, float | None]:
    """Population skew and NON-excess kurtosis (normal = 3) of daily P&L."""
    a = _arr(pnl)
    if a.size < 3:
        return None, None
    d = a - a.mean()
    m2 = float(np.mean(d ** 2))
    if m2 == 0:
        return None, None
    return float(np.mean(d ** 3) / m2 ** 1.5), float(np.mean(d ** 4) / m2 ** 2)


# ---------------------------------------------------------------- Deflated Sharpe

def expected_max_sharpe(N: int, V: float) -> float:
    """SR0 = sqrt(V) * ((1-g) Phi^-1(1-1/N) + g Phi^-1(1-1/(N e))). N <= 1 gives 0."""
    if N is None or N <= 1:
        return 0.0
    if V is None or V <= 0:
        raise ValueError("V must be > 0")
    z1 = _N.inv_cdf(1.0 - 1.0 / N)
    z2 = _N.inv_cdf(1.0 - 1.0 / (N * math.e))
    return math.sqrt(V) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe_from_stats(sr: float, T: int, skew: float, kurt: float,
                               N: int, V: float | None = None) -> float | None:
    """DSR as a probability. kurt is non-excess. V defaults to 1/T (rubric section 4)."""
    if sr is None or skew is None or kurt is None or T is None or T < 2:
        return None
    if V is None:
        V = 1.0 / T
    sr0 = expected_max_sharpe(N, V)
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return None
    return float(_N.cdf((sr - sr0) * math.sqrt(T - 1) / math.sqrt(denom)))


def sharpe_variance_across_trials(trial_sharpes) -> float | None:
    """V for the SR0 benchmark: sample variance of per-day Sharpe across the N trials."""
    a = _arr(trial_sharpes)
    a = a[np.isfinite(a)]
    if a.size < 2:
        return None
    return float(a.var(ddof=1))


def deflated_sharpe(pnl, N: int, V: float | None = None) -> float | None:
    """DSR from a daily P&L series. V=None means 1/T."""
    a = _arr(pnl)
    sr = daily_sharpe(a)
    sk, ku = skew_kurtosis(a)
    return deflated_sharpe_from_stats(sr, a.size, sk, ku, N, V)


# ---------------------------------------------------------------- concentration, stress, years

def top5_share(pnl) -> float | None:
    """Sum of the 5 best days / total net. None if total net <= 0."""
    a = _arr(pnl)
    total = float(a.sum())
    if total <= 0:
        return None
    best = np.sort(a)[::-1][:5]
    return float(best.sum() / total)


def stress_net(net_total: float, slippage_total: float | None = None,
               noncommission_cost_total: float | None = None,
               total_cost: float | None = None) -> tuple[float | None, str]:
    """Net with slippage doubled: net - one extra copy of slippage.

    Falls back to doubling non-commission cost, then total cost (rubric section 4).
    Returns (stress_net, method).
    """
    for extra, method in ((slippage_total, "2x_slippage"),
                          (noncommission_cost_total, "2x_noncommission_cost"),
                          (total_cost, "2x_total_cost")):
        if extra is not None:
            return float(net_total - abs(extra)), method
    return None, "unavailable"


def years_positive(dates, pnl) -> float | None:
    """Share of calendar years (with any nonzero day) whose net P&L > 0."""
    a = _arr(pnl)
    yrs = np.array([str(d)[:4] for d in dates])
    if yrs.size != a.size:
        raise ValueError("dates and pnl length differ")
    active = [y for y in sorted(set(yrs)) if np.any(a[yrs == y] != 0)]
    if not active:
        return None
    return float(np.mean([a[yrs == y].sum() > 0 for y in active]))


# ---------------------------------------------------------------- verdicts

def _ok(x, test) -> bool:
    return x is not None and test(x)


def symbol_verdict(*, oos: bool, net_total, gross_per_trade, cost_per_trade, dsr,
                   twin_p, twin_kind: str | None, top5, stress, years_pos,
                   regime_rule_tested_oos: bool = False,
                   discovery_net: float | None = None) -> tuple[str, str | None]:
    """Rubric section 5. Missing (None) metrics fail their test. Returns (verdict, dead_reason).

    Dead-reason precedence (frozen here):
      net <= 0 : oos_reversal (OOS and discovery net > 0) > worse_than_random (twin p >= 0.5)
                 > gross_le_costs (gross > 0, eaten by costs) > net_negative
      net > 0  : gross_le_costs (gross <= cost or net within 10% of cost) > worse_than_random
                 > few_days (top5 >= 0.5) > weak_stats
    """
    net_pos = _ok(net_total, lambda v: v > 0)
    gross_gt_cost = (gross_per_trade is not None and cost_per_trade is not None
                     and gross_per_trade > cost_per_trade)

    if oos and net_pos:
        strong = (_ok(dsr, lambda v: v >= 0.95)
                  and twin_kind == "side_matched" and _ok(twin_p, lambda v: v < 0.05)
                  and _ok(top5, lambda v: v < 0.50)
                  and _ok(stress, lambda v: v > 0)
                  and (regime_rule_tested_oos or _ok(years_pos, lambda v: v >= 0.60)))
        if strong:
            return "STRONG", None

    if net_pos and gross_gt_cost and (_ok(dsr, lambda v: v >= 0.5) or _ok(twin_p, lambda v: v < 0.10)):
        return "PROMISING", None

    if not net_pos:
        if oos and _ok(discovery_net, lambda v: v > 0):
            return "DEAD", "oos_reversal"
        if _ok(twin_p, lambda v: v >= 0.5):
            return "DEAD", "worse_than_random"
        if _ok(gross_per_trade, lambda v: v > 0):
            return "DEAD", "gross_le_costs"
        return "DEAD", "net_negative"
    near_cost = (gross_per_trade is not None and cost_per_trade is not None and cost_per_trade > 0
                 and (gross_per_trade - cost_per_trade) <= 0.10 * cost_per_trade)
    if not gross_gt_cost or near_cost:
        return "DEAD", "gross_le_costs"
    if _ok(twin_p, lambda v: v >= 0.5):
        return "DEAD", "worse_than_random"
    if _ok(top5, lambda v: v >= 0.5):
        return "DEAD", "few_days"
    return "DEAD", "weak_stats"


def study_verdict(symbol_verdicts) -> str:
    """Best verdict over symbols."""
    vs = list(symbol_verdicts)
    if not vs:
        return "DEAD"
    return max(vs, key=lambda v: VERDICT_RANK[v])


# ---------------------------------------------------------------- convenience

def score_symbol(daily_pnl, *, N: int, oos: bool, dates=None, V: float | None = None,
                 trades: int | None = None, gross_per_trade=None, cost_per_trade=None,
                 twin_p=None, twin_kind=None, slippage_total=None,
                 noncommission_cost_total=None, total_cost=None,
                 regime_rule_tested_oos: bool = False, discovery_net=None) -> dict:
    """All per-symbol metrics + verdict from one daily series."""
    a = _arr(daily_pnl)
    net = float(a.sum())
    sr = daily_sharpe(a)
    sk, ku = skew_kurtosis(a)
    dsr = deflated_sharpe_from_stats(sr, a.size, sk, ku, N, V)
    t5 = top5_share(a)
    st, st_method = stress_net(net, slippage_total, noncommission_cost_total, total_cost)
    yp = years_positive(dates, a) if dates is not None else None
    verdict, reason = symbol_verdict(
        oos=oos, net_total=net, gross_per_trade=gross_per_trade, cost_per_trade=cost_per_trade,
        dsr=dsr, twin_p=twin_p, twin_kind=twin_kind, top5=t5, stress=st, years_pos=yp,
        regime_rule_tested_oos=regime_rule_tested_oos, discovery_net=discovery_net)
    return {
        "oos": oos, "T": int(a.size), "trades": trades, "net_total": net,
        "net_per_trade": (net / trades) if trades else None,
        "gross_per_trade": gross_per_trade, "cost_per_trade": cost_per_trade,
        "sharpe": sr, "skew": sk, "kurtosis": ku, "dsr": dsr,
        "twin_p": twin_p, "twin_kind": twin_kind, "top5_share": t5,
        "stress_net": st, "stress_method": st_method, "years_positive": yp,
        "verdict": verdict, "dead_reason": reason,
    }


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


REQUIRED_STUDY_FIELDS = ("study", "old_verdict", "new_verdict", "per_symbol", "N", "V_source",
                         "prop_ev", "reason", "partial", "rubric_sha256", "script_sha256", "sources")
REQUIRED_SYMBOL_FIELDS = ("window", "oos", "units", "days_basis", "T", "trades", "net_total",
                          "net_per_trade", "gross_per_trade", "cost_per_trade", "sharpe", "skew",
                          "kurtosis", "dsr", "twin_p", "twin_kind", "top5_share", "stress_net",
                          "stress_method", "years_positive", "verdict", "dead_reason")


def missing_fields(study_json: dict) -> list[str]:
    """Field names (rubric section 8) absent from a <study>.json."""
    miss = [k for k in REQUIRED_STUDY_FIELDS if k not in study_json]
    for sym, row in (study_json.get("per_symbol") or {}).items():
        miss += [f"{sym}.{k}" for k in REQUIRED_SYMBOL_FIELDS if k not in row]
    return miss
