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

The bundled `frontend/public/backtest/*.json` files are synthetic (see PR #17). Real research datasets use the
same format; `Dataset.from_frame` takes any OHLCV DataFrame, for example Databento bars.

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
left, which is a state machine. 500,000 one-minute bars take about 1.5 to 2 s. If that ever matters, the loop
is the part to compile with numba; the strategy interface would not change.

**Pessimistic fills.** A bar that opens past the stop fills at the open, not at the stop. When one bar's range
contains both stop and target, the stop is assumed to have hit first. Without tick data the worse fill is the
only defensible guess.

**Costs are inside every number.** Slippage is in the fill prices, and both commissions are in `pnl`.
`pnl_pct` is net, so a bootstrap or Monte Carlo over trades cannot quietly use gross returns.

**Same contract as the JS strategies.** `prepare(ds, params) -> state`, `warmup(params, ds) -> int`,
`signal(i, state, ds, params, prev) -> -1|0|1`. Strategy ids and parameter names match the JS registry
(camelCase on purpose), so a run config moves between the browser and Python unchanged. The engine's own
cost and risk keys are snake_case and unknown keys raise, so a camelCase typo cannot be silently ignored.

**Bit-for-bit parity, which shaped the code.** Trades and equity curves match the JS engine exactly on every
test case, not just to a tolerance. Getting there took a few choices that look odd in isolation:

- The SMA is a running sum (add the new bar, subtract the old one), like the JS. `pandas.rolling().mean()`
  rounds differently in the last bit, and a crossover compares two nearly equal numbers, so one ulp can move a
  trade by a bar.
- Sums use `np.cumsum(x)[-1]` (left to right) and never `np.sum` (pairwise). They are different
  floating-point operations.
- `Math.round` is ported as `floor(x + 0.5)`. Python's `round(2.5)` is 2 (it rounds to even).
- The normal CDF is the same closed-form approximation as the JS, not `scipy.stats.norm`, so PSR and
  deflated Sharpe print the same digits in both places.

Metrics that go through `pow`/`sqrt` are checked to 1e-9 relative, since V8 and libm may differ in the last
bit there.

## How parity is tested

`test_backtest_parity.py` writes a batch of run configs, runs them through the real JS engine with
`node frontend/scripts/backtest-parity.mjs` (no `npm install`; a resolve hook supplies the `.js` extensions the
bundler normally adds), runs the same configs through Python, and compares every trade field, the equity
curve, positions, prop-replay bar extremes and every metric.

There are 24 configs on each of QQQ and SPY, covering every ported strategy, parameter variants, stops,
targets, max bars, flat at close, flat by ET, long only, news blackouts (including the `max_bar_min` skip),
percent costs, futures sizing and a trading window. Five more run on a synthetic 23-hour Globex week across
the 2025 DST switch and a CPI print, because the RTH samples almost never put a stop and a target in the same
bar. One test checks that those rare paths really happen.

To check that the test can fail, I broke the engine on purpose in several ways, and each of these was caught:
target checked before stop, gapped stop filled at the stop price, lockout not reset at a new session, no
"don't enter right before news" rule, flat-by blocking off, and prop bar extremes wrong.

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
