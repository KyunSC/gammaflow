import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createJiti } from 'jiti'
import { makeFetch, verdict, evaluateDataset, toMarkdown, breakEven, isTransient, assignVerdicts, researchEntries, nothingTested } from '../../scripts/nightly-backtest.mjs'

const jiti = createJiti(import.meta.url)
const { loadResearchDataset } = await jiti.import('./datasets.js')

const row = (holdout, research = {}, breakEvenBps = 5) => ({
  holdout: { nTrades: 20, totalReturn: 0.02, familyCi: [0.1, 2], ...holdout },
  research: { dsr: 0.97, ...research },
  breakEvenBps,
})

test('verdict: every check must pass for CANDIDATE', () => {
  assert.equal(verdict(row({})), 'CANDIDATE')
  assert.equal(verdict(row({ nTrades: 9 })), 'INSUFFICIENT')
  assert.equal(verdict(row({ totalReturn: 0 })), 'NO EDGE')
  assert.equal(verdict(row({ totalReturn: -0.01 })), 'NO EDGE')
  assert.equal(verdict(row({ familyCi: [-0.1, 2] })), 'WEAK')
  assert.equal(verdict(row({}, { dsr: 0.94 })), 'WEAK')
  assert.equal(verdict(row({}, {}, 1.5)), 'WEAK')
  assert.equal(verdict(row({}, { dsr: Number.NaN })), 'WEAK')
})

test('research-plane run: every strategy reports a holdout disjoint from its sweep', async () => {
  const original = globalThis.fetch
  globalThis.fetch = makeFetch({ apiBase: null })
  try {
    const ds = await loadResearchDataset({ symbol: 'QQQ', example: true })
    const rows = evaluateDataset(ds)
    assert.ok(rows.length >= 5)
    for (const r of rows) {
      assert.equal(r.error, undefined, `${r.strategy}: ${r.error}`)
      assert.ok(Number.isFinite(r.holdout.sharpe), r.strategy)
      assert.ok(r.research.bars <= ds.close.length - r.holdout.bars, r.strategy)
      assert.ok(r.research.trials > 1, r.strategy)
      assert.ok(['CANDIDATE', 'WEAK', 'NO EDGE', 'INSUFFICIENT'].includes(r.verdict))
    }
    const md = toMarkdown({
      generatedAt: new Date().toISOString(), engineVersion: '2', holdoutPct: 25,
      costs: { slippageBps: 1.5, commissionPerTrade: 0.5 },
      datasets: [{ label: 'QQQ 5m · research', stale: true, end: '2026-07-10T19:40:00Z', rows }],
    })
    assert.equal(md.split('\n').filter((l) => l.startsWith('| ') && !l.startsWith('| Verdict')).length, rows.length)
    assert.match(md, /stale/)
  } finally {
    globalThis.fetch = original
  }
})

test('the fetch shim never reaches the network for unrouted URLs', async () => {
  const f = makeFetch({ apiBase: null })
  await assert.rejects(f('https://example.com/x'), /Unrouted/)
  await assert.rejects(f('/api/historical'), /API_BASE/)
  assert.equal((await f('/backtest/missing.json')).status, 404)
})

test('the shim, once installed globally, forwards /api calls to the real fetch', async () => {
  const original = globalThis.fetch
  const seen = []
  globalThis.fetch = async (url, opts) => { seen.push([url, opts.headers?.['X-Api-Key']]); return { ok: true } }
  globalThis.fetch = makeFetch({ apiBase: 'https://api.test/', apiKey: 'k' })
  try {
    await globalThis.fetch('/api/historical?symbol=QQQ')
    assert.deepEqual(seen, [['https://api.test/api/historical?symbol=QQQ', 'k']])
  } finally {
    globalThis.fetch = original
  }
})

test('break-even interpolates between the last profitable rung and the first losing one', () => {
  const curve = [0, 0.5, 1, 2, 3].map((bps) => ({ slippageBps: bps, totalReturn: 0.016 - 0.01 * bps }))
  assert.ok(Math.abs(breakEven(curve) - 1.6) < 1e-9)
  assert.equal(breakEven([{ slippageBps: 0, totalReturn: -0.01 }]), 0)
  assert.equal(breakEven([{ slippageBps: 0, totalReturn: 0.01 }]), Infinity)
})

test('only transient fetch failures are retried', () => {
  assert.ok(isTransient(Object.assign(new Error('x'), { name: 'TimeoutError' })))
  assert.ok(isTransient(new TypeError('fetch failed')))
  assert.ok(isTransient(new Error('Historical fetch failed (503)')))
  assert.ok(isTransient(new Error('Historical service temporarily unavailable — retry shortly')))
  assert.ok(!isTransient(new Error('Historical fetch failed (404)')))
  assert.ok(!isTransient(new Error('No 5m bars stored for NQ=F over 1mo')))
})

test('family-wise CIs widen with the number of rows judged together', () => {
  const mk = () => ({ holdout: { nTrades: 20, totalReturn: 0.02, sr: 0.03, se: 0.01, periodsPerYear: 252 }, research: { dsr: 0.99 }, breakEvenBps: 5 })
  const one = [mk()]
  assignVerdicts(one)
  const many = Array.from({ length: 50 }, mk)
  assignVerdicts(many)
  assert.equal(one[0].verdict, 'CANDIDATE') // z = 1.96: 0.03 - 0.0196 > 0
  assert.equal(many[0].verdict, 'WEAK') // z ≈ 3.29: 0.03 - 0.0329 < 0
  assert.ok(many[0].holdout.familyCi[0] < one[0].holdout.familyCi[0])
})

// --- research plane: the published backend datasets, behind a stubbed network ---

const API = 'https://api.test'
const VERSION = 'a'.repeat(64)
const ID = `qqq-5m-${VERSION}`
const CATALOG = '/api/backtest/datasets'
const ARTIFACT = `${CATALOG}/${ID}`
const catalog = (extra = {}, entry = {}) => ({ schemaVersion: 1, datasets: [{ id: ID, symbol: 'QQQ', interval: '5m', ...entry }], ...extra })
const fixture = JSON.parse(await readFile(new URL('../../public/backtest/qqq_5m.json', import.meta.url), 'utf8'))
const artifact = (extra = {}) => ({ ...fixture, synthetic: false, id: ID, version: VERSION, schemaVersion: 1, ...extra })
const report = (datasets) => ({ generatedAt: new Date().toISOString(), engineVersion: '2', holdoutPct: 25, costs: { slippageBps: 1.5, commissionPerTrade: 0.5 }, datasets })

/**
 * Runs `researchEntries` with `routes` (path → body, HTTP status, or Error to
 * throw) as the backend, through the real shim. `urls` is every URL the loaders
 * asked for, so a request for the bundled example would show up.
 */
async function runResearch(routes, { apiBase = API, apiKey = 'k' } = {}) {
  const original = globalThis.fetch
  const urls = []
  const keys = []
  globalThis.fetch = async (url, opts) => {
    keys.push(opts.headers?.['X-Api-Key'])
    const res = routes[url.slice(API.length)] ?? 404
    if (res instanceof Error) throw res
    return typeof res === 'number' ? { ok: false, status: res, json: async () => ({}) } : { ok: true, status: 200, json: async () => res }
  }
  const shim = makeFetch({ apiBase, apiKey })
  globalThis.fetch = (url, opts) => { urls.push(url); return shim(url, opts) }
  try {
    const entries = await researchEntries({ apiBase, apiKey, waitMs: 0 })
    assert.ok(!urls.some((u) => u.startsWith('/backtest/')), `requested the bundled example: ${urls}`)
    return { entries, urls, keys }
  } finally {
    globalThis.fetch = original
  }
}

test('research skip: no backend, or a synthetic or empty catalog, is a skip and never a failure', async () => {
  const cases = [
    [{ [CATALOG]: catalog() }, { apiBase: '' }, /no API_BASE/],
    [{ [CATALOG]: 401 }, { apiKey: '' }, /GAMMAFLOW_API_KEY is not set/],
    [{ [CATALOG]: catalog({ synthetic: true }) }, {}, /catalog is synthetic/],
    [{ [CATALOG]: catalog({ datasets: [] }) }, {}, /no datasets/],
    [{ [CATALOG]: catalog({}, { synthetic: true }) }, {}, /entry is synthetic/],
    [{ [CATALOG]: catalog(), [ARTIFACT]: artifact({ synthetic: true }) }, {}, /dataset is synthetic/],
  ]
  for (const [routes, opts, reason] of cases) {
    const { entries } = await runResearch(routes, opts)
    assert.equal(entries.length, 1)
    assert.match(entries[0].skipped, reason)
    assert.equal(entries[0].error, undefined)
    assert.equal(entries[0].rows, undefined)
  }
  assert.deepEqual((await runResearch({}, { apiBase: '' })).urls, [])
})

test('research failure: a fetch that should have worked stays a failure, with no example fallback', async () => {
  const cases = [
    [{ [CATALOG]: 503 }, {}, 'research index', /\(503\)/], // also what an unpublished backend answers
    [{ [CATALOG]: 401 }, {}, 'research index', /\(401\)/], // a key was sent and refused
    [{ [CATALOG]: new TypeError('fetch failed') }, {}, 'research index', /fetch failed/],
    [{ [CATALOG]: { datasets: [] } }, {}, 'research index', /Unsupported/],
    [{ [CATALOG]: catalog(), [ARTIFACT]: 404 }, {}, 'QQQ · research', /version unavailable/],
    [{ [CATALOG]: catalog(), [ARTIFACT]: artifact({ id: 'other' }) }, {}, 'QQQ · research', /mismatch/],
  ]
  for (const [routes, opts, label, message] of cases) {
    const { entries } = await runResearch(routes, opts)
    assert.equal(entries.length, 1)
    assert.equal(entries[0].label, label)
    assert.match(entries[0].error, message)
    assert.equal(entries[0].skipped, undefined)
  }
  const { urls } = await runResearch({ [CATALOG]: 503 })
  assert.equal(urls.length, 3) // Transient: worth the retries.
})

test('research success: published datasets are scored with the key and run GEX and ML strategies', async () => {
  const { entries, urls, keys } = await runResearch({ [CATALOG]: catalog(), [ARTIFACT]: artifact() })
  assert.deepEqual(urls, [CATALOG, ARTIFACT])
  assert.deepEqual(keys, ['k', 'k'])
  assert.equal(entries.length, 1)
  const [entry] = entries
  assert.equal(entry.plane, 'research')
  assert.equal(entry.label, 'QQQ 5m · research')
  const families = new Set(entry.rows.map((r) => r.family))
  assert.ok(families.has('gex') && families.has('ml'), [...families].join())
  assert.ok(entry.rows.every((r) => !r.error))
  assert.equal(assignVerdicts(entry.rows), entry.rows.length)
})

test('the report published from a research run holds aggregates, never the underlying data', async () => {
  const { entries } = await runResearch({ [CATALOG]: catalog(), [ARTIFACT]: artifact() })
  const banned = new Set(['open', 'high', 'low', 'close', 'volume', 'time', 'features', 'ml', 'pred', 'target', 'id', 'version'])
  const walk = (v, path) => {
    if (Array.isArray(v)) assert.ok(v.length <= 8, `series at ${path}`) // The longest aggregate is the cost ladder.
    if (v && typeof v === 'object') for (const [k, c] of Object.entries(v)) {
      assert.ok(!banned.has(k), `${path}.${k}`)
      walk(c, `${path}.${k}`)
    }
  }
  walk(entries, 'entries')
  const text = JSON.stringify(entries) + toMarkdown(report(entries))
  assert.ok(!text.includes(VERSION))
  for (const i of [100, 2000, 4000]) assert.ok(!text.includes(String(fixture.close[i])), `close[${i}]`)
})

test('a skip stays out of the family and the failures, and a failure stays out of the skips', () => {
  const rows = () => [{ strategy: 'ema', family: 'ta', bestParams: { fast: 5 }, holdout: { nTrades: 20, totalReturn: 0.02, sharpe: 1, sr: 0.03, se: 0.01, periodsPerYear: 252 }, research: { dsr: 0.99, sharpe: 1 }, walkForward: { error: 'short' }, breakEvenBps: 5 }]
  const tested = { label: 'QQQ 5m · live 1mo', plane: 'live', rows: rows() }
  const skip = { label: 'research datasets', plane: 'research', skipped: 'backend catalog is synthetic, not market data' }
  const fail = { label: 'research index', plane: 'research', error: 'Dataset service unavailable (503)' }

  const datasets = [tested, skip]
  assert.equal(assignVerdicts(datasets.flatMap((d) => d.rows || [])), 1)
  const skippedMd = toMarkdown(report(datasets))
  assert.match(skippedMd, /### Skipped \(deliberately not tested\)\n- research datasets: backend catalog is synthetic/)
  assert.doesNotMatch(skippedMd, /dataset failed|### Failed/)

  const failedMd = toMarkdown(report([tested, fail]))
  assert.match(failedMd, /### Failed\n- research index: dataset failed — Dataset service unavailable \(503\)/)
  assert.doesNotMatch(failedMd, /### Skipped/)
})

test('the run only fails when nothing was tested, and a skip does not count as tested', () => {
  const liveFailed = { label: 'QQQ 5m · live 1mo', plane: 'live', error: 'Historical fetch failed (503)' }
  const skip = { label: 'research datasets', plane: 'research', skipped: 'no API_BASE configured' }
  assert.equal(nothingTested([liveFailed, skip]), true)
  assert.equal(nothingTested([liveFailed, skip, { label: 'SPY 5m · research', rows: [] }]), false)
})
