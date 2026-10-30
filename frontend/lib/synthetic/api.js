/**
 * Request handling shared by the synthetic /api/* routes (app/api/**). Bodies
 * match the Spring backend's, so the pages can't tell the difference; the
 * X-Data-Source header and each payload's `synthetic: true` say what they are.
 */
import { createHash } from 'node:crypto'
import { GENERATOR_VERSION, dayString, dayNumber, etToUtc, lastSessionDay, previousTradingDay, sessionWindow, symbolSpec, tradingDays, dayBar } from './market'
import { datasetQuality, researchDataset } from './research'

const HEADERS = { 'X-Data-Source': 'synthetic' }

export function json(body, { status = 200, cache = 'no-store' } = {}) {
  return Response.json(body, { status, headers: { ...HEADERS, 'Cache-Control': cache } })
}

export const error = (status, message) => json({ message, synthetic: true }, { status })

const SYMBOL = /^[A-Za-z0-9.^=_-]{1,20}$/
/** Upper-cased symbol, or null when it isn't a plausible ticker. */
export function cleanSymbol(raw) {
  const s = (raw || '').trim()
  return SYMBOL.test(s) ? s.toUpperCase() : null
}

export const nowSeconds = () => Date.now() / 1000

// --- research catalog ------------------------------------------------------------

export const RESEARCH_SYMBOLS = ['QQQ', 'SPY']
const CATALOG_SESSIONS = 60
const MAX_SESSIONS = 260
const BARS_PER_SESSION = 78

const compact = (day) => dayString(day).replaceAll('-', '')
const fromCompact = (s) => dayNumber(+s.slice(0, 4), +s.slice(4, 6), +s.slice(6, 8))
const sha256 = (s) => createHash('sha256').update(s).digest('hex')

/** Versioned id in the backend's format ([a-z0-9_-]+-<64 hex>), carrying its own window. */
export function datasetId(symbol, from, to) {
  const tag = `synthetic-${symbol.toLowerCase()}-5m-${compact(from)}-${compact(to)}`
  const version = sha256(`v${GENERATOR_VERSION}|${tag}`)
  return { id: `${tag}-${version}`, version }
}

/** {symbol, from, to, version} for an id this generator issued, else null. */
export function parseDatasetId(id, now = nowSeconds()) {
  const m = /^synthetic-([a-z]+)-5m-(\d{8})-(\d{8})-([a-f0-9]{64})$/.exec(id || '')
  if (!m) return null
  const symbol = m[1].toUpperCase()
  const from = fromCompact(m[2])
  const to = fromCompact(m[3])
  if (!RESEARCH_SYMBOLS.includes(symbol) || !(from <= to) || datasetId(symbol, from, to).id !== id) return null
  const spec = symbolSpec(symbol)
  const days = tradingDays(spec, from, to)
  const [start, minutes] = sessionWindow('rth', to)
  if (!days.length || days.length > MAX_SESSIONS || start + minutes * 60 > now) return null
  return { symbol, from, to, version: m[4] }
}

/** The last `CATALOG_SESSIONS` finished RTH sessions. */
export function catalogWindow(now = nowSeconds()) {
  const spec = symbolSpec('SPY')
  let to = lastSessionDay(spec, now)
  const [start, minutes] = sessionWindow('rth', to)
  if (start + minutes * 60 > now) to = previousTradingDay(spec, to)
  let from = to
  for (let k = 1; k < CATALOG_SESSIONS; k++) from = previousTradingDay(spec, from)
  return { from, to }
}

const iso = (t) => new Date(t * 1000).toISOString().replace('.000Z', '+00:00')

/** Body of GET /api/backtest/datasets. */
export function researchCatalog(now = nowSeconds()) {
  const { from, to } = catalogWindow(now)
  const sessions = tradingDays(symbolSpec('SPY'), from, to).length
  return {
    schemaVersion: 1,
    synthetic: true,
    generatedAt: `${dayString(to + 1)}T00:00:00+00:00`,
    datasets: RESEARCH_SYMBOLS.map((symbol) => ({
      ...datasetId(symbol, from, to),
      schemaVersion: 1,
      symbol,
      interval: '5m',
      bars: sessions * BARS_PER_SESSION,
      start: iso(etToUtc(from, 570)),
      end: iso(etToUtc(to, 955)),
      generatedAt: `${dayString(to + 1)}T00:00:00+00:00`,
      capabilities: { gex: true, ml: true },
      quality: { gapsOver5Minutes: sessions - 1, predictionValidation: 'synthetic-random', completedBarsOnly: true },
      hasMl: true,
      synthetic: true,
    })),
  }
}

const built = new Map()
/** Body of GET /api/backtest/datasets/{id}, or null for an unknown id. */
export function researchArtifact(id, now = nowSeconds()) {
  const parsed = parseDatasetId(id, now)
  if (!parsed) return null
  let ds = built.get(id)
  if (!ds) {
    ds = researchDataset(parsed.symbol, parsed.from, parsed.to)
    ds.quality = datasetQuality(ds)
    ds.schemaVersion = 1
    ds.capabilities = { gex: true, ml: true }
    ds.id = id
    ds.version = parsed.version
    built.set(id, ds)
    if (built.size > 4) built.delete(built.keys().next().value)
  }
  return ds
}

// --- benchmark ---------------------------------------------------------------------

export const BENCHMARK_SYMBOLS = ['SPY', 'QQQ', 'XEQT.TO']
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

/** Body of GET /api/backtest/benchmark, or an Error carrying the backend's 400 message. */
export function benchmark(symbol, start, end, now = nowSeconds()) {
  if (!BENCHMARK_SYMBOLS.includes(symbol)) return new Error('Unsupported benchmark')
  if (!ISO_DATE.test(start || '') || !ISO_DATE.test(end || '')) return new Error('Use ISO dates for benchmark coverage')
  const from = Date.parse(`${start}T00:00:00Z`) / 86400000
  const to = Date.parse(`${end}T00:00:00Z`) / 86400000
  const spec = symbolSpec(symbol)
  const today = lastSessionDay(spec, now)
  if (!(to >= from) || from < to - 3653 || to > today + 1) return new Error('Benchmark range must be historical and at most ten years')
  const data = tradingDays(spec, from, Math.min(to, today - 1))
    .map((d) => dayBar(spec, d, now))
    .filter(Boolean)
    .map((b) => ({ date: dayString(b.t), adjustedClose: b.c }))
  if (data.length < 2) return new Error('At least two completed daily closes required')
  return { symbol, currency: symbol === 'XEQT.TO' ? 'CAD' : 'USD', priceBasis: 'adjusted-close', synthetic: true, data }
}
