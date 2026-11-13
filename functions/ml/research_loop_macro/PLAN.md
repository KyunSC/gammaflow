# Macro futures research loop (ZN, GC, 6E: Treasury auctions, the gold auction, the FX fix)

## Context
- ES and NQ have been tested about 37 times and are highly correlated, so another index idea adds little new evidence.
- This loop moves to **three new tapes that futures prop firms also allow**:
  - 10-year notes (ZN)
  - Gold (GC, traded as MGC)
  - Euro FX (6E, traded as M6E)
- Each one has a **scheduled, documented flow event** with a published mechanism:
  - Treasury auctions, where dealers absorb new supply.
  - The LBMA gold price auction.
  - The WM/Reuters 4pm London FX fix.
- These are price-pressure-and-reversal stories tied to known calendar times. That is the kind of idea that has survived in the literature after costs. "Pattern on a chart" ideas have not.

Everything in the ES plan (`~/.claude/plans/can-you-review-this-peppy-moon.md`) applies unless changed below. That includes the frozen evaluator, the side-matched twins, the gate, the stop conditions and the "never inside the loop" list.

## Decisions
- **Billing:** a Claude Code chat via `/loop`, with no nested calls.
- **Prop container:** an intraday-only futures evaluation (Lucid, Topstep, Apex style). Flat by 15:55 ET, with no overnight holds.
  - Contracts: ZN (full size; check whether the firm lists micro yield futures), MGC, M6E.
  - Re-check each firm's product list and commission at bootstrap. Use $0.50/side for micros and the firm's posted full-size rate for ZN.
- **Market data:**
  - Databento `GLBX.MDP3` ohlcv-1m continuous `ZN.v.0`, `GC.v.0`, `6E.v.0`, 2011-01 → 2026-08-14, so the splits match ES/NQ.
  - **This is a purchase.** ES and NQ cost $19.92 and $19.38 for the same span, so expect roughly **$15–25 per product, about $60 in all**.
  - The loop only gets a quote: `databento_fetch.py` quotes without spending unless `--download` is given. It then stops for Sunny's approval.
  - Free alternative for GC and 6E only: Dukascopy's public tick archive (spot XAU/USD and EUR/USD, bid/ask ticks back to the 2000s). It was **not verified**: it returned HTTP 429 (rate-limited) from this machine. Spot is a close intraday proxy for GC and 6E (the basis moves slowly), but it is not the traded contract.
  - Nothing free was found for intraday Treasury futures.
- **Event calendars (free, verified 2026-11-03):**
  - **Treasury auctions:** `api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query`. It gives auction date, security term, announcement date, competitive close time (for example "11:30 AM" for bills and 13:00 for coupons) and bid-to-cover, back to 2011.
  - **LBMA gold price auctions:** 10:30 and 15:00 London; the PM auction moved to an electronic auction on 2015-03-20.
  - **WMR fix:** 16:00 London; the window widened from 1 to 5 minutes on 2015-02-15.
  - Convert all London times with zoneinfo, because the US and UK DST weeks do not match.
- **Splits:** the same as ES/NQ. dev 2011-02 → 2018-12, val1 2019-01 → 2021-12, val2 2022-01 → 2026-08-14, 20 warmup sessions, 5-session gaps.
  - Holdout: after 2026-08-14, not on disk.
  - Sessions are built per product. Use ZN 08:20–15:00 ET, GC 08:20–13:30 ET and 6E 03:00–15:55 ET. All are flat by 15:55 ET. State the windows in `config.py`.
- **Cost rule.** Each prereg shows its cost in R at 2011 and 2024 levels:
  - **MGC:** $1 per 0.10 tick. A 0.4% stop is about 100 ticks, so costs are about 0.03R; this is the cheapest of the three.
  - **M6E:** $1.25 per 0.0001 tick. It needs a stop of about 50 ticks or more to keep costs ≤ 0.06R.
  - **ZN:** $15.625 per tick. One tick of slippage dominates, so it needs a stop of about 25 ticks or more. Use a 0.5-tick base slip on limit-like fills only where the fill rule justifies it.
- **Gate:** identical to ES/NQ. Dev twin p < 0.005; val1 and val2 each need ≥ 100 trades and p < 0.05. The criteria are never lowered.

## Layout
- **Parallel-safe shared writes:** other loops may be running at the same time.
  - Every write to `research_loop/CLOSED_IDEAS.md` or `research_loop/data_spend_ledger.json` (and to `data/binance/looks.jsonl`) takes an exclusive `fcntl.flock` on `functions/ml/research_loop/.shared.lock`, re-reads the file under the lock, appends its own rows only, and writes atomically (temp file + `os.replace`). Never rewrite or reorder rows written by other loops.
  - Cap worker processes at 3 for twin and permutation runs.
- `functions/ml/research_loop_macro/`: `PLAN.md`, `calendars.py`, `eval/`, `tests/`, `controller.py`, `prereg/`, `strategies/`, `ledger.jsonl`, `REPORT.md`.
- State: `functions/ml/data/research_loop_macro/`. Calendars are cached in `data/research_loop_macro/calendars/` with a fetch log and SHA-256 hashes.
- Shared: `research_loop/CLOSED_IDEAS.md` and `research_loop/data_spend_ledger.json`, with markets "ZN", "GC" and "6E".
- Adding the three products to `databento_fetch.py` (the `products` tuple and the job) is an allowed code change outside `eval/`.

## Evaluator (step 2)
- Start from a copy of `research_loop_nq/eval/` and drop the ES companion.
- Add a per-product contract block and per-product session windows.
- Add an **event field** on each bar dict, `bar['events']`: scheduled events whose time is ≥ the bar's end and ≤ the session end, with their kind and tenor.
  - Use **scheduled times only**. Outcome fields such as bid-to-cover are attached only to bars that end after the release time, plus a 2-minute delay. Test that.
- The roll calendar is per product. Test that no trade spans a roll.
- Review with a subagent, focused on:
  - Timezone and DST handling for London events.
  - The look-ahead in auction results.
  - Tick and $ arithmetic per product.
  - Session windows.
- Then freeze with a manifest covering the code, tests, all three products' parquets and the calendar files.

## Candidate queue (step 4a writes the exact rules; check the sources before the prereg)
| # | Idea | Mechanism and sources | Product | Trades in dev | Notes |
|---|---|---|---|---|---|
| M1 | **Treasury auction concession and recovery.** On coupon-auction days (5/7/10/30y), short ZN from the morning open to the 13:00 auction close, then long from about 13:02 to 15:00 | Dealers absorb supply: prices fall into auctions and recover after. Sources: Lou, Yan & Zhang 2013 (RFS, "Anticipated and repeated shocks in liquid markets"); Fleming & Rosenberg (NY Fed dealer inventories) | ZN | ~500 auction days × 2 legs | The side comes from the calendar, so twins test timing vs random side. Report the pre- and post-auction legs separately. Variant: condition the post leg on bid-to-cover vs the trailing 6 auctions of the same tenor (published after 13:00) |
| M2 | **WMR 4pm fix pressure reversal.** Fade the EUR/USD move from 10:45 to 11:00 ET (London 15:45–16:00) after the fix, holding 30–90 min | Fix order flow moves the price, then it reverts. Sources: Evans 2018 (JIMF, "Forex trading and the WMR fix"); Evans, O'Neill, Rime & Saakvitne 2018 ("Fixing the fix?"); Melvin & Prins 2015 (month-end hedging flows) | 6E | ~2,000 | Report month-end days separately: Melvin & Prins predicts a *signed* month-end flow from equity returns. That is too few days (96) for its own gate; report it only |
| M3 | **LBMA PM gold auction drift.** Trade the post-auction direction relative to the pre-auction drift (fade or follow, chosen from the sources before data) | Caminschi & Heaney 2014 (J. Futures Markets, "Fixing a leaky fixing") found pre-fix drift. Test whether anything survives the 2015 electronic auction | GC | ~1,900 | Split pre- and post-2015-03-20 in the report. The gate uses the whole dev period |
| reserve | Gold–ZN real-rate catch-up | Residual momentum is closed on NQ/ES. Use only with a mechanism that differs (real-yield pass-through) | GC + ZN | | Needs a companion bar; likely skip |

**Budget:** 10 configurations (3 hypotheses × ≤3 variants, plus 1 spare). Grids are chosen in the prereg: for example the hold length for M2, and the start time of the pre-auction leg for M1.

## Running it with /loop
```text
/loop Run one iteration of the macro futures research loop defined in /Users/sunnychen/.claude/plans/macro-futures-research-loop.md (section "Running it with /loop"). Read functions/ml/data/research_loop_macro/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy the plan to `research_loop_macro/PLAN.md`.
   - Add ZN, GC and 6E to `databento_fetch.py` and run a **quote only**. Write the quote to `state.json`.
   - **Stop and ask Sunny to approve the purchase**, or to choose the Dukascopy path for GC and 6E. Sunny runs `--download` themselves, or tells the next firing to.
2. **Data checks** (once the files are on disk):
   - Run an inventory per product: coverage, duplicates, bad OHLC, half days, and roll events in-session.
   - Fetch the auction calendar and build the gold-auction and fix calendars.
   - Cross-check 20 auction dates by hand against TreasuryDirect press releases (logged).
3. **Evaluator:** (a) copy and adapt, (b) review subagent, (c) freeze.
4. **Controller and sanity checks:**
   - Always-flat gives 0 trades.
   - Random direction gives ≈ −cost **per product**.
   - Kill and resume leaves no duplicate rows.
   - A one-byte change is refused.
5. **Per candidate:** prereg → implement → dev → val1 → val2 (each only after a pass) → decision. Update `CLOSED_IDEAS.md` and the spend ledger on every rejection.
6. **Report and memory, then stop.**

**Stop conditions:**
- 10 configurations.
- 120 active minutes.
- The queue is empty.
- Any purchase or approval is needed. The first stop is expected at bootstrap (the data quote).
- The same step has failed 3 times.

**Never inside the loop:**
- Run `--download` without Sunny's go-ahead in chat.
- Edit `eval/` after the freeze.
- Open holdout data.
- Commit or push.
- Lower the criteria.
- Open `.env` files. The Databento key is read by `databento_fetch.py` itself; never print it.

**Forward and paper data (outside the loop):** the prop account's own feed (Rithmic/Tradovate) or the TopstepX/ProjectX API. That API is $29/month, or $14.50 with the Topstep discount, and includes historical bars. It is the cheapest way to extend the tape past 2026-08-14 for paper trading.
