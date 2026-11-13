# NQ strategy research loop — report (2026-11-02)

**Result: no strategy passed. Nothing is shortlisted.** Two pre-registered hypotheses (6 configurations), both
using ES as a companion signal, were tested on the NQ development split, 2011-02 → 2018-12. All 6 failed the
frozen gate.
- `smt_divergence` did significantly **worse** than random direction.
- `nq_residual_momentum` beat random direction by about the cost of trading (~0.05R) and netted ≈ 0. Its own mechanism check showed the effect it relied on is absent.

No validation split was run (none was allowed). The holdout was never bought or opened.

Loop stopped on: **candidate queue empty**, at 6/10 configurations and ~39/120 active minutes. The 4 reserve
configurations were not spent: no third hypothesis met the bar, and neither failure suggested a refinement (§4).

## 1. Setup

| Item | Value |
|---|---|
| Market | NQ.v.0 (Databento `fut-ohlcv-1m-cont`, front month, unadjusted), traded as **MNQ**: $2/pt, 0.25 tick = $0.50 |
| Companion | Each NQ 5m bar carries the **same-slot ES 5m bar** (`bar['es']`: same ET minutes, closes with the NQ bar; None if missing), ES's previous RTH close and an ES roll flag. Built by the same session builder; ES is information only |
| Decisions / fills | Closed 5m RTH bars (America/New_York); fills simulated on the 1m bars inside them |
| Costs, base | $0.50/side; slippage in ticks: market 1, stop 1, limit 0, target 0, flat 1 |
| Costs, stress | $1.00/side; market/flat 2 ticks; stops 1 tick + a draw from the measured NQ stop-slip PMF (native to NQ) |
| Splits | dev 2011-02-01 → 2018-12-31 (1,986 sessions), val1 2019-01-09 → 2021-12-31 (752), val2 2022-01-10 → 2026-08-14 (1,153); 20 warmup sessions; 5-session gaps |
| Holdout | NQ after 2026-08-14, not on disk; buying it needs Sunny's approval |
| Gate | Identical to the ES loop: dev twin p < 0.005 (side-matched permutation twins, 0.05/10), mean R > 0 with bootstrap CI low > 0, stress R > 0, no year > 40% of P&L, > 0 without the top 5 trades, ≥ 2/3 folds positive, grid neighbours positive; val1 and val2 each with ≥ 100 trades and p < 0.05 |
| Evaluator | `eval/`, a copy of the ES evaluator with only the contract, companion and manifest changed. Frozen at manifest digest `4d7b1cf4…` (392 entries: code, tests, 188 NQ + 188 ES data files, library versions). The ES freeze (`a538db52…`) still verifies |

### Data (step 1)
- NQ 2011-01 → 2026-08-14: no missing months, 0 duplicate timestamps, 0 bad bars, no RTH session mixing contracts. 62 rolls, all at 00:00 UTC.
- ES and NQ have identical session sets in every split under the evaluator's rules. On common sessions, the minute sets differ by 7 ES-only minutes. **0 NQ 5m slots lack an ES bar** in any split.

### Evaluator review (step 2b)
An independent reviewer rebuilt both markets' sessions for every split and **found no look-ahead** in the companion.
- It mutated a scratch copy four ways, and the tests caught each one: next ES slot, today's ES close as previous close, no close trim, no close guard.
- Fixed before the freeze:
  - An `es_roll` flag added (ES and NQ roll on different days).
  - Leftover `_mes` dollar keys renamed.
  - A `build_snapshots` usage line that pointed at the ES package.
  - Two alignment tests tightened to exact.
- Tests: 59 evaluator + 4 controller = 63, all passing. The ES suite still passes unchanged (55).

### Sanity checks (step 3)
- **Always-flat:** 0 trades.
- **Random direction**, one trade a day, 1:1 bracket of 0.2% of price (median 34 ticks), 6 seeds: net −0.13 to −0.16R. That is cost 0.119R plus gross −0.01 to −0.04R, the same conservative-fill drag as ES. Twin p 0.35–0.89.
- **Kill/resume:** 0 duplicate rows.
- **One-byte change:** refused.

**Correction to the plan's cost assumption:**
- A base MNQ round trip costs **3.6 ticks**, because the $1 commission alone is 2 ticks at $0.50/tick (0.8 ticks on MES).
- So a 40-tick stop costs ~0.09R, not ~0.05R. 0.05R needs ~72 ticks (18 pts): 0.78% of price at 2011's ~2,300 (the median whole-session range was 1.16%), 0.10% at 2024's ~18,000.
- At a matched relative stop, NQ is ~20% cheaper in R than ES (0.119R vs 0.153R), not the third to half the plan expected.
- Early-dev years are where costs bite.

## 2. Candidates

Each was pre-registered before its code existed: hypothesis, mechanism, sources, prior, closed-ideas check, exact rules, grid, expected cost at 2011 and 2024 prices, rejection evidence. Hashes are in `ledger.jsonl`. Both trade long and short, because side-matched twins cannot reward drift.

### 2.1 `smt_divergence` — fade NQ when exactly one of NQ/ES takes out an established session extreme (3 configurations) — REJECTED
- **Rule:**
  - Signal: at 10:30–14:40, exactly one market makes a new RTH session high (low) by a tick over an extreme at least 30 minutes old, while the other stays below (above) its own.
  - Trade: fade NQ at the next open. Stop beyond NQ's session extreme and at least M × ADR20. 1:1 target, 60-minute time stop. News-filtered. First signal per side per session.
- **Sources:**
  - Brown, Goetzmann & Kumar 1998 (Dow-theory confirmation; daily/weekly horizon).
  - Retail SMT-divergence indicators (untested).
  - Prior stated as weak.

| M (× ADR20) | trades | net R | 95% CI | stress | gross | cost | twin mean | twin p |
|---|---|---|---|---|---|---|---|---|
| 0.25 | 1,909 | −0.159 | [−0.191, −0.129] | −0.252 | −0.069 | 0.090 | −0.095 | 1.000 |
| 0.35 | 1,895 | −0.119 | [−0.144, −0.094] | −0.187 | −0.052 | 0.067 | −0.070 | 0.9999 |
| 0.5 | 1,888 | −0.086 | [−0.105, −0.068] | −0.135 | −0.038 | 0.048 | −0.049 | 0.9999 |

- The fade loses in every year (2011–18: −0.08 to −0.18R at M=0.35) and in all four pre-registered cases (NQ-led or ES-led, long or short).
- It is 0.04–0.06R worse than random direction: **unconfirmed one-sided extremes continue mildly; they do not fail.**
- The opposite side ("follow the extreme") is ≈ −0.02R net (~+0.05R gross against a 0.067R cost). That is post-hoc and was not tested.

### 2.2 `nq_residual_momentum` — trade NQ in the sign of its β-adjusted residual vs ES at 12:00 (3 configurations) — REJECTED
- **Rule:**
  - Signal: at 12:00, resid = r_NQ − β·r_ES since the RTH open, with β = no-intercept OLS of 5m log returns over the prior 20 full sessions. z = resid / RMS of the prior 20 sessions' 12:00 residuals.
  - Trade: if |z| ≥ Z, trade NQ in the residual's sign at 12:00. Stop 0.5 × ADR20, no target, flat at 15:55.
  - Skip: half days and sessions with a scheduled release between 12:00 and 15:55.
- **Sources:**
  - Chordia & Subrahmanyam 2004 (order-imbalance persistence from order splitting).
  - Against: Lou, Polk & Skouras (industry momentum is overnight, not intraday).
  - Heston, Korajczyk & Sadka 2010 (same-slot continuation across days, not within the day).
  - Prior stated as weak, leaning negative.
  - Distinct from the closed market-level "intraday momentum into the close" (Gao et al.; Baltussen et al.): the signal is orthogonal to the market move.

| Z | trades | net R | 95% CI | stress | gross | cost | twin mean | twin p |
|---|---|---|---|---|---|---|---|---|
| 0.5 | 1,059 | +0.006 | [−0.041, +0.057] | −0.044 | +0.055 | 0.049 | −0.049 | 0.0074 |
| 1.0 | 570 | −0.001 | [−0.068, +0.075] | −0.051 | +0.049 | 0.050 | −0.057 | 0.041 |
| 1.5 | 262 | +0.010 | [−0.105, +0.133] | −0.041 | +0.058 | 0.049 | −0.043 | 0.157 |

- It is the only rule in either loop to beat random direction, but by about the cost (~0.05R), so the net is ≈ 0.
- Twin p 0.0074 at best, against 0.005. The CI spans 0, stress is negative and only 1/3 folds are positive. One year carries ≥ 98% of the P&L, and the result is negative without the top 5 trades.
- Unstable years: 2013 −0.17, 2014 −0.07, 2017 +0.06, 2018 +0.15 (Z=0.5).
- **Mechanism check (information only):** on the Z=0.5 trades, the afternoon *residual itself* moved +0.6 bp in the signal's direction, with a hit rate of 50.5%. The small gross edge came from **ES's** afternoon move lining up with the signal (+2.7 bp), not from residual persistence. It is not the hypothesised effect and is most likely chance in a few years.

## 3. Findings that hold across the candidates
1. **Costs remain first-order on MNQ.**
   - 3.6 ticks per round trip (half of it commission).
   - Wide ADR-scaled stops held costs at 0.05–0.09R. The early-dev years, at 2,300–4,000, carry most of that.
   - An idea needs well over 0.05R gross per trade before the gate is even in play.
2. **The ES companion does not add an exploitable direction signal at 5m–afternoon horizons in 2011–18.**
   - Cross-market non-confirmation at session extremes points the wrong way (continuation, not reversal).
   - The β-adjusted residual does not persist intraday.
   - Together with the ES loop: five intraday families across ES and NQ, none above random direction net of costs.
3. **Continuation, not reversal, is the mild tendency of NQ/ES intraday extremes in 2011–18:** ES shock fade, ES round-number crosses and NQ SMT. The reverse readings are all post-hoc and below cost, and they are recorded so nobody "discovers" them later on the same tape.

## 4. Multiple testing and data spent
- This loop: 6 configurations, all on NQ dev. The ES loop spent 8 on ES dev.
- With the ~23 earlier studies in `data_spend_ledger.json`, the honest trial count on this tape (ES + NQ, highly correlated) is **~37 hypotheses**.
- Under that count, even `nq_residual_momentum`'s p = 0.0074 (best of 3 Z) is unremarkable.
- **Spent by this loop:** NQ dev 2011-02 → 2018-12 for intermarket_divergence / smt_divergence / session_extreme_non_confirmation / session_extreme_follow, and residual_momentum / relative_strength_intraday / order_flow_persistence / residual_reversal. Rows are in `research_loop/data_spend_ledger.json`; families are in `research_loop/CLOSED_IDEAS.md` (shared with ES).
- **Reserve not spent:** 4 configurations. Considered and dropped:
  - Long-only calendar effects (turn of month, pre-FOMC drift): unpassable under side-matched twins.
  - Gap fade / overnight levels: closed or near-closed families.
  - Same-slot half-hour continuation and 5m ES→NQ lead-lag: expected edges of a few bp against 3.6 ticks.
- **Not touched by this loop:** NQ val1, val2 and the holdout. val1/val2 were already seen by earlier families (ORB, CHoCH, VWAP, opening-candle EMA on ES/NQ; ETF proxies 2022+).

## 5. Limitations
- **Same-chat evaluator.** The chat that wrote the evaluator also wrote the strategies, and it had seen the ES results first. The NQ evaluator was frozen before the first NQ candidate existed and hash-checked on every run; strategies run in a child process behind an import/attribute allowlist. This is weaker than true isolation.
- **Prior exposure.** NQ dev overlaps windows used by earlier CME studies, and the model knew the ES-loop outcomes when choosing candidates. ES and NQ are ~0.9 correlated intraday, so ES evidence counts against NQ re-runs. That is why no ES family was re-run here.
- **Stress stop slip.** The PMF was measured on NQ in 2025–26 (~25,000) and is applied to 2011–18 (2,300–7,000), when a tick was much larger relative to price. Stress scenario only.
- **Companion edge case.** A fully dropped ES day would make `es` None for the whole day (end-of-day information). There are 0 such days on disk.
- **Calendar.** As in the ES loop: ISM dates 2011–2021 are rule-based; `news_day` is unknown for 2011.
- **Warmup.** `nq_residual_momentum` needs 20 sessions of β plus 20 stored residuals, so it could not trade in roughly the first 20 dev sessions.
- **Sources** were checked at abstract or secondary-summary level (noted in each prereg). The SMT sources are practitioner material.

## 6. Holdout and paper trading
No candidate qualifies, so **no holdout should be bought or run**. If a future NQ candidate passes dev and **both** val1 and val2 under this frozen evaluator:
1. Freeze it (prereg and strategy hashes in the ledger). Get Sunny's approval to buy NQ (and ES, for the companion) `fut-ohlcv-1m-cont` from 2026-08-15 to the freeze date (roughly $1–2 each on Databento; `databento_fetch.py`).
2. Add the new files to a **new** manifest version, with the evaluator code unchanged. Run the frozen strategy on the holdout **once** and record it in the ledger whatever the result.
3. If it is positive: paper-trade 1 MNQ for at least 60 sessions, logging fills against the model's assumed fills (3.6 ticks/RT, stop slip, time-stop exits). Only then consider a prop-firm container (`lucid_structure` / `prop_structure`).

## 7. Files
- `research_loop_nq/PLAN.md`: plan copy (sha 5e051fdc…).
- `eval/`: frozen evaluator + `MANIFEST.sha256` (digest 4d7b1cf4…).
- `controller.py` and `tests/` (`test_eval.py` is frozen; `test_controller.py` is not).
- `prereg/*.json`, `strategies/*.py` (plus `_sanity_*`).
- `ledger.jsonl`: every run and sanity check.
- Shared with ES: `research_loop/data_spend_ledger.json`, `research_loop/CLOSED_IDEAS.md`.
- `functions/ml/data/research_loop_nq/`:
  - `state.json`
  - `LOG.md` (one entry per firing)
  - `runs/<id>/<split>_<k>.json` (per-trade detail)
  - `inventory_nq.json`
