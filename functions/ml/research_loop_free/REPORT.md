# Free-data ideas loop — final report (2026-11-05, 02:58 ET)

**Outcome: no idea passed.** 15 ideas were proposed over 3 batches. 13 were tested (38 configurations) and all 13
failed their frozen discovery gate. The other 2 were dropped before running because they could never reach the
200-trade floor. No validation, val1, val2 or holdout data was opened. No data was bought.

The loop stopped because batch 3's queue is empty, about 10.5 hours before the 13:30 ET deadline.

Detail is in `data/research_loop_free/LOG.md` (firings 1–20). Each idea's prereg, strategy and unit test is under
`research_loop_free/{,b2/,b3/}<eval>/`, with run files under `data/research_loop_free/`.

## The bar

A result passes only if it clears its evaluator's own gate (twin p < 0.005 plus the inherited CI, stress, year-share,
fold and neighbour checks) **and** the loop-wide bar **p < 0.05 / 38 = 0.0013**.

## Results

"Best p" is the lowest side-matched twin p across that idea's configs and gated assets.

| Batch | Idea | Evaluator | Configs | Best p | Clears 0.005? | Clears 0.0013? | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | F1 pre-open news gap | ES intraday dev | 3 | 0.32 | no | no | FAIL (gross ≈ 0 vs 0.19R cost) |
| 1 | F2 Friday squaring | ES intraday dev | 3 | 0.91 | no | no | FAIL, wrong sign |
| 1 | F3 yield shock | ES daily dev | 3 | 0.67 | no | no | FAIL, wrong sign |
| 1 | F4 wide-range continuation | ES daily | 0 | — | — | — | DROPPED on count (170/77/34) |
| 1 | F5 weekend fade | crypto train | 0 | — | — | — | DROPPED on count (BTC 107/46/26, ETH 125/67/38) |
| 1 | F6 funding print | crypto train | 3 | 0.37 (ETH) | no | no | FAIL |
| 1 | F7 liquidation fade | crypto train | 3 | 0.25 (BTC) | no | no | FAIL (volume filter inert) |
| 2 | G1 VIX9D/VIX inversion | ES daily dev | 3 | 0.43 | no | no | FAIL (gross ≈ 0) |
| 2 | G4 VRP direction | ES daily dev | 3 | 0.88 | no | no | FAIL, wrong sign |
| 2 | G2 top-trader fade | crypto train | 2 | **0.0005 (BTC)** | BTC yes, ETH no | BTC yes, ETH no | FAIL: BTC session CI < 0, stress < 0, 61–68% of R in one year; ETH p 0.11; 24h-reversal proxy |
| 2 | G5 smart vs retail | crypto train | 3 | 0.0045 (BTC) | BTC yes, ETH no | no | FAIL: BTC gross ≈ cost, CI/stress/year share fail; ETH negative |
| 2 | G3 US-open fade | crypto train | 3 | 0.63 | no | no | FAIL, wrong sign |
| 3 | H3 crypto TSMOM | crypto train | 3 | 0.018 (BTC) | no | no | FAIL (long leg carries it) |
| 3 | H2 crypto same-hour periodicity | crypto train | 3 | 0.11 (ETH) | no | no | FAIL (gross ≈ 0 vs 0.051R) |
| 3 | H1 ES same-hour periodicity | ES intraday dev | 3 | 0.55 | no | no | FAIL (gross ≈ 0 vs 0.118R) |

**Configs per evaluator copy** (each capped at 10):

| Batch | ES intraday | ES daily | Crypto |
|---|---|---|---|
| 1 | 6 | 3 | 6 |
| 2 | — | 6 | 8 |
| 3 | 3 | — | 6 |

**The two near-misses are both BTC-only and both fail on robustness, not on p:**
- **G2:** its edge sat only in trades where the prior 24h move agreed with the crowd's lean, which makes it a 24h price-reversal proxy.
- **G5:** its gross ≈ cost.

Neither passes, and neither is put forward for validation.

## Data looks and spend

- **ES dev (2011-02 → 2018-12):** read by F1–F4, G1, G4 and H1.
- **Crypto train block (2020-01 → 2024-06):** opened by every crypto run and count check. Each open is in `data/binance/looks.jsonl`, tagged `loop: crypto_perp` by the frozen code. The counts:
  - 10 count-only checks;
  - 6 report-only controls;
  - 2 sanity runs (b3);
  - 2 opens from a crashed G2 run that wrote no results (wrapper missing a `__main__` guard; fixed and rerun);
  - the gated runs themselves.
- **Validation, val1, val2, test and holdout:** never opened.
- Every run, spend row and closed idea is mirrored into the shared `research_loop/ledger.jsonl`, `data_spend_ledger.json` and `CLOSED_IDEAS.md` under the shared lock.

## Report-only observations (not traded, never run as candidates)

- **H1 previous-hour control: ES 1h intraday momentum.** Gross +0.019R with twin p 2e-5 over 11,255 trades, but net −0.098R because a one-hour 1:1 bracket costs 0.117R.
  - The signal is real but about 1/6 of cost.
  - It sits in the closed intraday-momentum neighbourhood.
- **H3: crypto momentum beyond drift.** At L = 14–28 days, gross is +0.035 to +0.041R vs +0.014 to +0.020R for always-long. It is carried by the long leg, and p is 0.018–0.04.

Post-hoc reversals, logged and never run (each would need a fresh, unspent window):
- F2: follow WTD on Friday.
- F3: ES follows the 10y yield move.
- F6: BTC fades the crowd after a funding print.
- G4: low VRP → long.
- G2: BTC 24h reversal when accounts lean with it.
- G3: follow the overnight move at the US open.
- H1: ES 1h momentum.

## Deviations and fixes (all logged where they happened)

- **F1:** the day filter was tightened in the prereg (news_day and no RTH release).
- **Count-drop rule:** applied to every config of every idea, using the non-overlapping count, as F7 did. G2 Z = 2.0 was dropped this way, and run through `b2/crypto/run_subset.py`, a wrapper that leaves the frozen evaluator untouched.
- **Shared-ledger mirror rows:** tagged `external_run`. The crypto controllers' `cmd_run` purpose label still reads "crypto perp loop".
- **Test fixes:** test-only fixes before runs (G5 field name, H3 vacuous assert, F7 helper), plus one docstring reword (G3) to satisfy the sandbox regex. No strategy logic changed after a result.
- **Crypto truncation check:** it reports one mismatch per cut for decisions on a bar that closes exactly at the cut (H3 and H2: no entry bar in the truncated data). This is an artifact, not lookahead, and both ideas fail on p anyway.

## Waiting for Sunny

1. **F4 (wide-range continuation) and F5 (weekend fade)** were dropped untested because they can't reach 200 trades. Testing them needs a looser F4 spec (a new prereg) or a pooled or longer crypto window (an evaluator change).
2. **Judgement calls on "distinct from a closed idea":**
   - G1 (VIX9D/VIX *level*) vs the closed V3 (VIX/VIX3M *change*);
   - H3 (crypto TSMOM) vs the closed E1 (ES daily TSMOM).

   Both were judged distinct and both failed, so this only affects the bookkeeping.
3. **Approvals:** `val2 approval: PENDING` and `crypto val approval: PENDING`, unchanged. Nothing passed, so there is nothing to validate.
4. **Crypto evaluator truncation check:** it could compare only signals with an entry bar before the cut, so daily and hourly decisions closing on a cut stop false-flagging. This is an evaluator change, out of scope for this loop.
5. **Uncommitted files:** all new files are uncommitted (no git writes, per CLAUDE.md):
   - `research_loop_free/{b2,b3}/`, the batch preregs, `bootstrap_b3.py` and this report;
   - `data/research_loop_free/`;
   - the shared ledger appends.
