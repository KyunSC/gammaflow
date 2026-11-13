# Free-data ideas loop — batch 3 proposal (written 2026-11-05 ~02:40 ET, before any batch-3 data was read)

Hashed into `data/research_loop_free/state.json` (`batch3_sha256`) in the same firing. Each idea still gets its own
`prereg/<id>.json` (exact rules, ≤ 3 configs, as below) and a count check before its run. No config is added later.

**Data:**
- Everything is on disk: Binance UM 1m klines (BTC, ETH; SOL report-only) and ES 1m continuous futures (the ES intraday evaluator's 5m bars).
- No new download, no features series.

**Evaluators:** fresh copies in `research_loop_free/b3/{crypto,es_intraday}/`, made the same way as batches 1–2
(`ATTEMPT_LIMIT` / `TRAIN_CONFIG_LIMIT` 10 each), bootstrapped in the next firing.

**Loop-wide bar:** batches 1–2 ran 29 configs, and batch 3 adds at most 9, for ≤ 38 and a bar of p < 0.0013. A result needs
p below its evaluator's bar and also below 0.05 / (total configs run loop-wide).

## How earlier results influenced this batch (disclosure)

- **Only 3 ideas, not about 7.** After removing every CLOSED_IDEAS family, every batch-1/2 idea, their variants, and their
  logged post-hoc reversals, I could find only three mechanisms I judge clearly distinct and backed by published work.
  - The others I considered and rejected as variants:
    - SKEW / VVIX levels: variants of G1/G4.
    - 4h volume-conditioned reversal: a variant of F7 and K2.
    - Treasury-auction-time moves: a variant of release fade/follow.
    - Same-hour periodicity on NQ: a third copy of H1.
    - Pre-FOMC drift: one-sided.
    - Crypto ETH-vs-BTC residual: a variant of the closed NQ/ES residual family.
  - I'd rather run fewer clean tests than pad the batch.
- **Costs.** Batch 1 showed tight ES brackets cost about 0.19R (F1). Crypto costs about 0.053R at a 1.5% bracket. The ES and crypto brackets below are therefore sized from the trailing range of the same holding window (ES), or 1.5% / one daily sd (crypto). The crypto evaluator's gate needs a median stop ≥ 1.5%.
- **Possible steering, disclosed.**
  - H3 (crypto time-series momentum) is a momentum idea, chosen after G3 showed the overnight crypto move tends to continue into the US session (G3 failed in the wrong sign).
  - I picked H3 from the published crypto-TSMOM literature (1–4 week lookbacks), and its horizon (7–28 days, daily hold) is not G3's 12h. Still, I can't rule out that G3 nudged the choice.
  - CLOSED_IDEAS also holds ES daily TSMOM (E1, research_loop_daily). I judge a crypto TSMOM test distinct because it is a different market with a different investor base. I'm noting it in case you disagree, as with G1 vs V3.
- **Directions.** H1 and H2 follow the published sign (same-slot continuation). H3 follows the past return. None is taken from a batch-1/2 sign.

## Ideas

### H3_crypto_tsmom: crypto train (BTC + ETH)

- **Mechanism.** Crypto returns show time-series momentum at 1–4 week horizons, attributed to slow-moving investor attention (Liu & Tsyvinski 2021). Follow the sign of the trailing L-day return for one day.
- **Rule.**
  - Daily decision on the 23:59 UTC 1m bar (closing at 00:00 UTC); entry at the 00:00 open.
  - r_L = c[s] / c[bar exactly L×86400 s earlier] − 1. No trade if that bar is missing or stale, or r_L = 0.
  - side = sign(r_L).
  - Stop = target = sd(last 30 complete-UTC-day log returns) × c[s], floored at 1.5% of c[s].
  - Time exit 86,280 s after entry (through the 23:57 bar), so the next day's decision is free.
- **Configs.** L ∈ {7, 14, 28}. About 1,600 trades per asset; one per day, with no overlap.
- **Against the mechanism.**
  - Report the long and short legs separately. If the long leg alone carries it (2020–21 bull), that is drift, not momentum. Side-matched twins already control this, but it is reported anyway.
  - Report only: an always-long control with the same bracket and exit.
  - BTC-only or ETH-only.
  - The gate fails for all L.

### H2_crypto_hour_periodicity: crypto train (BTC + ETH)

- **Mechanism.** Same-time-of-day return continuation (Heston, Korajczyk & Sadka 2010). Returns in a given intraday interval predict returns in the same interval on later days, because of periodic institutional trading and liquidity needs. Crypto has strong time-of-day volume cycles (Asia, Europe and US hand-offs, funding prints).
- **Rule.**
  - Hourly decision on each xx:59 UTC 1m bar; entry at the next hour's open.
  - For the coming UTC hour h: μ = mean over the previous N calendar days of that hour's log return (close of hh:59 vs close of the (hh−1):59 bar). Each day's value needs both bars present and not stale; need ≥ ⌈0.8N⌉ valid days.
  - side = sign(μ); no trade if μ = 0.
  - Stop = target = 1.5% of c[s].
  - Time exit 3,540 s after entry (through the hh:58 bar).
- **Configs.** N ∈ {1, 7, 30}. About 38,000 trades per asset (24 a day).
- **Against the mechanism.**
  - Report only: a previous-hour control. side = sign(the return of the hour just ended), same bracket. If it does as well, this is plain 1h momentum, not periodicity.
  - Report per-hour mean net R. If the effect sits only around funding prints (00/08/16 UTC), it is a funding-flow effect, not general periodicity.
  - BTC-only or ETH-only.
  - The gate fails for all N.

### H1_es_hour_periodicity: ES intraday dev (2011 → 2018)

- **Mechanism.** The same as H2 (Heston, Korajczyk & Sadka 2010) on the index future. Periodic institutional execution, such as VWAP and TWAP schedules, recurs at the same clock hour across days.
- **Rule.**
  - RTH hours starting at 10:00, 11:00, 12:00, 13:00, 14:00 and 15:00 ET (ET clock, evaluator 5m bars).
  - Decision on the 5m bar that closes at the hour start, H (bar mod = H − 5); market entry at the next open.
  - μ = mean over the previous N full (non-half-day) sessions of hour H's log return: the close of the bar ending at H+60 vs the close of the bar ending at H. A session with either bar missing doesn't count, and ≥ ⌈0.8N⌉ valid sessions are needed.
  - side = sign(μ); no trade if μ = 0.
  - Stop = target = mean of hour H's high−low range over the previous 20 valid sessions (≥ 16 needed).
  - Exit with `{"op": "exit"}` on the bar closing at H+55. That flattens at the next open, a 55-minute hold, so the next hour can trade. Hour 15:00 ends at the evaluator's flat slot (15:55).
  - No trades on half days or roll days.
- **Configs.** N ∈ {1, 5, 20}. About 11,000 trades (6 a session).
- **Against the mechanism.**
  - Report only: a previous-hour control. side = sign(the hour just ended), same bracket and exit. If it does as well, this is intraday momentum, not periodicity.
  - Report per-hour mean net R. If only the 15:00 hour carries it, that is the closed into-the-close momentum family.
  - The gate fails for all N.

## Order and budget

1. b3 bootstrap: copies, manifests, sanity (crypto, es_intraday).
2. H3 (crypto 3).
3. H2 (crypto 3).
4. H1 (es_intraday 3).

That makes 9 configs, for a loop-wide total of ≤ 38 and a bar of p < 0.0013.

val2 approval: PENDING · crypto val approval: PENDING (unchanged).
