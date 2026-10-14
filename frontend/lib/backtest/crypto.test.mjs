import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { runBacktest } = await jiti.import('./engine.js')
const { loadLiveDataset, LIVE_SYMBOLS, barsPerDay } = await jiti.import('./datasets.js')
const { calendarCoverage, isCrypto, CRYPTO_SYMBOLS } = await jiti.import('./markets.js')

// Friday 2025-01-03 22:00 UTC through the weekend, every 5 minutes.
const T0 = Date.parse('2025-01-03T22:00:00Z') / 1000
function cryptoDataset(n, symbol = 'BTC-USD') {
  const time = Array.from({ length: n }, (_, i) => T0 + i * 300)
  const close = time.map((_, i) => 100 * 1.001 ** i)
  return { id: 'c', symbol, interval: '5m', time, open: close, high: close, low: close, close, volume: close.map(() => 1) }
}
const frictionless = { slippageBps: 0, commissionPerTrade: 0 }
const always = { id: 'always', signal: () => 1 }

test('every live crypto symbol is recognised as crypto and offered on the live plane', () => {
  for (const symbol of CRYPTO_SYMBOLS) {
    assert.ok(isCrypto(symbol))
    assert.ok(LIVE_SYMBOLS.includes(symbol))
  }
  for (const symbol of ['SPY', 'QQQ', 'NQ=F', 'ES=F', 'XEQT.TO']) assert.equal(isCrypto(symbol), false)
  assert.equal(barsPerDay('5m', 'BTC-USD'), 288)
  assert.equal(barsPerDay('5m', 'SPY'), 78)
})

test('a crypto backtest annualises on the 24/7 calendar and trades through the weekend', () => {
  const ds = cryptoDataset(48 * 12) // 48 hours
  const crypto = runBacktest({ dataset: ds, strategy: always, params: {}, costs: frictionless })
  const equity = runBacktest({ dataset: { ...ds, symbol: 'SPY' }, strategy: always, params: {}, costs: frictionless })
  assert.equal(crypto.metrics.periodsPerYear, 365 * 288)
  assert.equal(equity.metrics.periodsPerYear, 252 * 78)
  // Identical bars: only the annualisation differs.
  assert.equal(crypto.metrics.totalReturn, equity.metrics.totalReturn)
  assert.ok(Math.abs(crypto.metrics.volAnn / equity.metrics.volAnn - Math.sqrt((365 * 288) / (252 * 78))) < 1e-9)
})

test('flat-at-session-end closes crypto positions at 00:00 UTC, weekends included', () => {
  const r = runBacktest({ dataset: cryptoDataset(48 * 12), strategy: always, params: {}, costs: frictionless, risk: { flatAtSessionEnd: true } })
  const exits = r.trades.filter(t => t.reason === 'session').map(t => new Date(t.exitTime * 1000).toISOString())
  // Friday and Saturday midnights, then the final bar of the data.
  assert.deepEqual(exits, ['2025-01-03T23:55:00.000Z', '2025-01-04T23:55:00.000Z', '2025-01-05T21:55:00.000Z'])
})

test('calendar coverage flags crypto stored only during equity hours', () => {
  const full = cryptoDataset(288)
  assert.deepEqual(calendarCoverage(full.time, '5m', 'ETH-USD'), { share: 1, expected: 288, maxGapSeconds: 300 })
  // Keep 13:30–20:00 UTC on weekdays only, as the equity-hours ingester used to.
  const time = []
  for (let t = Date.parse('2025-01-06T00:00:00Z') / 1000; t < Date.parse('2025-01-18T00:00:00Z') / 1000; t += 300) {
    const d = new Date(t * 1000)
    const minute = d.getUTCHours() * 60 + d.getUTCMinutes()
    if (d.getUTCDay() >= 1 && d.getUTCDay() <= 5 && minute >= 810 && minute < 1200) time.push(t)
  }
  const gappy = calendarCoverage(time, '5m', 'SOL-USD')
  assert.equal(gappy.share, 780 / gappy.expected) // 78 bars on each of 10 weekdays
  assert.ok(gappy.share < 0.25)
  assert.equal(gappy.maxGapSeconds, Date.parse('2025-01-13T13:30:00Z') / 1000 - Date.parse('2025-01-10T19:55:00Z') / 1000)
  assert.equal(calendarCoverage(time, '5m', 'SPY'), null)
})

test('live crypto datasets carry their calendar coverage', async () => {
  const rows = [0, 1, 2, 10].map(i => ({ time: T0 + i * 300, open: 100, high: 101, low: 99, close: 100, volume: 5 }))
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ data: rows }) })
    const crypto = await loadLiveDataset({ symbol: 'BTC-USD', period: '5d', interval: '5m' })
    assert.deepEqual(crypto.coverage, { share: 4 / 11, expected: 11, maxGapSeconds: 8 * 300 })
    const equity = await loadLiveDataset({ symbol: 'SPY', period: '5d', interval: '5m' })
    assert.equal(equity.coverage, null)
  } finally { globalThis.fetch = original }
})
