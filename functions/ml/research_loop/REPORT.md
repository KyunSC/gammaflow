# ES strategy research loop — report (2026-11-02)

**Result: no strategy passed. Nothing is shortlisted.** Three pre-registered hypotheses (8 configurations) were
tested on the ES development split, 2011-02 → 2018-12. All 8 failed the frozen gate, and every one of them did
*worse* than random-direction trades placed at the same times. No validation split was run (none was allowed),
and the holdout was never bought or opened.

Loop stopped on: **candidate queue empty**, at 8/10 configurations and 68/120 active minutes. The 2 reserve
configurations were not spent, because no refinement had evidence behind it.

## 1. Setup

| Item | Value |
|---|---|
| Market | ES.v.0 (Databento `fut-ohlcv-1m-cont`, front month, unadjusted), traded as **MES**: $5/pt, 0.25 tick = $1.25 |
| Decisions / fills | Closed 5m RTH bars (America/New_York); fills simulated on the 1m bars inside them |
| Costs, base | $0.50/side; slippage in ticks: market 1, stop 1, limit 0, target 0, flat 1 |
| Costs, stress | $1.00/side; market/flat 2 ticks; stops 1 tick + a draw from the measured NQ stop-slip PMF (conservative for ES) |
| Splits | dev 2011-02-01 → 2018-12-31 (1,986 sessions), val1 2019-01-09 → 2021-12-31 (752), val2 2022-01-10 → 2026-08-14 (1,153); 20 warmup sessions; 5-session gaps |
| Holdout | ES after 2026-08-14, not on disk; buying it needs Sunny's approval |
| Gate (dev) | ≥ 200 trades; side-matched twin p < 0.005 (0.05 / 10, Bonferroni); mean net R > 0 with the session-bootstrap CI low > 0; stress R > 0; no year > 40% of P&L; still > 0 without the top 5 trades; ≥ 2 of 3 folds positive; grid neighbours positive |
| Gate (val1, val2 each) | Same, with ≥ 100 trades and p < 0.05 |
| Evaluator | `eval/`, frozen at manifest digest `a538db52…` (204 entries: code, tests, 188 data files, library versions) |

Fill rules (all structural, all tested):
- Next-bar fills.
- Stop wins when one 1m bar touches both the stop and the target.
- Targets and limits need a tick traded through and never fill better than their price.
- Limits must be passive; all prices snap to the tick.
- A gap through the stop fills at the open.
- Flat at the open of 15:55 (12:55 on half days).

### Evaluator review (step 2b)
An independent reviewer found 4 major and 10 minor issues. All were fixed before the freeze:
- **M1:** a marketable limit got a market fill with zero slip.
- **M2:** prices off the tick grid filled at prices that cannot trade (about +0.5 tick per stop).
- **M3:** **50/50 coin-flip twins rewarded drift.** A long-only strategy with no skill passed at p = 0.0005. The gate now uses side-matched permutation twins.
- **M4:** the 2020-03-03 emergency cut sat in the "scheduled" calendar.
- Minor:
  - Action validation added.
  - Half days taken from the published NYSE rule and checked against the data.
  - Sandbox loopholes closed.
  - Manifest coverage widened.
  - 50,000 twins.

Tests went from 31 to 52; with the controller tests, 55 pass.

### Sanity checks (step 3)
- **Always-flat:** 0 trades.
- **Random direction:** one trade a day, 4 pt 1:1 bracket, 6 seeds. Net −0.17 to −0.20R = cost 0.15R + gross about −0.03R. That gross is the expected drag from the conservative rules: a stop fills on a touch, while a target needs a tick through. Twin p was 0.32–0.94.
- **Kill/resume:** 0 duplicate or lost ledger rows.
- **One-byte change:** refused.

## 2. Candidates

Each was pre-registered (hypothesis, mechanism, sources, exact rules, grid, rejection evidence) before its
code existed. The prereg and strategy hashes are in `ledger.jsonl`.

### 2.1 `shock_fade` — fade unusually large mid-session 5m moves (3 configurations) — REJECTED
- **Rule:** at 10:00–15:15, a 5m close-to-close move of at least K × the same-slot mean |move| over the prior 20 sessions and at least 3 pts, with no scheduled release near it. Fade it at the next open with a 1:1 bracket of the shock size and a 30-minute time stop.
- **Sources:** Grant, Wolf & Yu 2005 (S&P futures open reversals, largely erased by costs); Nagel 2012 (reversal = liquidity provision).

| K | trades | net R | 95% CI | stress | gross | cost | twin p |
|---|---|---|---|---|---|---|---|
| 2.5 | 3,071 | −0.219 | [−0.249, −0.188] | −0.374 | −0.069 | 0.149 | 0.998 |
| 3.0 | 2,452 | −0.211 | [−0.246, −0.178] | −0.364 | −0.063 | 0.148 | 0.993 |
| 3.5 | 1,921 | −0.195 | [−0.231, −0.159] | −0.344 | −0.049 | 0.145 | 0.936 |

- Negative in all 8 years, for longs and shorts alike.
- The fade is 0.03–0.05R worse than random direction: non-news shocks **continue mildly**.
- Costs (0.15R at a 4 pt median risk) swamp either direction.

### 2.2 `round_cross` — trade with a 5m close through a round number (3 configurations) — REJECTED
- **Rule:** at 10:00–14:50, a 5m close at least 2 ticks through a multiple of STEP, the first such cross of each level per session. Enter in the cross direction, stop 8 pts back through the level, 1:1 bracket, 60-minute time stop.
- **Sources:** Osler 2003 (FX stop-losses cluster beyond round numbers); Donaldson & Kim 1993; Ley & Varian 1994 (sceptical).

| STEP | trades | net R | 95% CI | stress | gross | cost | twin p |
|---|---|---|---|---|---|---|---|
| 25 | 940 | −0.118 | [−0.156, −0.083] | −0.192 | −0.046 | 0.072 | 0.992 |
| 50 | 490 | −0.107 | [−0.160, −0.053] | −0.181 | −0.034 | 0.072 | 0.892 |
| 100 | 221 | −0.137 | [−0.219, −0.056] | −0.211 | −0.065 | 0.071 | 0.950 |

- The wider bracket held costs to 0.07R.
- The cross direction is 0.03–0.07R worse than random: price **mildly reverts** after the cross.
- No "rounder is stronger" ordering. Only 2014 was positive.

### 2.3 `release_fade` — fade the first move after a scheduled in-session release (2 configurations) — REJECTED
- **Rule:** on the first in-session release (FOMC decision or minutes, ISM 10:00), compare the close W minutes later with the close at the release. Fade a move of at least 2 pts with risk = max(|move|, 8 pts), a 1:1 bracket and a 120-minute time stop.
- The direction was switched from "follow" to "fade" before any data, on the sources: Boguth et al. (~60% of post-FOMC returns reverse); an E-mini press-conference-day reversal (secondary).

| W | trades | net R | 95% CI | stress | gross | cost | twin p |
|---|---|---|---|---|---|---|---|
| 5 min | 144 | −0.059 | [−0.197, +0.084] | −0.141 | +0.017 | 0.076 | 0.305 |
| 15 min | 174 | −0.118 | [−0.227, +0.003] | −0.200 | −0.042 | 0.076 | 0.752 |

- Both fail, starting with the 200-trade minimum.
- Report-only splits: ISM days ≈ 0 (−0.02 / −0.05R). Press-conference days, the subset the sources support, were the **worst** (−0.29 / −0.39R, n = 23): the move continued.

## 3. Findings that hold across the candidates
1. **Costs are first-order for intraday MES.**
   - 1–2 ticks of slippage plus $1 commission cost 0.15R at a 4 pt risk and 0.07R at about 9 pts.
   - The conservative fill rules add about −0.03R gross even for a random strategy.
   - A real edge has to be well above 0.1R gross per trade to survive.
2. **None of the three hypothesised directions beat random direction.**
   - The reverse readings (shock momentum, fading round-number crosses, following press-conference moves) are post-hoc, small (≤ 0.07R gross) and below costs. They were deliberately not tested.
   - They are recorded here so nobody "discovers" them later on the same data.
3. **Literature effects did not transfer to mid-session ES 2011–2018**, consistent with Grant et al.'s own cost caveat and with the repo's earlier failures (`CLOSED_IDEAS.md`).

## 4. Multiple testing and data spent
- This loop: 8 configurations, all on dev.
- With the ~21 earlier studies in `data_spend_ledger.json`, the honest trial count on this tape is ~29 hypotheses.
- Under that count, a single "pass" would have needed far more than p < 0.005 to be convincing. None came close.
- **Spent by this loop:** ES dev 2011-02 → 2018-12 for the families short_term_reversal / liquidity_provision / shock_fade / shock_momentum, round_number_* / stop_cascade, and macro_release_reaction / post_announcement_*. Rows are in `data_spend_ledger.json`; the families are in `CLOSED_IDEAS.md`.
- **Not touched by this loop:** val1, val2 and the holdout. val1/val2 were already seen by earlier families (ORB, CHoCH, VWAP, opening-candle EMA on ES; ETF proxies 2022+).

## 5. Limitations
- **Same-chat evaluator.** The chat that wrote the evaluator also wrote the strategies. Protections:
  - The evaluator was frozen before the first candidate existed.
  - Every run is hash-verified.
  - Strategies run in a child process behind a static import/attribute allowlist.

  This is weaker than process or user isolation.
- **Prior exposure.** The dev data had been used by earlier ES families, and the model knew those results. All three candidates were chosen outside those families, but regime knowledge cannot be removed.
- **Calendar.**
  - ISM dates 2011–2021 come from a rule (first/third business day), not verified releases.
  - `news_day` is unknown for 2011.
  - The FOMC presser split used 12:30/14:30 calendar entries.
- **Data.**
  - No ES bars at all on 2014-06-12/13 (logged, not fixed).
  - The stress stop slip uses the NQ PMF in ES ticks, which overstates ES slip.
- **Twins** keep fixed brackets and the real trade's exit time. They do not copy the strategy's own exits beyond that. Here all exits were brackets or time stops, so this mattered little.
- **Sources** were checked only at abstract or secondary-summary level for several papers (noted in each prereg).

## 6. Holdout and paper trading
No candidate qualifies, so **no holdout should be bought or run**. If a future candidate passes dev and **both** val1 and val2 under this frozen evaluator:
1. Freeze it (prereg and strategy hashes in the ledger). Get Sunny's approval to buy ES `fut-ohlcv-1m-cont` from 2026-08-15 to the freeze date (well under $1–2 on Databento; `databento_fetch.py`).
2. Add the new files' hashes to a **new** manifest version, with the evaluator code unchanged. Run the frozen strategy on the holdout **once** and record it in the ledger whatever the result.
3. If it is positive: paper-trade 1 MES for at least 60 sessions, logging fills against the model's assumed fills (slippage, time-stop exits). Only then consider a prop-firm container (see the `lucid_structure` / `prop_structure` results).

## 7. Files
- `research_loop/PLAN.md` — plan copy.
- `eval/` — frozen evaluator + `MANIFEST.sha256`.
- `controller.py`.
- `prereg/*.json`, `strategies/*.py`.
- `ledger.jsonl` — every run, sanity check and decision.
- `data_spend_ledger.json`, `CLOSED_IDEAS.md`.
- `functions/ml/data/research_loop/`: `state.json`, `LOG.md` (one entry per firing), `runs/<id>/<split>_<k>.json` (per-trade detail), `inventory_es.json`.
