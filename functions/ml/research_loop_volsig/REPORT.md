# Options-signal futures research loop: report (2026-11-03)

Plan: `research_loop_volsig/PLAN.md` (copy of `~/.claude/plans/volsignal-futures-research-loop.md`). Log: `data/research_loop_volsig/LOG.md` (20 iterations, 00:49–02:28 ET, about 61 active minutes). State: `data/research_loop_volsig/state.json`.

**Result: nothing passed.** All three ideas failed the frozen dev gate:
- V1: QQQ call-minus-put IV spread innovation → MNQ afternoon.
- V2: QQQ 25Δ skew-shock fade → MNQ.
- V3: VIX/VIX3M slope change → MES session.

Each one's gross edge was zero or below its cost (about 0.04R), and none beat side-matched random-direction twins (p ≥ 0.29). The loop stopped on its 10-configuration budget. **val1 (2019–21), val2 (2022–26) and the holdout were never opened**, for any of the three.

## 1. Setup

### Data (steps 1–2)
- **ThetaData iv_5m:**
  - Coverage: QQQ 2016-01-04 → 2026-10-23 (2,718 days), SPY 2017-01-03 → (2,466 days); every ES session has a file.
  - **Timestamps:** a row stamped T is a **snapshot at T**. Its `underlying_price` matches futures as of T: correlation 0.993–1.000 at lag 0 vs ≤ 0.86 at ±1 min. The review confirmed this to within about 2 s on trade prints and on 21 dates across DST changes. So the row belongs to the futures 5m bar that *ends* at T.
  - The 09:30 row is unusable: empty from 2019, stale before that.
- **Features** (`build_features.py`, frozen parquet per ETF):
  - Each day uses one expiry: the nearest with DTE ≥ 7.
  - Per 5m slot: ATM IV (strike-interpolated at S), the call − put ATM IV spread, and 25Δ put − call skew (interpolated in own-IV BS delta, OTM only).
  - Coverage: 0 missing values on QQQ dev, and 0.06% missing ATM over the whole series.
- **Cboe daily CSVs:** VIX, VIX9D, VIX3M, VVIX, SKEW, hashed.
  - `bar['daily']` = closes dated the **previous ES session**.
  - Not "latest Cboe row before today": VIX has rows on CME holidays from 2022.
- **Ex-dividend flag:**
  - ThetaData IVs ignore dividends. When an ex-date falls in (today, expiry], iv_spread reads 2–8 vol points low and skew25 about 2× normal.
  - The frozen ex-date list (yfinance, plus one manual fix: QQQ 2020-09-21, missing from yfinance) explains every day with a −2 vol-point spread (SPY 217/217, QQQ 208/208).
  - It is exposed as `bar['opt']['exdiv']`; all IV ideas excluded those days.
- **Half days:** ThetaData keeps writing stale snapshots after options stop at 13:15. The evaluator's half-day sessions end at 13:00 anyway.

### Evaluator (step 3)
- Copied from `research_loop_nq/eval`, with these changes:
  - the product is selected by `VOLSIG_PRODUCT` (NQ = MNQ on QQQ options, ES = MES on SPY options; no default);
  - a generic companion bar;
  - `bar['opt']`, joined on the exact slot end;
  - `bar['daily']`;
  - a `dev_opt` split.
- One manifest covers both products. Frozen digest **fba1a717…**.
- **Independent review** (subagent):
  - Found no look-ahead and no misalignment.
  - 16 of 20 scratch mutations were caught. The 3 survivors that mattered got tests.
  - It found two real problems, both fixed before the freeze:
    1. **ES `dev_opt` (2017-02 → 2018-12) can never pass.** With two calendar years, one year holds ≥ 50% of any positive total, and the cap is 0.40. The criteria were not changed; IV ideas ran on NQ only.
    2. The ex-dividend distortion (above).
- 123 tests at the end.

### Controller and sanity (step 4)
- Each prereg names one dev split (opt ideas → `dev_opt`, Cboe-only → `dev`), and the controller refuses the other. The product is recorded on every ledger row.
- Shared-file writes go through `fcntl.flock` on `research_loop/.shared.lock` and are append-only. A table-row helper refuses to write if the file no longer ends in the table. Another loop was active (the lock file appeared at 01:52), and every diff was a pure append.
- **Sanity:**

  | Check | Result |
  |---|---|
  | Always-flat | 0 trades |
  | Random direction, NQ `dev_opt` | −0.03 to −0.11R; cost 0.080R |
  | Random direction, ES `dev` | −0.17 / −0.20R; cost 0.16R |
  | Random restricted to bars carrying opt + daily (NQ) | traded every session |
  | Kill/resume | 0 duplicates |
  | One flipped byte | run refused |

## 2. Candidates

| # | Idea | Product, split | Configurations | n | Net R | Gross R | Twin p | Verdict |
|---|---|---|---|---|---|---|---|---|
| V1 | `V1_flow_divergence`: morning change in QQQ ATM call − put IV spread, residual on NQ's morning return → trade 12:00–15:55 in its sign | NQ `dev_opt` 2016-02 → 18 | Z 0.25 / 0.5 / 0.75 | 476 / 374 / 284 | −0.062 / −0.080 / −0.070 | −0.03 to −0.04 | 0.58 / 0.71 / 0.56 | REJECTED |
| V2 | `V2_skew_shock`: 30-min QQQ 25Δ skew change residual on NQ's 30-min move → fade for 90 min | NQ `dev_opt` | K 2.0 / 2.5 / 3.0 | 472 / 356 / 238 | −0.039 / −0.058 / −0.065 | — | 0.61 / 0.80 / 0.82 | **INVALID** (bug) |
| V2′ | `V2_skew_shock_fix`: the same rules, bug fixed | NQ `dev_opt` | K 2.5 (the spare) | 356 | −0.017 | +0.020 | 0.30 | REJECTED |
| V3 | `V3_term_slope`: weekday-adjusted 1-day change in VIX/VIX3M at the prior close → ES 09:35–15:55 against the change | ES `dev` 2011-02 → 18 | Z 0 / 0.5 / 1.0 | 1,747 / 961 / 449 | −0.044 / −0.032 / −0.036 | 0.000 / +0.012 / +0.008 | 0.44 / 0.29 / 0.34 | REJECTED |

### V1 notes
- corr(z, 12:00 → 15:55 return) over 645 eligible days = **−0.049**.
- The plan's "options disagree with the move" subset was the worst (−0.086R).
- That divergence condition was dropped before the run: a count-only scan gave < 200 trades for 2 of 3 Z, and the spot-vol slope was ≈ 0.

### V2 notes
- **The raw skew change is the price move's mirror** (corr −0.53; 74–80% of triggers are skew up with price down). Fading it would re-test the closed ES price shock-fade, so the signal was residualised before any run.
- **The first V2 run was invalid:**
  - The strategy skipped storing history while a position was open, so beta/RMS depended on past trades. Its trades overlapped the prereg rule's signals only 53–78%.
  - Found because the trade counts differ from a verified count-only replay. The original pre-run check had never fed positions.
  - The 3 configurations stay counted. The fix used the plan's one spare configuration, with a clause that a pass would stop for approval (a 1-configuration grid has no neighbour check).
  - V2′: gross +0.020R ≈ half the cost. The subset that also faded the price move was the worst (−0.043R).

### V3 notes
- **No source predicts equity direction from the slope.** Johnson 2017 is about variance-asset returns.
- The raw 1-day ratio change carries a VIX weekend-quoting pattern (Mon 68% long, Tue 33–37%). Side-matched twins would not neutralise it, so the signal was weekday-adjusted before the run (by weekday 41–55% long).
- Gross ≈ 0 at every Z.

## 3. Findings that hold across the candidates
- **Option-implied innovations on QQQ carry no usable intraday direction for NQ in 2016–18.** Three different measures were tested:
  - ATM call − put spread change;
  - 25Δ skew shock (raw, which is just the price move, and residualised, which is noise);
  - for SPX, the VIX term-slope change.
  - All gave gross ≈ 0 ± 0.04R at holds of 90 min to a full session.
- **The literature these ideas rest on is cross-sectional single-stock** (An et al. 2014, Cremers–Weinbaum 2010, Xing–Zhang–Zhao 2010) **or about variance-asset returns** (Johnson 2017, Bollen–Whaley 2004). None of it supports index direction intraday, and the tests agree.
- **Count-only scans before preregistration were decisive in shaping the rules.** They exposed the V2 price-mirror and the V3 weekday pattern. Without them, both would have been disguised re-tests of closed ideas or calendar effects.
- **A strategy's history must not depend on its own positions.** Tests should feed positions on history days, and the controller's trade counts should be compared with a count-only replay.

## 4. Multiple testing and data spent
- **10 configurations** were judged with Bonferroni p < 0.005:
  - 3 on V1 and 3 on V2 (invalid) on NQ 2016-02 → 2018-12;
  - 1 on V2′ on the same window;
  - 3 on V3 on ES 2011-02 → 2018-12.
- Rows were appended to `research_loop/data_spend_ledger.json` (4 rows, kind `discovery`) and `research_loop/CLOSED_IDEAS.md` (3 rows).
- The NQ 2016–18 window is now spent for the options-flow, skew-shock and dealer-pressure families. ES 2011–18 is spent for the VIX-slope-change family.

## 5. Limitations
- Dev for IV ideas is short (NQ 734 sessions; SPY options start in 2017, so no ES IV dev).
- ThetaData IVs are dividend-naive. They are flagged, not corrected.
- r = q = 0 in the delta (≤ 0.008 of skew25 in the worst case).
- The evaluator is RTH-only. V3's signal arrives after the close, so any overnight reaction was not tradeable.
- The forward and live feasibility of V1/V2 was moot. They would have needed real-time option quotes (ThetaData is being cancelled; yfinance chains are about 15 min delayed).

## 6. Not a lead, recorded only
- Post-hoc in V3: sessions whose **prior close was already inverted** (VIX/VIX3M > 1) averaged +0.17 to +0.24R on 61–115 trades.
- That subset was chosen after seeing results. It is 4–14% of trades and concentrated in 2011, 2015 and 2018 stress episodes, and it is the inversion *level*, not the tested change.
- Testing it needs a new prereg, a fresh budget and untouched data. ES 2011–18 is now spent for this family, and val1/val2 are unopened.

## 7. Files
- Code: `research_loop_volsig/{build_features.py, eval/ (frozen, MANIFEST.sha256), controller.py, prereg/, strategies/, tests/}`, `ledger.jsonl`.
- Data: `data/research_loop_volsig/{features/, cboe/, exdiv/, runs/, state.json, LOG.md, bootstrap_coverage.txt, v2_bug_diagnosis.py}`.
