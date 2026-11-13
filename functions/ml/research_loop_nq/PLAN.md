# NQ strategy research loop (second run, after the ES loop of 2026-11-02)

## Context
The ES loop (`functions/ml/research_loop/`, report in `research_loop/REPORT.md`) found nothing.
- 3 ideas, 8 configurations, all FAILED on ES dev 2011-18, all worse than random direction.
- Main lesson: costs are 0.07–0.15R per MES trade, so an idea needs well over 0.1R gross.

This run repeats the method on NQ, for two reasons:
- **NQ is cheaper in R.** The tick is the same 0.25 pt, but NQ moves ~3–4× as many points, so a stop with the same volatility spans ~3–4× as many ticks. Slippage and $1 RT commission on MNQ cost roughly a third to half as much in R.
- **NQ has its own information.** ES is on disk for the same minutes, which allows cross-market ideas ES alone could not test.

NQ and ES are about 0.9 correlated intraday. Re-running the ES ideas on NQ is therefore a near-duplicate test, not new evidence. The ES results count against them.

Everything in the ES plan (`~/.claude/plans/can-you-review-this-peppy-moon.md`) applies unless changed below. That includes the review findings, the frozen-evaluator rules, the side-matched twins, the criteria, the stop conditions and the "never inside the loop" list.

## Decisions
- **Billing:** 2(b). The loop runs in a Claude Code chat via `/loop`, with no nested `claude -p` or SDK calls.
- **Contract:** MNQ at $0.50/side ($2 per point, so one 0.25-point tick = $0.50). Results are reported in R and in $ per 1 MNQ.
- **Market:** Databento `NQ.v.0` from `data/databento/fut-ohlcv-1m-cont/NQ` (2011-01 → 2026-08-14), resampled to 5m RTH bars in America/New_York. Fills use the 1m bars, as for ES.
- **Companion series:** each NQ bar dict also carries the **same-slot ES 5m bar** (`es`: o/h/l/c/v, or None when missing) and ES's `prev_close`. It is built from the same session builder, so it shows only completed bars, with no look-ahead. This is the one evaluator change from ES, and the review covers it.
- **Splits:** the same dates as ES: dev 2011-02 → 2018-12, val1 2019-01 → 2021-12, val2 2022-01 → 2026-08-14. 20 warmup sessions; 5-session gaps.
- **Holdout:** NQ after 2026-08-14, not on disk (roughly $1–2 on Databento). Buying it needs Sunny's approval, so the loop stops and asks at that point.
- **Criteria:** identical to ES, with dev twin p < 0.005 (0.05/10). They are never lowered.

## Layout (separate package; the ES freeze is untouched)
- `functions/ml/research_loop_nq/`: `eval/`, `tests/`, `controller.py`, `prereg/`, `strategies/`, `ledger.jsonl`, `REPORT.md`, `PLAN.md`.
- State lives in `functions/ml/data/research_loop_nq/`: `state.json`, `LOG.md`, `runs/`, `inventory_nq.json`.
- **Shared with ES (one list across markets):** `research_loop/data_spend_ledger.json` and `research_loop/CLOSED_IDEAS.md`.
  - The NQ controller reads them by path.
  - The NQ loop appends its own rows there, with market "NQ".
- Never write to `research_loop/eval/`, `research_loop/ledger.jsonl` or `data/research_loop/`.
- Run from `functions/ml` with `../../.venv/bin/python -B` (it has pytest, pyarrow and pandas).

## Rules for ideas (step 4a)
- Read `research_loop/CLOSED_IDEAS.md`, the spend ledger and `research_loop/REPORT.md` first.
- Closed families stay closed on NQ. That includes the ES loop's shock fade/momentum, round-number cross/fade and release fade/follow. A candidate near one of them must explain in its prereg what is mechanically different on NQ.
- At least one candidate must use the ES companion, for example NQ/ES relative strength or divergence, or a lead/lag between them. It must cite a mechanism and sources, not just "they are correlated".
- Thresholds must scale with price or recent volatility, never fixed points. NQ went from ~2,300 to ~23,000 over 2011–2026.
  - Keep the median stop at least ~40 ticks, so costs stay ≤ ~0.05R.
  - The prereg must state the expected cost in R for both 2011 and 2024 price levels.
- Budget: 10 configurations, i.e. about 3–4 hypotheses × ≤3 variants. Say in each prereg whether a parameter is fixed or selected.

## Running it with /loop

Paste in this chat or a new chat at the repo root:

```text
/loop Run one iteration of the NQ strategy research loop defined in /Users/sunnychen/.claude/plans/nq-research-loop.md (section "Running it with /loop"). Read functions/ml/data/research_loop_nq/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

All state lives on disk; each firing re-reads it. Commands print at most about 10 summary lines.

**Steps.** Each firing does the first one that is unfinished:

1. **Bootstrap** (when `state.json` is missing):
   - Copy this plan to `research_loop_nq/PLAN.md`.
   - Run `research_loop/data_inventory.py --product NQ`. Check coverage, duplicates, bad OHLC, half days, holiday sessions, and roll events inside RTH.
     - The script always writes `data/research_loop/inventory_nq.json`. Move that file to `data/research_loop_nq/`; it is the only allowed touch of the ES state folder.
   - Check that every ES session in each split has a matching NQ session, and the reverse. Log any mismatches.
2. **Build the evaluator:**
   - (a) Copy `research_loop/eval/` and `research_loop/tests/` into `research_loop_nq/`, then change only:
     - The contract block in `config.py`: PRODUCT, POINT_VALUE 2.0, comments, and OUT_DIR → `data/research_loop_nq`. The stress stop PMF is the measured NQ one, so it now applies natively.
     - The `es` companion field in `data.py` and `engine.py`.
     - Manifest coverage, so it tracks both the NQ and ES parquets.
     - Tests that hard-code $5/pt or $1.25 ticks; use `C.POINT_VALUE` / `C.TICK`.
     - New tests: the companion carries no look-ahead (the ES bar for slot k ends with NQ slot k); a missing ES bar gives None; session alignment.
     - Run `pytest` until it passes.
   - (b) Run one independent review subagent over the diff from `research_loop/eval/` and the new tests. Focus on the companion's look-ahead, session alignment, $/pt and tick-value arithmetic, and anything ES-specific left behind. Fix what it confirms and re-run `pytest`.
   - (c) Write `research_loop_nq/eval/MANIFEST.sha256`, `chmod a-w` the eval files, and pin the digest in `state.json`. From then on, `eval/` is frozen.
3. **Build the controller:**
   - Copy `research_loop/controller.py` and its tests. Point it at the NQ eval, the NQ ledger, and the shared spend ledger and closed-ideas files.
   - Run the sanity checks:
     - Always-flat gives 0 trades.
     - Random direction gives ≈ −cost. Expect a smaller cost in R than ES.
     - Kill and resume leaves no duplicate rows. Kill only the process group the test started; never use broad `pkill`.
     - A one-byte change is refused.
4. **Per candidate,** one firing per sub-step: (a) research and pre-register, (b) implement, (c) dev, (d) val1, then val2, only after a pass, (e) decision.
   - On a rejection, add the family to `CLOSED_IDEAS.md` and a row to `data_spend_ledger.json`.
5. **Report:**
   - Write `research_loop_nq/REPORT.md`: findings, every rejection, the honest trial count (ES tape plus NQ), limitations, a shortlist only if the criteria are met, and holdout plus paper-trading instructions.
   - Save one project memory and its MEMORY.md pointer.
   - Then stop.

**Stop conditions** (checked every firing):
- 10 configurations attempted.
- 120 cumulative active minutes.
- The candidate queue is empty.
- Any step needs a purchase or approval (including the holdout).
- The same step has failed 3 times.

On a stop, write the report (or the blocker) and end the loop.

**Never inside the loop:**
- Edit `research_loop_nq/eval/` after it is frozen, or edit anything in `research_loop/eval/`. If a fix is needed, log it, stop, and ask.
- Buy data.
- Open holdout data.
- Commit or push.
- Lower the criteria.
- Open `.env` files.

Caveat for the report: the same chat writes both the evaluator and the strategies, and it has already seen the ES results. The evaluator is frozen before the first candidate exists and is hash-checked on every run. That is weaker than true isolation.

## Verification (once built)
- `pytest functions/ml/research_loop_nq` passes, and the ES suite still passes unchanged (55 tests).
- The sanity checks above.
- The ES manifest still verifies at digest `a538db52…`, which proves the ES freeze was not touched.
