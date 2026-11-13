# Daily-bracket research loop (one wide 1:1 trade per session, sized for prop accounts → MES/MNQ)

## Context
- The prop structure work (`functions/ml/data/prop_structure/LOG.md`) sets the shape that pays best:
  - one trade a day, with a wide 1:1 bracket (~300 MNQ ticks; 2-3 wins to pass);
  - at that size costs are ~0.01R, not the 0.05-0.15R that killed the 5m ideas;
  - +0.02R of real edge is worth ~$35/account on LucidFlex 50K and ~$200 on LucidDirect.
- So this loop looks for a **next-session direction call**: enter 09:35 ET, 1:1 bracket, flat 15:55. It does not look
  for intraday patterns.
- Everything in `~/.claude/plans/volsignal-futures-research-loop.md` (and the NQ/ES plans it points to) applies
  unless changed below.
- Read `functions/ml/research_loop/CLOSED_IDEAS.md` and `data_spend_ledger.json` before any prereg.

## Decisions
- **Evaluator:** copy `research_loop_volsig/eval/` into `research_loop_daily/eval/`. It already has the ES/NQ
  companion bar and prior-close Cboe series. Add one series:
  - the US Treasury daily par yield curve: free CSV from home.treasury.gov, 10-year column;
  - verify the download and hash it at bootstrap;
  - if it can't be fetched without a bot-check workaround, D2 is dropped and logged.
  - Daily series are used **as of the prior close only**.
  - New tests: the yield series lags by one session, and missing values give None.
  - Review with a subagent (Opus), then freeze with a new manifest.
- **Trade shape:**
  - One trade per session at the 09:35 bar open, 1:1.
  - Stop = k × ATR20 of daily ranges as of the prior close, with k fixed in each prereg (default 0.5).
  - Flat 15:55 ET.
  - Costs as in the NQ/ES loops: MNQ 3.6 ticks per round trip; MES as in `research_loop/eval/costs.py`.
- **Splits:**
  - dev 2011-02 → 2018-12;
  - val1 2019-01 → 2021-12; val2 2022-01 → 2026-08-14;
  - the holdout (after 2026-08-14) is not on disk, apart from NQ 2026-08-15 → 11-03, which is **spent** for
    `vwap_cross_ema_exit` only and must not be used here.
- **Gate:** as in the other loops (dev twin p < 0.005 with side-matched twins, then val1 p < 0.05, then val2). Rules
  must be signed long AND short. No ML, at most 3 features per idea.
- **Budget:** 9 configurations + 1 spare.

## Candidate queue (step 4a writes the exact rules and checks the sources first)

| # | Idea | Mechanism, and sources to check | Data | Notes |
|---|---|---|---|---|
| D1 | **Daily-horizon reversal.** Prior L-day close-to-close return (L = 1 or 5), z-scored by 20-day daily vol. When abs(z) ≥ Z, trade the next session against it. Configs: (L1, Z1), (L1, Z1.5), (L5, Z1) | Short-horizon index reversal from liquidity provision and inventory. Check whether index *futures* show it after 2000 (Lehmann 1990 is single stocks; look for index-level evidence, e.g. Nagel 2012 RFS "Evaporating liquidity") | ES and NQ 1m bars | **Overlap:** `shock_fade` (5m same-slot shock, 90-minute hold) is tagged `short_term_reversal`. The prereg must show the mechanical difference: daily close-to-close signal, next full session, no intraday trigger. If a reviewer subagent calls it the same family, drop it |
| D2 | **Month-end rebalancing flow.** On the last 3 sessions of each month: ES month-to-date return minus the 10y Treasury return proxy (−8 × Δ10y yield, month-to-date). Equities ahead by > X → short; behind → long. Configs: X = 0 or top/bottom tercile; hold the last 3 sessions or only the last 1 | Balanced funds and pensions rebalance back to target weights. Sources: Harvey, Mazzoleni & Melone, "The Unintended Consequences of Rebalancing" (2025); check the timing they find (days before month-end) | ES (and NQ for report), Treasury yields | ~285 dev trades at 3 days/month; confirm ≥ 200 from a count-only scan of the calendar before any returns are seen |
| D3 | **VIX inversion level.** Prior close VIX/VIX3M > 1 → that session takes V3's sign: long when the 1-day slope change moved toward contango, short when it inverted further | Seen post hoc in `research_loop_volsig/REPORT.md` §6: +0.17 to +0.24R on 61-115 ES dev trades, concentrated in 2011, 2015 and 2018 | ES and NQ, Cboe | **Gated: D3 approval: PENDING.** ES 2011-18 is spent for this family, and NQ 2011-18 shares its dates, so it is not fresh. If the user changes this line to `D3 approval: YES`, the loop spends ONE look on val1 (2019-21, ES and NQ) at the exact post-hoc rule, then val2 only if val1 passes. Expect very few trades (2020 mostly): report the count first. Otherwise skip D3 |

## Layout
- `functions/ml/research_loop_daily/`, holding `PLAN.md`, `eval/`, `tests/`, `controller.py`, `prereg/`, `strategies/`,
  `ledger.jsonl`, `REPORT.md`.
- State: `functions/ml/data/research_loop_daily/`, holding `treasury/`, `state.json` and `LOG.md`.
- **Parallel-safe shared writes:** other loops may be running.
  - Every write to `research_loop/CLOSED_IDEAS.md` or `research_loop/data_spend_ledger.json` takes an exclusive
    `fcntl.flock` on `functions/ml/research_loop/.shared.lock`.
  - Under the lock: re-read the file, append only this loop's rows, and write atomically (temp file + `os.replace`).
  - Never rewrite or reorder other loops' rows.
- Cap worker processes at 3.
- Do not read or write `prop_realtape/`, `prop_policy/` or `data/prop_structure/`.

## Running it with /loop
```text
/loop Run one iteration of the daily-bracket research loop defined in /Users/sunnychen/.claude/plans/daily-bracket-research-loop.md (section "Running it with /loop"). Read functions/ml/data/research_loop_daily/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy the plan.
   - Fetch and hash the Treasury CSV, and check its date coverage against ES sessions.
   - Re-read CLOSED_IDEAS and the ledger. Log the D3 approval line's current value.
2. **Evaluator:** (a) copy and add the yield series; (b) review subagent; (c) freeze.
3. **Controller and sanity checks:** the same four as the volsig loop.
4. **Per candidate (D1, then D2, then D3 if approved):**
   - prereg, including source checks and the overlap argument, plus an overlap-review subagent for D1;
   - then implement → dev → val1 → val2 → decision.
   - Rejections go to the shared files under the lock.
   - If anything passes val2, record the per-trade R distribution in `REPORT.md`, so it can be fed straight into
     the prop structure model as an edge (`lucid_structure.make_days(edge=...)`).
5. **Report and memory, then stop.** Write `daily-bracket-loop-<date>.md` plus its MEMORY.md line.

**Stop conditions:**
- 10 configurations used.
- 150 active minutes.
- The queue is empty.
- Any purchase or approval is needed.
- The same step fails 3 times.

**Never inside the loop:**
- Edit a frozen `eval/` (any loop's).
- Buy data or open holdout data.
- Run D3 without `D3 approval: YES`.
- Commit or push.
- Lower the criteria.
- Open `.env` files.
