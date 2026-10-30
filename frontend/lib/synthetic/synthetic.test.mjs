import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createJiti } from 'jiti'

const jiti = createJiti(import.meta.url)
const M = await jiti.import('./market.js')
const { gammaExposure, gexLadder, keyLevels } = await jiti.import('./gex.js')
const { researchDataset } = await jiti.import('./research.js')
const api = await jiti.import('./api.js')
const { resolveDataSource } = await jiti.import('../dataSource.mjs')
const { validateDataset, normalizeBars } = await jiti.import('../backtest/datasets.js')
const { etMinuteOfDay } = await jiti.import('../backtest/time.js')

// Wednesday 2026-07-08, 11:07:30 EDT: mid-session, mid-minute.
const NOW = Date.parse('2026-07-08T15:07:30Z') / 1000
const weekday = (t) => new Date(t * 1000).getUTCDay()

function assertBar(b) {
  assert.ok(b.low > 0 && b.low <= Math.min(b.open, b.close) && b.high >= Math.max(b.open, b.close) && b.volume >= 0, JSON.stringify(b))
}

test('hosted builds can never be switched to real data', () => {
  assert.equal(resolveDataSource({}), 'synthetic')
  assert.equal(resolveDataSource({ GAMMAFLOW_DATA: 'yes' }), 'synthetic')
  assert.equal(resolveDataSource({ GAMMAFLOW_DATA: 'real' }), 'real')
  assert.throws(() => resolveDataSource({ GAMMAFLOW_DATA: 'real', VERCEL: '1' }), /local-only/)
  assert.throws(() => resolveDataSource({ GAMMAFLOW_DATA: 'real', RENDER: 'true' }), /local-only/)
})

test('the same request gives the same bars, and nothing after now', () => {
  const a = M.historicalRows('SPY', '5d', '5m', NOW)
  assert.deepEqual(M.historicalRows('SPY', '5d', '5m', NOW), a)
  assert.ok(a.length > 4 * 78)
  assert.ok(Number(a.at(-1).time) <= NOW)
  a.forEach(assertBar)
})

test('full fetch, /since, /recent and the live quote agree', () => {
  const full = M.historicalRows('NQ=F', '1d', '1m', NOW)
  const since = M.rowsSince('NQ=F', '1m', Number(full.at(-10).time), NOW)
  assert.deepEqual(since, full.slice(-10))
  assert.deepEqual(M.recentRows('NQ=F', NOW, 10), full.slice(-10))
  assert.equal(M.quote('NQ=F', NOW).price, full.at(-1).close)
  // The developing minute is cut at now and still a valid bar.
  assertBar(full.at(-1))
  assert.ok(full.at(-1).volume < full.at(-2).volume * 3)
})

test('sessions follow the instrument', () => {
  for (const r of M.historicalRows('QQQ', '5d', '5m', NOW)) {
    const m = etMinuteOfDay(Number(r.time))
    assert.ok(m >= 570 && m < 960, `QQQ bar outside RTH at ET minute ${m}`)
  }
  const es = M.historicalRows('ES=F', '5d', '1h', NOW).map((r) => etMinuteOfDay(Number(r.time)))
  assert.ok(es.some((m) => m < 570 || m >= 960), 'ES trades overnight')
  const weekend = Date.parse('2026-07-12T15:00:00Z') / 1000
  assert.ok(M.historicalRows('BTC-USD', '5d', '1h', weekend).some((r) => [0, 6].includes(weekday(Number(r.time)))))
  assert.ok(!M.historicalRows('SPY', '1mo', '1d', weekend).some((r) => [0, 6].includes(new Date(r.time).getUTCDay())))
})

test('ETF and futures views of one family move together', () => {
  const ratio = M.quote('ES=F', NOW).price / M.quote('SPY', NOW).price
  assert.ok(Math.abs(ratio - 10.05) < 0.05, `ES/SPY ${ratio}`)
  const g = gammaExposure('QQQ', NOW)
  assert.ok(Math.abs(g.conversionRatio - 41.2) < 0.3)
  for (const l of g.levels) assert.ok(Math.abs(l.strikeFutures - l.strikeEtf * g.conversionRatio) < 0.01)
})

test('daily bars and weekly bars are valid and cover the period', () => {
  const daily = M.historicalRows('SPY', '1y', '1d', NOW)
  assert.ok(daily.length > 250 && daily.length < 265)
  daily.forEach(assertBar)
  const weekly = M.historicalRows('SPY', '1y', '1wk', NOW)
  assert.ok(weekly.length >= 52 && weekly.length <= 54)
  assert.equal(weekly.at(-1).close, daily.at(-1).close)
  const ds = normalizeBars(daily, {})
  validateDataset({ ...ds, bars: daily.length })
})

test('GEX levels follow the backend rules', () => {
  const { strikes, spot } = gexLadder('SPY', NOW)
  const levels = keyLevels(strikes, spot)
  const call = levels.find((l) => l.label === 'call_wall')
  const put = levels.find((l) => l.label === 'put_wall')
  assert.equal(call.gex, Math.max(...strikes.map((s) => s.gex)))
  assert.equal(put.gex, Math.min(...strikes.map((s) => s.gex)))
  assert.equal(levels.filter((l) => l.label === 'significant_pos').length, 3)
  const body = gammaExposure('SPY', NOW)
  assert.equal(body.marketOpen, true)
  assert.match(body.timestamp, /^2026-07-08 11:05:00$/)
})

test('research datasets pass the frontend validator and the catalog ids round-trip', () => {
  const later = Date.parse('2026-10-01T12:00:00Z') / 1000
  const catalog = api.researchCatalog(later)
  assert.equal(catalog.datasets.length, 2)
  const entry = catalog.datasets[0]
  assert.match(entry.id, /^[a-z0-9_-]+-[a-f0-9]{64}$/)
  const ds = api.researchArtifact(entry.id, later)
  assert.equal(ds.id, entry.id)
  assert.equal(ds.bars, entry.bars)
  assert.equal(ds.start, entry.start)
  assert.equal(ds.end, entry.end)
  validateDataset(ds)
  // Tampered or not-yet-finished windows are unknown versions.
  assert.equal(api.researchArtifact(entry.id.replace(/.$/, (c) => (c === 'a' ? 'b' : 'a')), later), null)
  const { id } = api.datasetId('QQQ', M.dayNumber(2026, 9, 1), M.dayNumber(2026, 10, 1))
  assert.equal(api.researchArtifact(id, later), null)
})

test('the no-skill model really has no skill and never predicts before OOS', () => {
  const ds = researchDataset('SPY', M.dayNumber(2026, 3, 2), M.dayNumber(2026, 5, 29))
  ds.ml.pred.forEach((p, i) => assert.ok(p === null || (i >= ds.ml.oosStart && ds.ml.fold[i] !== null)))
  assert.ok(Math.abs(ds.ml.overall.ic_pearson) < 0.1)
})

test('benchmark mirrors the backend contract', () => {
  assert.match(api.benchmark('AAPL', '2026-01-02', '2026-03-02', NOW).message, /Unsupported/)
  assert.match(api.benchmark('SPY', 'jan', '2026-03-02', NOW).message, /ISO/)
  const body = api.benchmark('SPY', '2026-01-02', '2026-03-02', NOW)
  assert.ok(body.data.length > 35 && body.data.every((p) => p.adjustedClose > 0))
})

test('everything bundled under public/backtest is the synthetic sample', async () => {
  const dir = new URL('../../public/backtest/', import.meta.url)
  const index = JSON.parse(await readFile(new URL('index.json', dir), 'utf8'))
  assert.equal(index.synthetic, true)
  const files = (await readdir(dir)).filter((f) => f !== 'index.json')
  assert.deepEqual(files.sort(), index.datasets.map((d) => d.file).sort())
  for (const { symbol, file } of index.datasets) {
    const text = await readFile(new URL(file, dir), 'utf8')
    // Byte-identical to a fresh generation: real data can't slip in under this name.
    assert.equal(text, JSON.stringify(researchDataset(symbol, M.dayNumber(2026, 4, 27), M.dayNumber(2026, 7, 10))), file)
  }
})
