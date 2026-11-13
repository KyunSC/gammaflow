# Crypto perp research loop (MyFundedPerps Elite, BTC / ETH / SOL)

## Context
- Two research loops on CME index futures found nothing:
  - ES (`functions/ml/research_loop/`): 8 configurations.
  - NQ (`functions/ml/research_loop_nq/`): 6 configurations.
  - About 37 hypotheses have now been tried on the ES/NQ tape.
- Crypto is the one asset with years of history that has only been touched lightly:
  - The MFP study (branch `claude/myfundedperps-plan-bhgwrf`, PR #9, `functions/ml/MFP_TRAIN_RESULTS.md`) ran 40 configurations on the **train block only**.
  - The CHoCH study (C6) added 8 configurations on train.
  - **Validation and test have never been opened.**
- One thread is parked, waiting for Sunny's approval: **C4, the US-open range breakout** (stop = opposite side, m = 2, spec hash `422d4919183d40e8`).
  - It beat side-matched twins on BTC and on ETH, in every train year.
  - Net R was only +0.05 to +0.08, against costs of about 0.1R.
- This loop does two things:
  1. Validates C4 under a frozen evaluator, if approved (see Decisions).
  2. Looks for new crypto-native families that use **free derivatives data the earlier study did not have**: open interest, taker flow, perp premium, Coinbase spot and DVOL.

Everything in the ES plan (`~/.claude/plans/can-you-review-this-peppy-moon.md`) applies unless changed below. That includes the frozen-evaluator rules, the side-matched twins, the stop conditions and the "never inside the loop" list.

## Decisions
- **Billing:** the loop runs in a Claude Code chat via `/loop`, with no nested `claude -p` or SDK calls.
- **Venue and container:** MFP Elite 50K, 3% DLL. Figures are from `MFP_PLAN.md` §1, checked 2026-10-18; re-check them at bootstrap.
  - Costs: 3 bp commission per fill on notional; 0.8 bp slippage per fill for majors under $100K; 3 bp/day swap, charged hourly (1/24 of the daily rate at every UTC hour crossed); no funding credited.
  - Exposure caps: BTC 10×, ETH 8×, SOL per the current MFP table.
- **Cost rule (important):** a round trip costs about 7.6 bp plus swap.
  - A 1% stop therefore costs about 0.08R, and 0.05R needs a stop of about 1.5%.
  - **No idea may use a median stop under 1.5% of price.** That means holds of hours to days, never 1m scalps.
  - Each prereg states the expected cost in R at its median stop and hold.
- **Blocks:** the same as MFP (UTC):

  | Block | Dates | Rules |
  |---|---|---|
  | Train / dev | 2020-01-01 → 2024-06-30 | Already used for 48 configurations |
  | Validation | 2024-07-08 → 2025-06-30 | **At most 5 logged looks in total**, shared by every candidate in this loop |
  | Test | 2025-07-08 → 2026-09-30 | Sealed. **One look**, for all survivors together, and only with Sunny's approval |

  - The loader refuses dates on or after the test start, exactly like MFP's `--score` guard.
  - Forward data after 2026-09-30 is reserved for the MFP sandbox.
- **Gate:**
  - **Train:** ≥ 200 trades per asset; side-matched twin p < 0.005; mean net R > 0 with session-bootstrap CI low > 0; stress R > 0; no year > 40% of P&L; still > 0 without the top 5 trades.
  - **BTC and ETH must both pass**, since they are close to one bet; SOL is reported only.
  - **Validation:** ≥ 100 trades; twin p < 0.05 / K, where K is the number of candidates sent to validation; net R > 0.
  - **Both stages also need MFP Elite 50K EV above the twins' EV**, using `flybrain/prop.py` with MFP plans, as in the MFP study. EV > 0 alone does not count, because coin flips earn about +$300 at Elite.
- **C4 approval: PENDING.** Change this line to `C4 approval: YES` to let the loop spend one validation look on C4 BTC and ETH at the a-priori config. No train re-runs and no spec changes are allowed. Leave it PENDING and the loop skips C4.

## Data
**On disk** (`functions/ml/data/binance/um/`): klines-1m and funding for BTCUSDT, ETHUSDT and SOLUSDT, 2020-01 → 2026-09.
- Outage bars are padded with zero volume. Treat any run of 3 or more zero-volume bars as a hole (MFP §2).
- SOL has gaps in 2022-02 and 2022-04.

**Free additions, fetched at bootstrap.** All were checked from this machine on 2026-11-03; none needs a key.

| Source | What | From | URL |
|---|---|---|---|
| Binance public data `metrics` (daily zips) | 5m open interest, top-trader and global long/short ratios, taker buy/sell volume ratio | 2020-09-01 (check for gaps) | `data.binance.vision/data/futures/um/daily/metrics/<SYM>/` |
| Binance `premiumIndexKlines`, `markPriceKlines`, `indexPriceKlines` (monthly) | 1m perp premium vs index, mark price | like klines | `data.binance.vision/data/futures/um/monthly/...` |
| Coinbase Exchange candles | BTC-USD, ETH-USD and USDT-USD spot 1m (300 bars per call; throttle to ≤ 3 req/s) | 2020-03 verified | `api.exchange.coinbase.com/products/<P>/candles` |
| Deribit `public/get_volatility_index_data` | DVOL (30-day implied vol), BTC and ETH, hourly | 2021-03-24 | `www.deribit.com/api/v2/public/` |
| Hyperliquid `info` API + websocket | Candles and funding on the venue MFP marks crypto against; forward and paper only | recent | `api.hyperliquid.xyz/info` |

- Store everything under `functions/ml/data/research_loop_crypto/raw/<source>/`.
- Write a fetch log with every URL, the row counts and the SHA-256 of each file.
- The downloader must never read a row dated on or after 2025-07-08 for anything other than a row count.

## Layout
- **Parallel-safe shared writes:** other loops may be running at the same time.
  - Every write to `research_loop/CLOSED_IDEAS.md` or `research_loop/data_spend_ledger.json` (and to `data/binance/looks.jsonl`) takes an exclusive `fcntl.flock` on `functions/ml/research_loop/.shared.lock`, re-reads the file under the lock, appends its own rows only, and writes atomically (temp file + `os.replace`). Never rewrite or reorder rows written by other loops.
  - Cap worker processes at 3 for twin and permutation runs.
- `functions/ml/research_loop_crypto/`: `PLAN.md`, `fetch_free.py`, `eval/`, `tests/`, `controller.py`, `prereg/`, `strategies/`, `ledger.jsonl`, `REPORT.md`, and `legacy/`.
  - `legacy/` holds `mfp_crypto_study.py`, its tests, `flybrain/prop.py` with the MFP plans and the fixtures. Extract them read-only with `git show claude/myfundedperps-plan-bhgwrf:<path> > legacy/<file>`. Never check out, merge or commit.
- State: `functions/ml/data/research_loop_crypto/` holds `state.json`, `LOG.md`, `runs/` and `raw/`.
- Shared with the ES/NQ loops: `research_loop/CLOSED_IDEAS.md` and `research_loop/data_spend_ledger.json`, with rows tagged with the market.
  - Also append every block open to `data/binance/looks.jsonl`, which MFP already uses.
- Run from `functions/ml` with `../../.venv/bin/python -B`.

## Evaluator (step 2)
- Port the MFP execution model:
  - Next-1m-open market entries.
  - Stop and target triggered on 1m highs and lows; when one bar touches both, the stop fills; a gapped stop fills at the bar open.
  - Fixed $500 risk per trade, under the exposure caps.
  - Hourly swap.
  - Mirror-flat books: every signal is simulated long and short, and a new signal is taken only when both mirrors are flat.
  - Side-matched permutation twins.
  - The Elite EV test.
- Signals see only completed bars. Every feature series (OI, ratios, premium, Coinbase, DVOL) is joined **as of its publish time**:
  - A 5m metrics row stamped t counts only after t + 5m.
  - DVOL hourly counts at the hour's end.
- Tests:
  - A planted look-ahead must pass and a coin flip must fail (as in MFP §6).
  - Each feature join must show no look-ahead.
  - Zero-volume holes must be flagged.
  - The block guard must refuse test dates.
- **Parity:** the evaluator must reproduce MFP's C4 BTC train numbers (1,148 trades, net +0.082R) within rounding before it is frozen. If it does not, stop and log the difference; do not "fix" either side.
- Review with one independent subagent, then freeze with a manifest (code, tests, the hashes of every raw file in train and validation, and library versions).

## Candidate queue (step 4a refines it; every prereg needs a mechanism and sources)
Closed on crypto, so do not re-propose:
- C1 daily Donchian trend
- C3 volume-spike cascade fade, and its post-hoc reverse
- C5 CME weekend gap
- C6 CHoCH
- Everything in `CLOSED_IDEAS.md`

C2 (funding fade) passed on BTC only. It is not closed, but anything funding-like must say why it differs from C2.

| # | Idea | Mechanism and sources to check | Data | Notes |
|---|---|---|---|---|
| K0 | **C4 validation** (only if approved) | Already specified. Intraday momentum after the US equity open | on disk | 1 validation look; no train re-run |
| K1 | **Coinbase premium**: the sign and size of the Coinbase BTC-USD spot vs Binance perp gap (USDT-adjusted) over US hours predicts the next 4–24h | US spot order flow leads offshore perps. Sources: Makarov & Schoar 2020 (JFE, cross-exchange deviations driven by order flow); Alexander & Heck 2020 (price discovery across crypto venues) | Coinbase + Binance | Must adjust for USDT/USD. 2024 ETF creations are a regime change; report pre- and post-2024-01 |
| K2 | **OI-backed moves**: a 4h move with rising OI (new positioning) continues; the same move with falling OI (covering or liquidation) does not, so trade only the first | Futures volume/OI literature (Bessembinder & Seguin 1993); crypto leverage-cycle work. Differs from C3: there is no volume spike and no fade, and it is conditioned on positioning | metrics 2020-09+ | Train starts at 2020-09 + warmup. Check that the OI series has no gaps |
| K3 | **Taker-flow exhaustion vs continuation**: an extreme 1h taker buy/sell ratio, filtered by premium, then hold 8–24h | Order-flow imbalance persistence (Chordia & Subrahmanyam 2004; Cont, Kukanov & Stoikov 2014), with a perp-specific twist | metrics + premiumIndex | Pick the direction from the sources before any data |
| K4 | **DVOL vs realized regime**: implied far above or below realized selects breakout vs fade on daily-range extremes | Variance-risk-premium literature for BTC (e.g. Alexander & Imeraj on the BTC VRP) | Deribit DVOL 2021-03+ | Short train (2021-04 → 2024-06); fewer trades |

Rejected **a priori by costs**, logged here so they are not re-proposed: funding-settlement scalps (sell T−60m into 00/08/16 UTC) and BTC→alt 1m lead-lag. The effects reported are a few bp, against 7.6 bp per round trip.

**Budget:** 10 train configurations in total (about 3 hypotheses × ≤3 variants) plus ≤ 5 validation looks. Say in each prereg whether each parameter is fixed or selected.

## Running it with /loop
```text
/loop Run one iteration of the crypto perp research loop defined in /Users/sunnychen/.claude/plans/crypto-perp-research-loop.md (section "Running it with /loop"). Read functions/ml/data/research_loop_crypto/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy this plan to `research_loop_crypto/PLAN.md`.
   - Extract `legacy/`.
   - Re-check the MFP cost and plan figures on docs.myfundedperpetuals.com. Log any change; if costs went up, recompute the 1.5% rule.
2. **Fetch free data** (one source per firing): metrics → premium/mark/index → Coinbase → DVOL.
   - Write coverage reports: holes, zero-volume runs and first dates.
3. **Build the evaluator:** (a) port it and run parity, (b) review subagent, (c) freeze.
4. **Build the controller and run the sanity checks:**
   - Always-flat gives 0 trades.
   - Random direction gives ≈ −cost.
   - Kill and resume leaves no duplicate rows.
   - A one-byte change is refused.
5. **Per candidate,** one firing per sub-step: (a) prereg, (b) implement, (c) train, (d) validation only after a train pass (or directly for K0), (e) decision.
   - On a rejection, update `CLOSED_IDEAS.md` and the spend ledger.
6. **Report:** `REPORT.md`, one memory and its MEMORY.md pointer. Then stop.
   - If anything passes validation, the report proposes the single test look and the MFP sandbox plan, and stops for approval.

**Stop conditions:**
- 10 train configurations or 5 validation looks used.
- 150 active minutes (the fetch steps are slow).
- The queue is empty.
- Anything needs approval: the test block, a paid source, or changing the C4 spec.
- The same step has failed 3 times.

**Never inside the loop:**
- Open the test block.
- Edit `eval/` after the freeze.
- Re-run C4 on train or change its spec.
- Buy data.
- Commit or push.
- Lower the criteria.
- Open `.env` files.
- Check out or merge the MFP branch.

**Forward step (outside the loop, after a test pass):** two to four weeks in the MFP API sandbox, logging fills against the model, then one $36 5K Elite evaluation.
