import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
import { isLegacyCacheKey, sweepLegacyCaches, SWEEP_FLAG_KEY, SWEEP_VERSION } from './legacyCacheSweep.mjs'

const jiti = createJiti(import.meta.url)
const { loadResearchIndex } = await jiti.import('./backtest/datasets.js')

// The parts of the Storage API the sweep uses, in the same shape as the browser's.
class FakeStorage {
  constructor(entries = {}, { quota = Infinity } = {}) {
    this.map = new Map(Object.entries(entries))
    this.quota = quota
  }
  get length() { return this.map.size }
  key(i) { return [...this.map.keys()][i] ?? null }
  getItem(k) { return this.map.has(k) ? this.map.get(k) : null }
  setItem(k, v) {
    const used = [...this.map].reduce((sum, [key, val]) => sum + (key === k ? 0 : val.length), 0)
    if (used + v.length > this.quota) throw new Error('QuotaExceededError')
    this.map.set(k, v)
  }
  removeItem(k) { this.map.delete(k) }
}

// Exactly the keys origin/main wrote.
const LEGACY = [
  'marketDataCache:ES=F,NQ=F,SPY,QQQ,^VIX,XEQT.TO',
  'marketDataCache:BTC-USD,ETH-USD,SOL-USD',
  'historicalDataCache:NQ=F|1d|1m',
  'historicalDataCache:^VIX|5d|5m',
  'backtestCache:/api/backtest/datasets',
  'backtestCache:/api/backtest/datasets/spy-5m-abc',
]

const CURRENT = [
  'marketDataCache:synthetic:ES=F,NQ=F,SPY,QQQ,^VIX,XEQT.TO',
  'marketDataCache:real:BTC-USD,ETH-USD,SOL-USD',
  'historicalDataCache:synthetic:NQ=F|1d|1m',
  'historicalDataCache:real:^VIX|5d|5m',
  'backtestCache:synthetic:/api/backtest/datasets',
  'backtestCache:real:/api/backtest/datasets/spy-5m-abc',
]

const PREFERENCES = [
  'candlestick-chart-colors',
  'chart-timezone',
  'chart-active-indicators',
  'chart-indicator-overrides',
  'chartRange_NQ=F',
  'vpColors',
  'vpSide',
  'trendLogicTable:config',
  'backtest:advanced',
]

const seed = (keys) => Object.fromEntries(keys.map((k) => [k, 'x']))

// Runs fn with the global `localStorage` defined as given (a descriptor).
async function withGlobalStorage(descriptor, fn) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, ...descriptor })
  try {
    return await fn()
  } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
  }
}

test('classifies old keys as legacy and leaves source-prefixed keys alone', () => {
  for (const key of LEGACY) assert.equal(isLegacyCacheKey(key), true, key)
  for (const key of [...CURRENT, ...PREFERENCES, SWEEP_FLAG_KEY]) assert.equal(isLegacyCacheKey(key), false, key)
})

test('a prefix only matches at the start of a key, and needs its colon', () => {
  for (const key of ['historicalDataCache', 'mymarketDataCache:SPY', 'backtestCacheV2:/x', 'realmarketDataCache:SPY']) {
    assert.equal(isLegacyCacheKey(key), false, key)
  }
})

test('removes every legacy key and keeps everything else', () => {
  // Interleaved so a sweep that removed while walking by index would skip some.
  const keys = LEGACY.flatMap((k, i) => [k, CURRENT[i]]).concat(PREFERENCES)
  const storage = new FakeStorage(seed(keys))
  sweepLegacyCaches(storage)
  for (const key of LEGACY) assert.equal(storage.getItem(key), null, key)
  for (const key of [...CURRENT, ...PREFERENCES]) assert.equal(storage.getItem(key), 'x', key)
  assert.equal(storage.getItem(SWEEP_FLAG_KEY), SWEEP_VERSION)
})

test('runs once per browser', () => {
  const storage = new FakeStorage(seed(LEGACY))
  sweepLegacyCaches(storage)
  storage.setItem(LEGACY[0], 'written later')
  sweepLegacyCaches(storage)
  assert.equal(storage.getItem(LEGACY[0]), 'written later')
})

test('a different flag version sweeps again', () => {
  const storage = new FakeStorage({ ...seed(LEGACY), [SWEEP_FLAG_KEY]: '0' })
  sweepLegacyCaches(storage)
  for (const key of LEGACY) assert.equal(storage.getItem(key), null, key)
  assert.equal(storage.getItem(SWEEP_FLAG_KEY), SWEEP_VERSION)
})

test('frees the quota a new cache key needs', () => {
  const storage = new FakeStorage({ [LEGACY[2]]: 'x'.repeat(90) }, { quota: 100 })
  const key = CURRENT[2]
  assert.throws(() => storage.setItem(key, 'y'.repeat(50)), /Quota/)
  sweepLegacyCaches(storage)
  storage.setItem(key, 'y'.repeat(50))
  assert.equal(storage.getItem(key).length, 50)
})

test('uses the global localStorage by default', async () => {
  const storage = new FakeStorage(seed(LEGACY))
  await withGlobalStorage({ value: storage }, () => sweepLegacyCaches())
  for (const key of LEGACY) assert.equal(storage.getItem(key), null, key)
})

test('is a no-op without localStorage (SSR)', async () => {
  await withGlobalStorage({ value: undefined }, () => assert.doesNotThrow(() => sweepLegacyCaches()))
})

test('survives a localStorage that throws on access (blocked site data)', async () => {
  const get = () => { throw new Error('SecurityError') }
  await withGlobalStorage({ get }, () => assert.doesNotThrow(() => sweepLegacyCaches()))
})

test('swallows storage errors and leaves the flag unset so a later write retries', () => {
  const storage = new FakeStorage(seed(LEGACY))
  const removeItem = storage.removeItem.bind(storage)
  storage.removeItem = () => { throw new Error('SecurityError') }
  assert.doesNotThrow(() => sweepLegacyCaches(storage))
  assert.equal(storage.getItem(SWEEP_FLAG_KEY), null)

  storage.removeItem = removeItem
  sweepLegacyCaches(storage)
  for (const key of LEGACY) assert.equal(storage.getItem(key), null, key)

  const denied = { getItem() { throw new Error('SecurityError') } }
  assert.doesNotThrow(() => sweepLegacyCaches(denied))
})

test('the backtest dataset cache sweeps before its first write', async () => {
  const storage = new FakeStorage(seed([LEGACY[4], ...PREFERENCES]))
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ schemaVersion: 1, datasets: [] }) })
  try {
    await withGlobalStorage({ value: storage }, () => loadResearchIndex())
  } finally { globalThis.fetch = originalFetch }
  assert.equal(storage.getItem(LEGACY[4]), null)
  assert.notEqual(storage.getItem(CURRENT[4]), null)
  for (const key of PREFERENCES) assert.equal(storage.getItem(key), 'x', key)
})
