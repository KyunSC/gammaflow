# Pre-registration: NQ absorption at GEX levels in negative gamma

Written 2026-10-13, before any of the test data was bought. Once the test data is
downloaded, this rule must not change. It is scored once (see "One look").

## Why this test

`orderflow_backtest.py --study absorb` froze `absorb_vol/w30/m0.03/l2` on 81 NQ sessions
(2026-04-24 → 2026-08-14). It averaged +0.05R on NQ and failed its one-look ES test (−0.26R).
After that, an exploratory split by QQQ dealer gamma (net GEX at entry) found every
setup did better in negative gamma, on both NQ and ES. The best case (NQ absorption, 27
trades, +0.94R) came from two outsized winners; without them it was −0.17R. That split was
in-sample and post-hoc, so it is a hypothesis, not a result. This test checks it on NQ
sessions this strategy has never seen.

## Test data

- **Prints:** NQ trades (`NQ.v.0`, 09:25–16:00 ET), every session from **2025-10-24 to
  2026-04-23**: 127 files, quoted at $43.56 on 2026-10-13. A full year was quoted at
  $83.17; the user chose the half year. They are bought via `databento_fetch.py nq-trades`
  and land next to the research files in `data/databento/nq-trades/NQ/`.
  - The first session (2025-10-24) has no prior session, so it is skipped.
  - Exchange holidays with no RTH GEX snapshot produce no trades.
- **GEX:** `data/thetadata_gex/qqq_gex_snapshots.parquet`, whole chain, not 0DTE. It has a
  snapshot every 5 min, 09:30–16:00, for all 124 GEX sessions in the window.
- **Expected size:** about 45–50 trades. The smoke run on the 81 research sessions gave this rule
  32 trades (counts only, no R). The 30-trade minimum may bind, and a CI that excludes 0 is unlikely unless the
  effect is large.
- **Separation:** the existing studies (`--study bubble`, `--study absorb`) must only read
  sessions on or after 2026-04-24, so the new files never enter them.

## The rule (frozen)

Everything not listed here is unchanged from the frozen cell `absorb_vol/w30/m0.03/l2`:

- `units="range"`, `REF_RANGE=418.25`
- level tolerance 3 pts; stops min 4 / max 30 pts; stop buffer 2 ticks
- `approach_min=5`, `confirm_min=10`
- entries 09:30–15:30, flat by 15:55
- the target rule: nearest level at least 1R away, else 2R
- costs: $4.50 round trip, plus 1 tick of slippage on entries, stops and the end-of-day exit

1. **Absorption detector.**
   - Window W = 30 s; effort threshold 0.03 × the prior session's median minute volume,
     prorated to 30 s; leak = 2 ticks.
   - One event per side per window.
   - Absorbed buying under a level that price approached from below → short. The long is the
     mirror image.
2. **Levels.**
   - The existing set: prior-session high and low, prior-session LVNs, and VWAP ±1/±2 sd
     (after 09:45).
   - **Plus the GEX levels:** call wall, put wall and zero gamma (when not NaN), from the
     latest snapshot available at the decision time.
   - The GEX levels act as both trigger levels and targets, like the others.
3. **GEX availability.**
   - A snapshot counts as available 1 minute after its `computed_at`.
   - Snapshots more than 20 minutes old are ignored, which means no GEX levels and no trade.
4. **QQQ → NQ conversion.**
   - `level_NQ = strike × (NQ price / QQQ spot)`.
   - NQ price is the last NQ print at or before the snapshot's `computed_at`; QQQ spot is
     the snapshot's own `spot`.
   - This keeps the conversion point-in-time, with no fixed ratio.
5. **Regime filter.** Only take events when the snapshot's `net_gex < 0`. The filter is
   checked at the event time.

## Controls (same levels, regime filter, stops and targets)

- `push`: the same effort, but it moved the extreme by more than 2 ticks.
- `touch`: any print at a level.
- `random`: 20 seeds, as in the existing study.
- Secondary, reported only:
  - the same rule in **positive** gamma;
  - the same rule in negative gamma **without** the GEX levels.

## Pass criteria (decided now)

The statistic is mean R per trade over all test sessions. The 95% CI resamples whole
sessions (2,000 draws, seed 0), as `summarize()` already does.

| Verdict | Condition |
|---|---|
| **PASS** | n ≥ 30, mean R > 0, CI lower bound > 0, and mean R above both `push` and `touch` |
| **WEAK** | n ≥ 30, mean R > 0 and above both `push` and `touch`, but the CI includes 0 |
| **FAIL** | anything else |

Robustness checks, always reported next to the verdict without changing it:

- median R
- mean R without the 2 largest winners
- the share of total R from the top 5% of trades
- results per calendar quarter

## One look

- Before any test session is loaded, the run writes `data/orderflow/gex_NQ/preregistered.json`
  using exclusive create and fsync. It records:
  - the sha256 of `orderflow_backtest.py`
  - the sha256 of this file
  - the session window
- The run refuses to go ahead if that file already exists, or if either hash differs from
  the freeze record.
- The code is finished, unit-tested on synthetic prints, and hashed *before* the data is
  downloaded. Its only real-data run before then is a smoke run on the research sessions,
  which checks that it runs and counts events; its R is not looked at.
- Whatever the verdict, it is reported as is. There is no retuning on the test sessions.
