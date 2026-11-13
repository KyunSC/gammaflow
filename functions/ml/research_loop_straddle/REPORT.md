# Delta-hedged 0DTE straddle: confirmation result

**Verdict: FAILED in window A (2016/17 → 2018). Window B (2019 → 2021) was never opened. Thread closed.**

## What was tested
- Spec (frozen by hash, `prereg.json`): `delta_hedge.py`, unchanged.
  - Sell 1 ATM same-day-expiry QQQ/SPY straddle at the 09:35 ET bid.
  - Delta-hedge with shares every 5 minutes (primary) or every 30 minutes (secondary).
  - Settle at intrinsic at 16:00.
  - Half days skipped, including the 12 pre-2022 ones that `delta_hedge.EARLY_CLOSE` lacked.
- Costs (`confirm.py`):
  - Options: $0.65/contract × 2 (stress $1.00).
  - Hedge: $0.005 per share traded (stress $0.01).
  - Entry at the bid.
  - Cash settlement stands in for assignment. Real ETF options are American and physically settled, so pin risk is not modelled.
- Gate (approved 2026-11-03). A window passes only if the 5m cell passes on both QQQ and SPY. Each cell needs all of:
  - Mean net > 0.
  - Day-bootstrap 95% CI low > 0.
  - One-sided p < 0.0125.
  - Stress mean > 0.
  - No year below −2× the mean annual gain.
  - Mean with the 5 worst days doubled > 0.
- The 2022 → 2026-09 discovery figures still reproduce from `data/delta_hedge`: QQQ +$18.87 (SE 2.66), SPY +$13.30 (SE 2.35). These are before option commissions, at 0.5 bp hedge cost.

## Window A (one look, 2026-11-03)
QQQ: 156 days, 2016-01 → 2018-12, Fridays only. SPY: 248 days, 2017-01 → 2018-12. Dollar figures are per straddle (×100).

| Cell | Gross | Base cost | Net | SE | 95% CI | p | Stress | Worst day | CVaR 5% | Max DD | Margin | Return on margin |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **QQQ 5m** | +4.38 | 4.10 | **+0.28** | 1.51 | −2.72..+3.20 | 0.43 | −3.22 | −63 | −48 | 298 | ~2,890 | +0.01% |
| **SPY 5m** | +1.59 | 4.17 | **−2.58** | 2.05 | −6.66..+1.37 | 0.90 | −6.15 | −168 | −94 | 938 | ~5,360 | −0.05% |
| QQQ 30m | +4.79 | 2.58 | +2.21 | 2.19 | −2.06..+6.39 | 0.16 | +0.23 | −97 | −71 | 338 | ~2,890 | +0.08% |
| SPY 30m | +2.59 | 2.60 | −0.01 | 2.99 | −6.10..+5.68 | 0.50 | −2.00 | −321 | −135 | 810 | ~5,360 | 0.00% |

- Both deciding cells fail; SPY 5m misses all six rules. 30m (reported only) fails as well.
- By year (5m net): QQQ 2016 +$66, 2017 +$148, 2018 −$169; SPY 2017 +$98, 2018 −$738. 2018 is negative in every cell (Feb Volmageddon, Oct–Dec selloff).
- The 5 worst days are all late 2017 / 2018. Doubling them turns every cell negative.

## Why
- The premium was barely there. Mean entry IV minus realized vol: SPY +0.2 vol points, QQQ +2.1. At 2016–18 prices (QQQ ~$140, SPY ~$262) the straddle averaged $83 / $115.
- Gross 5m P&L of +$4.4 / +$1.6 is about the size of the per-straddle costs. ~560 shares trade per day whatever the share price, plus $1.30 commission.
- The 2022+ result came from a period with a wider implied-over-realized gap and higher share prices. It did not hold in the earlier regime.

## Data spent
- QQQ 0DTE 2016-01 → 2018-12 and SPY 0DTE 2017-01 → 2018-12 are spent for this trade.
- 2019 → 2021 (window B) is unopened. It stays closed for this spec under the plan rule; a different idea may use it.
- 2026-09-26 → 2026-10-23 is untouched.

## Files
- `prereg.json`, `confirm.py`, `tests/test_confirm.py` (26 tests), `ledger.jsonl`.
- Under `data/research_loop_straddle/`: `window_A_days.parquet`, `window_A_stats.json`, `LOG.md`.
