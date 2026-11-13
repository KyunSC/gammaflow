# Delta-hedged 0DTE straddle: confirmation loop (options account, not a prop firm)

## Context
- The only options thread still open (memory `iron-condor-study-2026-11-01`) is `delta_hedge.py`: short the ATM straddle at 09:35 ET and delta-hedge it with shares every 5 minutes until 16:00.
- On 2022-01 → 2026-09-25 same-day expiries (`data/delta_hedge/*_dte0.parquet`, variant `5m`, 1,097 days each) it earned, per straddle and **before option commissions**:

  | Symbol | Mean P&L | SE | 2022 → 2025-03 only (the memory's figures) |
  |---|---|---|---|
  | QQQ | +$18.87 | 2.66 | +$19.89 (SE 2.55) |
  | SPY | +$13.30 | 2.35 | +$14.46 (SE 2.30) |

- That is the variance risk premium: implied above realized, harvested at ATM, with hedging removing most of the noise. It is a well-documented effect with a known tail.
- **Every date it was measured on is 2022+.** The repo holds unspent same-day-expiry data before that: QQQ from 2016-01 and SPY from 2017-01, through 2021, on the Mon/Wed/Fri weekly expiries. That window includes the stress days a short-vol trade must survive: 2018-02-05 (Volmageddon), 2018-10/12, 2020-03 and 2021-01.
- This loop is a **confirmation, not a search**:
  - The spec is the existing code, frozen before the window is opened.
  - Two pre-set sub-windows, each looked at once.
  - Full costs and tail statistics.
- **No mainstream futures prop firm offers this.** A few options-funding firms exist (for example Maverick Trading, T3, and newer simulated options evaluations), but their rules on naked short options and 0DTE are unverified. Assume a personal margin account with naked-option approval, or portfolio margin, unless a firm confirms in writing. The report must state the capital each straddle ties up.

## Decisions
- **Spec:** the `delta_hedge.py` variant "5m" at dte 0, plus its "30m" variant as the single secondary. The code is frozen by hash. Add only the cost and statistics wrapper, which lives in a new file.
  - QQQ and SPY are both reported; they are correlated, so they are not two independent tests.
- **Windows (UTC dates, NYSE sessions with a same-day expiry, half days skipped as in the code):**

  | Window | Dates |
  |---|---|
  | A | 2016-01-04 (QQQ) / 2017-01-03 (SPY) → 2018-12-31 |
  | B | 2019-01-02 → 2021-12-31 |

  - Each is opened once, in order. B opens only after A's result is written to the ledger.
  - Log the number of eligible days per year. Same-day expiries were not available every day before 2022, and `delta_hedge.py` already skips days without one.
- **Costs** (wrapper):
  - Option commission $0.65 per contract on entry. 0DTE settles at intrinsic, so there is no exit leg; that is 2 contracts per straddle.
  - Stress case: $1.00 per contract.
  - Share hedging pays half the quoted spread, about $0.005/share for SPY and QQQ; stress $0.01. No commission.
  - Entry is at the bid, as in the code.
  - Assignment and pin risk at 16:00 are approximated by cash settlement at intrinsic. State in the report that real ETF options are American and physically settled.
- **Gate. Each window must pass on its own; both are required:**
  - Mean net P&L per straddle > 0 with a day-bootstrap 95% CI low > 0, at base costs.
  - Stress costs give > 0.
  - No calendar year is negative by more than 2× the mean annual gain.
  - **Tail checks** (reported, and they count against the result):
    - Worst day.
    - 5% CVaR per straddle.
    - Max drawdown in $ per straddle.
    - Days losing more than 10× the mean gain.
    - The result with the worst 5 days removed and with them doubled.
  - Capital: show broker-style margin per straddle (about 20% of the underlying notional plus the premium, or the broker's posted formula) and the return on margin.
  - K = 4 (2 variants × 2 symbols), so p < 0.05/4 on a one-sided test of the mean > 0.
- **No search.** The strike rule, entry time, hedge clock and expiry rule do not change. If window A fails, B is not opened and the thread is closed.

## Layout
- **Parallel-safe shared writes:** other loops may be running at the same time.
  - Every write to `research_loop/CLOSED_IDEAS.md` or `research_loop/data_spend_ledger.json` (and to `data/binance/looks.jsonl`) takes an exclusive `fcntl.flock` on `functions/ml/research_loop/.shared.lock`, re-reads the file under the lock, appends its own rows only, and writes atomically (temp file + `os.replace`). Never rewrite or reorder rows written by other loops.
  - Cap worker processes at 3 for twin and permutation runs.
- `functions/ml/research_loop_straddle/`: `PLAN.md`, `prereg.json` (spec, code hashes, gate, windows), `confirm.py` (calls `delta_hedge.py` functions, adds costs and statistics), `tests/`, `ledger.jsonl` (every look), `REPORT.md`.
- State: `functions/ml/data/research_loop_straddle/`, holding `state.json`, `LOG.md` and per-window outputs.
- Shared: append the result to `research_loop/data_spend_ledger.json` (markets QQQ/SPY options, 0DTE short vol) and, on failure, to `CLOSED_IDEAS.md`.

## Running it with /loop
```text
/loop Run one iteration of the hedged straddle confirmation loop defined in /Users/sunnychen/.claude/plans/hedged-straddle-confirm-loop.md (section "Running it with /loop"). Read functions/ml/data/research_loop_straddle/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy the plan.
   - Confirm the 2022+ figures still reproduce from `data/delta_hedge` **without re-running anything on 2016–2021**.
   - Count eligible days per year in windows A and B from the **directory listing and expiry lists only** (no prices).
   - If either window has fewer than 150 eligible days per symbol, stop and report the power problem.
2. **Prereg:** write `prereg.json` with the SHA-256 of `delta_hedge.py` and `confirm.py`, the costs, the gate and the windows.
3. **Tests:**
   - The cost wrapper on hand-built days.
   - The window guard refuses B before A is in the ledger and refuses a second look at either window.
   - A synthetic day with realized = implied gives ≈ −costs.
   - Then freeze `confirm.py` and its tests by hash.
4. **Window A:** run once (in the background if slow), write the ledger row, and decide pass/fail against the gate.
5. **Window B:** only if A passed.
6. **Report and memory, then stop.**
   - If both pass, the report includes a paper-trading plan: 60 sessions of 1 SPY straddle on a broker paper account, logging the real bid/ask at 09:35 and the hedge fills against the model. Then the margin and approval steps.

**Stop conditions:** a window fails; both windows are done; 60 active minutes; anything needs approval; the same step failing 3 times.

**Never inside the loop:**
- Change the spec after the prereg.
- Open a window twice.
- Open 2026-09-26 → 2026-10-23 (the only post-study IV on disk, kept as a tiny forward check).
- Commit or push.
- Open `.env` files.

**Live data:** ThetaData is being cancelled. Paper trading needs a broker with real-time option quotes and an API. yfinance chains are about 15 minutes delayed, which is not usable for a 09:35 entry or a 5-minute hedge.
