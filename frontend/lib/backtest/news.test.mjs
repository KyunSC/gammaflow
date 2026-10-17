import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const news = await jiti.import('./news.js')
const { runBacktest } = await jiti.import('./engine.js')
const { getSeries } = await jiti.import('./series.js')
const { propSetup } = await jiti.import('./prop/index.js')

// CPI for Aug 2026 printed 2026-09-11 08:30 EDT = 12:30 UTC.
const CPI = Date.parse('2026-09-11T12:30:00Z') / 1000

/** 5m bars from `start` (epoch s), flat price unless `px` says otherwise. */
function dataset(start, n, px = () => 100) {
  const time = Array.from({ length: n }, (_, i) => start + i * 300)
  const close = time.map((_, i) => px(i))
  return { id: 't', symbol: 'ES', interval: '5m', time, open: close, high: close, low: close, close, volume: close.map(() => 1) }
}

test('the calendar has the September 2026 CPI and FOMC at their ET times', () => {
  const ev = news.newsEvents({ minImpact: 'high' })
  assert.ok(ev.some((e) => e.type === 'cpi' && e.t === CPI))
  const fomc = ev.find((e) => e.type === 'fomc' && e.t === Date.parse('2026-09-16T18:00:00Z') / 1000)
  assert.equal(fomc?.impact, 'high')
  for (let i = 1; i < ev.length; i++) assert.ok(ev[i].t >= ev[i - 1].t, 'sorted')
})

test('medium includes claims, high does not', () => {
  const claims = (impact) => news.newsEvents({ minImpact: impact }).filter((e) => e.type === 'claims').length
  assert.equal(claims('high'), 0)
  assert.ok(claims('medium') > 200)
})

test('window flags mark exactly the bars that overlap [event - before, event + after)', () => {
  const ds = dataset(CPI - 3600, 25) // 07:30 → 09:30 ET
  const f = news.newsWindowFlags(ds, { minImpact: 'high', beforeMin: 5, afterMin: 15 })
  const on = [...f.keys()].filter((i) => f[i] === 1).map((i) => (ds.time[i] - CPI) / 60)
  // bars opening 08:25, 08:30, 08:35, 08:40 overlap 08:25–08:45
  assert.deepEqual(on, [-5, 0, 5, 10])
  const inBar = getSeries(ds, 'news:high:0:0')
  assert.deepEqual([...inBar.keys()].filter((i) => inBar[i] === 1).map((i) => (ds.time[i] - CPI) / 60), [0])
})

test('minutes to next / since are measured from the bar close', () => {
  const ds = dataset(CPI - 3600, 25)
  const next = news.minutesToNextNews(ds, { minImpact: 'high' })
  const prev = news.minutesSinceNews(ds, { minImpact: 'high' })
  assert.equal(next[0], 55) // 07:30 bar closes 07:35
  assert.equal(prev[12], 5) // 08:30 bar closes 08:35
  assert.ok(next[11] > 0 && next[11] !== 0) // 08:25 bar closes at the print: next is the one after
  assert.equal(prev[11], 0)
})

test('bars past the calendar coverage are unknown, not "no news"', () => {
  const end = news.newsCoverEnd({ minImpact: 'high' })
  const ds = dataset(end - 600, 4)
  const f = news.newsWindowFlags(ds, { minImpact: 'high' })
  assert.equal(f[0], 0)
  assert.ok(Number.isNaN(f[2]) && Number.isNaN(f[3]))
  assert.ok(news.newsCoverEnd({ minImpact: 'medium' }) <= end)
})

test('a news blackout flattens before the release and re-enters after', () => {
  const ds = dataset(CPI - 3600, 25, (i) => 100 + i)
  const always = { id: 'always', signal: () => 1 }
  const free = { slippageBps: 0, commissionPerTrade: 0 }
  const base = runBacktest({ dataset: ds, strategy: always, params: {}, costs: free, risk: {} })
  assert.equal(base.trades.length, 1)
  const r = runBacktest({ dataset: ds, strategy: always, params: {}, costs: free, risk: { newsBlackout: { impact: 'high', beforeMin: 5, afterMin: 15 } } })
  assert.equal(r.trades.length, 2)
  assert.equal(r.trades[0].reason, 'news')
  // closed at the close of the 08:20 bar, back in at the open of 08:45 (orders
  // placed at the 08:40 close land after the window)
  assert.equal(ds.time[r.trades[0].exitIdx], CPI - 600)
  assert.equal(ds.time[r.trades[1].entryIdx], CPI + 900)
  for (let i = 0; i < ds.time.length; i++) {
    const m = (ds.time[i] - CPI) / 60
    if (m >= -5 && m < 15) assert.equal(r.positions[i], 0, `flat at ${m}`)
  }
  assert.equal(r.newsUncoveredBars, 0)
})

test('LucidDaily carries its one-minute high-impact rule into the engine', () => {
  const prop = { enabled: true, firm: 'lucid', plan: 'daily', size: '50k', dll: true, overrides: {}, contract: 'MES', contracts: 1, commissionPerSide: 0.5, slippageTicks: 1 }
  const s = propSetup({ prop, symbol: 'ES=F', costs: {}, risk: {} })
  assert.deepEqual(s.risk.newsBlackout, { impact: 'high', beforeMin: 1, afterMin: 1 })
  const flex = propSetup({ prop: { ...prop, plan: 'flex' }, symbol: 'ES=F', costs: {}, risk: {} })
  assert.equal(flex.risk.newsBlackout, null)
})
