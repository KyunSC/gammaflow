# MyFundedPerps crypto study: train-block results (C1–C5)

Run 2026-10-18 on the **train block only** (2020-01-01 → 2024-06-30 UTC, BTCUSDT and ETHUSDT 1m perps from data.binance.vision). The validation and test blocks were not opened. No Binance bar dated after 2024-07-01 was read, apart from the downloader's own coverage counts (bar counts and holes, no prices). Code: [mfp_crypto_study.py](mfp_crypto_study.py), tests: [test_mfp_crypto_study.py](test_mfp_crypto_study.py). Raw output: `data/mfp_crypto/train_results.json` (gitignored).

## Bottom line

- **Beats its twins on train, with both tests passing on both assets: C4 (US-open range breakout).** Its per-trade R beats the twins in every year on both BTC and ETH. Account EV beats the twins' EV on both assets (BTC +$1,570, ETH +$605 over twins).
- **That is still not an edge.**
  - Deflated for the 40 configs tried, the best result has DSR **0.51** (BTC) and 0.05 (ETH), far from 0.95.
  - Net R is thin: +0.08 R/trade on BTC and +0.05 R on ETH, against costs of 0.11 and 0.09 R.
  - BTC and ETH trade the same days, so they are close to one test, not two.
  - The plan rated C4 the *least* likely idea because of the 3 bp commission, so a train pass here deserves more suspicion, not less.
- **Weak, one asset only: C2 (funding crowding).**
  - BTC passes both tests: R p = 0.023, EV +$3,488 over twins with p = 0.010.
  - ETH fails both: R p = 0.37, EV p = 0.17.
  - DSR is 0.005. Most likely noise or a BTC-specific quirk.
- **Fail: C1 (daily trend).** Raw net R is positive (ETH +0.31 R/trade), but the twins with the same long share earn the same. This is the drift trap from plan §7: long-leaning rules "win" on BTC/ETH beta alone.
- **Fail, and worse than a coin flip: C3 (cascade fade) and C5 (CME weekend gap fill).** They lose to their twins with excess CIs below zero in most configs. The opposite directions (cascade momentum, gap continuation) would "beat" twins on train, but that is a post-hoc reading. It would need its own written spec and would spend validation looks.

Nothing here is frozen. Section 9 proposes what could go to validation; it needs your approval first.

## 1. What was run

**Block and looks.** Four train opens, all logged in `data/binance/looks.jsonl`:

| Time (UTC) | Run | Notes |
|---|---|---|
| 21:05 | smoke | crashed on a parameter-name bug before C3 ran |
| 21:06 | smoke | 200 twins |
| 21:09 | full run | |
| 21:19 | full rerun | after a dedupe refactor and the daily-DSR fix; every number other than DSR reproduced exactly |

The specs and grids were committed (`12a918e`) before the first open.

**Specs.** These are the §5 rule sketches made exact. The full rule text is in `SPECS` and goes into each hash.

| Spec | Rule | A-priori config | Grid (4 configs each) |
|---|---|---|---|
| C1 | Daily Donchian breakout. Stop k×ATR20, trailed off the best daily close. 60-day time exit | n=20, k=3 | n ∈ {20, 50}, k ∈ {2, 3} |
| C2 | Fade Binance funding beyond the q / 1−q quantile of the prior 270 prints. Stop 1×ATR20. Exit after h hours | q=0.05, h=72 | q ∈ {0.05, 0.10}, h ∈ {24, 72} |
| C3 | Fade an hour with \|move\| > k×ATR(168h) and volume above the 99th percentile of the prior 720h. Stop 0.25 ATR past the extreme. Target m× the stop. 24h exit | k=3, m=1 | k ∈ {2, 3}, m ∈ {1, 2} |
| C4 | 09:30–09:59 ET range. First 1m close outside it between 10:00 and 14:59 ET. Stop at the opposite side or the midpoint. Target m× the stop. Flat at 16:00 ET | opposite, m=2 | stop ∈ {opposite, mid}, m ∈ {1, 2} |
| C5 | Gap between Friday 16:59 ET and Sunday 18:00 ET above g×ATR20: trade toward the Friday level. Target \|G\|, stop s×\|G\|. Exit Friday 16:00 ET | g=0.5, s=1 | g ∈ {0.25, 0.5}, s ∈ {1, 2} |

**Configs tried: 40** (5 specs × 4 configs × 2 assets). That K is used for the deflated Sharpe.

One deviation from the plan: C4 uses the ET clock instead of a fixed 13:30 UTC, so the window follows the US cash open through DST. This was decided in the spec, before data.

**Execution.** Identical for every spec, its twins and the controls.

- **Orders:** market orders only. Entry is at the next 1m open. Stops and targets trigger on 1m highs and lows. A gapped stop fills at the bar open. When one bar touches both levels, the stop fills.
- **MFP Elite costs**, read from `flybrain/fixtures/mfp_markets.json`, which is exported from `frontend/lib/backtest/prop/perps.js` so the tables are not restated:
  - 3 bp commission per fill;
  - worst-case published slippage per fill notional: 0.8 / 1.2 / 2.0 bp;
  - 3 bp/day swap, charged at every UTC hour crossed;
  - no funding credited.
- **Sizing:** fixed risk of $500 per trade (1% of 50K), independent of the balance and capped at 10× (BTC) or 8× (ETH) of the start balance. The cap bound on 1 trade at most for the primaries, and on 7 for C4 `mid`.
- **One book per spec and symbol, mirror-flat.** Every signal is simulated both long and short. A new signal is taken only when both mirrors are flat, so the strategy and every twin share entry times, stop and target distances, exit rules and sizes exactly.

**Twin tests.**

- **R test:** 2,000 twins per config, each drawing every trade's side with P(long) equal to the strategy's own long share.
  - p = (1 + #twins ≥ strategy) / 2,001, so the floor is 0.0005.
  - The 95% CI is for the mean per-trade excess over the twins' expectation, from a moving-block bootstrap with blocks of 10 trades.
  - The fair-coin p (P(long) = 0.5) is reported alongside.
- **EV test:** Elite 50K 3% DLL at the $495 list price, through `flybrain/prop.py`, with 2,000 twins.
  - Each twin is replayed on the same 200 block-bootstrapped lifecycles as the strategy: 7-day blocks of NY days with a 4-year horizon.
  - Run for each spec's a-priori config and its train-best config (highest excess over twins).
  - Inactivity is not modelled. A slow book is assumed to place a keep-alive micro trade (about $0.70 each), the same for strategy and twins.

## 2. Data coverage

| | BTCUSDT | ETHUSDT | SOLUSDT (downloaded, not studied) |
|---|---|---|---|
| Months downloaded | 2020-01 → 2026-09, 81 | 2020-01 → 2026-09, 81 | 2020-10 → 2026-09, 72 |
| Gappy months (`*.gappy.parquet`) | none | none | **2022-02** (89.3%: 4,320 bars missing from 2022-02-26) and **2022-04** (93.3%: 2,880 bars missing from 2022-04-01). Left untouched |
| Funding months missing | none | none | none |
| Train bars | 2,365,920, every minute present | 2,365,920, every minute present | |

**Surprise 1: the archive pads outages with flat zero-volume bars.** Coverage is 100.0% with no timestamp gaps, but there are runs of zero-volume bars at the same moments on both symbols. These are exchange outages or maintenance, filled with placeholders:

| Start (UTC) | BTC | ETH |
|---|---|---|
| 2021-03-02 01:01 | 59 min | 59 min |
| 2022-05-28 16:40 | 35 min | 35 min |
| 2022-05-01 22:26 | 29 min | 29 min |
| 2023-09-12 08:34 | 19 min | 19 min |
| 2023-11-10 15:07 | **99 min** | — |

The downloader's 99.9% coverage check cannot see these. The study treats any run of 3 or more zero-volume bars as a hole (241 BTC and 145 ETH stale bars in train). Trades whose window touches one are flagged. Excluding the flagged trades changes no verdict (the "unholed p" column in the appendix):

| Spec | Flagged trades per config |
|---|---|
| C1 | 2–3 |
| C2 | 1–4 |
| C3 | 0–1 |
| C4, C5 | 0 |

`binance_fetch.py --check` should probably report zero-volume runs too. I did not change it.

**Surprise 2: funding history starts in 2020-01**, not late 2021 as the plan says. That date applies to the `metrics` files. So C2 has the full train block, less its 90-day warm-up.

## 3. Results, a-priori config of each spec

Net R is per trade after all costs. "Excess" is net R minus the twins' expectation on the same trades.

| Asset | Spec | Trades | Long share | Median hold | Cost (R) | Net R | Twins R | Excess [95% CI] | p (twins) | p (fair coin) |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | C1 | 39 | 0.69 | 396h | 0.050 | −0.043 | +0.059 | −0.105 [−0.431, +0.247] | 0.74 | 0.58 |
| BTC | C2 | 153 | 0.64 | 72h | 0.034 | +0.181 | +0.033 | +0.147 [+0.017, +0.265] | **0.023** | 0.003 |
| BTC | C3 | 158 | 0.54 | 0.4h | 0.109 | −0.248 | −0.116 | −0.129 [−0.227, +0.026] | 0.96 | 0.95 |
| BTC | C4 | 1,148 | 0.50 | 2.5h | 0.108 | +0.082 | −0.067 | +0.148 [+0.088, +0.205] | **0.0005** | 0.0005 |
| BTC | C5 | 54 | 0.39 | 15h | 0.028 | −0.254 | +0.002 | −0.256 [−0.423, −0.084] | 0.98 | 0.97 |
| ETH | C1 | 35 | 0.57 | 459h | 0.048 | +0.313 | +0.242 | +0.072 [−0.420, +0.469] | 0.37 | 0.23 |
| ETH | C2 | 158 | 0.61 | 72h | 0.026 | −0.016 | −0.042 | +0.026 [−0.155, +0.152] | 0.37 | 0.23 |
| ETH | C3 | 137 | 0.55 | 0.6h | 0.087 | −0.256 | −0.085 | −0.170 [−0.305, −0.041] | 0.99 | 0.98 |
| ETH | C4 | 1,156 | 0.50 | 2.2h | 0.089 | +0.051 | −0.043 | +0.094 [+0.028, +0.160] | **0.002** | 0.002 |
| ETH | C5 | 79 | 0.33 | 23h | 0.025 | −0.215 | −0.041 | −0.173 [−0.432, +0.024] | 0.95 | 0.97 |

All four C4 configs beat their twins on both assets, with p between 0.0005 and 0.04. They share the same entries, so they are not independent confirmations. All 40 rows are in the appendix.

## 4. By year (trades: net R / excess over twins)

| Asset | Spec (config) | 2020 | 2021 | 2022 | 2023 | 2024 H1 |
|---|---|---|---|---|---|---|
| BTC | C4 (opposite, m=2) | 257: +0.07 / +0.15 | 258: +0.05 / +0.08 | 251: +0.12 / +0.13 | 253: +0.06 / +0.19 | 129: +0.16 / +0.23 |
| ETH | C4 (opposite, m=2) | 261: +0.04 / +0.11 | 260: +0.05 / +0.05 | 252: +0.07 / +0.10 | 254: +0.02 / +0.09 | 129: +0.10 / +0.15 |
| BTC | C2 (q=0.05, h=72) | 21: +0.40 / +0.35 | 41: +0.08 / +0.02 | 33: +0.12 / +0.13 | 38: +0.17 / +0.23 | 20: +0.29 / +0.07 |
| ETH | C2 (q=0.05, h=72) | 32: −0.16 / −0.10 | 37: −0.09 / −0.13 | 34: −0.14 / −0.11 | 34: +0.11 / +0.32 | 21: +0.33 / +0.24 |
| BTC | C1 (n=20, k=3) | 9: +0.83 / +0.54 | 8: −0.12 / −0.07 | 8: −0.48 / −0.11 | 9: +0.02 / −0.31 | 5: −0.89 / −0.95 |
| ETH | C1 (n=20, k=3) | 9: +1.15 / +0.76 | 8: +0.03 / −0.15 | 6: +0.55 / +0.41 | 8: −0.45 / −0.67 | 4: +0.15 / −0.06 |
| BTC | C3 (k=3, m=1) | 42: −0.23 / −0.15 | 20: −0.27 / −0.21 | 32: −0.23 / −0.12 | 44: −0.28 / −0.11 | 20: −0.22 / −0.06 |
| BTC | C5 (g=0.5, s=1) | 16: −0.31 / −0.29 | 16: −0.09 / −0.09 | 9: −0.04 / −0.16 | 10: −0.44 / −0.40 | 3: −0.85 / −0.79 |

**C4:**
- Its excess over twins is positive in every year on both assets, across bull, crash and recovery. This is the only result here with that property.
- Its *net* R is small every year: ETH 2023 is +0.02.
- Extra fill cost of about 0.05 R per trade (for example, about 4 bp more round-trip slippage on an 80 bp stop) would put ETH at zero and leave BTC's net R at roughly +0.03 R.
- The twins pay the same costs, so the edge *over twins* survives extra cost, but the account result does not.

**C2:**
- BTC is mostly positive.
- ETH is negative in 2020–2022 and positive only from 2023.

**C1:** its gains are concentrated in 2020.

## 5. Elite 50K 3% DLL: EV per evaluation vs the twins

EV is at the $495 list price; the $371 sale price adds $124 to every row. "Censored" counts the 200 lifecycles still open in evaluation at the 4-year horizon.

| Asset | Spec (config) | Role | EV | Pass rate | P(payout) | Censored | Twins' mean EV | Twins 5–95% | EV − twins | p |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | C4 (opposite, m=2) | primary, best | **+1,421** | 0.59 | 0.51 | 0 | −149 | −365 to +167 | **+1,570** | **0.0005** |
| ETH | C4 (opposite, m=2) | primary, best | +526 | 0.44 | 0.34 | 0 | −79 | −334 to +295 | +605 | **0.010** |
| BTC | C2 (q=.05, h=72) | primary, best | +4,270 | 0.80 | 0.72 | 1 | +782 | −329 to +2,764 | +3,488 | **0.010** |
| ETH | C2 (q=.05, h=72) | primary | +55 | 0.31 | 0.21 | 9 | −165 | −470 to +497 | +219 | 0.17 |
| ETH | C2 (q=.05, h=24) | best | +411 | 0.39 | 0.30 | 12 | +54 | −475 to +1,289 | +357 | 0.19 |
| BTC | C1 (n=20, k=3) | primary | −289 | 0.18 | 0.11 | 58 | +202 | −484 to +1,542 | −491 | 0.69 |
| BTC | C1 (n=50, k=3) | best | +642 | 0.74 | 0.52 | 83 | −84 | −495 to +942 | +725 | 0.096 |
| ETH | C1 (n=20, k=3) | primary, best | +1,358 | 0.81 | 0.64 | 57 | +953 | −439 to +3,061 | +405 | 0.31 |
| BTC | C3 (k=3, m=1) | primary | −495 | 0.00 | 0.00 | 0 | −361 | −495 to +98 | −134 | 1.00 |
| BTC | C3 (k=3, m=2) | best | −490 | 0.01 | 0.01 | 0 | −278 | −483 to +145 | −212 | 0.97 |
| ETH | C3 (k=3, m=1) | primary | −495 | 0.00 | 0.00 | 0 | −170 | −493 to +723 | −325 | 1.00 |
| ETH | C3 (k=2, m=1) | best | −495 | 0.00 | 0.00 | 0 | −240 | −488 to +413 | −255 | 1.00 |
| BTC | C5 (g=0.5, s=1) | primary | −495 | 0.01 | 0.00 | 20 | +8 | −495 to +1,316 | −503 | 1.00 |
| BTC | C5 (g=0.25, s=2) | best | −495 | 0.00 | 0.00 | 4 | −415 | −495 to −57 | −80 | 1.00 |
| ETH | C5 (g=0.5, s=1) | primary | −495 | 0.01 | 0.00 | 6 | −66 | −492 to +1,149 | −429 | 1.00 |
| ETH | C5 (g=0.25, s=2) | best | −495 | 0.00 | 0.00 | 11 | −400 | −495 to +13 | −95 | 1.00 |

Reading this skeptically:

- **The firm pays coin flips here, as plan §2 predicted.** C1 ETH's twins average **+$953** and C2 BTC's twins +$782: a slow, large-R book with no edge is worth money at Elite. That is why C1 ETH's +$1,358 counts for nothing (p = 0.31).
- **High-frequency, high-cost twins are negative.** C4's twins are −$149 and −$79. The C4 EV lift comes from the per-trade excess compounding over about 255 trades a year, not from the account structure.
- **The EV figures include up to 4 years of funded payouts.** C2 BTC averages 6 payouts. They assume MFP pays every one. Payouts have existed only since 2026-09; see the counterparty haircut in plan §8.
- **Censoring is heavy for C1.** 57–83 of 200 lifecycles are still in evaluation after 4 years. Its EVs come from the resolved lifecycles only and are biased toward failures.

## 6. Controls

| Asset | Spec | Planted look-ahead: excess, p | Passes | One coin flip: excess, p | Share of 200 coin flips passing (p < 0.05 and CI > 0) |
|---|---|---|---|---|---|
| BTC | C1 | +0.643, 0.0005 | yes | −0.068, 0.65 | 0.055 |
| BTC | C2 | +0.453, 0.0005 | yes | −0.064, 0.79 | 0.025 |
| BTC | C3 | +0.313, 0.0005 | yes | +0.088, 0.14 | 0.040 |
| BTC | C4 | +0.653, 0.0005 | yes | +0.004, 0.46 | 0.035 |
| BTC | C5 | +0.704, 0.0005 | yes | +0.142, 0.14 | 0.050 |
| ETH | C1 | +0.685, 0.0005 | yes | −0.286, 0.93 | 0.045 |
| ETH | C2 | +0.498, 0.0005 | yes | −0.039, 0.69 | 0.030 |
| ETH | C3 | +0.375, 0.0005 | yes | +0.032, 0.35 | 0.005 |
| ETH | C4 | +0.673, 0.0005 | yes | +0.033, 0.16 | 0.020 |
| ETH | C5 | +0.519, 0.0005 | yes | +0.112, 0.15 | 0.035 |

- **The planted look-ahead takes the side of the price a quarter of the way into each trade's time-exit window.** It passes on all 10 primaries. The first version peeked a fixed 4 hours ahead and *failed* on C1, whose holds run 200–460h. A small, fixed leak cannot be seen on slow books with about 35 trades. That is a power limit, and it applies to any real C1 edge as well.
- **The coin flips pass at 0.5–5.5%**, consistent with α = 0.05.
- **EV controls on C4's book:**
  - The look-ahead makes $64,144 (BTC) and $58,474 (ETH) against twins of −$156 and −$78 (p = 0.0005), so it passes.
  - The coin flip makes −$213 against −$152 (BTC, p = 0.60) and +$225 against −$78 (ETH, p = 0.079), so it fails.

## 7. Multiple testing and deflated Sharpe

DSR is computed on **daily** R series: trade R summed by UTC exit day over all 1,643 train days, with zeros on days with no trade. Every config then has the same length. The 40 trial Sharpe ratios set the benchmark SR₀ = 0.109 per day, about 2.07 annualised. (A per-trade DSR, used in the first run, mixed books with 26 trades and books with 1,156 and was discarded.)

| Asset | Config | Daily Sharpe, net R (ann.) | DSR | Daily Sharpe, excess over twins (ann.) | DSR |
|---|---|---|---|---|---|
| BTC | C4 opposite, m=2 | 1.05 | 0.013 | 2.18 | **0.51** |
| BTC | C4 opposite, m=1 | 0.30 | 0.000 | 2.15 | 0.48 |
| ETH | C4 opposite, m=2 | 0.66 | 0.001 | 1.38 | 0.047 |
| BTC | C2 q=.05, h=72 | 0.94 | 0.004 | 0.88 | 0.005 |
| BTC | C2 q=.05, h=24 | 0.87 | 0.003 | 0.95 | 0.008 |
| every other config | | ≤ 0.71 | ≤ 0.001 | ≤ 1.67 | ≤ 0.14 |

- **DSR:** nothing reaches 0.95. SR₀ is high partly because the 40 trials are spread wide: C3 and C5 are strongly negative and C4's excess is strongly positive. That makes DSR conservative here, but it is the declared method.
- **Bonferroni over 40 configs (α = 0.00125):** only the BTC C4 configs clear it, at p = 0.0005, which is the floor that 2,000 twins can resolve. ETH C4 (p = 0.002) and BTC C2 do not.

## 8. What could still be wrong with C4

1. **Fill realism dominates.**
   - Net R is +0.05 to +0.08 R against costs of about 0.1 R.
   - Real stop slippage beyond MFP's published bound, Hyperliquid marks a few bps away from Binance, or a lag between a 1m close and a market order would erase the net figure.
   - The edge over twins would survive, since twins pay the same costs, but the account would not.
   - MFP's sandbox (plan §8) is the only way to measure this.
2. **BTC and ETH are one bet.** They break the same way on most days, so the two "passes" are not independent.
3. **US market holidays are traded.** The window follows the clock, not the NYSE calendar. That is a small and harmless spec simplification.
4. **The prior said C4 was the worst idea** because of the cost hurdle, and the train block disagrees. A small directional effect after the US open (intraday momentum) is plausible. A bug-shaped result is too, so the code was checked: the range closes at 10:00, signals use completed bars and entry is at the next open. The planted look-ahead shows the tests can see leaks; it cannot rule one out.
5. **Power in validation is limited.** About 255 trades/year with a per-trade R sd of about 1.2 gives an SE of about 0.075 R over 358 days. A true excess of +0.15 R would show at about t = 2. A smaller true effect would probably fail validation even if it is real.

## 9. Proposed for validation (NOT frozen; needs your approval)

Plan §6 allows at most 3 frozen specs and up to 5 validation looks. These are proposals, not freezes. I recommend the **a-priori** configs, which were picked before any data, rather than train-best:

| # | Spec, asset | Config | Hash (spec only) | Why |
|---|---|---|---|---|
| 1 | C4, BTC | stop=opposite, m=2 | `422d4919183d40e8` | Passes both tests, positive excess every year, clears Bonferroni |
| 2 | C4, ETH | stop=opposite, m=2 | `422d4919183d40e8` | Passes both tests, but it is mostly the same bet as #1 |
| 3 | C2, BTC (optional) | q=0.05, h=72 | `66d2fbfd05186920` | Passes on BTC only, DSR about 0; include only if a third α slice is worth spending |

- The freeze step should hash spec + symbol + code version. The current hash covers the rule, parameters and execution, not the symbol.
- With all three, K = 3 and α ≈ 0.017. Dropping C2 gives K = 2 and α = 0.025.

C1, C3 and C5 should be closed as failed on train.

## 10. Reproduce

```
python functions/ml/binance_fetch.py            # once; ~860 MB in data/binance (gitignored)
python functions/ml/mfp_crypto_study.py          # ~10 min on 9 workers; logs one train open
python -m pytest functions/ml/test_mfp_crypto_study.py
```

## Appendix: every config (R test)

"Unholed p" re-runs the twin test without trades whose window touches a data hole.

| Asset | Spec | Config | A-priori | Trades | Long | Hold (h) | Cost (R) | Net R | Twins R | Excess | 95% CI | p | Fair-coin p | Unholed p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | C1 | n=20, k=2 | | 48 | 0.65 | 229.7 | 0.057 | +0.408 | +0.248 | +0.162 | [−0.246, +0.384] | 0.214 | 0.147 | 0.261 |
| BTC | C1 | n=20, k=3 | * | 39 | 0.69 | 396.4 | 0.050 | −0.043 | +0.059 | −0.105 | [−0.431, +0.247] | 0.737 | 0.580 | 0.424 |
| BTC | C1 | n=50, k=2 | | 37 | 0.73 | 218.2 | 0.047 | +0.117 | +0.219 | −0.108 | [−0.575, +0.139] | 0.699 | 0.569 | 0.673 |
| BTC | C1 | n=50, k=3 | | 29 | 0.76 | 403.6 | 0.061 | +0.254 | +0.037 | +0.215 | [+0.051, +0.367] | 0.104 | 0.102 | 0.078 |
| BTC | C2 | q=0.05, h=24 | | 283 | 0.61 | 24.0 | 0.023 | +0.083 | −0.001 | +0.085 | [+0.016, +0.150] | 0.015 | 0.005 | 0.020 |
| BTC | C2 | q=0.05, h=72 | * | 153 | 0.64 | 72.0 | 0.034 | +0.181 | +0.033 | +0.147 | [+0.017, +0.265] | 0.023 | 0.003 | 0.022 |
| BTC | C2 | q=0.1, h=24 | | 418 | 0.62 | 24.0 | 0.023 | +0.047 | −0.002 | +0.048 | [−0.009, +0.098] | 0.055 | 0.021 | 0.060 |
| BTC | C2 | q=0.1, h=72 | | 215 | 0.65 | 72.0 | 0.034 | +0.109 | +0.030 | +0.079 | [−0.033, +0.159] | 0.118 | 0.038 | 0.103 |
| BTC | C3 | k=2, m=1 | | 255 | 0.55 | 0.5 | 0.103 | −0.296 | −0.118 | −0.179 | [−0.263, −0.064] | 0.999 | 1.000 | 0.999 |
| BTC | C3 | k=2, m=2 | | 248 | 0.55 | 0.8 | 0.106 | −0.302 | −0.128 | −0.173 | [−0.281, −0.038] | 0.988 | 0.993 | 0.996 |
| BTC | C3 | k=3, m=1 | * | 158 | 0.54 | 0.4 | 0.109 | −0.248 | −0.116 | −0.129 | [−0.227, +0.026] | 0.955 | 0.946 | 0.962 |
| BTC | C3 | k=3, m=2 | | 154 | 0.55 | 0.8 | 0.112 | −0.250 | −0.125 | −0.125 | [−0.261, +0.058] | 0.915 | 0.900 | 0.927 |
| BTC | C4 | opposite, m=1 | | 1148 | 0.50 | 1.2 | 0.107 | +0.017 | −0.107 | +0.124 | [+0.074, +0.170] | 0.0005 | 0.0005 | 0.0005 |
| BTC | C4 | opposite, m=2 | * | 1148 | 0.50 | 2.5 | 0.108 | +0.082 | −0.067 | +0.148 | [+0.088, +0.205] | 0.0005 | 0.0005 | 0.0005 |
| BTC | C4 | mid, m=1 | | 1148 | 0.50 | 0.3 | 0.202 | −0.125 | −0.202 | +0.076 | [+0.020, +0.131] | 0.003 | 0.005 | 0.003 |
| BTC | C4 | mid, m=2 | | 1148 | 0.50 | 0.6 | 0.203 | −0.062 | −0.186 | +0.124 | [+0.056, +0.186] | 0.0005 | 0.0005 | 0.0005 |
| BTC | C5 | g=0.25, s=1 | | 112 | 0.35 | 10.3 | 0.042 | −0.222 | −0.032 | −0.189 | [−0.363, −0.036] | 0.987 | 0.974 | 0.987 |
| BTC | C5 | g=0.25, s=2 | | 112 | 0.35 | 16.5 | 0.024 | −0.195 | −0.066 | −0.129 | [−0.248, −0.036] | 0.992 | 0.978 | 0.992 |
| BTC | C5 | g=0.5, s=1 | * | 54 | 0.39 | 15.3 | 0.028 | −0.254 | +0.002 | −0.256 | [−0.423, −0.084] | 0.978 | 0.969 | 0.978 |
| BTC | C5 | g=0.5, s=2 | | 54 | 0.39 | 32.2 | 0.018 | −0.187 | −0.037 | −0.150 | [−0.268, −0.023] | 0.978 | 0.964 | 0.978 |
| ETH | C1 | n=20, k=2 | | 46 | 0.65 | 206.7 | 0.041 | +0.375 | +0.380 | −0.005 | [−0.620, +0.336] | 0.515 | 0.252 | 0.684 |
| ETH | C1 | n=20, k=3 | * | 35 | 0.57 | 459.1 | 0.048 | +0.313 | +0.242 | +0.072 | [−0.420, +0.469] | 0.367 | 0.229 | 0.425 |
| ETH | C1 | n=50, k=2 | | 33 | 0.79 | 198.6 | 0.041 | +0.410 | +0.409 | +0.002 | [−0.446, +0.524] | 0.510 | 0.167 | 0.810 |
| ETH | C1 | n=50, k=3 | | 26 | 0.73 | 467.5 | 0.050 | +0.282 | +0.275 | +0.006 | [−0.333, +0.412] | 0.499 | 0.212 | 0.482 |
| ETH | C2 | q=0.05, h=24 | | 275 | 0.61 | 24.0 | 0.018 | +0.008 | −0.021 | +0.029 | [−0.070, +0.099] | 0.238 | 0.154 | 0.309 |
| ETH | C2 | q=0.05, h=72 | * | 158 | 0.61 | 72.0 | 0.026 | −0.016 | −0.042 | +0.026 | [−0.155, +0.152] | 0.370 | 0.235 | 0.385 |
| ETH | C2 | q=0.1, h=24 | | 414 | 0.59 | 24.0 | 0.019 | −0.017 | −0.018 | +0.001 | [−0.070, +0.060] | 0.485 | 0.369 | 0.558 |
| ETH | C2 | q=0.1, h=72 | | 217 | 0.60 | 72.0 | 0.027 | −0.075 | −0.033 | −0.041 | [−0.166, +0.066] | 0.745 | 0.637 | 0.768 |
| ETH | C3 | k=2, m=1 | | 244 | 0.59 | 0.5 | 0.085 | −0.214 | −0.084 | −0.131 | [−0.237, −0.034] | 0.982 | 0.975 | 0.982 |
| ETH | C3 | k=2, m=2 | | 240 | 0.59 | 0.9 | 0.086 | −0.181 | −0.011 | −0.171 | [−0.297, −0.056] | 0.986 | 0.982 | 0.986 |
| ETH | C3 | k=3, m=1 | * | 137 | 0.55 | 0.6 | 0.087 | −0.256 | −0.085 | −0.170 | [−0.305, −0.041] | 0.986 | 0.979 | 0.986 |
| ETH | C3 | k=3, m=2 | | 137 | 0.55 | 0.9 | 0.089 | −0.211 | −0.008 | −0.204 | [−0.377, −0.064] | 0.977 | 0.974 | 0.977 |
| ETH | C4 | opposite, m=1 | | 1156 | 0.50 | 1.1 | 0.088 | −0.003 | −0.088 | +0.086 | [+0.030, +0.141] | 0.002 | 0.002 | 0.002 |
| ETH | C4 | opposite, m=2 | * | 1156 | 0.50 | 2.2 | 0.089 | +0.051 | −0.043 | +0.094 | [+0.028, +0.160] | 0.002 | 0.002 | 0.002 |
| ETH | C4 | mid, m=1 | | 1156 | 0.50 | 0.3 | 0.165 | −0.114 | −0.165 | +0.051 | [−0.007, +0.107] | 0.041 | 0.047 | 0.041 |
| ETH | C4 | mid, m=2 | | 1156 | 0.50 | 0.6 | 0.166 | −0.039 | −0.132 | +0.093 | [+0.022, +0.165] | 0.008 | 0.007 | 0.008 |
| ETH | C5 | g=0.25, s=1 | | 131 | 0.39 | 15.5 | 0.031 | −0.177 | −0.035 | −0.142 | [−0.371, +0.043] | 0.961 | 0.963 | 0.961 |
| ETH | C5 | g=0.25, s=2 | | 131 | 0.39 | 24.4 | 0.018 | −0.121 | −0.064 | −0.055 | [−0.162, +0.052] | 0.859 | 0.886 | 0.859 |
| ETH | C5 | g=0.5, s=1 | * | 79 | 0.33 | 22.9 | 0.025 | −0.215 | −0.041 | −0.173 | [−0.432, +0.024] | 0.945 | 0.967 | 0.945 |
| ETH | C5 | g=0.5, s=2 | | 79 | 0.33 | 54.8 | 0.015 | −0.153 | −0.052 | −0.101 | [−0.220, +0.011] | 0.954 | 0.981 | 0.954 |
