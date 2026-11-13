"""Constants of the crypto perp loop's frozen evaluator. Values follow the MFP study (mfp_crypto_study.py, 416dbd4).

Costs come from fixtures/mfp_markets.json (asof 2026-10-18), re-checked against docs.myfundedperpetuals.com on
2026-11-03 (LOG.md firing 1): unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

EVAL = Path(__file__).resolve().parent
LOOP = EVAL.parent                       # functions/ml/research_loop_crypto
ML = LOOP.parent.parent                  # functions/ml
STATE = ML / 'data' / 'research_loop_free' / 'crypto'
RAW = ML / 'data' / 'research_loop_crypto' / 'raw'
BINANCE = ML / 'data' / 'binance' / 'um'
LOOKS = ML / 'data' / 'binance' / 'looks.jsonl'
SHARED_LOCK = ML / 'research_loop' / '.shared.lock'

ET = 'America/New_York'
BLOCKS = {
    'train': ('2020-01-01', '2024-07-01'),
    'validation': ('2024-07-08', '2025-07-01'),
}
TEST_START = pd.Timestamp('2025-07-08', tz='UTC')   # this loop never opens it
MAX_VALIDATION_LOOKS = 5

MARKETS = json.loads((EVAL / 'fixtures' / 'mfp_markets.json').read_text())['markets']
SYMBOLS = {'BTCUSDT': 'BTC', 'ETHUSDT': 'ETH', 'SOLUSDT': 'SOL'}

N_TWINS = 2000
EV_PATHS = 200
EV_BLOCK_DAYS = 7
EV_HORIZON_DAYS = 1460
EV_SEED = 42
R_BOOT = 4000
R_BOOT_BLOCK = 10
SEED = 20261105
LOOKAHEAD_FRAC = 0.25
COIN_CONTROLS = 200
STALE_RUN = 3
MAX_WORKERS = 3                          # plan: cap twin/permutation workers at 3 (other loops run in parallel)
