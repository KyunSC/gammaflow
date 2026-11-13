# Prop structure on the real tape: coin-flip direction, ES/NQ 2011-2026

Loop: `prop_realtape/PLAN.md`. Log: `data/prop_realtape/LOG.md`. Per-plan results: `data/prop_realtape/results/*.json`.
Cross-plan tables: `data/prop_realtape/synthesis.json` (`prop_realtape/synthesize.py`). Date: 2026-11-04.

**Strategy-free.** Direction is a seeded coin per calendar date (64 sequences), so no entry edge is tested and no
validation window is spent. The always-long line is context only and is never a PASS or FAIL.

## Follow-ups, 2026-11-04 (after the loop): read this first
**Prices.** Prices now live only in `frontend/lib/backtest/prop/firms.js`: list price, a per-firm promo, and Apex.
- Python reads them through `prop_prices.py`.
- Every stored result in `data/prop_structure` and `data/prop_realtape` (results, hist_fix) is repriced at list
  price, with the promo EV alongside (`promo`) and the old value kept under `at_run`.
- After a price change: re-export the fixture (`export_fixtures.mjs`), then run `prop_prices.py reprice --write`.
- **Sections 1–5 below are at run-time prices** (Lucid Flex 50K at $90.20, the old firms.js Lucid prices).

**Lucid list prices** come from Lucid's pricing page (user screenshots). Flex 50K is $115 (coupon $80.50); Direct 150K
is $836 (coupon $585.20). The $90.20 Flex 50K fee paid was already about 22% off list.

**Current numbers.** NQ 09:35 fixed bracket, $ EV per account, list / promo. Promos: Lucid 30% coupon, MFF 40%;
Apex is already at its 90% coupon.

| plan | fee (list) | synthetic | real 2022-26 (boot) | real pooled (boot, 20d blocks) | real pooled (fixed hist) |
|---|---:|---:|---:|---:|---:|
| Topstep Cons no-fee 150K | $199/mo | +219 | +211 | +102 | **+27** |
| Topstep Cons no-fee 50K noDLL | $95/mo | +153 | +148 | +80 | **+53** |
| LucidFlex 50K | $115 | +64 / +99 | +60 / +94 | +38 / +72 | **+19 / +54** |
| LucidDirect 150K | $836 | +153 / +404 | +157 / +407 | −48 / +202 | **−148 / +103** |
| Alpha Standard 50K | $129/mo | +75 | +123 | +38 | **+7** |
| Alpha Direct 50K | $519 | +77 | +96 | −21 | **−107** |
| MFF Builder 50K | $153 | +7 / +68 | +9 / +70 | −23 / +39 | **−48 / +13** |
| Apex 50K EOD (coupon $59) | +$129 on pass | +96 | +103 | +40 | **+30** |
| Apex 50K Intraday (coupon $24.90), as run | +$99 on pass | +80 | +53 | +33 | **+27** |
| ↳ Apex Intraday, verified rules | | +86 | +88 | +54 | |

**What the four follow-ups changed:**
1. **The historical replay was not a lower bound** (`data/prop_realtape/hist_fix/FINDINGS.md`).
   - End-of-era truncation was small (0–6% of accounts).
   - The gap to the bootstrap comes from its 20-day blocks, which splice volatility regimes into one account and
     rescue slow accounts. With 250-day blocks the bootstrap reproduces the fixed replay.
   - **So the fixed-hist column is the realistic pooled view.** On it:
     - Topstep 150K's CI includes 0, and Alpha Standard is about +7.
     - The funded-only plans are clearly negative at list price.
     - LucidFlex (+19 list / +54 coupon) and Topstep 50K (+53) lead.
2. **Apex rules verified on Apex's own pages** (`data/prop_realtape/apex_verified/FINDINGS.md`).
   - Prices are confirmed. The coupon excludes activation fees.
   - Intraday had a funded-account DLL and payout terms wrong. Corrected, it is +54 pooled / +88 2022-26, which closes
     most of the "intraday trail is optimistic" gap for Apex.
   - EOD matches at funded scaling levels L1–L2; its true EV is slightly lower once the L3+ DLL rises.
   - Conduct risk: Apex bans stockpiling discounted evaluations to cycle through. No EV here includes that.
3. **A synthetic give-back law, proposal only** (`prop_realtape/proposals/PROPOSAL.md`).
   - It is a parameter-free random-walk law. It puts 8 of 10 intraday-trail plans with a real-tape run inside their
     2022-26 CI (the old law: 2). MFF Rapid was the worst miss and now matches.
   - EOD plans are unchanged to the cent.
   - It does not fix the DLL-inside-stop effect (real winners dip less than a random walk).
   - Not applied to `lucid_structure.py`.
4. **Regime-aware bracket** (`data/prop_realtape/regime_bracket/FINDINGS.md`).
   - **Preregistered verdict: NO.** A vol-scaled stop fitted leave-one-era-out does not beat the fixed headline pooled
     in any plan.
   - 2011-18 alone clearly wants a narrower stop (0.33–0.65×).
   - In a post-prereg check with long blocks, the vol rule never loses and wins in 11 of 36 cells, mostly on ES. That
     is exploratory only.

## Setup
- **Tape:** Databento `.v.0` 1m bars, ES and NQ, 2011-01-03 → 2026-08-14 (NQ to 2026-11-03).
  - Sessions with a contract roll, thin sessions and CME holiday early halts are dropped (copied from
    `vwap_ema_3m_study`).
  - About 1,960 / 744 / 1,140 days per era (2011-18 / 2019-21 / 2022-26).
- **Trade:** one per day at the entry bar's open, 1:1 bracket on MNQ or MES.
  - Contracts and $ risk come from each plan's headline. The MES stop is the same $ risk at $1.25 a tick.
  - Stop first when a bar touches both levels; the target needs a tick through.
  - A gap through the stop fills at the bar's open plus the measured stop-slip distribution.
  - Flat at the plan's flat-by time (Apex 16:59).
- **Accounts:** replayed through the unchanged `flybrain.prop.simulate_account`.
  - Moving-block bootstrap (blocks of 20 days, horizon 250), plus a historical replay.
  - EV is computed exactly as `lucid_structure.score` does; Apex uses `apex_study`'s rule.
- **Verification:**
  - 40 tests, and parity checks to the cent against the synthetic engine.
  - An Opus review found 8 issues; 7 were fixed before `realdays.py` was frozen
    (`state.json` `frozen.realdays_sha256`).
  - Rules for step 4 were fixed in `state.json` `step4_rules` before any plan result was seen.

## 1. Real vs synthetic EV per plan ($ per account, NQ 09:35 fixed bracket, bootstrap, 64 coins, 95% CI)

| plan | synthetic | real 2022-26 | real pooled 2011-26 | real 2011-18 | ES 2022-26 | ES pooled | always-long NQ pooled |
|---|---:|---:|---:|---:|---:|---:|---:|
| Topstep Cons no-fee 150K | +219 | **+211** [152, 270] | **+102** [70, 134] | −70 | +128 | +1 | −17 |
| Topstep Cons no-fee 50K noDLL | +153 | **+148** [119, 178] | **+80** [66, 95] | +10 | +100 | +37 | +27 |
| LucidDirect 150K | +153 | **+157** [63, 250] | **−48** [−97, 0] | −292 | +77 | −170 | +82 |
| Apex 50K EOD, coupon *(provisional)* | +96 | **+103** [78, 127] | **+40** [29, 51] | −12 | +65 | +6 | +16 |
| LucidFlex 50K | +89 | **+85** [64, 105] | **+63** [51, 75] | +34 | +61 | +33 | +33 |
| Apex 50K Intraday, coupon *(provisional)* | +80 | **+53** [40, 66] | **+33** [26, 40] | +23 | +36 | +20 | +24 |
| Alpha Direct 50K | +77 | **+96** [32, 160] | **−21** [−56, 14] | −235 | +10 | −133 | −11 |
| Alpha Standard 50K | +75 | **+123** [93, 152] | **+38** [24, 53] | −39 | +46 | −7 | +23 |
| MFF Builder 50K, 40% promo | +68 | **+70** [52, 89] | **+39** [27, 50] | −8 | +37 | +3 | +25 |
| MFF Builder 50K, list | +7 | **+9** [−9, 28] | **−23** [−34, −11] | −69 | −24 | −58 | −36 |

The two Apex regular-price rows are the coupon rows minus a constant (−$531 EOD, −$224 intraday), so they are
negative in every era.

### Does each headline survive?
- **In 2022-26, the vol regime the headlines were sized for, yes for 8 of 9 plans.** The real-tape EV contains or
  beats the synthetic, with near-identical pass / paid / days. Two plans deviate, each for a specific reason:
  - **Alpha Standard 50K beats the synthetic (+123 vs +75).** Its DLL ($1,000) is tighter than its stop ($1,550), so
    a winning trade is lost to the DLL if it first dips about 200 ticks. Real NQ winners dip that far less often than
    the synthetic's driftless walk assumes (18.1% vs 21.6% in 2022-26; 6–14% in older eras).
  - **Apex Intraday falls short (+53 vs +80).** With an intraday trail, a winner that rallies and then gives back
    $2,000 inside the trade breaches the account, even though the trade wins. The synthetic draws every winner as
    dip-then-run, so it never gives anything back. Real NQ winners do: 7.1% fall back ≥ $2,000 and 26% ≥ $1,500 in
    2022-26.
  - Ruled out: the 1m bar-order convention (a low-first bound gives the same EV).
  - Synthetic numbers for intraday-trail plans are optimistic. EOD-drawdown plans are unaffected.
- **Pooled over 2011-26, no: every plan is lower.** Two funded-only plans are not positive (LucidDirect −48, Alpha
  Direct −21), and MFF at list price is negative. The cause is the bracket, not the tape:
  - A headline stop of about 300 MNQ ticks (75 NQ points) resolves on only about 9% of 2011-18 days, so about 90% of
    trades exit at flat-by.
  - Accounts then run 13–106 days. What that costs depends on the fee model:

  | fee model | 2011-18 | example |
  |---|---|---|
  | one-off fee, eval plan | stays positive | LucidFlex +34 |
  | monthly rebill | goes negative (fees +30%) | Topstep 150K −70, Alpha Std −39 |
  | funded-only, large up-front fee | strongly negative (account creeps 73–106 days, P(paid) 15%) | LucidDirect −292, Alpha Direct −235 |
  | Apex 21-day eval limit | about flat (45% of evaluations go late and fail, but that also saves most activations) | Apex EOD −12 |

- **ES at the same $ risk is weaker everywhere.** In 2022-26 it is typically 50–70% of NQ's EV, and as low as 10%
  (Alpha Direct) and 37% (Alpha Standard). The headlines are MNQ-calibrated, and on MES the same $ is a wider stop
  relative to ES volatility.
- **The historical replay sits below the bootstrap** (end-of-era truncation of long-lived funded accounts). Treat it
  as a lower bound for plans with more than about 20 days per account.

## 2. Entry time: what is robust across eras?
Robust means the same ranking in 2011-18, 2019-21 and 2022-26 (16 coins × 1,000 paths per grid cell; cell CIs are
±15–300).

| | 2011-18 | 2019-21 | 2022-26 |
|---|---|---|---|
| NQ best entry (count of plans out of 9) | 09:35 (9) | 09:35 / 10:00 (4 / 4) | 11:00 (6) |
| NQ 13:00 vs 09:35, mean $ | −110 | −23 | −22 |
| ES best entry | 09:35 (6) | 11:00 (6) | 11:00 (9) |
| ES 13:00 vs 09:35, mean $ | −99 | −49 | −16 |

- **No best entry is robust.** The best entry moves with volatility. In 2011-18 only the earliest entry gives a ~75 pt
  bracket enough of the day to resolve; in 2022-26 any entry resolves, and 11:00 edges ahead.
- **Robust only in the negative sense: avoid 13:00.** It is never the best entry on ES, and best only once on NQ (out
  of 27 plan-eras). Its mean shortfall against 09:35 is negative in every era on both products, because it leaves the
  fewest resolving bars before the flat-by.

## 3. Fixed vs vol-scaled stop: what is robust?
Mean EV difference against `fixed`, averaged over entries and plans:

| | 2011-18 | 2019-21 | 2022-26 | plans with this rule first (2011-18 / 2019-21 / 2022-26) |
|---|---:|---:|---:|---|
| NQ rel_vix | −27 | +8 | +19 | 0 / 2 / 7 |
| NQ abs_vix | −9 | −7 | +7 | 3 / 0 / 1 |
| NQ fixed | 0 | 0 | 0 | 6 / 3 / 0 |
| ES abs_vix | +48* | +7 | −3 | 8 / 6 / 2 |
| ES abs_atr | +39* | −9 | +1 | 1 / 0 / 3 |

- **No stop scheme is robust.** On NQ the fixed stop wins 2011-18 and rel_vix (stop × VIX / its 250-day median) wins
  2022-26; the sign flips between eras.
- **The ES abs_vix lead is mostly a 2011-18 effect.**
  - *Where the plan's contract cap binds (Topstep, Alpha Standard, Apex: 73–99% of 2011-18 ES days), part of the
    lead is just smaller risk.
  - Where the cap does not bind (ES for LucidFlex, MFF, LucidDirect and Alpha Direct; NQ for LucidDirect and Alpha
    Direct), abs_vix still beats fixed in 2011-18 by +7 to +113 per account, at full $ risk. That is the "bracket
    too wide for low vol" problem: an absolute vol-scaled stop resolves more trades.
  - The help is largest for the funded-only plans, but it does not rescue them: LucidDirect NQ 2011-18 goes from
    about −292 to about −261.
  - By 2022-26 the difference has mixed sign (−15 to +21), as it should, since k was set to match the plan's ticks
    in that era.
  - Conclusion: vol-scaling helps when vol is far below the regime the bracket was sized for and the cap leaves room
    to size up. It is not an all-era improvement.
- The absolute stop constants (k = plan ticks ÷ 2022-26 median vol) were declared per plan and are in each result file.

## 4. Drift (always-long, context only)
Always-long against the coin-flip average, pooled NQ, is between −119 and +130 across plans (mean about −14). That
is one sequence against a coin spread with sd $28–193. Drift adds nothing detectable at these brackets. Flybrain
already closed constant-direction session opens as an entry edge, and nothing here reopens it.

## 5. Does the firm ranking change?

| rank | synthetic | real NQ 2022-26 | real NQ pooled 2011-26 |
|---:|---|---|---|
| 1 | Topstep 150K +219 | Topstep 150K +211 | Topstep 150K +102 |
| 2 | Topstep 50K +153 | LucidDirect 150K +157 | Topstep 50K +80 |
| 3 | LucidDirect 150K +153 | Topstep 50K +148 | **LucidFlex 50K +63** |
| 4 | Apex EOD +96 | **Alpha Standard +123** | Apex EOD +40 |
| 5 | LucidFlex +89 | Apex EOD +103 | MFF promo +39 |
| 6 | Apex Intraday +80 | Alpha Direct +96 | Alpha Standard +38 |
| 7 | Alpha Direct +77 | LucidFlex +85 | Apex Intraday +33 |
| 8 | Alpha Standard +75 | MFF promo +70 | Alpha Direct −21 |
| 9 | MFF promo +68 | **Apex Intraday +53** | MFF list −23 |
| 10 | MFF list +7 | MFF list +9 | **LucidDirect −48** |

- **Topstep stays on top in every view.**
- **The funded-only plans (LucidDirect, Alpha Direct) are regime bets.** They rank high on 2022-26 vol and last
  pooled.
- **LucidFlex is the only plan positive in every era** (+34 / +78 / +85), which makes it the most robust per-account
  structure even though its 2022-26 EV is mid-table.
- **Alpha Standard moves up on real tape** (the DLL-inside-stop effect); **Apex Intraday moves down** (whipsaw breaches).

## Bottom line
- The synthetic iid model is a good guide **for the current vol regime and for EOD-drawdown plans.** In 2022-26, 7
  of 9 plans match it within the CI.
- It misses two path-shape effects:
  - A DLL tighter than the stop makes it **pessimistic**.
  - An intraday trail makes it **optimistic**, because real winners give back gains.
- Its EVs are **conditional on a vol regime where a ~75-point NQ bracket resolves intraday.** In a 2011-18-like regime
  the same bracket mostly times out at flat-by. Then fee structure decides: one-off fees survive, monthly rebills and
  large funded-only fees do not.
- If the headline structures are traded, size the stop to current volatility. The tested vol-scaling rules do not
  rank consistently, but a bracket that never resolves is the main way these EVs disappear.
