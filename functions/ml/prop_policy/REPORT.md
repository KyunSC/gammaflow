# State-dependent sizing for prop accounts: report (2026-11-04)

**Question.** At zero edge, can choosing each day's risk from the account's state beat the best fixed risk per account?
The state is the cushion above the floor, the distance to the target or payout, and the stage.

**Answer.** Only a little. Four of nine plans have an executable gain, all of +$4.5 to +$11 per account. Every large
gain needs sizing the plan forbids:
- risk at 1.0x the max loss;
- the firm's daily loss limit used as the stop;
- or an all-in opening bet once funded.

No market data was read. Outcomes come from the zero-edge 1:1 bracket model in `lucid_structure.py`.

## Method

- **Simulator.** `sim.py` is a frozen port of `flybrain.prop.run_stage` with the risk chosen per day.
  - It matches all 60 `prop_parity.json` cases to the cent at constant risk.
  - It equals flybrain on random level sequences across all 9 plans.
  - It passed an Opus review.
  - Unresolved evaluations count as failures.
- **Outcome tables.** `outcomes.py` stores, per seed, the three risk-independent draws of `make_days`, and rebuilds any
  level's day table bit for bit. All levels share common random numbers.
- **Policies** (`policies.py`). All are scored twice: capped (risk <= 0.5x the max loss) and uncapped.
  - Class 1: fixed risk, one level or one per stage.
  - Class 2: a ladder, sized to clear what is still needed in k wins and capped by the cushion. "What is still needed"
    includes the consistency rules.
  - Class 3: an 18-cell grid of cushion tercile x need tercile x stage, found by coordinate search.
  - Class 4: exact DP. It was not run; see Gaps.
- **Selection** (`search.py`) runs on seeds 0-7 x 3k paths. It uses the stage decomposition
  EV = P(pass) x V_funded - cost, because the funded stage restarts at the start balance.
- **Score.** Seeds 100-115 x 25k paths, paired with the fixed-risk headline on the same draws. The 95% CI is
  ±2.13 x the standard error over the 16 seeds. A gain counts only if its CI excludes 0.
- **Validation.** Every re-scored headline is identical to the stored `multi_seed` headline.

## Results (EV per account)

| Plan | Fixed headline | Capped winner | Capped − headline | Uncapped winner | Uncapped − headline | Executable gain |
|---|---|---|---|---|---|---|
| Topstep Cons no-fee 50K noDLL | +$153.1 ($1,550, 0.78x) | +$105.0 | −$48.1 [−52.7, −43.5] | +$156.1 | +$3.0 [+0.2, +5.8] | no |
| Topstep Cons no-fee 150K | +$219.2 ($3,040, 0.68x) | +$138.7 | −$80.4 [−87.8, −73.1] | +$233.3 | +$14.1 [+3.0, +25.3] (all-in $4,500 cells) | no |
| LucidFlex 50K | +$89.2 ($1,050, 0.53x) | +$88.2 | −$1.0 [−2.7, +0.6] | +$156.0 | +$66.9 [+63.9, +69.8] (DLL as stop, checked) | no |
| LucidDirect 150K | +$152.8 ($1,622, 0.32x) | +$164.1 | **+$11.2 [+9.9, +12.6]** | +$160.9 | +$8.1 [+6.0, +10.1] | **yes** |
| Alpha Standard 50K | +$74.5 ($1,550, 0.78x) | +$66.2 | −$8.4 [−14.3, −2.4] | +$105.9 | +$31.3 [+27.5, +35.2] | no |
| Alpha Direct 50K | +$76.7 ($450, 0.23x) | +$86.0 | **+$9.3 [+7.2, +11.5]** | +$82.6 | +$6.0 [+4.5, +7.4] | **yes** |
| MFF Builder 50K, $91.80 promo | +$68.0 ($1,050, 0.53x) | +$58.7 | −$9.3 [−11.2, −7.4] | +$99.2 | +$31.1 [+29.1, +33.1] | no |
| Apex 50K EOD (provisional) | +$95.8 ($1,050, 0.53x) | +$103.8 | **+$8.0 [+4.8, +11.2]** | +$164.1 | +$68.4 [+64.7, +72.1] | **yes (provisional)** |
| Apex 50K Intraday (provisional) | +$80.1 ($1,550, 0.78x) | +$84.5 | **+$4.5 [+2.2, +6.8]** | +$184.8 | +$104.7 [+101.4, +108.0] (all-in opening bet) | **yes (provisional)** |

Per-plan detail, plain-words policies and mechanism checks are in `data/prop_policy/results/<plan>.json` and `LOG.md`.

## What generalises

1. **Inside the 0.5x cap, state-dependent sizing adds +$4.5 to +$18 over the best capped fixed risk on every plan.**
   - It is a real but small effect.
   - It matters only where the plan's best fixed risk is already near or under the cap. That is the Direct plans and the
     Apex plans (whose headline is $1,050-1,550 but whose capped winner can still pass and pay).
2. **One simple rule shows up in all four executable winners. Size down when the cushion is fat and the next payout is
   close; size at or slightly above the base when the payout is still far.**
   - LucidDirect: $1,600, cut to $1,377-1,525 at a high cushion with the payout near. Trimming alone is +$7.9 [6.8, 9.1]; the low-cushion bump is noise.
   - Alpha Direct: $450, $400 near and $500 far at a high cushion.
   - Apex EOD: funded $676, $476 near and $1,001 far.
   - Apex Intraday: funded $650, $500-600 near and $975 far.
   - Likely reason (unverified): these plans pay only under a consistency or minimum-day rule, so a big win close to the
     payout hurts more than it helps.
3. **The 0.5x cap is expensive where the headline lives above it.** The capped policy ends up −$48 (Topstep 50K),
   −$80 (Topstep 150K), −$8 (Alpha Standard) and −$9 (MFF) against the headline. Six of the nine fixed-risk headlines
   themselves size above 0.5x the max loss.
4. **Every large uncapped gain is the trap the plan warned about.**
   - **The DLL as the stop.**
     - Sizing above a soft daily loss limit freezes every losing day at the limit, which turns a 1:1 bracket into
       roughly a 1:1.67 one.
     - Checked on Flex: the DLL is hit on 25% of days.
     - Likely on MFF and Apex EOD (not checked).
     - The Alpha Standard headline already does this: the DLL is hit on 51% of funded days.
   - **All-in sizing.**
     - Topstep 150K funded cells risk $4,500, the whole max loss.
     - Apex Intraday risks $1,976 on day one of every funded account, against a $2,000 max loss.
   - None of these is executable.

## Gaps and caveats

- **DP (class 4) was not run.** It applies to the MFF and Apex EOD evaluations (EOD, no consistency). There was no time
  inside the 180-minute budget. Every other plan has a consistency rule or an intraday trail.
- **Thinner checks on plans 7-9.** They were written up without mechanism checks or ablations. Only LucidDirect had an
  ablation, and it was post hoc on the scoring seeds.
- **Apex rules are provisional.** The PA rules come from an unverified table, so the two Apex gains are provisional too.
- **Real-tape check: pending.** `prop_realtape/realdays.py` does not exist.
- **Model limits, as in all the headlines:** 1:1 brackets, one trade a day, no flat-by time, news or timeouts.
  - DLL fills have no slippage, which is slightly optimistic for the DLL-as-stop results.
- **Follow-up, not run.** The DLL-as-stop effect suggests an R:R study: a real stop at or under 0.5x the max loss with a
  target above it. That is a bracket-shape question, not a sizing one.
