"""Metrics and the frozen pass/fail gate."""
from __future__ import annotations

import math

import numpy as np

from . import config as C


def session_bootstrap_ci(r: np.ndarray, days: np.ndarray, n: int = C.N_BOOT, seed: int = C.SEED) -> tuple[float, float]:
    """95% CI of mean R, resampling whole sessions (trades on one day move together)."""
    if len(r) == 0:
        return (float("nan"), float("nan"))
    u, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=r, minlength=len(u))
    cnts = np.bincount(inv, minlength=len(u)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), size=(n, len(u)))
    means = sums[idx].sum(axis=1) / np.maximum(cnts[idx].sum(axis=1), 1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def year_share(usd: np.ndarray, days: np.ndarray) -> float:
    """Largest single year's share of total P&L (inf when the total is not positive)."""
    total = usd.sum()
    if total <= 0:
        return math.inf
    years = np.array([d[:4] for d in days])
    return float(max(usd[years == y].sum() for y in np.unique(years)) / total)


def folds_positive(r: np.ndarray, days: np.ndarray, sessions: list[str], k: int = C.FOLDS) -> list[float]:
    """Mean R in k contiguous blocks of the split's sessions (not of trades)."""
    blocks = np.array_split(np.array(sessions), k)
    out = []
    for b in blocks:
        m = (days >= b[0]) & (days <= b[-1]) if len(b) else np.zeros(len(days), bool)
        out.append(float(r[m].mean()) if m.any() else float("nan"))
    return out


def ex_top(r: np.ndarray, k: int = 5) -> float:
    if len(r) <= k:
        return float("nan")
    return float(np.sort(r)[:-k].mean())


def deflated_sharpe(daily: np.ndarray, n_trials: int) -> float:
    """Bailey & Lopez de Prado DSR probability (information only, never a gate)."""
    from statistics import NormalDist
    n = len(daily)
    if n < 3 or daily.std() == 0:
        return float("nan")
    sr = daily.mean() / daily.std()
    z = (daily - daily.mean()) / daily.std()
    skew, kurt = float((z ** 3).mean()), float((z ** 4).mean())
    nd = NormalDist()
    g = 0.5772156649
    sr0 = math.sqrt(1 / n) * ((1 - g) * nd.inv_cdf(1 - 1 / max(n_trials, 2)) + g * nd.inv_cdf(1 - 1 / (max(n_trials, 2) * math.e)))
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return float(nd.cdf((sr - sr0) * math.sqrt(n - 1) / den))


def summarize(r_base: np.ndarray, usd_base: np.ndarray, r_stress: np.ndarray, days: np.ndarray, sessions: list[str],
              twin: dict, n_trials: int) -> dict:
    n = len(r_base)
    lo, hi = session_bootstrap_ci(r_base, days)
    daily = np.zeros(len(sessions))
    pos = {d: i for i, d in enumerate(sessions)}
    for r, d in zip(r_base, days):
        daily[pos[d]] += r
    return {
        "trades": n,
        "sessions": len(sessions),
        "trades_per_session": n / max(len(sessions), 1),
        "mean_r_base": float(r_base.mean()) if n else float("nan"),
        "ci_base": [lo, hi],
        "mean_r_stress": float(r_stress.mean()) if n else float("nan"),
        "win_rate": float((r_base > 0).mean()) if n else float("nan"),
        "usd_per_trade": float(usd_base.mean()) if n else float("nan"),
        "usd_total": float(usd_base.sum()),
        "max_year_share": year_share(usd_base, days),
        "ex_top5_mean": ex_top(r_base),
        "folds": folds_positive(r_base, days, sessions),
        "twin": twin,
        "dsr_info": deflated_sharpe(daily, n_trials),
        "by_year": {y: {"n": int((np.char.startswith(days.astype(str), y)).sum()),
                        "mean_r": float(r_base[np.char.startswith(days.astype(str), y)].mean())}
                    for y in sorted({d[:4] for d in days})},
    }


def gate(m: dict, split: str) -> tuple[bool, list[str]]:
    """Frozen criteria for one split. Returns (pass, failed reasons). Neighbour stability is the controller's."""
    c = C.CRITERIA["dev" if split == "dev" else "val"]
    fails = []
    if m["trades"] < c["min_trades"]:
        fails.append(f"trades {m['trades']} < {c['min_trades']}")
    if not m["twin"]["p"] < c["twin_p_max"]:
        fails.append(f"twin p {m['twin']['p']:.4f} >= {c['twin_p_max']}")
    if not m["mean_r_base"] > c["mean_r_base_gt"]:
        fails.append(f"mean R {m['mean_r_base']:+.4f} <= 0")
    if not m["ci_base"][0] > c["ci_low_base_gt"]:
        fails.append(f"CI low {m['ci_base'][0]:+.4f} <= 0")
    if not m["mean_r_stress"] > c["mean_r_stress_gt"]:
        fails.append(f"stress R {m['mean_r_stress']:+.4f} <= 0")
    if not m["max_year_share"] <= c["max_year_share"]:
        fails.append(f"max year share {m['max_year_share']:.2f} > {c['max_year_share']}")
    if not m["ex_top5_mean"] > c["ex_top5_mean_gt"]:
        fails.append(f"ex-top5 mean {m['ex_top5_mean']:+.4f} <= 0")
    if sum(1 for f in m["folds"] if f > 0) < c["min_folds_positive"]:
        fails.append(f"folds positive {sum(1 for f in m['folds'] if f > 0)} < {c['min_folds_positive']}")
    return (not fails, fails)
