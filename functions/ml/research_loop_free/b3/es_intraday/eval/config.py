"""Frozen evaluator constants: contract, costs, splits, sessions, and the pass criteria.

Everything a candidate is judged by lives here and is covered by MANIFEST.sha256. Set before any candidate exists.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
LOOP_DIR = EVAL_DIR.parent
ML = LOOP_DIR.parent.parent.parent
BARS_DIR = ML / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT_DIR = ML / "data" / "research_loop_free" / "b3" / "es_intraday"

# --- Market and contract -------------------------------------------------------------------------------------
PRODUCT = "ES"            # Databento ES.v.0: front month, volume roll, unadjusted
POINT_VALUE = 5.0         # traded as MES: $5 per index point
TICK = 0.25               # 1 tick = $1.25 on MES
COMMISSION_PER_SIDE = 0.50          # Lucid MES all-in (memory lucid-commission)
STRESS_COMMISSION_PER_SIDE = 1.00   # 2x

# Slippage in ticks, adverse, by fill kind. Limit entries and targets fill at their price only after the market
# trades a tick through it (fill_study: tick-through ~ truth). Stops: base 1 tick; stress 1 tick + a draw from
# the measured NQ stop-slip PMF in ticks (ES's book is thicker, so applying NQ ticks to ES is conservative).
SLIP_BASE = {"market": 1, "stop": 1, "limit": 0, "target": 0, "flat": 1}
SLIP_STRESS = {"market": 2, "stop": 1, "limit": 0, "target": 0, "flat": 2}
STRESS_STOP_PMF = True

# --- Sessions ------------------------------------------------------------------------------------------------
TZ = "America/New_York"
RTH_OPEN = 9 * 60 + 30     # ET minutes after midnight
RTH_CLOSE = 16 * 60        # normal NYSE close
HALF_CLOSE = 13 * 60       # NYSE early close (ES trades to 13:15; RTH here stops at 13:00)
BAR_MINUTES = 5
MIN_RTH_BARS = 200         # 1m bars; anything thinner is not a tradeable session
# NYSE closed although CME printed RTH-hour bars (bar shape alone would not drop them).
NYSE_ADHOC_CLOSURES = {date(2012, 10, 29), date(2012, 10, 30), date(2018, 12, 5), date(2025, 1, 9)}
# A session whose last RTH 1m bar starts at or before 13:00 ET is a CME holiday session (NYSE closed): dropped.
CME_HOLIDAY_LAST_MOD = 13 * 60
# NYSE half days come from the published rule (data.nyse_half_day), known in advance; the data must agree: a
# half day's last RTH-hour 1m bar is 13:14 or 13:15 ET.
HALF_DAY_LAST_MODS = {13 * 60 + 14, 13 * 60 + 15}
# Unscheduled releases that must not appear in the "known in advance" calendar.
UNSCHEDULED_EVENT_DAYS = {date(2020, 3, 3)}   # emergency FOMC cut, announced 10:00 that day

# --- Splits --------------------------------------------------------------------------------------------------
# [start, end) ET dates. The holdout (after LAST_ON_DISK) is not on disk; the evaluator refuses any other split.
SPLITS = {
    "dev": (date(2011, 1, 1), date(2019, 1, 1)),
    "val1": (date(2019, 1, 1), date(2022, 1, 1)),
    "val2": (date(2022, 1, 1), date(2026, 8, 15)),
}
LAST_ON_DISK = date(2026, 8, 14)
GAP_SESSIONS = 5           # first sessions of val1 / val2 are warmup only (no trades), as holdout.py
WARMUP_SESSIONS = 20       # sessions fed to the strategy before the first tradeable one, actions ignored
FOLDS = 3                  # contiguous session blocks for the sign-stability check

# --- Statistics ----------------------------------------------------------------------------------------------
N_TWINS = 50000           # MC SE of p at 0.005 ~ 0.0003
N_BOOT = 2000
SEED = 20261105
ATTEMPT_LIMIT = 10

# --- Criteria (frozen; never lowered inside the loop) --------------------------------------------------------
CRITERIA = {
    "dev": {
        "min_trades": 200,
        "twin_p_max": 0.05 / ATTEMPT_LIMIT,   # Bonferroni across the loop's configurations; side-matched twins
        "mean_r_base_gt": 0.0,
        "ci_low_base_gt": 0.0,
        "mean_r_stress_gt": 0.0,
        "max_year_share": 0.40,
        "ex_top5_mean_gt": 0.0,
        "min_folds_positive": 2,
        "neighbours_positive": True,          # checked by the controller across the candidate's grid
    },
    "val": {   # applied to val1 and val2 separately; a shortlist needs both
        "min_trades": 100,
        "twin_p_max": 0.05,
        "mean_r_base_gt": 0.0,
        "ci_low_base_gt": 0.0,
        "mean_r_stress_gt": 0.0,
        "max_year_share": 0.40,
        "ex_top5_mean_gt": 0.0,
        "min_folds_positive": 2,
    },
}
