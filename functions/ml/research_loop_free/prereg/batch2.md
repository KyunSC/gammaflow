# Free-data ideas loop — batch 2 proposal (written 2026-11-05 ~01:45 ET, before any batch-2 data was read)

Hashed into `data/research_loop_free/state.json` (`batch2_sha256`) in the same firing. Each idea still gets its own
`prereg/<id>.json` (exact rules, ≤ 3 configs, as below) and a count check before its run. No config is added later.

**Data:**
- Everything is on disk.
- Cboe VIX/VIX9D (frozen volsig CSVs, read by the es_daily evaluator as `bar['daily']`).
- ES `hist` returns.
- Binance UM 1m klines.
- Binance metrics (5m: BTC from 2020-09, ETH from 2021-12).
- Only file names, column names and date ranges were checked, never values.

**Evaluators:** fresh copies in `research_loop_free/b2/{es_daily,crypto}/`, made the same way as batch 1 (`ATTEMPT_LIMIT` /
`TRAIN_CONFIG_LIMIT` 10 each).

**Loop-wide bar:** batch 1 ran 15 configs, and batch 2 adds at most 15. A result needs p below its evaluator's bar and
also below 0.05 / (total configs run loop-wide).

## How batch-1 results influenced this batch (disclosure)

- **Trade counts.** F4 and F5 could not reach the 200-trade floor (one signal per day or per week, with filters). Every
  batch-2 config is sized from base rates to expect ≥ 300 trades: 4h or daily decisions with ≥ 20% hit rates. This
  influence comes from counts, not outcomes.
- **Costs.** F1's tight opening-bar stops cost about 0.19R. Every batch-2 bracket is at least 0.5×ATR20 (ES) or 1.5% (crypto).
- **Excluded ideas.** Batch 1's logged post-hoc reversals (follow WTD on Friday, ES follows the yield move, BTC fade after the funding print) and every CLOSED_IDEAS family are excluded. So are variants of F1–F7 and loosened F4/F5 thresholds.
- **Directions.** No direction was chosen from a batch-1 sign. Each comes from its mechanism, stated before data.
- **Not used:**
  - ES intraday and NQ. ES intraday has been mined heavily (shock, release, round, VWAP, ORB, momentum, gap families closed), and I found no clean, distinct mechanism for it. For NQ, the ES-companion ideas (SMT, residual momentum or reversal) are closed.
  - G2 and G5 below use related positioning series with opposite stances (fade top-trader accounts vs follow top-trader positions against retail). At most one mechanism can be right, and both count against the Bonferroni budget.

## Ideas

### G1_vix9d_inversion: ES daily

- **Mechanism.** An ultra-short-term fear spike, with VIX9D far above VIX, marks capitulation hedging that unwinds the next day, so ES rebounds. Extreme complacency, with VIX9D far below VIX, precedes a mild reversal down.
- **Rule.**
  - x = ln(VIX9D / VIX) from `bar['daily']`, at the prior close.
  - Percentile of x within the strategy's trailing x history: up to 250 sessions, at least 120.
  - x ≥ the upper q-quantile → long. x ≤ the lower (1−q)-quantile → short.
  - Evaluator shape: 09:35 → 15:55, 1:1 at 0.5×ATR20(tr).
- **Configs.** q ∈ {0.75, 0.80, 0.90}, giving about 50%, 40% and 20% of sessions, or roughly 900 / 740 / 370 dev trades.
- **Against the mechanism.**
  - The long leg alone carries it (report each leg separately).
  - Report only: a VIX-level control. Take the same top and bottom fractions of the VIX level itself. If it does as well, the term-structure inversion adds nothing.
  - The gate fails for all q.
- **Closed-family check.** V3 (closed) traded the 1-day CHANGE of VIX/VIX3M. This idea trades the LEVEL of VIX9D/VIX, a different maturity pair. That is not a change signal and not the same tenor, which I judge distinct; I'm noting it in case you disagree.

### G4_vrp_direction: ES daily

- **Mechanism.** The variance risk premium VRP = VIX − RV20 (RV20 = sd of the last 20 `hist` close-to-close returns × √252 × 100).
  - A high VRP means investors are over-insured, and dealer hedging of that insurance supports index drift the next day.
  - A low or negative VRP means realized vol exceeds implied, so vol-targeting funds keep de-levering and selling.
- **Rule.**
  - Percentile of VRP within its trailing history (≤ 250 sessions, ≥ 120).
  - Top fraction → long, bottom fraction → short.
  - Evaluator shape as G1.
- **Configs.** q ∈ {0.67, 0.80, 0.90}, about 1,230 / 740 / 370 trades.
- **Against the mechanism.**
  - The long leg alone carries it.
  - Report only: a VIX-level control, as in G1. If it does as well, VRP adds nothing beyond the VIX level.
  - Report only: an RV20-only control. If it does as well, this is realized-vol timing, not a premium.
  - The gate fails for all q.

### G2_toptrader_fade: crypto train (BTC + ETH)

- **Mechanism.** When top traders (by account count) lean unusually long, positioning is crowded, and the unwind moves price against them over the next hours. The same holds in reverse for a short lean.
- **Rule.**
  - At each UTC 4h boundary (00, 04, …, 20; decision on the bar ending at the boundary), take the latest `count_toptrader_long_short_ratio` with `avail = stamp + 300` ≤ the decision time, and at most 15 minutes old.
  - z = ln(ratio) against the trailing 30 days of 4h samples (≥ 150 of 180).
  - z ≥ Z → short. z ≤ −Z → long.
  - Stop = target = 1.5%, exit after 8h, one trade at a time.
- **Configs.** Z ∈ {1.0, 1.5, 2.0}.
- **Against the mechanism.**
  - Report only: split trades by whether the prior 24h return agrees with the crowd's side. If the effect exists only when it does, the ratio is just a proxy for past price, which makes it a price reversal, not a crowding effect.
  - BTC-only or ETH-only.
  - The gate fails for all Z.

### G5_smart_vs_retail: crypto train (BTC + ETH)

- **Mechanism.** When large accounts' position ratio diverges from the all-accounts ratio, the large accounts are informed. Follow them.
- **Rule.**
  - Same 4h grid and freshness as G2.
  - d = z(ln `sum_toptrader_long_short_ratio`) − z(ln `count_long_short_ratio`), each z against the trailing 30 days of 4h samples.
  - |d| ≥ D → side = sign(d).
  - Stop = target = 1.5%, exit after 8h.
- **Configs.** D ∈ {1.0, 1.5, 2.0}.
- **Against the mechanism.**
  - Report only: a top-trader-only control, following the top-trader position z without subtracting retail. If it does as well, the divergence adds nothing.
  - BTC-only or ETH-only.
  - The gate fails for all D.

### G3_us_open_fade: crypto train (BTC + ETH)

- **Mechanism.** Moves made in the 12 non-US hours before the US equity open (21:30 → 09:30 ET) happen in thinner books. US-hours liquidity providers and arbitrageurs partly revert them during the US session.
- **Rule.**
  - Weekdays (ET).
  - move = close of the 09:29 ET 1m bar − close of the 21:29 ET 1m bar 12h earlier.
  - sd = 30-day sd of daily UTC log returns × price (complete days before the decision).
  - |move| ≥ m × sd → at the 09:30 ET bar open, trade against the move.
  - Stop = target = 1.5%, exit at 16:00 ET.
- **Configs.** m ∈ {0.25, 0.5, 0.75}, expecting about 850 / 560 / 340 trades per asset from the √(12/24)-scaled normal base rate (≈ 1,170 weekdays).
- **Against the mechanism.**
  - Report only: the same rule at the Asia open (decision at 20:30 ET, i.e. 09:30 Tokyo, against the 12h move before it, exit 03:00 ET). If it does as well, this is a generic 12h reversal, not about US liquidity.
  - BTC-only or ETH-only.
  - The gate fails for all m.

## Order and budget

1. b2 bootstrap: copies, manifests, sanity.
2. G1 (es_daily 3).
3. G4 (es_daily 3).
4. G2 (crypto 3).
5. G5 (crypto 3).
6. G3 (crypto 3).

That makes 15 configs, for a loop-wide total of ≤ 30 and a bar of p < 0.00167.

val2 approval: PENDING · crypto val approval: PENDING (unchanged).
