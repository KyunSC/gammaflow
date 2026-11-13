# Daily-bracket research loop: report (2026-11-04, extension 2026-11-05)

Plan: `research_loop_daily/PLAN.md` (copy of `~/.claude/plans/daily-bracket-research-loop.md`). Log: `data/research_loop_daily/LOG.md`. State: `data/research_loop_daily/state.json`.

**Outcome: nothing passed dev.** D1, D2 and the two approved extension ideas E1 and E2 all FAILED on ES dev 2011-02→2018-12 on every configuration. D3 was skipped because its approval is still `PENDING`. **All 10 of 10 configurations are used**, so the loop has stopped on its budget. val1, val2 and the holdout were never opened. No edge exists to feed into `lucid_structure.make_days(edge=...)`.

## Trade shape
- One trade per RTH session, entered at the 09:35 open, with a 1:1 bracket of 0.5 × ATR20 (roll-adjusted true range) around the 09:30 close. Flat at 15:55. MES costs as in the ES/NQ loops.
- The controller enforces the shape on every run (`controller.shape_violations`).

## Results (ES dev, frozen evaluator `2ca6f8df`)

| Idea | Config | Trades | Net R | Gross R | Twin p | Verdict |
|---|---|---|---|---|---|---|
| D1 daily reversal: fade the prior L-day same-contract return, z-scored by 20-day vol | L1 Z1.5 | 295 | −0.070 | −0.000 | 0.42 | FAIL |
| | L1 Z1 | 577 | −0.073 | −0.005 | 0.49 | FAIL |
| | L5 Z1 | 605 | −0.087 | −0.018 | 0.49 | FAIL |
| D2 month-end rebalancing: last N sessions, fade the MTD return of ES minus the 10y bond proxy | N3 | 279 | −0.038 | +0.029 | 0.13 | FAIL |
| | N5 | 459 | −0.041 | +0.027 | 0.18 | FAIL |
| | N5, abs(z) ≥ 0.43 | 326 | −0.009 | +0.061 | 0.10 | FAIL |
| D3 VIX inversion level (val1 one-look) | — | — | — | — | — | skipped: `D3 approval: PENDING` |
| E1 daily time-series momentum: follow the sign of the summed last-L-session return, every session | L20 | 1,967 | −0.067 | +0.002 | 0.28 | FAIL |
| | L40 | 1,947 | −0.075 | −0.006 | 0.43 | FAIL |
| E2 option-expiration week: long the third-Friday week, short the week after | full weeks | 905 | −0.060 | +0.009 | 0.24 | FAIL |
| | last 3 / first 3 sessions | 564 | −0.046 | +0.023 | 0.14 | FAIL |

Report-only observations (descriptions, not gates):
- **D1** is worst in the high-VIX tercile (−0.16/−0.21R), and longs after down days do worse than shorts. Both are the opposite of Jones-Pyun-Wang's conditional prediction. Post-2000 index daily reversal is not tradable in the next RTH session.
- **D2:** the largest MTD-gap tercile is the worst (−0.10/−0.11R), against the mechanism. Quarter-ends are not stronger. The sessions-left profile flips sign from day to day.
- **E1:**
  - Beats side-matched twins by only +0.010R (L20) and +0.003R (L40), with 0 of 3 folds and 7 of 8 years negative.
  - Always-long and always-short are both ≈ −0.077R, so the 09:35→15:55 RTH leg had no drift worth timing in dev.
  - Its side agrees with the sign of D1's 5-day return on 65–68% of days. MOP-style monthly trend does not show up as a next-session RTH edge.
- **E2:**
  - Both legs are negative. The week-after short is the worst in full weeks (−0.09R), against the mechanism.
  - The quarterly long leg is negative (−0.05/−0.11R), the sign Schaeffer's reports.
  - Short-leg days inside D2's month-end window don't rescue it.
  - Stivers-Sun's stock-level pattern is not tradable on the index in RTH.

## Evaluator built (frozen, reusable)
- `research_loop_daily/eval/` is a copy of `research_loop_volsig/eval/` plus the additions below. Its 426-entry manifest digest is `2ca6f8df…`, and the product is set by `DAILY_PRODUCT`.
- **UST 10y par yield** from home.treasury.gov (plain curl, no bot check):
  - files: `data/research_loop_daily/treasury/`, rebuildable byte-for-byte with `build_ust.py`;
  - lag: dated the previous ES session, else None (Columbus/Veterans Day);
  - Good Friday prints never leak.
- **`bar['hist']`**: 60 prior sessions with own-contract RTH o/h/l/c, `adj`, a roll-adjusted `ret` and `tr`, `nyse_skipped` and `ust10y`.
  - Rolls: all 62 ES/NQ switches in 2011-26 are adjacent Globex bars 1–6 min apart, and the gap is measured before 09:30.
- **`bar['mtd']`**: roll-adjusted MTD return and Δ10y as of the prior close.
- **`bar['sessions_left_in_month']`**: taken from the published NYSE holiday rule; ad hoc closures are not anticipated.
- 106 tests. An Opus review found 2 blockers and 1 should-fix, all fixed before the freeze. 6/6 UST lag mutations were caught.

## Extension (2026-11-05)
- Proposals were written after D1/D2/D3 finished and approved by the user in chat (2026-11-04 19:04 ET). Count-only scans were done before each prereg.
- An Opus overlap review of E1 vs D1 returned **DIFFERENT FAMILY - proceed**, with 4 required wording/tag changes applied (E1 also carries `index_serial_dependence`).
- E2 needed no reviewer under the plan; its overlap with D2 is disclosed. 173 of 437 full-week short days fall in D2's last-5 window.
- Pre-registrations: `prereg/E1_tsmom_daily.json` and `prereg/E2_opex_week.json`. Strategies and tests are in `strategies/` and `tests/` (115 tests pass).
- The E2 strategy carries its own integer-day copy of the NYSE holiday rule, because the sandbox has no `datetime`. A test checks it against `eval.data.nyse_holidays` for 2010–27.
- CLOSED_IDEAS rows and spend-ledger rows (`discovery`, ES 2011-02..2018-12) were appended under the lock; the ledger now has 47 rows.

## Lessons
- **Before costs, every one of the 10 configs is within ±0.06R of zero, and most within ±0.03R.**
  - The 0.069R MES cost is larger than any daily-horizon signal tried here: reversal, momentum, month-end and expiration calendar.
  - A daily ES idea in this 09:35→15:55 bracket shape needs a gross edge ≳ 0.14R (the stress gate) to pass.
  - The next daily ES idea should change the shape (wider bracket or multi-day hold, to cut cost in R) before it changes the signal.
- **Costs at this shape in 2011-18 are not ~0.01R.** At 0.5 × ATR20 they are MES 0.069R and MNQ 0.041R; the plan's figure assumed 2025 NQ with ~300-tick stops.
- **A one-trade-per-day idea needs ≥ 200 dev trades.**
  - Month-calendar rules with 1 day per month (~92 dev trades) cannot pass by construction.
  - Trailing-history thresholds restart in each split, because each split loads only ~60 days before its start. Use scale-free thresholds.
- Databento `*.v.0` has no bars at all on 2014-06-12/13, 09-23..25 and 12-31 (ES and NQ). The prior session is stale after them.
