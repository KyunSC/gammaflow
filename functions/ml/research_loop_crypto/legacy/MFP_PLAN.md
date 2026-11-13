# MyFundedPerps: simulator plan and edge search

Written 2026-10-18 for Sunny's ask: add MyFundedPerps (MFP) to the backtester, and look for an edge on crypto or any other MFP market that beats a coin flip, with separate training and test data. An edge that only pays because of MFP's rules is acceptable.

Nothing is implemented yet. This file is the proposal; the questions at the end decide what gets built first.

## 1. The firm, as checked on 2026-10-18

Sources: [docs.myfundedperpetuals.com](https://docs.myfundedperpetuals.com/llms.txt) (Challenges and Rules, Elite Accounts, Payouts, Commissions and Fees, Trading Guide, Breaches, Tradable Assets), the [home page](https://myfundedperpetuals.com/) and the [terms](https://myfundedperpetuals.com/terms) (dated "September 2026"). Anything marked *third-party* came from [comparefuturesprop.com](https://comparefuturesprop.com/firms/myfundedperps) and is not confirmed by MFP.

**What it is.** It's a simulated perpetual-futures prop firm (formerly Funding Perpetuals, now part of the MyFundedFutures family). It has 122 markets: 66 crypto, 31 stocks, 7 indices, 6 FX and 12 commodities. Marks come from Hyperliquid, Binance, Ostium and Veranta. Crypto, gold, and NAS100/SP500 on Hyperliquid trade 24/7. There is a public trading API with a sandbox, and automated trading through it is allowed. Payouts only opened on 2026-09-11, so the firm has a short payout record.

**Plans (all 1-step, no minimum days, no time limit, all % of starting balance):**

| Plan | Sizes | Target | Static max loss | DLL | Floor after 1st payout | Price |
|---|---|---|---|---|---|---|
| Select | 10K–100K | 9% | 3% | 3% | locks at start | 50K $190 *third-party* |
| Prime | 10K–100K | 12% | 5% | 3% | locks at start | 50K $300 *third-party* |
| Signature | 10K–100K | 10% | 6% | 3% | locks at start | 50K $430 *third-party* |
| Elite 3% DLL | 5K/10K/25K/50K | 10% | 5% | 3% | never moves | $49/$95/$249/$495 list; home page sale $36/$71/$186/$371 |
| Elite No DLL | same | 10% | 5% | none | never moves | $89/$175/$449/$889 list |

**Rules the simulator must get right:**
- Target, max loss and DLL are all measured on **equity including open P&L**, monitored continuously. Hitting the target passes the evaluation and closes positions automatically. Touching a floor counts as a breach (the floor is inclusive).
- The **DLL is a hard fail**, not a flatten-for-the-day like Lucid's. The day starts at **midnight America/New_York**. The DLL floor is start-of-day equity minus 3% of starting balance.
- The drawdown is static and never trails. Elite's floor stays at start − 5% for life. The other plans lock the floor at the starting balance on the first withdrawal.
- **Payouts:** Elite is on demand from the first funded day, with no consistency rule and no profit-day rule. You must be flat. The minimum is 1% of size (gross). The split is 80/20, or 90/10 as a paid upgrade bought at checkout. The gross amount is deducted from the balance and the floor stays put. Profit left behind when a payout is approved becomes a buffer that can never be withdrawn. Non-Elite plans allow one request per NY day, $100 minimum. Lifetime cap is $100K per user after split. Funded allocation is capped at $100K for Elite and $300K across all plans.
- **Costs:** commission is per fill on notional. Crypto pays 3 bps, stocks/indices/commodities 0.5 bp, FX 0.25 bp, and Elite NAS100/SP500/Gold/WTI 0.1 bp. Swap is charged hourly at 1/24 of a daily rate: crypto 0.03%/day, stocks/indices/commodities 0.015%, Elite NAS100/SP500 0.01%. Longs and shorts pay the same. Venue funding rates are informational only, so **there is no funding carry to earn**.
- **Market-order slippage** is bounded, not fixed. Majors with OI above $500M get 0.8 / 1.2 / 2.0 bps for orders up to $100K / up to $500K / above that. Indices get 0.25–1.0 bp. Limit orders fill their full size at the limit price after two book checks.
- **Leverage and exposure caps:** BTC is up to 10×, ETH 8×, most alts 2–3×. Elite NAS100/SP500 are 40×, US30 25×, gold 20×, oil 10×. Long and short exposure add up rather than net.
- **Inactivity:** an evaluation fails after 30 days with no executed trade. A funded account closes after **7 days** with no trade. A slow strategy needs a cheap keep-alive trade.
- **News:** funded Elite only. No new exposure in the affected market from 10 to 2 minutes before a high-impact release, and no manual trades from 2 minutes before to 2 minutes after. Profit from those trades can be excluded. The docs don't say whether crypto counts as an "affected market".
- **Conduct (terms):** the terms ban exploiting latency, stale data or pricing errors, hedging across accounts, wash trading, HFT-style request patterns, and "abusive concentration or position sizing" to exploit the payout environment. Every payout is reviewed at MFP's discretion.

## 2. What the rules alone are worth (coin flip, no edge)

Script: [coin_flip_ev.py](coin_flip_ev.py), output in [coin_flip_ev_results.txt](coin_flip_ev_results.txt). It is a rough model: 1:1 brackets with p(win) = 0.5, cost `c` in R per round trip, size trimmed so no trade can jump a floor, and all profit withdrawn as soon as it reaches the minimum. It is not the real simulator.

With zero edge, a static 5% floor and a 10% target, a fair game passes about 1/3 of the time and then pays out about 5% of size in expectation (the floor). The 50K Elite 3% DLL is therefore worth about 0.8 × $2,500 / 3 ≈ **$667 gross to a coin flip**, before costs:

| cost per trade | 50K 3% DLL, 2.5% risk, 1 trade/day | same, 0.5% risk, 3/day | 50K No DLL, single 5% bet |
|---|---|---|---|
| 0 | +$297 at $371 sale / +$173 at $495 list | +$304 | −$236 at $889 |
| 0.02 R | +$205 / +$81 | −$19 | −$301 |
| 0.05 R | +$85 / −$39 | −$272 | −$359 |
| 0.10 R | −$68 / −$192 | −$360 | −$456 |

What follows from this:
1. **MFP Elite 3% DLL pays a coin flip more than Lucid did** (+$300 vs Lucid's ±$50), as long as costs are low and trades are few and large. The No-DLL version is −EV for a coin flip at list price. So "profitable only because of the prop firm" is real here. It is also exactly why "the account made money" proves nothing about a strategy.
2. **Costs decide almost everything.** A round trip as a fraction of R is round-trip bps divided by stop distance in bps:
   - BTC with a 1% stop costs about (6 + 2×1.2 + swap) / 100 ≈ **0.085 R**. A crypto coin flip is then roughly break-even (−$14 at the sale price).
   - Elite NAS100 with a 0.5% stop costs about (0.2 + 2×0.5) / 50 ≈ **0.025 R**.
   - So the same signal is worth far more on Elite indices than on crypto, and a crypto edge has to clear about 4 times the cost hurdle.
3. **Trade count is the enemy of a zero-edge strategy.** Small risk and many trades turn +$300 into −$270 at 0.05 R. Any strategy we test has to be compared with a coin flip that **trades at the same times and size**, not with zero.
4. **These numbers assume MFP pays.** The "big bets, few trades" sizing that maximizes the coin flip's value is also what the terms could call abusive concentration. Treat the structural +EV as real but discretionary.

## 3. Implementing MFP in the backtester

The current prop mode (`frontend/lib/backtest/prop/`) is built for CME futures with fixed contract counts, Lucid-style EOD trailing drawdown, a soft DLL, an 18:00 ET day and flat-at-close. MFP breaks each of those assumptions. Proposed changes:

**Instrument (engine.js, prop/index.js, new `prop/perps.js`):**
- A `perp` instrument kind. Size is set as notional, or derived from risk ÷ stop distance. Commission is bps per fill on notional, by asset class. Slippage is MFP's tier table, keyed on notional and an OI band per market. Hourly swap is charged on notional at every UTC hour boundary crossed while in a position.
- Leverage and exposure caps reject an order instead of resizing it, as MFP does.
- No forced flat-at-close for 24/7 markets. Weekend auto-close happens 15 minutes before a 24/5 market's Friday close.
- `propSetup` currently refuses anything that isn't NQ/ES. Perps would bypass the contract mapping.

**Rules (prop/firms.js, prop/account.js):**
- Per-firm sizes. MFP has 5K–100K; `SIZES` is currently global, 25K–150K.
- A `mfp` firm with plans Select, Prime, Signature and Elite (3% DLL and No DLL), with values in % of start.
- New rule modes in `runStage`:
  - `drawdown: 'static'` (threshold fixed at start − maxLoss) and `lockOnPayout: true|false` (Select/Prime/Signature vs Elite).
  - `dllMode: 'fail'` as well as Lucid's `'flatten'`.
  - `dayBoundary: 'ny-midnight'` as well as `'globex'` (today `tradingDay` = 22:00 UTC). This touches `buildDayTable` and `time.js`.
  - Pass and breach checks run intrabar on equity extremes. When one bar touches both the target and a floor, the floor wins (conservative), and the replay reports how often that happened.
  - Payout modes `'on-demand'` (any flat moment with profit ≥ 1% of size, withdraw all, a buffer forms if not) and `'daily'` (one per NY day). A lifetime cap.
  - An inactivity breach after 30 days in evaluation or 7 days funded with no fill.
  - An Elite funded news blackout using the calendar from PR #7, for index and commodity markets.
- The day table must be mark-to-market (equity including open positions), because MFP lets positions run overnight. Payouts are only allowed at points where the position is flat.

**Python mirror (`functions/ml/mfp_prop.py`).** Research scripts are in Python with the holdout guard, as in PRs #4–#6. The same day table should give the same outcome in JS and Python, pinned by a parity test on a handful of hand-built paths. Each rule gets one test: DLL fail, inclusive floor, static floor after a payout, buffer formation, inactivity, a bar that touches both target and floor, and the swap at midnight counting toward the previous day.

**UI.** Add MFP to the firm picker, a sale/list price override, and a coin-flip twin EV next to the strategy's EV in the prop panel.

Crypto in the JS backtester depends on draft PR #3 (24/7 ingestion, crypto calendar), which Sunny wanted to approve before merging. The Python study doesn't need it.

## 4. Data

- **Crypto: Binance USD-M perpetuals from data.binance.vision.** It's free, has monthly zips with checksums, and covers 1m klines for BTCUSDT and ETHUSDT from 2020-01 (SOLUSDT from 2020-09). Funding-rate history and the daily `metrics` files (open interest, long/short ratios) start in late 2021.
  - MFP doesn't say which venue marks crypto. Binance is one of its listed venues and is close enough for 1m research. Before trusting costs, compare a week of Hyperliquid candles against Binance; the expected difference is a few bps.
  - **The cloud sandbox can't reach data.binance.vision** (the proxy refused it). Two options: run the downloader on Sunny's machine, like the ThetaData files, or add `data.binance.vision` under Allowed domains in a cloud environment ([Project settings](#project-settings/environment) → Cloud environment → Add cloud environment).
  - The existing crypto rows in the database are gappy outside US hours and won't be used.
- **Databento credits (~$120) aren't needed for crypto.** Keep them. CME BTC/ETH futures exist there if a regulated-venue cross-check is wanted later.
- **Elite indices** would reuse the project's Databento NQ/ES and QQQ/SPY minute data as a proxy for the Hyperliquid NAS100/SP500 perps. That ignores perp basis and weekend trading.
- The downloader gets a coverage check. It refuses any month with less than 99.9% of the expected 1m bars and lists every hole, because gapped bars already distorted two earlier studies.

## 5. Candidate hypotheses (crypto)

Each one has an economic reason it might work. Each is written as a single spec before any data is loaded, with at most a small grid explored on training data only. Literature claims below are claims to test, not facts.

| # | Idea | Rule sketch | Why it might work | Cost exposure |
|---|---|---|---|---|
| C1 | Daily trend | Long/short BTC, ETH on a 20/50-day breakout, ATR stop, vol-scaled | Crypto time-series momentum is reported repeatedly (e.g. Liu & Tsyvinski 2021) | Few trades; swap 3 bp/day on held notional is the main cost |
| C2 | Funding crowding | Fade when Binance 8h funding is in the top/bottom 5% of its trailing 90 days; hold 24–72h | Crowded leveraged positioning unwinds | Moderate; signal uses real funding, which costs nothing at MFP |
| C3 | Liquidation-cascade reversal | After a 1h move > k × ATR with volume above the 99th percentile, fade with a stop past the extreme | Forced selling overshoots | Short holds; wide stops keep cost per R low |
| C4 | US-open range breakout | BTC 13:30–14:00 UTC range, trade the first close outside it, 2R | Equity-hours flow; ORB analogue | Intraday; tightest stops, so the highest cost per R |
| C5 | Weekend / CME gap | Trade toward the Friday CME close when BTC opens the CME week away from it | A popular claim that is easy to test | One trade a week; inactivity rule fine |

Expectation, stated plainly: most of these will fail like the equity ideas did. C4 has the worst odds because of the 3 bp commission. C1 and C2 have the best cost profile.

**Other MFP markets.** Elite NAS100/SP500/Gold cost about a quarter as much per R. But the project's index history is already spent or reserved: the research window runs to 2026-08-14, the sealed blocks are used, and the SPY 2025-03-27 → 2026-08-14 window is reserved for PR #5. So index ideas can only get a clean test on new data. Crypto is the one asset with years of history that nobody in this project has backtested. That makes it the best place for a historical train/test split, even with higher costs.

## 6. Training, validation and test

| Block | Dates (UTC) | Use |
|---|---|---|
| Train | 2020-01-01 → 2024-06-30 | Explore freely, with every run logged. Covers the 2020–21 bull, 2022 crash and 2023 recovery |
| Embargo | 7 days | Covers the longest hold (72h) plus slack |
| Validation | 2024-07-08 → 2025-06-30 | Cut candidates to **at most 3 frozen specs**. Up to 5 logged looks in total |
| Embargo | 7 days | |
| **Test (sealed)** | 2025-07-08 → 2026-09-30 | **One look.** All frozen specs scored together in one run |
| Forward | from the freeze date | MFP sandbox, then a real $36 5K Elite if the test passes |

- **Code guard.** The loader refuses dates on or after the test start unless `--score` is passed. `--score` checks each spec's hash (pinned by a test, like PR #4), runs once, and writes a looks log. A second `--score` refuses to run.
- **Honest caveat.** Sunny has probably seen BTC charts from 2025–26. Casual chart memory can't be undone, so the specs should come from the train block's evidence and the table above, not from what "worked lately".
- **Multiple testing.** α = 0.05 / K, where K = the number of specs × assets actually scored (at most 3 × 2 = 6, so α ≈ 0.008). The deflated Sharpe from stats.js is reported for the train-block winner, given how many configurations were tried there.
- **Power.** The test has about 450 days. At one 1:1 trade a day, the standard error of mean R is about 0.047, so the test can only confirm an edge over a coin flip of about **+0.12 R per trade or more**. Smaller edges may be real but this window can't show them. Low-frequency ideas (C1, C5) get even fewer trades, and their test is mostly about whether they lose. If the test fails, that window is spent for crypto and only forward data counts after that.

## 7. What "beats a coin flip" means here

This reuses PR #6's design, with one change for crypto's drift.
- **Twin.** Each strategy gets 2,000 coin-flip twins with the same entry times, the same stop and target distances, the same exit rules and the same sizes. Only the direction is random. The twin's **P(long) equals the strategy's own long share**. BTC rose more than tenfold over 2020–2026, so a fair coin would let any long-leaning rule "win" on beta alone. The fair-coin result is reported as well.
- **Two tests, both required, on the test block:**
  1. Mean net R per trade (MFP costs) above the twins: permutation p < α, and the 95% CI of the difference above 0.
  2. MFP Elite 50K 3% DLL **EV per evaluation above the twins' EV**, using block-bootstrapped account lifecycles from the test-block trades. EV > 0 alone doesn't count, because the twins have positive EV too (section 2).
- **Controls.** A planted look-ahead version must pass (it proves the test can detect an edge), and a pure coin flip must fail.
- **Verdicts:** BEATS-COIN-FLIP, or FAILS. A "prop-only" result is recorded for any strategy whose mean R loses to the twins but whose EV beats them. That would be an exit or sizing effect, and it gets no headline.

## 8. Forward step and risks

- If something passes, the next step is two to four weeks in the MFP API sandbox to measure real fills, slippage and swap against the model. After that comes one $36 5K Elite evaluation.
- **Counterparty risk.** The accounts are simulated, every payout is reviewed at the firm's discretion, and payouts have only existed since September 2026. Model a haircut (for example a 20% chance a payout is refused) as a sensitivity, not a headline.
- **Don't build on simulator quirks.** Limit orders that fill full size without queue position, or stale-mark windows, would make backtests look better and are banned by the terms. Research uses market orders at the published worst-case slippage.

## 9. Order of work (after Sunny's go)

Status (2026-10-18): Sunny picked both crypto and Elite indices. Step 1 is in draft PR gammaflow#9 (branch `claude/myfundedperps-plan-bhgwrf`). The Binance download runs on Sunny's machine. Screenshot: backtester-mfp-twins.png (in the project files). It shows the bundled QQQ sample at 1× notional on Elite 50K, where the coin-flip twins average **+$321 EV**, which is the section 2 effect showing up in the app.

1. PR A: `perp` instrument and MFP rule modes in JS, the Python mirror, the parity tests, and a coin-flip twin in the prop panel. This needs no new data.
2. PR B: Binance downloader with coverage checks and the holdout guard (run on Sunny's machine or after allowing the host). Then a train-block study of C1–C5, with every run logged.
3. Validation cut to at most 3 specs, then freeze and hash them. Sunny reviews the frozen specs before `--score`.
4. One `--score` run on the test block, with a write-up whatever the result.

## 10. Questions for Sunny

1. **Asset for the first study:** crypto BTC/ETH (recommended, because it has a clean historical test), Elite NAS100/SP500 (costs about a quarter as much, but forward data only), or both.
2. **Plan to model first:** Elite 3% DLL 50K (recommended; it is the plan with structural +EV), or all plans.
3. **Data download:** your machine, or add `data.binance.vision` to a cloud environment.
