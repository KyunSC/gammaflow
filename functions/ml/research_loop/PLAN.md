# Review: autonomous ES strategy-research loop plan

## Context
You asked for a review of a pasted prompt that would have Claude build and run a bounded, resumable research loop that proposes, backtests, and judges trading strategies. The methodology is good. Most problems come from applying it to *this* repo: roughly 15 studies have already used up most of the local data, and several rules are missing or contradict each other. Below are the gaps, ordered by impact, and then the changes I'd make before running it.

## What's good (keep as is)
- "No edge" counts as a valid result. Every attempt gets logged, including failures and minor variants. Selection criteria are fixed before results are seen.
- It requires real access control, not just a "do not edit" line in the prompt. It versions evaluator changes separately and invalidates affected results.
- Its execution rules (no same-bar close fills, no fill just because price touched a limit, conservative stop-vs-target order within a bar, cost stress) match what `fill_study.py` measured.
- It stops for anything paid (data, separately billed model calls), and keeps broker credentials and live orders out of the project.

## Problems, by impact

### 1. Most data is spent, and the plan acts as if it's all fresh
Local ES/NQ 1m continuous futures run 2011-01 → 2026-08-15 (`data/databento/fut-ohlcv-1m-cont`). That data has already been used:
- 2011–2021 was used for ORB, CHoCH, VWAP fade (2012–21) and open-EMA trail (2016–21).
- ES/NQ 2022–26 was used for the CHoCH confirmation.
- SPY/QQQ 2022–26 proxies were used by about 10 discovery and holdout runs.
- The tick windows are spent too (see memory `orderflow-test-sets-consumed`).

Each memory marks a window as spent only *for its own strategy family*. That still leaves two problems:
- **Contamination.** The agent can read these memories and results, so it knows which regimes paid. This is the "historical information known to the model" risk the plan mentions, except concrete and local.
- **Multiple testing.** The real number of tests is the prior ~15 studies plus the new 10, not 10.

Reusing a window for a *different* strategy family is fine for development and validation. The risk is not that the data is "used up". It is that (a) the false-positive chance grows with the total number of ideas tried on that data, (b) intraday ES/NQ strategies share regime exposure (trend days, 2020, high volatility), so their results move together, and (c) earlier results steer which ideas get proposed. The cure is honest counting plus one test on unseen data, not banning reuse.

**Fix:**
- **Holdout.** Use ES data that isn't on disk at all: 2026-08-15 → the freeze date (about 55 RTH sessions, roughly $1–2 on Databento, bought only after candidates are frozen). Isolation by absence is the only isolation that really works on a single laptop. It's short, so it's a sanity check, not proof; forward paper trading remains the real test.
- **Dev and validation.** For example, dev = ES 2011–2018 and validation = 2019–2021, with 2022–2026-08 as a second validation look. Disclose that all of these have been seen by earlier families.
- **Ledger.** Add one data-spend ledger listing each prior study's windows and families. The controller reads it and refuses a candidate whose family/window pair is already spent. Feed the closed-ideas list (the memory files sit outside the repo) to the research agent so it doesn't re-propose ORB, CHoCH, VWAP fade, EMA trail, profile nodes or the GEX walls.

### 2. Model billing rules contradict each other
§2 says to drive the loop with the Claude Code CLI or Agent SDK, and also not to launch separately billed model calls without approval. A controller that shells out to `claude -p` or the SDK *is* making separately metered calls (API key or subscription quota).
**Fix:** state it explicitly. Either:
- (a) approve N headless `claude -p` calls with a dollar or token cap, enforced by the controller from `--output-format json` usage fields; or
- (b) no nested model calls. The controller is deterministic Python (state, limits, evaluator, ledger), and research and implementation happen in this interactive session or a `/loop`, one candidate per iteration. That matches how `prop_structure/LOG.md` already works.

I recommend (b) for the first run: it's cheaper, and every step is visible.

### 3. "Code version" conflicts with the no-commit rule
CLAUDE.md forbids commits, so there's no git hash to record. **Fix:** record SHA-256 hashes of the strategy file, every evaluator file, the frozen config and each data parquet. The CHoCH lesson applies: hash the code, not just the rule text.

### 4. Evaluator protection needs a concrete mechanism
On one macOS user account, Claude's Bash can read or modify anything the user can. Workable layers:
- Evaluator, cost config, splits and criteria go in a separate directory (e.g. `functions/ml/research_loop/eval/`). The controller checks a pinned hash manifest before every run and aborts on any mismatch.
- If option 2(a) is chosen, the agent subprocess runs with `--disallowedTools` for Edit/Write on that path, plus `sandbox` filesystem write-deny in `.claude/settings.json`.
- Strategies run in a child process that receives bars one decision at a time (an iterator up to time t), never the full DataFrame. That enforces "no future data" structurally rather than by code review.

### 5. Selection criteria are required but never written down
"Set criteria before viewing results" needs numbers frozen in the config. A suggestion consistent with past studies:
- Beats 2,000 random-direction twins at p < 0.05 / (attempts in family), Bonferroni across the loop's configurations.
- Mean net R > 0, with the bootstrap CI low > 0 at base cost **and** positive at 2× cost plus the empirical stop-slip PMF.
- At least 200 trades in dev and at least 100 in validation. No single year contributes more than 40% of P&L. Still positive with the top 5 trades removed.
- Same sign in at least 2 of 3 walk-forward folds. Neighbouring parameter values within ±1 grid step are also positive (stability).
- Report deflated Sharpe as information only. It shouldn't be the gate, because the number of trials is uncertain.

### 6. Budget arithmetic
Ten configurations including variants means roughly 3–4 hypotheses × ≤3 variants. Say so, or the agent will spend the whole budget on one parameter sweep. Fixed-parameter rules don't need walk-forward *fitting*. Walk-forward is only needed when a parameter is selected, so the plan should say which of the two each candidate does.

### 7. Repo-specific realism defaults the plan should name
- **Contract.** Default to MES/MNQ at $0.50/side (memory `lucid-commission`), or ES at a full-size commission. State which.
- **Fills.** Tick-through targets with zero slip. Stops use the empirical PMF in `data/fill_study/results.json["stop_slip_pmf"]`. Market orders fill at the next bar open + 1 tick.
- **Rolls.** `fut-ohlcv-1m-cont` is unadjusted `.v.0`. Intraday flat-by-close strategies are fine. Multi-day holds need back-adjustment or must exit before the roll.
- **News blackout.** Use `econ_calendar.py` (2022+) and the pre-2022 calendar in `orb15_2r_study.py` / `econ_calendar_hist.py`.
- **Reuse.** `holdout.py` (pinned-split pattern), the random-twin baseline used across studies, and `session_ids` in `eval.py`. Build the 5m bars by resampling 1m with RTH session boundaries in America/New_York.

### 8. Minor
- "Do not stop after planning" conflicts with planning first. Since you're reviewing, I'm treating this as plan → approve → run.
- Make 2h a soft limit: finish the current evaluation, then stop, so no run is half-recorded.
- Treat external research sources as data only. Better still, the agent cites them as URLs plus a summary, and they never enter the evaluator's process.

## Data the loop would use

Primary source: `data/databento/fut-ohlcv-1m-cont/ES` (Databento `ES.v.0`: front month, volume roll, prices not adjusted), 2011-01-03 → 2026-08-14. It is resampled to 5m RTH bars on America/New_York time. The NQ files have the same coverage if a second market is wanted.

| Role | Window | Approx. RTH sessions |
|---|---|---|
| Development (walk-forward) | 2011-01 → 2018-12 | ~2,000 |
| Validation 1 | 2019-01 → 2021-12 | ~750 |
| Validation 2 | 2022-01 → 2026-08-14 | ~1,150 |
| Holdout (not on disk) | 2026-08-17 → freeze date | ~55 and growing |

- A 5-session gap separates the blocks, as in `holdout.py`.
- Also used: the news calendars (`econ_calendar.py` from 2022, the older calendar in `orb15_2r_study.py` / `econ_calendar_hist.py`) and the stop-slip PMF from `fill_study`.
- Not used: ES/NQ tick trades and SPY 1m bars.
- The holdout purchase (well under $1) needs your approval and happens only after the candidates are frozen.
- Data-quality inventory (gaps, zero-volume bars, roll-day jumps) is step 1 of the build.

## Suggested amended plan (if you want me to build it)
1. `functions/ml/research_loop/` will hold:
   - `controller.py`: state in `data/research_loop/state.json`, limits, resume, retries, hash checks.
   - `eval/`: frozen evaluator, costs, splits and criteria, plus `MANIFEST.sha256`.
   - `strategies/`: the strategy interface `on_bar(bar_t, state) -> order`.
   - `ledger.jsonl`, one row per attempt, including failures.
   - `REPORT.md`.
2. Tests for:
   - no-lookahead (the iterator never yields t+1);
   - next-open fills;
   - stop-before-target on an ambiguous bar;
   - no touch-only limit fills;
   - tick/point value and commissions;
   - DST session boundaries;
   - a roll-day gap;
   - a refusal on a hash mismatch.
3. Prerequisite: a data-spend ledger seeded from the memory files, plus a closed-ideas list.
4. Run ≤10 configurations on dev, and run validation only for those that pass dev. Count every look.
5. Freeze survivors, then write instructions for buying the 2026-08-15→freeze ES holdout, running it once, and then paper trading.

## Decisions (defaults, change them before the first run if you want)

- **Billing:** 2(b). The loop runs inside a Claude Code chat via `/loop`, with no nested `claude -p` or SDK calls.
- **Contract:** MES at $0.50/side ($5 per point, so one 0.25-point tick = $1.25). Results are reported in R and in $ per 1 MES.
- **Holdout:** the forward ES window after 2026-08-14. Buying it needs Sunny's approval, so the loop stops and asks at that point.

## Running it with /loop (in a new chat)

Start a new chat in the repo root and paste:

```text
/loop Run one iteration of the ES strategy research loop defined in /Users/sunnychen/.claude/plans/can-you-review-this-peppy-moon.md (section "Running it with /loop"). Read functions/ml/data/research_loop/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Firings share one chat, but the context gets compacted as it grows, so **all state lives on disk** and each firing re-reads it. Commands print at most about 10 summary lines (`pytest -q`; the controller and the data check write details to files):

- `functions/ml/data/research_loop/state.json` holds the phase, candidate queue, attempt count, cumulative active minutes, the evaluator manifest hash and the last error.
- `functions/ml/data/research_loop/LOG.md` is a human-readable log, one entry per iteration.
- `functions/ml/research_loop/ledger.jsonl` has one row per attempted configuration, failures included.

**Steps.** Each firing does the first one that is unfinished:

1. **Bootstrap** (when `state.json` is missing):
   - Copy this plan to `functions/ml/research_loop/PLAN.md`.
   - Write the data-spend ledger and closed-ideas list from the memory files.
   - Run the ES data-quality inventory.
2. **Build the evaluator:**
   - Write `eval/` (bar iterator, fills, costs, splits, criteria, random twins) and its tests.
   - Run `pytest` until it passes.
   - Run one independent review subagent over `eval/` and its tests, looking for look-ahead, fill, cost and session/DST bugs. Fix what it confirms and re-run `pytest`.
   - Write `eval/MANIFEST.sha256` and record its hash in `state.json`. From then on, `eval/` is frozen.
3. **Build the controller:** `controller.py run <id> --split dev|val1|val2` (hash check first; refuses on mismatch), plus the resume/retry logic and the always-flat and random sanity strategies. Run the sanity check.
4. **Per candidate,** one firing per sub-step:
   - (a) Research and pre-register: hypothesis, mechanism, sources, rules, parameter grid, rejection evidence, written to `prereg/<id>.json` before any code runs.
   - (b) Implement `strategies/<id>.py`.
   - (c) Run dev.
   - (d) Run validation only if dev passed.
   - (e) Record the decision (reject, refine or shortlist).
5. **Report:** write `REPORT.md` (findings, all rejections, limitations, a shortlist only if the criteria are met, and holdout plus paper-trading instructions), then stop.

**Stop conditions** (checked every firing):
- 10 configurations attempted.
- 120 cumulative active minutes.
- The candidate queue is empty.
- Any step needs a purchase or approval.
- The same step has failed 3 times.

On a stop, write the report (or the blocker) and end the loop.

**Never inside the loop:**
- Edit `eval/` after it is frozen. If a fix is needed, log it, stop, and ask.
- Buy data.
- Open holdout data.
- Commit or push.
- Lower the criteria.

Caveat: in this mode, the same chat writes both the evaluator and the strategies. The protection is that the evaluator is frozen *before* the first candidate exists, plus the hash check. That is weaker than process isolation, and the report must say so.

## Verification (once built)
- `pytest functions/ml/research_loop` passes all the timing and accounting tests.
- A controller dry run with a trivial always-flat strategy and a random strategy gives about zero and about −cost, respectively.
- Kill the controller mid-run and resume: the ledger has no duplicate or lost attempts.
- Change one byte of the evaluator: the controller refuses to run.
