"""Frozen evaluator constants: contract, costs, splits, sessions, and the pass criteria.

Everything a candidate is judged by lives here and is covered by MANIFEST.sha256. Set before any candidate exists.

Daily-bracket loop copy of research_loop_volsig/eval (+ UST 10y daily series).

The traded product is chosen per PROCESS by the environment variable DAILY_PRODUCT ("NQ" -> MNQ on QQQ options
features, "ES" -> MES on SPY options features); there is no default, so a run can never silently use the wrong
contract. Spawned strategy children and twin workers inherit it. The manifest covers both products.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
LOOP_DIR = EVAL_DIR.parent
ML = LOOP_DIR.parent
BARS_DIR = ML / "data" / "databento" / "fut-ohlcv-1m-cont"
OUT_DIR = ML / "data" / "research_loop_daily"
# Daily loop: copied from research_loop_volsig/eval. The options features, Cboe CSVs and ex-div dates are READ from the
# volsig loop's frozen data dir (hashed there and pinned again in this manifest), not copied.
VOLSIG_LOOP_DIR = ML / "research_loop_volsig"
VOLSIG_DATA = ML / "data" / "research_loop_volsig"
FEATURES_DIR = VOLSIG_DATA / "features"  # volsig build_features.py output, frozen: <OPTIONS>.parquet
CBOE_DIR = VOLSIG_DATA / "cboe"          # Cboe daily history CSVs, frozen
EXDIV_DIR = VOLSIG_DATA / "exdiv"        # <OPTIONS>.csv ex-dividend dates (yfinance + 1 manual fix), frozen
UST_DIR = OUT_DIR / "treasury"           # US Treasury daily par yield curve (home.treasury.gov), frozen: ust10y_daily.csv

# --- Market and contract -------------------------------------------------------------------------------------
# Databento <PRODUCT>.v.0: front month, volume roll, unadjusted. The companion's same-slot 5m bar rides on each bar
# as bar['comp'] (information only, never traded). OPTIONS = the ETF whose 5m options features are bar['opt'].
PRODUCTS = {
    "NQ": {"companion": "ES", "options": "QQQ", "point_value": 2.0},   # MNQ: $2/pt, tick $0.50
    "ES": {"companion": "NQ", "options": "SPY", "point_value": 5.0},   # MES: $5/pt, tick $1.25
}
PRODUCT = os.environ.get("DAILY_PRODUCT", "")
if PRODUCT not in PRODUCTS:
    raise RuntimeError(f"set DAILY_PRODUCT to one of {sorted(PRODUCTS)} (got {PRODUCT!r})")
COMPANION = PRODUCTS[PRODUCT]["companion"]
OPTIONS = PRODUCTS[PRODUCT]["options"]
POINT_VALUE = PRODUCTS[PRODUCT]["point_value"]
TICK = 0.25
COMMISSION_PER_SIDE = 0.50          # Lucid MNQ/MES all-in (memory lucid-commission)
STRESS_COMMISSION_PER_SIDE = 1.00   # 2x

# Slippage in ticks, adverse, by fill kind. Limit entries and targets fill at their price only after the market
# trades a tick through it (fill_study: tick-through ~ truth). Stops: base 1 tick; stress 1 tick + a draw from
# the measured NQ stop-slip PMF in ticks (fill_study measured NQ; native for MNQ, conservative for MES).
SLIP_BASE = {"market": 1, "stop": 1, "limit": 0, "target": 0, "flat": 1}
SLIP_STRESS = {"market": 2, "stop": 1, "limit": 0, "target": 0, "flat": 2}
STRESS_STOP_PMF = True

# --- Sessions ------------------------------------------------------------------------------------------------
TZ = "America/New_York"
RTH_OPEN = 9 * 60 + 30     # ET minutes after midnight
RTH_CLOSE = 16 * 60        # normal NYSE close
HALF_CLOSE = 13 * 60       # NYSE early close (CME trades to 13:15; RTH here stops at 13:00)
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
# Dev for ideas that read bar['opt']: starts at the options data (QQQ 2016-01-04); the 20 warmup sessions put the
# first trade on 2016-02-02. Cboe-only ideas use "dev". ES has NO dev_opt: SPY options start 2017-01-03, so its dev
# would be 2017-02..2018-12, two calendar years, where max_year_share 0.40 can never pass (one year always holds
# >= 50% of a positive total). The criteria are not changed for it: IV ideas run on NQ (QQQ -> MNQ) only.
if PRODUCT == "NQ":
    SPLITS["dev_opt"] = (date(2016, 1, 1), date(2019, 1, 1))
DEV_OPT_REFUSED = {"ES": "SPY options start 2017-01-03: an ES dev_opt spans 2 calendar years and max_year_share 0.40 "
                         "cannot pass; IV ideas run on NQ only"}
DEV_SPLITS = ("dev", "dev_opt")   # warmup = WARMUP_SESSIONS from the split start; val splits: GAP_SESSIONS

# --- Options and daily inputs --------------------------------------------------------------------------------
# bar['opt'] for 5m slot k (start S_k) is the features row with slot_end == S_k + 5 min: the ThetaData snapshot
# taken at the bar's close (iv_5m rows are snapshots at their timestamp, LOG iteration 1). Missing row -> None;
# NaN field -> None. bar['opt']['exdiv'] is True when an ex-dividend date of the ETF falls in (trade date, expiry]:
# ThetaData's IVs ignore dividends, so on those days call IVs read low and put IVs high (iv_spread -2..-8 vol pts,
# skew25 ~2x; review 3b). Ex-dates are announced in advance, so the flag is known that morning. bar['daily'] holds Cboe closes and the UST 10y yield dated the PREVIOUS session of the traded product (published
# after 16:15 ET that day); a series without a row that date -> None.
OPT_FIELDS = ("expiry", "dte", "S", "atm_iv", "atm_call_iv", "atm_put_iv", "iv_spread", "put25_iv", "call25_iv",
              "skew25", "n_call", "n_put")
DAILY_SERIES = ("VIX", "VIX9D", "VIX3M", "VVIX", "SKEW")
# US Treasury 10-year par yield (percent), from UST_DIR/ust10y_daily.csv. Same lag rule as the Cboe series: the value
# dated the PREVIOUS session of the traded product, else None (bond-market holidays such as Columbus and Veterans Day
# have no print although ES trades). Never "latest print before today": Treasury prints on Good Friday and on some
# NYSE closures (2012-10-29, 2025-01-09) when ES has no session.
UST_SERIES = ("UST10Y",)
# bar['hist'] carries up to HIST_SESSIONS prior sessions of the product's own list (load_split loads 60 calendar days
# before a split, so the first dev trades see fewer: ~20 sessions at 2011-02-01). ROLL_MAX_GAP_S bounds the spacing of
# the two 1m bars around a contract switch (all 2011-2026 switches: <= 6 min, Globex).
HIST_SESSIONS = 60
ROLL_MAX_GAP_S = 600
LAST_ON_DISK = date(2026, 8, 14)
GAP_SESSIONS = 5           # first sessions of val1 / val2 are warmup only (no trades), as holdout.py
WARMUP_SESSIONS = 20       # sessions fed to the strategy before the first tradeable one, actions ignored
FOLDS = 3                  # contiguous session blocks for the sign-stability check

# --- Statistics ----------------------------------------------------------------------------------------------
N_TWINS = 50000           # MC SE of p at 0.005 ~ 0.0003
N_BOOT = 2000
SEED = 20261102
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
