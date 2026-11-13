# Crypto perp research loop: report (2026-11-03)

**Result: nothing passed.** All four new crypto-native hypotheses (K1–K4) failed the frozen train gate on BTC and ETH. No validation look was spent by the loop; one was later spent on K2 by user override (FAIL, see below). The test block was never touched. C4 (K0) was skipped because its approval is still PENDING.

Plan: `PLAN.md` (copy of `~/.claude/plans/crypto-perp-research-loop.md`). Log: `data/research_loop_crypto/LOG.md`, 28 firings over 2 runs. State: `data/research_loop_crypto/state.json`.

## What was built
- **Free data** (`data/research_loop_crypto/raw/`, nothing dated on or after 2025-07-08 was parsed):
  - Binance metrics (OI, ratios): BTC from 2020-09, ETH/SOL from 2021-12.
  - Premium, mark and index 1m.
  - Coinbase BTC/ETH/USDT-USD 5m; USDT-USD only from 2021-05.
  - Deribit DVOL hourly from 2021-03-24.
- **Frozen evaluator** `eval/`: a verbatim port of the MFP engine and prop code, with parity reproducing C4 BTC exactly (1,148 trades, +0.0821R, EV +$1,421).
  - The manifest digest is `820494e2…` and covers 5,627 files: code, tests and every train/validation data file.
  - Validation can only be read through the logged `open_block`.
  - An independent review found 8 issues; all were fixed before the freeze.
- **Controller** `controller.py`, with 12 tests:
  - The gate from the plan, per asset, needing both BTC and ETH.
  - Budget, spent-family and validation refusals.
  - A source token check, resume without duplicate rows, and a 4-cut truncation-invariance check on every train config.
  - Sanity: always-flat gives 0 trades, and random direction gives about −cost with gross R's CI covering 0 (8/8 runs).
- **Strategies** `strategies/k1…k4`. Each has synthetic tests (22 in all) and, for K2–K4, matches an independent brute-force reference exactly.

## Results (train; 8 of 10 configs used)

| # | Idea | Configs | BTC net R (twin p) | ETH net R (twin p) | Verdict |
|---|---|---|---|---|---|
| K1 | Coinbase premium (USDT- and basis-adjusted, US hours) → follow 24h | z 0.5 / 1.0 | +0.030 (0.12) / +0.014 (0.33) | +0.015 (0.18) / −0.001 (0.36) | FAIL; stronger z weaker |
| K2 | 4h move with rising OI → follow 24h | k 1.0 / 1.5 | +0.058 (0.12) / **+0.122 (0.028)** | +0.046 (0.14) / +0.082 (0.076, n=160) | FAIL; BTC near miss from longs in bull years |
| K3 | Extreme 1h taker imbalance, premium-filtered → follow 12h | Z 2 / 3 | +0.005 (0.049) / +0.010 (0.19, n=110) | +0.016 (0.014) / −0.057 (0.81, n=97) | FAIL; beats twins only by about the cost |
| K4 | DVOL/RV tertile → follow or fade N-day breaks, 48h | N 5 / 10 | +0.113 (0.25, n=98) / +0.055 (0.50, n=69) | −0.069 (0.43, n=105) / +0.003 (0.17, n=72) | FAIL; too few trades, regime luck |

Gate: ≥ 200 trades, side-matched twin p < 0.005, session CI low > 0, stress R > 0, no year > 40%, positive without the top 5, median stop ≥ 1.5%, and EV above the twins.

## K2 validation (after the loop, user override)
The user chose to run K2 on validation (2024-07-08 → 2025-06-30) despite its train FAIL: one look, both k, K=2, reading rules written first (`prereg/k2_oi_backed_validation_override.json`). **It failed on every cell:** BTC −0.038R / −0.116R (p 0.68 / 0.87), ETH −0.011R / −0.078R (p 0.43 / 0.72), EV below the twins everywhere. The best train cell became the worst, larger k was weaker, and BTC shorts lost again. The train near miss was noise plus long-side drift. Crypto validation looks used: 1 of 5.

## What we learned
- **Costs are not what binds at daily-ATR brackets.** Median stops ran 4.4–5.8%, so a round trip plus swap is only 0.017–0.037R, well under the plan's 1.5% floor scenario. Every candidate failed on signal strength.
- **The bull drift leaks into long-heavy books.** BTC twins earn up to +0.05R (K2, K4), and K2's best cell is long +0.27R against short −0.07R. Side-matched twins absorb the average drift, but not a candidate whose long share moves with the regime.
- **Most mechanisms are not ordered the way they predict.** K1 and K3 are weaker at the stricter threshold. Only K2 has the right ordering, and its edge is one-sided.
- **The EV criterion does not discriminate on its own.** Random books beat their twins' EV 3 times in 8.
- **The sources were thin for every idea.** No peer-reviewed test exists of the Coinbase premium, signed OI momentum, or hourly taker flow predicting crypto returns, and the closest crypto study (15m taker-flow reversal) points against K3.

## Spend
- `research_loop/CLOSED_IDEAS.md`: 4 rows (K1–K4).
- `research_loop/data_spend_ledger.json`: 4 `discovery` rows, BTC+ETH train windows.
- `data/binance/looks.jsonl`: train opens only (parity, sanity, K1–K4); **0 validation opens**.
- **Still unspent for crypto:** validation 2024-07-08 → 2025-06-30 (5 looks) and test 2025-07-08 → 2026-09-30 (sealed).

## What's left (needs Sunny)
1. **C4 validation:** change `C4 approval: PENDING` to `YES` in the plan to spend one validation look on C4 BTC+ETH at its a-priori config (stop = opposite, m = 2). It remains the only crypto thread that beat its twins on train in every year (MFP study). Its net R (+0.05–0.08) is thin against about 0.1R of cost.
2. **No test-block proposal:** nothing passed validation.
3. **Open threads not taken here:** the K4 follow-vs-fade arm split was not computed (report-only, time budget). K2's BTC long-side effect could only be checked on unseen data under a new prereg, and since its train data has been seen, it would have to be framed as a new hypothesis.
