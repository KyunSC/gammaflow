# State-dependent sizing policy for prop accounts (no market data)

## Context
- Every prop EV so far uses one fixed risk per trade (the sawtooth rule: size wins to clear the target in N whole
  wins). See `functions/ml/data/prop_structure/LOG.md` and memory `lucid-structure-coinflip-2026-10-16`.
- A policy where risk depends on the account's state could add EV at zero edge. The state is distance to target,
  cushion above the floor, consistency headroom, payout-cycle progress, and evaluation vs funded stage. The
  funded stage is where the payout asymmetry lives.
- **No market data.** Outcomes come from the zero-edge trade model in `lucid_structure.py`: 1:1, tick-through
  target, measured stop-slip PMF, driftless-walk excursions. Nothing is spent.
- **Known trap:** at zero edge with a convex payoff, the optimum may be "maximise variance", which is martingale-like
  (size up near the floor or near the target).
  - Topstep's Responsible Trading Program names "going all-in" with no threshold.
  - Most firms can refuse payouts for gambling-like sizing.
  - So every result is reported twice: unconstrained, and with a risk cap of 0.5x the max loss per trade.
  - A policy that wins only unconstrained is reported as not executable.

## Decisions
- **Simulator:** write `prop_policy/sim.py`.
  - Same rules as `flybrain.prop.run_stage` (read it, don't import its loop), with risk chosen per day from the state.
  - It must reproduce `flybrain.prop.simulate_account` to the cent at constant risk on the
    `flybrain/fixtures/prop_parity.json` day table and plans. That is a test.
  - Plan dicts come from `lucid_structure.all_plans(firm)` (fixture-backed) and Apex's
    `data/prop_structure/apex/apex_study.py` SETUPS (provisional).
- **Trade outcomes per risk level:** precompute, per $ risk on a $25 grid from 0.2x to 1.0x the max loss, the outcome
  distribution of one day.
  - Use `lucid_structure.make_days` with that risk.
  - Record win net, loss net with slip, and the flat-by partials with intraday lo/hi.
  - Contracts are integers capped by `fundedStartMinis`/`maxMinis` x 10 micros (the `sweep` rule).
- **Policy classes, simplest first:**
  1. **Two-stage fixed:** one risk in the evaluation, another once funded.
  2. **Distance-to-target ladder:** risk = whatever clears the remaining target in k wins, k ∈ {1,2,3,4}, re-chosen
     daily, capped by the floor cushion.
  3. **Small grid policy:** risk on a coarse grid (cushion tercile × remaining-target tercile × stage), searched with
     CMA-ES or coordinate search.
  4. **Exact DP** where the state is small enough: an EOD-trailing evaluation with no consistency rule, state
     (balance - floor, target - profit) on a $25 grid. Value = P(pass) x V_funded - expected fees, with V_funded
     from a funded-stage DP or policy 3.
- **Scoring:**
  - Pick policies on seeds 0-7.
  - Re-score the winner on fresh seeds 100-115 x 25k paths (`multi_seed` style).
  - Report EV and its CI against the fixed-risk headline for the same plan.
  - Gain counts only if the CI excludes 0.
  - Also report pass rate, P(paid), days used, and the 95th-percentile risk the policy uses.
- **Real-tape check:** if `functions/ml/prop_realtape/realdays.py` exists and is frozen (its sha256 appears in
  `functions/ml/data/prop_realtape/state.json`), replay the winning policy on its random-direction day paths. That is
  a third score. If it doesn't exist yet, mark the check pending and do not wait.

## Plans (one per iteration, in this order)
1. Topstep Cons no-fee 50K noDLL
2. Topstep Cons no-fee 150K
3. LucidFlex 50K
4. LucidDirect 150K
5. Alpha Standard 50K
6. Alpha Direct 50K
7. MFF Builder 50K (at the 40% promo)
8. Apex 50K EOD (provisional)
9. Apex 50K Intraday (provisional)

## Layout
- Code: `functions/ml/prop_policy/`, holding `PLAN.md`, `outcomes.py`, `sim.py`, `policies.py`, `search.py`, `tests/`,
  `REPORT.md`.
- State and outputs: `functions/ml/data/prop_policy/`, holding `state.json`, `LOG.md`, `outcomes/*.npz` and
  `results/<plan>.json`.
- **Read-only:** `lucid_structure.py`, `flybrain/*`, `frontend/*`, `data/prop_structure/*`, `prop_realtape/*`. Other
  loops are running; never edit shared code.
- No writes to `research_loop/` shared files. This loop spends no data.
- Cap worker processes at 3.

## Running it with /loop
```text
/loop Run one iteration of the prop sizing-policy loop defined in /Users/sunnychen/.claude/plans/prop-policy-loop.md (section "Running it with /loop"). Read functions/ml/data/prop_policy/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy the plan.
   - Load each plan dict.
   - Read `flybrain/prop.py` `run_stage` and list every rule the simulator must match (EOD/intraday trailing,
     `evalDrawdown`/`evalLockOffset`, lock, DLL, consistency, buffer, caps, rebill, activation on pass).
2. **Simulator and tests:**
   - Build `sim.py`.
   - Parity to the cent against `prop_parity.json` at constant risk (all 60 cases).
   - Run a hand-checked 3-day variable-risk case.
   - Review with a subagent (Opus), then freeze (record the sha256).
3. **Outcome tables:** `outcomes.py`, one npz per (commission, tick value) pair, built in the background if slow.
4. **Per plan (one per firing):**
   - Policy classes 1 → 4 as feasible, scored as above, capped and uncapped.
   - Real-tape check if available.
   - Write `results/<plan>.json` and a LOG.md paragraph.
   - The paragraph states, in plain words, what the winning policy does (e.g., "risk $1,550 until the first payout,
     then $800").
5. **Synthesis:**
   - Table of fixed vs best-capped vs best-uncapped EV per plan.
   - Whether one simple rule generalises across firms.
   - Write REPORT.md and a memory file (`prop-policy-<date>.md`) plus its MEMORY.md line. Then stop.

**Stop conditions:**
- All plans are done.
- 180 active minutes.
- The same step fails 3 times.
- Anything needs approval.

**Never inside the loop:**
- Edit shared code.
- Touch market data.
- Commit or push.
- Open `.env` files.
- Recommend an uncapped martingale policy as executable.
