# Options-signal futures loop (QQQ/SPY implied vol + Cboe VIX family → MNQ/MES at a futures prop firm)

## Context
- Mainstream evaluation prop firms (Topstep, Apex, Tradeify, MyFundedFutures, Lucid) are **futures-only**. Their help pages prohibit options, including options on futures. Confirm this for your firm before relying on it.
- So the realistic "options prop trade" is to **read the options market and trade the futures**.
- The repo already holds the inputs:
  - ThetaData 5-minute IV and quotes for every strike: QQQ from 2016-01-04 and SPY from 2017-01-03, both to 2026-10-23. This is `data/thetadata/iv_5m`, about 7.6 GB.
  - ES/NQ 1m futures to 2026-08-14.
- No earlier family used intraday option-implied *changes* as a directional signal. GEX levels, implied-move bands and condors are closed.

Everything in the NQ plan (`~/.claude/plans/nq-research-loop.md`) and the ES plan it points to applies unless changed below.

## Decisions
- **Contracts:** MNQ (signals from QQQ options) and MES (signals from SPY options). Costs are as in the NQ/ES loops: MNQ 3.6 ticks per round trip.
  - The cost rules from `research_loop_nq/REPORT.md` apply: a median stop of about 72 ticks or more for MNQ.
- **Free daily series (verified 2026-11-03).** These are Cboe CSVs at `cdn.cboe.com/api/global/us_indices/daily_prices/<NAME>_History.csv` (follow the redirect):

  | Series | From |
  |---|---|
  | VIX | 1990 |
  | VIX9D | 2011-01-04 |
  | VIX3M | 2009-09-18 |
  | VVIX | 2006 (close only) |
  | SKEW | 1990 |

  - They are used **as of the prior close only**, because Cboe finalises after 16:15 ET.
- **Intraday options features,** derived once from `iv_5m` into a compact parquet:
  - Per 5m slot: ATM IV for the nearest expiry with DTE ≥ 7; 25-delta put minus 25-delta call IV (skew); call-minus-put IV at ATM (IV spread); the quote counts.
  - A slot's features use only rows whose timestamp is ≤ the slot end. ThetaData's 09:30 row has no quotes, so 09:35 is the first usable slot (as in `delta_hedge.py`).
  - **Check the timestamp semantics** of `iv_5m` (bar start vs snapshot time) before building anything. Record the answer in the prereg of every feature user.
- **Splits:** the ES/NQ dates.
  - Ideas that use the IV features have a shorter dev period: QQQ/NQ 2016-02 → 2018-12 (about 730 sessions) and SPY/ES 2017-02 → 2018-12 (about 480).
  - Ideas that use only the Cboe series get the full 2011-02 → 2018-12.
  - val1 2019-01 → 2021-12; val2 2022-01 → 2026-08-14. The holdout is futures after 2026-08-14 (not on disk; a purchase).
- **Gate:** as in ES/NQ; dev twin p < 0.005. Side-matched twins mean **signals must be signed** (long and short). A "fear spike → buy" rule that is long-only cannot pass, and must not be proposed.
- **Feature budget:** at most 3 features per idea, each named in the prereg. No ML and no feature search.

## Layout
- **Parallel-safe shared writes:** other loops may be running at the same time.
  - Every write to `research_loop/CLOSED_IDEAS.md` or `research_loop/data_spend_ledger.json` (and to `data/binance/looks.jsonl`) takes an exclusive `fcntl.flock` on `functions/ml/research_loop/.shared.lock`, re-reads the file under the lock, appends its own rows only, and writes atomically (temp file + `os.replace`). Never rewrite or reorder rows written by other loops.
  - Cap worker processes at 3 for twin and permutation runs.
- `functions/ml/research_loop_volsig/`: `PLAN.md`, `build_features.py`, `eval/`, `tests/`, `controller.py`, `prereg/`, `strategies/`, `ledger.jsonl`, `REPORT.md`.
- State: `functions/ml/data/research_loop_volsig/`, holding `features/*.parquet`, `cboe/*.csv` (with SHA-256 hashes) and `state.json`/`LOG.md`.
- Shared: `research_loop/CLOSED_IDEAS.md` and `research_loop/data_spend_ledger.json`, with markets "NQ"/"ES" and a note that the signals come from options.

## Evaluator (step 2)
- Copy `research_loop_nq/eval/`, keeping the ES companion so MNQ ideas can see ES.
- Add `bar['opt']`: the slot's options features, or None when missing.
- Add `bar['daily']`: the prior-close Cboe values.
- Both come from frozen parquet and CSV files listed in the manifest.
- Tests:
  - No look-ahead: features at slot k use only option timestamps ≤ the slot-k end.
  - The daily series lags by exactly one session.
  - Missing data gives None.
  - On 20 random slots, the recomputed IV and skew match the raw `iv_5m` rows.
- Review with a subagent, focused on:
  - Timestamp alignment between ThetaData (ET, `underlying_timestamp`) and the Databento bars.
  - Expiry selection across roll days.
  - Delta-bucket interpolation.
- Then freeze.

## Candidate queue (step 4a writes the exact rules and checks the sources first)
Closed and not to be reused: GEX walls (fade and break), implied-move band fade, condors and flies, intraday momentum into the close, gap fill, ORB, and anything with a VIX filter layered on a closed family. A filter on a closed idea is still that idea.

| # | Idea | Mechanism and sources to check | Data | Notes |
|---|---|---|---|---|
| V1 | **Options-implied flow divergence.** By 12:00, NQ is up (down) since the open but QQQ call-minus-put IV spread or ATM IV moved against it, beyond its trailing 20-day spot-vol beta. Trade the afternoon in the direction the options imply | Informed or hedging demand shows up in options first. Sources: An, Ang, Bali & Cakici 2014 (JF, changes in call/put IV predict returns); Cremers & Weinbaum 2010 (JFQA, the IV spread predicts returns); Pan & Poteshman 2006 (RFS, option volume) | iv_5m QQQ → MNQ | Stock-level evidence; untested at index level, intraday. The prior is weak, but the mechanism is distinct |
| V2 | **Intraday skew shock.** A 30-minute change in 25-delta skew beyond K × its trailing same-slot sd: trade against (or with) the spot move over the next 60–120 min, with the direction fixed from the sources before data | Skew as a demand-for-protection signal. Sources: Xing, Zhang & Zhao 2010 (JFQA, the smirk predicts returns); Bollen & Whaley 2004 (JF, net buying pressure moves the IV function) | iv_5m SPY → MES, QQQ → MNQ | The trade count depends on K. The prereg must show ≥ 200 dev trades from a count-only scan of the *feature* series (no returns) |
| V3 | **Term-structure slope change → next-session direction.** Sign of the 1-day change in VIX9D/VIX or VIX/VIX3M at the prior close: long when the curve steepens back toward contango, short when it inverts further. One trade per session with a wide stop | Term-structure risk premia. Sources: Johnson 2017 (JFQA, "Risk premia and the VIX term structure"); check whether any source predicts *equity* direction, not only variance returns | Cboe free | Full 2011-18 dev. Report whether it is just day-of-week or drift (twins handle drift) |

**Budget:** 9 configurations (3 × 3) plus 1 spare.

## Running it with /loop
```text
/loop Run one iteration of the options-signal futures loop defined in /Users/sunnychen/.claude/plans/volsignal-futures-research-loop.md (section "Running it with /loop"). Read functions/ml/data/research_loop_volsig/state.json and LOG.md first (they may not exist yet), do exactly one step, update both, and schedule the next wakeup in 60s, or stop the loop if a stop condition holds.
```

Each firing does the first unfinished step:
1. **Bootstrap:**
   - Copy the plan.
   - Download the Cboe CSVs, hash them, and check their date coverage against the ES sessions.
   - Inspect the `iv_5m` schema and timestamp semantics on 3 dates (2016, 2019, 2024) and log the result.
2. **Build features:** run `build_features.py` once per symbol, in a background run if it is slow. Coverage report: slots with no ATM quote, and days with no expiry ≥ 7 DTE.
3. **Evaluator:** (a) copy and adapt, (b) review subagent, (c) freeze.
4. **Controller and sanity checks:** the same four as NQ.
5. **Per candidate:** prereg → implement → dev → val1 → val2 → decision. Rejections go to the shared files.
6. **Report and memory, then stop.**

**Stop conditions:** 10 configurations; 150 active minutes (feature building is slow); the queue is empty; any purchase or approval; the same step failing 3 times.

**Never inside the loop:** edit a frozen `eval/` (NQ, ES or volsig), buy data, open holdout data, commit or push, lower the criteria, or open `.env` files.

**Forward and live inputs (outside the loop):**
- The Cboe series are free daily.
- yfinance `^VIX9D`, `^VIX` and `^VIX3M` are free.
- QQQ/SPY chains with IV come free from yfinance, about 15 minutes delayed. The repo's GEX Function already pulls the QQQ chain on a timer.
- A delayed chain is fine for V3. It is **not** good enough to trade V1 or V2 live; those would need a broker feed with real-time options quotes. ThetaData is being cancelled, so no new IV arrives after the final download.
