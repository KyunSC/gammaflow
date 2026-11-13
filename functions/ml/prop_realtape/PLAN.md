# Prop structure on the real tape (random direction, ES/NQ 2011-2026)

## Context
- Every prop EV so far (`functions/ml/data/prop_structure/LOG.md`, e.g. Topstep Cons no-fee 50K noDLL +$153) comes from
  `functions/ml/lucid_structure.py`: synthetic iid days, a driftless-walk excursion, the measured stop-slip PMF.
- Real days have volatility clustering, gaps, fat tails and runs of losses. They can move those numbers either way.
- This loop replays the real 1m ES/NQ tape with a **coin-flip direction** and answers:
  1. Does each firm's headline EV survive?
  2. What entry time works best?
  3. Should the stop be fixed in ticks or scaled to volatility?
  4. How much does an always-long line add? Context only.
- **Strategy-free.** Direction is random, so no entry edge is tested and no validation window is spent. Log one
  `strategy_free` row to the spend ledger (see Layout).
- The always-long line peeks at index drift, which is a well-known premium, not a discovery. It is reported only and
  is never a PASS/FAIL. Flybrain already closed "constant-direction session-open" as an entry edge.

## Decisions
- **Data:** `functions/ml/data/databento/fut-ohlcv-1m-cont` ES and NQ, 2011-01-03 → 2026-08-14, plus NQ 2026-08-15 →
  2026-11-03 if on disk.
  - Use the unadjusted `.v.0` bars **within a day**, so a day's path is one contract.
  - Drop roll days where the front contract changes intraday.
  - Reuse an existing loader. `vwap_ema_3m_study.py` and `research_loop_nq/eval` both read this source; copy their
    session handling, don't invent new handling.
- **Contracts:** MNQ (tick $0.50) and MES (tick $1.25). Commission per the firm (`commissionPerSide` in the plan dict).
  Stop slippage comes from `lucid_structure.stop_pmf()`. Targets fill on a tick-through. If one 1m bar touches both
  the stop and the target, the stop fills first.
- **One trade per day.**
  - Enter at the entry-time bar open with a 1:1 bracket.
  - Contracts and stop ticks come from each plan's headline risk; `lucid_structure.sweep` has the rule
    (`n = round(risk/150)` capped, `st = risk/(n*TICK_USD)`).
  - Exit at the target, the stop, or the firm's flat-by time (`flatByEt`, default 16:10 ET).
  - The day's bars (lo/hi/open/close of equity relative to the day open) form the day table. Its format is
    `flybrain.prop.build_day_table`, so `flybrain.prop.simulate_account` replays it unchanged.
- **Direction:**
  - Store BOTH sides' day paths per day (long and short), so any direction rule is a lookup.
  - Random direction is a seeded coin per day, with 64 independent coin sequences.
  - Always-long is the long column.
- **Replay:**
  - (a) Moving-block bootstrap of real days, block 20 trading days, which keeps the volatility clustering.
  - (b) Every historical start date replayed in order.
  - Compare both against the synthetic model at the same plan and risk (`lucid_structure.multi_seed` numbers from
    each firm's `headline.json`).
  - Report EV with a CI across coin sequences.
- **Eras:** report 2011-18, 2019-21 and 2022-26 separately, as well as pooled. A structural choice (entry time,
  stop scheme) counts as robust only if it ranks the same in all three eras.

## Plans (one per iteration, in this order)
Take plan and risk from `functions/ml/data/prop_structure/<firm>/headline.json` (Lucid: `lucid_headline.json`):

1. Topstep Cons no-fee 50K noDLL
2. Topstep Cons no-fee 150K
3. LucidFlex 50K
4. LucidDirect 150K
5. Alpha Standard 50K
6. Alpha Direct 50K
7. MFF Builder 50K (list price and 40% promo)
8. Apex 50K EOD Standard (`data/prop_structure/apex/apex_study.py` SETUPS)
9. Apex 50K Intraday Standard

Apex rules are provisional: label them so.

## Layout
- Code: `functions/ml/prop_realtape/`, holding `PLAN.md`, `realdays.py` (builds day paths), `replay.py`, `tests/`,
  `REPORT.md`.
  - `realdays.py` must expose `load_day_paths(product, entry_et, stop_scheme) -> dict` so the policy loop
    (`~/.claude/plans/prop-policy-loop.md`) can import it read-only.
- State and outputs: `functions/ml/data/prop_realtape/`, holding `state.json`, `LOG.md`,
  `paths/<product>_<entry>_<scheme>.parquet` and `results/<plan>.json`.
- **Read-only for this loop:** `lucid_structure.py`, `flybrain/prop.py`, `flybrain/fixtures/*`,
  `frontend/lib/backtest/prop/*`, `data/prop_structure/*`. Other loops are running; never edit shared code. If the
  engine needs a change, write it up in LOG.md and stop.
- **Parallel-safe shared write:** only once, at the report step. Append one `strategy_free` row to
  `functions/ml/research_loop/data_spend_ledger.json`:
  - Take an exclusive `fcntl.flock` on `functions/ml/research_loop/.shared.lock`.
  - Re-read the file, append, then write atomically (temp file + `os.replace`).
- Cap worker processes at 3.

## Running it with /loop
```text
/loop Run one iteration of the real-tape prop loop defined in /Users/sunnychen/.claude/plans/prop-realtape-loop.md (section "Running it with /loop"). Read functions/ml/data/prop_realtape/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy the plan to `prop_realtape/PLAN.md`.
   - Inventory the ES/NQ files and session counts per era, and the roll days dropped.
   - Confirm each `headline.json` loads.
2. **Day paths:** build `realdays.py`.
   - Grid: products ES, NQ × entry 09:35 / 10:00 / 11:00 / 13:00 ET × stop scheme:
     - `fixed`: the plan's ticks.
     - `atr`: the stop = the plan's $ risk spread over ticks scaled to the 20-day ATR of daily ranges, as of the prior
       close, at the same $ risk, with contracts re-rounded.
     - `vix`: the same, scaled to the prior-close VIX (Cboe free CSV, used for ES and NQ alike; hash it).
   - Write the parquet files, in a background run if slow.
3. **Tests**, in `prop_realtape/tests/`:
   - A toy 3-day tape reproduces hand-computed fills: the same-bar stop-first rule, tick-through, slip, flat-by.
   - Feeding `lucid_structure.make_days` synthetic days through `replay.py` reproduces `lucid_structure.score` EV
     to the cent.
   - No look-ahead in the ATR/VIX scaling: it uses prior-close values only.
   - Review with a subagent (Opus), then freeze `realdays.py` (record its sha256 in state.json).
4. **Per plan (one per firing):**
   - Real-tape random-direction EV (block bootstrap and historical replay) vs synthetic, at the `fixed` scheme and
     09:35 entry.
   - Then the entry × scheme grid for that plan, by era.
   - Always-long line.
   - Pass rate, P(paid), days per account, EV per day.
   - Write `results/<plan>.json` and one LOG.md paragraph.
5. **Synthesis:**
   - One table: real vs synthetic EV per plan.
   - Which entry time and scheme is robust across eras, if any.
   - How much drift (always-long) adds, as context.
   - Whether the firm ranking changes.
   - Write REPORT.md, the ledger row and a memory file (`prop-realtape-<date>.md`) plus its MEMORY.md line. Then stop.

**Stop conditions:**
- All plans are done and the synthesis is written.
- 150 active minutes.
- The same step fails 3 times.
- Anything needs a purchase or the user's approval.

**Never inside the loop:**
- Edit shared code or frozen evaluators.
- Buy data.
- Commit or push.
- Open `.env` files.
- Present the always-long line as an edge.
