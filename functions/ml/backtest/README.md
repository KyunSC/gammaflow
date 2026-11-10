# `backtest`: the GammaFlow engine in Python

A port of the browser engine in `frontend/lib/backtest`. Bars go in, trades and stats come out, with the
same costs, the same risk rules and the same Sharpe inference. A parity test holds the two engines to each
other trade for trade.

```python
from backtest import Dataset, run_backtest

ds = Dataset.from_json("../../frontend/public/backtest/qqq_5m.json")   # or Dataset.from_frame(df, "5m")
res = run_backtest(ds, "smaCross", {"fast": 10, "slow": 50},
                   costs={"slippage_bps": 1.5, "commission_per_trade": 0.5},
                   risk={"stop_pct": 0.5, "flat_at_session_end": True,
                         "news_blackout": {"impact": "high", "before_min": 5, "after_min": 15}})
res.metrics["sharpe"], res.metrics["inference"]["ci"], res.trades_frame()
```

```bash
cd functions/ml
python -m backtest --data ../../frontend/public/backtest/qqq_5m.json --strategy bbReversion \
    --param period=30 --stop-pct 0.3 --flat-by 15:45 --news high --trades trades.csv
python -m unittest test_backtest_engine test_backtest_parity -v
```

The package lives in `functions/ml`, like the other research scripts: run from there, or put that folder on
`PYTHONPATH`.

The bundled `frontend/public/backtest/*.json` files are synthetic (see PR #17). Real research datasets use the
same format. `Dataset.from_frame` takes an OHLCV DataFrame (column names in any case) with a tz-aware
DatetimeIndex or a `time` column, for example Databento bars.

## Layout

| module | what it holds | JS original |
|---|---|---|
| `engine.py` | `run_backtest`, `Trade`, `Instrument`, costs and risk defaults | `engine.js` |
| `series.py` | SMA/EMA/stdev/RSI/ATR/VWAP, session-end and flat-by flags, `get_series` | `series.js` |
| `news.py` | news-window and blackout flags (calendar from `econ_calendar.py`) | `news.js` |
| `metrics.py` | Sharpe, Sortino, drawdown, CAGR, hit rate, PF, annualisation | `metrics.js` |
| `stats.py` | Mertens SE, PSR, deflated Sharpe, holdout split | `stats.js` |
| `clock.py` | trading day (rolls 22:00 UTC), ET minute of day | `time.js` |
| `strategies/` | smaCross, bbReversion, vwapReversion, gexWallFade, gexRegime, mlSignal | `strategies/*.js` |

## Design choices, and why

**One bar of delay, enforced by the engine.** A strategy answers "what position do you want?" after bar *i*
closes, and the engine fills that at bar *i+1*'s open. Strategies cannot opt out, so look-ahead through the
fill is impossible by construction instead of something every strategy has to remember.

**A loop, not vectorised pandas.** The textbook vectorised backtest is
`pnl = signal.shift(1) * returns`. It is fast and fine for an always-in-market signal, but it cannot express
an intrabar stop, a stop that the open gaps through, "no re-entry in the stopped direction until the signal
resets", "flat by 16:45 ET" or a news blackout. Each of those makes bar *i* depend on the position bar *i-1*
left, which is a state machine. 500,000 one-minute bars take about 1.4 to 2 s on a 4-vCPU cloud container.
If that ever matters, the loop is the part to compile with numba; the strategy interface would not change.

**Pessimistic fills.** A bar that opens past the stop fills at the open, not at the stop. When one bar's range
contains both stop and target, the stop is assumed to have hit first. Without tick data the worse fill is the
only defensible guess.

**Costs are inside every number.** Slippage is in the fill prices, and both commissions are in `pnl`.
`pnl_pct` is net, so a bootstrap or Monte Carlo over trades cannot quietly use gross returns.

**Same contract as the JS strategies.** `prepare(ds, params) -> state`, `warmup(params, ds) -> int`,
`signal(i, state, ds, params, prev) -> -1|0|1`. Strategy ids and parameter names match the JS registry
(camelCase on purpose), so a strategy's params copy straight from the browser. The engine's own cost and risk
keys are Pythonic snake_case (`stopPct` becomes `stop_pct`; the parity test converts mechanically). Per-run
state belongs in what `prepare` returns, never on `self`, because strategy instances are shared.

**Wrong input fails loudly.** A typo that silently runs the defaults is the worst kind of backtest bug, so:
unknown strategy params, cost, risk or news keys raise (with the valid names), and so do params of the
wrong type (`shortSide="no"`, a non-finite number) and nulls JS would read differently (an instrument
without `contracts`, `allow_short=None`); NaN prices, millisecond or
row-number timestamps and impossible OHLC are refused when the `Dataset` is built; a research strategy whose
GEX/ML columns are all NaN warns that it cannot trade. The bar columns are read-only, because indicators are
memoised per dataset and editing prices in place would leave them stale; `dataclasses.replace` gets a fresh
cache.

**Bit-for-bit parity, which shaped the code.** Trades, equity, returns, positions, the buy-and-hold and
drawdown curves match the JS engine exactly: the test compares them at zero tolerance. Getting there took a
few choices that look odd in isolation:

- The SMA is a running sum (add the new bar, subtract the old one), like the JS. `pandas.rolling().mean()`
  rounds differently in the last bit, and a crossover compares two nearly equal numbers, so one ulp can move a
  trade by a bar.
- Sums use `np.cumsum(x)[-1]` (left to right) and never `np.sum` (pairwise). They are different
  floating-point operations.
- `Math.round` is ported by hand (`_js.py`). Python's `round(2.5)` is 2 (it rounds to even), and the obvious
  `floor(x + 0.5)` is wrong for 0.49999999999999994.
- Squares are `x * x`, not `x ** 2`: V8's `**` with exponent 2 is exactly `x * x`, CPython's `pow` is not
  always.
- The normal CDF is the same closed-form approximation as the JS, not `scipy.stats.norm`, so PSR and
  deflated Sharpe print the same digits in both places.

Metrics that go through a general `pow` (CAGR, skew) are checked to 1e-9 relative, since V8 and libm may
differ in the last bit there. Where Python would raise and JS returns a value (a CAGR that overflows on a
short window), Python returns the same `inf`.

## How parity is tested

`test_backtest_parity.py` runs batches of configs through the real JS engine with
`node frontend/scripts/backtest-parity.mjs` (no `npm install`; a resolve hook supplies the `.js` extensions the
bundler normally adds), runs the same configs through Python, and compares every trade field, the equity,
returns, buy-and-hold and drawdown curves, positions, prop-replay bar extremes and every metric. Three layers:

- **30 hand-picked configs on each of QQQ and SPY**: every ported strategy, parameter variants, fractional
  periods (`holdBars=2.5`, where JS and Python rounding differ), stops, targets, max bars, flat at close,
  flat by ET, long only, news blackouts (default window, a 0/0 window, the `max_bar_min` skip at and past the
  boundary), percent costs, futures sizing and a trading window.
- **9 configs on each of two synthetic 23-hour Globex weeks**: one across the 2025 DST switch and a CPI print,
  one running past the news calendar's coverage. Prices sit on a tick grid so averages tie, some volume is zero
  or missing, and the GEX/ML columns have NaN runs. The RTH samples almost never put a stop and a target in
  one bar, and one test checks that these weeks really do hit those paths.
- **A seeded fuzz test** (`FuzzParity`, 144 random configs on 12 random datasets: 1m to 1h bars, RTH or
  Globex, 2022 to 2026, data gaps). Set `BACKTEST_FUZZ_SEED` to explore further; a failure prints the seed and
  case. During review, 4,000 such cases matched exactly.

`test_backtest_engine.py` mirrors the engine cases in `engine.test.mjs` (all but the two walk-forward tests,
since walk-forward is not ported) and adds validation and edge-case tests.

To check that the suite can fail, it was run against deliberately broken engines: 34 single-line mutants in
review (wrong slippage side, off-by-one windows, lockout flips, VWAP reset, rounding, news shifts, coverage
boundaries...). The first version of the suite let 12 through; every one of them now fails it.

`.github/workflows/backtest-parity.yml` runs both test files on every PR that touches either engine or the
news calendar. With `CI` set, a missing Node fails the run instead of skipping it.

If the JS engine changes (for example PR #8 adds `slippage`/`stopPrice`/`targetPrice` to trades), the parity
test fails and names the new fields. That is intended: the two engines cannot drift apart silently.

## Not ported yet

- `srLevels` (needs `lib/levels.js` zone scoring) and `custom` (needs the rule-builder AST in `ruleAst.js`).
- Analytics around the engine: parameter sweep, walk-forward with embargo, Monte Carlo block bootstrap,
  cost curve (`analytics.js`).
- Prop-firm replays (`prop/`). Lucid already has a Python port in `flybrain/prop.py`; MFP lives in draft PR #9.
- Series keys the ported strategies don't use: session levels (`pdh`, `orh`...), floor pivots, S/R zones,
  `newsNext` / `newsPrev`. `get_series` raises on them instead of returning NaN.
- `flybrain/stats.py` and `delta_hedge.py` carry their own copies of the Sharpe statistics; they could import
  `backtest.stats` instead.
