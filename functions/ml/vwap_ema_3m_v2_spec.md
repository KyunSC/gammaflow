# VWAP/EMA 3m — v2 addendum (2026-11-03)

Status: written after the v1 grid (vwap_ema_3m_spec.md) FAILED discovery on ES+NQ 2011–2018. The user asked
for (a) the implementations v1 did not test and (b) a test on newer data, because someone else's backtest of
the idea was profitable. Everything not stated here is as in vwap_ema_3m_spec.md (data, 3m bars, EMA/ATR,
fills, costs, twins, stats).

## New dimensions (grid v2: 2 × 2 × 2 × 4 × 2 = 64 variants per symbol)

| Dimension | Values |
|---|---|
| Entry trigger | `price`: 3m close crosses VWAP (v1 cue). `ema`: the EMA crosses VWAP on a 3m close (EMA[k-1] ≤ VWAP[k-1] and EMA[k] > VWAP[k] for a long) with that close on the same side of VWAP, i.e. "price crossed, then wait for the EMA to cross" |
| Opposite signal | `flip`: closes the position and opens the other side at the next open (v1). `noflip`: closes only; a later fresh signal is needed |
| Session | `globex`: 18:00 ET → flat 16:55, VWAP from 18:00 (v1, warm-up 0). `rth`: VWAP anchored at 09:30 ET, entries fill 09:30–15:29, flat 15:55 (half days: no entries from 12:30, flat 12:55) |
| EMA | 9, 13, 21, 34 (EMA exit: a 3m close through the EMA, active from entry) |
| Stop | `none` (signal/EMA exits only), `atr1` (1.0 × ATR(14) from the fill, 1m stop-first) |

`v2|price|flip|globex|…` reproduces the v1 `none|ema…|vwap_close|w0` / `none|ema…|atr1|w0` cells (sanity check).
Not tested (judged unlikely to change a gross ≈ 0 result): 1m-typical VWAP, VWAP bands, other bar sizes.

## Discovery gate (v2, 2011-01-03 → 2018-12-31)

As v1 (both symbols: net > 0, twin p < 0.005, ≥ 5/8 positive years, top-5 days < 50% of net, neighbouring
EMA lengths net > 0). With 72 + 64 cells looked at on the same window, a pass here is already weak evidence.

## Newer data (user-approved in chat, 2026-11-03)

- Before any 2019+ bar is read, all v1 + v2 variants (136 per symbol) are frozen in vwap_ema_3m_prereg.json,
  with the hashes of both spec files and the study script, and a lock file is created.
- Windows: **2019-01-02 → 2021-12-31** (unseen by this family) and **2022-01-03 → 2026-08-14**. Each is run once.
- Pass in a window = net > 0 on both ES and NQ with side-matched twin p < 0.05 / 136 on both.
  A variant is called robust only if it passes both windows and discovery's sign agrees.
- Gross (no cost) results are reported alongside net, to compare with backtests that omit costs.
- Afterwards both looks go into research_loop/data_spend_ledger.json as `one_look` (family `vwap_cross_ema_exit`).
