# VWAP close-through / EMA exit, 3-minute, NQ + ES (draft spec, 2026-11-03)

Status: DRAFT. Not frozen, not run. No data looked at for this idea yet.

## Data

- Databento `fut-ohlcv-1m-cont` NQ.v.0 / ES.v.0 (already on disk), resampled to 3m bars anchored at 18:00 ET.
- Roll days are skipped. EMA restarts at each roll. VWAP resets every session.
- Trades are sized as 1 MNQ or 1 MES.

## Indicators

- **VWAP:** Globex session VWAP from 18:00 ET, cumulative `sum(typical * vol) / sum(vol)`, typical = (H+L+C)/3.
- **EMA:** EMA of 3m closes, carried across sessions within a contract. Length N ∈ {9, 13, 21, 34}.
- **ATR:** ATR(14) on 3m bars (used by the ATR stop only).

## Signals (evaluated on 3m closes, filled at the next 3m open)

- **Long cue:** previous close ≤ VWAP and current close > VWAP.
- **Short cue:** previous close ≥ VWAP and current close < VWAP.
- **EMA exit:** a long exits when a 3m candle closes below the EMA; a short exits when one closes above it.

## Cross modes (the "wait for EMA and VWAP to cross" rule)

| Mode | Entry | EMA exit |
|---|---|---|
| `none` | any VWAP cue | active from entry |
| `arm_exit` | any VWAP cue | active only once the EMA is on the trade side of VWAP (EMA > VWAP for longs), checked on closes; active immediately if that's already true at entry |
| `filter_entry` | only if the EMA is already on the trade side of VWAP at the cue close | active from entry |

"Both" (filter the entry and arm the exit) is identical to `filter_entry`: the filter guarantees the exit is armed at entry, so it's not a separate cell.

## Opposite cue = flip

An opposite VWAP cue that passes the mode's entry rule closes the position and opens the other side at the same next-bar open. A cue that fails the filter does nothing to the position by itself. In that case, the EMA exit fires anyway whenever the close is below VWAP and the EMA is above it.

## Stops

| Stop | Rule |
|---|---|
| `vwap_close` | exit on a 3m close back through VWAP. **With flip on, this is identical to no hard stop** (the first close back through VWAP is always an opposite cue). The only difference is after 16:30, when no new entries are allowed. The two are run as one cell. |
| `atr1` | hard stop 1.0 × ATR(14) from the fill price |
| `entry_bar` | hard stop 1 tick beyond the cue candle's low (longs) / high (shorts) |

- Hard stops are checked on 1m bars inside each 3m bar, stop-first.
- After a stop-out, stay flat until a fresh VWAP cue.

## Session

- Entries from 18:00 ET (`warmup0`) or 18:30 ET (`warmup30`).
- No new entries after 16:30 ET. Flat at 16:55 ET (before the CME halt), or at the early close on half days.

## Costs

- Commission $0.50/side per micro.
- Market fills (entries, EMA exits, flips, flat-at-close) get 1 tick of slippage.
- Stops get the measured stop slip (~1.1 tick mean, per `fill_study`).
- No fills at the same bar's close. Entries fill at the next bar's open.

## Grid

3 modes × 4 EMA lengths × 3 stops × 2 warm-ups = **72 variants per symbol**, 144 in total.

## Discovery: ES + NQ 2011-01-03 → 2018-12-31

Report per variant and symbol:
- trades/day
- net $/trade and net $/day per micro
- gross vs. net
- points per trade
- R per trade (ATR and entry-bar stops only)
- win rate
- yearly split
- top-5-day share
- max drawdown

Baselines:
- side-matched random-direction twins (same entry times and exits, random side)
- always-long over the same holding windows
- the reversed signal

Pass gate:
- net > 0 on **both** ES and NQ
- permutation p vs random twins < 0.005 (about 144 cells tested)
- positive in ≥ 5 of 8 years
- top 5 days < 50% of net
- neighbouring EMA lengths also positive (not a lone spike)

At most 2 variants get frozen (prereg JSON with spec hash).

## Confirmation: one look, ES + NQ 2022-01-03 → 2026-08-14

- Run only the frozen variants, with a lock file against a second look.
- Pass = net > 0 on both symbols with p < 0.05 vs random twins.
- Afterwards, record the look in `research_loop/data_spend_ledger.json` (family `vwap_cross_ema_exit`).

## Known risks going in

- **Trade count and costs.** Over nearly 24 hours, 3m VWAP crosses are frequent, especially overnight. Round-trip cost is about $2 on MNQ and $3.50 on MES, so cost drag will be large.
- **Related ideas that failed.** VWAP-touch break/fade and first-pullback continuation (ES/NQ 2012–21), opening-candle-vs-EMA direction (2016–21), and the posted `vwap_ema` prop rule (QQQ/SPY RTH 2022–25) all FAILED. This idea differs in three ways: the session is nearly 24 hours, entry is a close-through rather than a touch, and the exit is an EMA trail. Even so, a pass should be checked hard against drift (always-long) and against the random-direction twins.
- **Not using the research_loop evaluator.** That evaluator is frozen at 5m decisions. This is a standalone script that copies its fill and cost rules rather than editing the frozen evaluator.
