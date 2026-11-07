import test from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFile, readdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
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

const et = (s) => Date.parse(`${s}-04:00`) / 1000 // October dates, EDT.
const closes = (s) => s.data.map((p) => p.date)

test('benchmark limits use the New York calendar date, like BenchmarkService', () => {
  const range = /must be historical/
  // Friday 2026-10-23 is the last close over the weekend, and the end date may be today.
  const saturday = et('2026-10-24T12:00:00')
  assert.equal(closes(api.benchmark('SPY', '2026-10-01', '2026-10-24', saturday)).at(-1), '2026-10-23')
  const sunday = et('2026-10-25T12:00:00')
  assert.equal(closes(api.benchmark('SPY', '2026-10-01', '2026-10-25', sunday)).at(-1), '2026-10-23')
  const mondayPremarket = et('2026-10-26T08:00:00')
  assert.equal(closes(api.benchmark('SPY', '2026-10-01', '2026-10-26', mondayPremarket)).at(-1), '2026-10-23')
  const tuesdayPremarket = et('2026-10-27T08:00:00')
  assert.equal(closes(api.benchmark('SPY', '2026-10-01', '2026-10-27', tuesdayPremarket)).at(-1), '2026-10-26')
  // Today never counts as a completed close, even after the bell.
  assert.equal(closes(api.benchmark('SPY', '2026-10-01', '2026-10-27', et('2026-10-27T17:00:00'))).at(-1), '2026-10-26')
  // 23:30 ET is already tomorrow in UTC, and tomorrow is still rejected.
  assert.match(api.benchmark('SPY', '2026-10-01', '2026-10-28', et('2026-10-27T23:30:00')).message, range)
  assert.match(api.benchmark('SPY', '2026-10-01', '2026-10-27', sunday).message, range)
})

test('benchmark date parsing and the ten-year limit follow LocalDate', () => {
  const later = et('2026-10-27T12:00:00')
  assert.match(api.benchmark('SPY', '2026-02-30', '2026-03-02', later).message, /ISO/)
  assert.match(api.benchmark('SPY', '2026-13-01', '2026-03-02', later).message, /ISO/)
  assert.ok(api.benchmark('SPY', '2016-03-01', '2026-03-01', later).data)
  assert.match(api.benchmark('SPY', '2016-02-29', '2026-03-01', later).message, /at most ten years/)
  // Feb 29 minus ten years clamps to Feb 28.
  assert.ok(api.benchmark('SPY', '2014-02-28', '2024-02-29', later).data)
  assert.match(api.benchmark('SPY', '2014-02-27', '2024-02-29', later).message, /at most ten years/)
  // Too few closes reach the backend's provider catch: a 503, not a 400.
  const thin = api.benchmark('SPY', '2026-10-24', '2026-10-25', later)
  assert.equal(thin.status, 503)
})

test('bodies over the buffered limit stream the same bytes', async () => {
  const data = M.historicalRows('BTC-USD', '6mo', '5m', NOW)
  assert.ok(data.length > 50_000)
  const body = { symbol: 'BTC-USD', period: '6mo', interval: '5m', timestamp: M.timestamp(NOW), synthetic: true, data, unavailable: false, lastFetched: null }
  const text = JSON.stringify(body)
  assert.ok(text.length > 5e6, 'the case that overflowed 4.5 MB')
  const res = api.json(body)
  assert.equal(res.headers.get('content-type'), 'application/json')
  assert.equal(res.headers.get('x-data-source'), 'synthetic')
  const chunks = []
  for await (const chunk of res.body) chunks.push(chunk)
  assert.ok(chunks.length > 50 && chunks.every((c) => c.length <= 65536))
  assert.equal(Buffer.concat(chunks).toString(), text)
  // Everything else stays one plain body, and errors keep their status.
  const small = []
  for await (const chunk of api.json({ ok: true }).body) small.push(chunk)
  assert.equal(small.length, 1)
  assert.equal(api.error(400, 'x').status, 400)
})

test('the historical route answers the largest crypto request in the usual shape', async () => {
  const { GET } = await jiti.import('../../app/api/historical/route.js')
  const res = GET(new Request('http://test/api/historical?symbol=BTC-USD&period=1y&interval=5m'))
  assert.equal(res.status, 200)
  const body = await res.json()
  assert.deepEqual(Object.keys(body), ['symbol', 'period', 'interval', 'timestamp', 'synthetic', 'data', 'unavailable', 'lastFetched'])
  assert.deepEqual(Object.keys(body.data[0]), ['time', 'open', 'high', 'low', 'close', 'volume'])
  assert.ok(body.data.length > 50_000)
})

// What the ticker page does with a /since response.
const mergeBars = (bars, fresh) => bars.filter((b) => Number(b.time) < Number(fresh[0].time)).concat(fresh)

test('/since starts at since, so a chart that slept two weeks has no hole', () => {
  const now = et('2026-10-30T11:00:00')
  const since = et('2026-10-14T09:30:00')
  const rows = M.rowsSince('SPY', '5m', since, now)
  assert.equal(Number(rows[0].time), since)
  const full = M.historicalRows('SPY', '1mo', '5m', now)
  const stale = full.filter((b) => Number(b.time) <= since)
  assert.deepEqual(mergeBars(stale, rows), full)
  // Daily bars too, not just the last five sessions.
  const daily = M.rowsSince('SPY', '1d', since, now)
  assert.equal(daily.at(-1).time, '2026-10-30')
  assert.ok(daily.length >= 12)
})

test('/since far behind stays bounded and catches up without a gap', () => {
  const now = Math.floor(NOW / 60) * 60
  const since = now - 120 * 86400
  let bars = [{ time: String(since) }]
  let polls = 0
  while (Number(bars.at(-1).time) < now && polls < 20) {
    const rows = M.rowsSince('BTC-USD', '1m', Number(bars.at(-1).time), now)
    assert.equal(rows[0].time, bars.at(-1).time, 'each response starts on the last bar held')
    assert.ok(rows.length <= 33 * 1440, `unbounded: ${rows.length}`)
    bars = mergeBars(bars, rows)
    polls++
  }
  assert.ok(polls >= 4 && polls < 20, `${polls} polls`)
  for (let i = 1; i < bars.length; i++) assert.equal(Number(bars[i].time) - Number(bars[i - 1].time), 60)
  // A since before the history starts at the history, not at the newest bars.
  assert.equal(M.etDay(Number(M.rowsSince('SPY', '5m', -1e15, NOW)[0].time)), M.FIRST_DAY)
})

test('caches stay bounded under unknown symbols and rebuild identically', () => {
  const unknown = { quote: M.quote('ZQX1', NOW), rows: M.historicalRows('ZQX1', '5d', '5m', NOW), spec: { ...M.symbolSpec('ZQX1') } }
  const known = { quote: M.quote('SPY', NOW), rows: M.historicalRows('ES=F', '5d', '1h', NOW) }
  for (let i = 0; i < 600; i++) M.quote(`U${i}`, NOW)
  const sizes = M.cacheSizes()
  for (const [name, size] of Object.entries(sizes)) assert.ok(size <= 256, `${name}: ${size}`)
  assert.deepEqual(M.quote('ZQX1', NOW), unknown.quote)
  assert.deepEqual(M.historicalRows('ZQX1', '5d', '5m', NOW), unknown.rows)
  assert.deepEqual({ ...M.symbolSpec('ZQX1') }, unknown.spec)
  assert.deepEqual(M.quote('SPY', NOW), known.quote)
  assert.deepEqual(M.historicalRows('ES=F', '5d', '1h', NOW), known.rows)
})

// A synchronous spin can't be timed out from inside this process, so anything
// that could hang runs in a child that spawnSync kills, and the test fails fast.
function inChild(body) {
  const script = `
    import { createJiti } from 'jiti'
    const jiti = createJiti(${JSON.stringify(import.meta.url)})
    const M = await jiti.import('./market.js')
    const route = (path) => jiti.import('../../app/api/' + path + '/route.js')
    console.log(JSON.stringify(await (async () => {${body}})()))
  `
  const cwd = fileURLToPath(new URL('../..', import.meta.url))
  const run = spawnSync(process.execPath, ['--input-type=module', '-e', script], { cwd, encoding: 'utf8', timeout: 30_000 })
  assert.equal(run.signal, null, 'hung until the 30s timeout')
  assert.equal(run.status, 0, run.stderr)
  return JSON.parse(run.stdout)
}

test('calendar walks end on any input', () => {
  const out = inChild(`
    const spec = M.symbolSpec('SPY')
    const last = M.lastSessionDay(spec, ${NOW})
    return {
      outOfRange: M.previousTradingDay(spec, -2e8),
      notANumber: M.previousTradingDay(spec, NaN),
      starts: ['200000000d', '9'.repeat(400) + 'd', '9'.repeat(400) + 'y', '99999999mo', '99999999wk'].map((p) => M.periodStart(spec, p, last)),
      huge: M.historicalRows('SPY', '200000000d', '1d', ${NOW}).length,
      max: M.historicalRows('SPY', 'max', '1d', ${NOW}).length,
    }
  `)
  assert.equal(out.outOfRange, -2e8 - 1)
  assert.equal(out.notANumber, null)
  assert.deepEqual(out.starts, new Array(5).fill(M.FIRST_DAY))
  assert.equal(out.huge, out.max)
})

test('no request can hang a route', () => {
  const out = inChild(`
    const huge = '9'.repeat(400)
    const url = (path, query) => new Request('http://test/api/' + path + '?' + query)
    const out = {}
    const historical = await route('historical')
    for (const period of ['200000000d', huge + 'd', huge + 'wk', huge + 'mo', huge + 'y', '-5d', 'Infinityd', '1e9d', 'max', '']) {
      for (const interval of ['1d', '1wk', '1mo', '1m', 'constructor', '__proto__', 'nonsense']) {
        const res = historical.GET(url('historical', 'symbol=SPY&period=' + period + '&interval=' + interval))
        out['historical ' + period.slice(0, 12) + ' ' + interval] = [res.status, (await res.json()).data.length]
      }
    }
    const since = await route('historical/since')
    for (const value of ['0', '-1', '-99999999999999', '9999999999999999', '1e400', 'Infinity', 'NaN', 'abc', '']) {
      for (const interval of ['1m', '1h', '1d', '1wk', 'constructor']) {
        const res = since.GET(url('historical/since', 'symbol=SPY&since=' + value + '&interval=' + interval))
        out['since ' + value.slice(0, 12) + ' ' + interval] = [res.status]
      }
    }
    out['since missing'] = [since.GET(url('historical/since', 'symbol=SPY&interval=1m')).status]
    const benchmark = await route('backtest/benchmark')
    for (const q of ['start=0000-01-01&end=9999-12-31', 'start=9999-12-31&end=9999-12-31', 'start=2026-02-30&end=2026-02-31', 'start=x&end=y', '']) {
      out['benchmark ' + q] = [benchmark.GET(url('backtest/benchmark', q)).status]
    }
    const dataset = await jiti.import('../../app/api/backtest/datasets/[id]/route.js')
    const { createHash } = await import('node:crypto')
    const tag = 'synthetic-spy-5m-20260101-99991231'
    const forged = tag + '-' + createHash('sha256').update('v1|' + tag).digest('hex')
    out['dataset far future'] = [(await dataset.GET(url('x', ''), { params: Promise.resolve({ id: forged }) })).status]
    for (const [path, query] of [['market', 'tickers=' + 'A,'.repeat(500)], ['market/live', 'symbol=ZZZ'], ['gamma', 'symbol=ZZZ'], ['historical/recent', 'symbol=ZZZ']]) {
      out[path] = [(await route(path)).GET(url(path, query)).status]
    }
    return out
  `)
  for (const [name, [status]] of Object.entries(out)) assert.ok(status === 200 || status === 400 || status === 404 || status === 503, `${name}: ${status}`)
  assert.deepEqual(out['since missing'], [400])
  assert.deepEqual(out['since abc 1m'], [400])
  assert.deepEqual(out['since 999999999999 1m'], [200])
  assert.deepEqual(out['dataset far future'], [404])
  // A period past the history is the whole history, not an empty chart.
  assert.deepEqual(out['historical 200000000d 1d'], out['historical max 1d'])
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
