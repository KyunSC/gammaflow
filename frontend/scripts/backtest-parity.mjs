#!/usr/bin/env node
/**
 * Runs the JS backtest engine on a batch of configs and prints the results as JSON, so the Python port
 * (functions/ml/backtest) can be checked trade for trade. Used by functions/ml/test_backtest_parity.py.
 *
 *   node scripts/backtest-parity.mjs < cases.json > results.json
 *
 * Input:  { "dataset": "<path to a research JSON>", "cases": [{ strategy, params, costs, risk, window }] }
 * Output: { "defaults": {strategyId: params}, "results": [{ trades, equity, positions, metrics, ... }] }
 *
 * No npm install needed: a resolve hook adds the `.js` the bundler normally fills in for extensionless
 * imports, so plain Node can load lib/backtest directly.
 */
import { register } from 'node:module'
import { readFileSync } from 'node:fs'

register('data:text/javascript,' + encodeURIComponent(`
  export async function resolve(spec, ctx, next) {
    try { return await next(spec, ctx) } catch (e) {
      if (e.code === 'ERR_MODULE_NOT_FOUND' && /^\\.\\.?\\//.test(spec) && !/\\.[cm]?js$/.test(spec)) return next(spec + '.js', ctx)
      throw e
    }
  }`))

const { runBacktest } = await import('../lib/backtest/engine.js')
const { getStrategy, defaultParams, STRATEGIES } = await import('../lib/backtest/strategies/index.js')

const input = JSON.parse(readFileSync(0, 'utf8'))
const j = JSON.parse(readFileSync(input.dataset, 'utf8'))
const f64 = (a) => Float64Array.from(a, (v) => (v === null || v === undefined ? NaN : v))
const ds = {
  id: 'parity', symbol: j.symbol, interval: j.interval, n: j.bars,
  time: f64(j.time), open: f64(j.open), high: f64(j.high), low: f64(j.low), close: f64(j.close), volume: f64(j.volume),
  features: Object.fromEntries(Object.entries(j.features || {}).map(([k, v]) => [k, f64(v)])),
  ml: j.ml ? { pred: f64(j.ml.pred), target: f64(j.ml.target_return) } : null,
}

// JSON has no NaN/Infinity; tag them so the Python side can tell them apart from null.
const num = (v) => (Number.isFinite(v) ? v : Number.isNaN(v) ? 'NaN' : v > 0 ? 'Infinity' : '-Infinity')
const arr = (a) => (a ? Array.from(a, num) : null)
const clean = (o) => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === 'number' ? num(v) : ArrayBuffer.isView(v) ? Array.from(v, num) : v)))

const results = input.cases.map((cfg) => {
  const params = { ...defaultParams(cfg.strategy), ...cfg.params }
  const r = runBacktest({ dataset: ds, strategy: getStrategy(cfg.strategy), params, costs: cfg.costs, risk: cfg.risk, window: cfg.window })
  const { ddCurve, ...metrics } = r.metrics
  return {
    trades: clean(r.trades),
    equity: arr(r.equity),
    positions: Array.from(r.positions),
    barLo: arr(r.barLo),
    barHi: arr(r.barHi),
    barOpen: arr(r.barOpen),
    metrics: clean(metrics),
    newsUncoveredBars: r.newsUncoveredBars,
    newsSkipped: r.newsSkipped,
  }
})

process.stdout.write(JSON.stringify({ defaults: Object.fromEntries(STRATEGIES.map((s) => [s.id, defaultParams(s.id)])), results }))
