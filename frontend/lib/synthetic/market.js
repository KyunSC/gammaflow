/**
 * Synthetic market data for the public site.
 *
 * Yahoo prices, the in-house GEX built from Yahoo option chains, and anything
 * bought from Databento or ThetaData can't be redistributed, so a deployed
 * build never serves them (see lib/dataSource.mjs). It serves these instead:
 * prices that look and behave like the real symbols (sessions, overnight
 * gaps, U-shaped intraday volatility and volume, volatility regimes, fat
 * tails) but come from a seeded random walk and carry no information about
 * any real market. Nothing here is fit to, or derived from, real data.
 *
 * Everything is a pure function of (symbol, time), so a full fetch, a /since
 * poll and the live tick all agree, and two visitors see the same chart.
 *
 * Layout: each "family" (S&P, Nasdaq, Bitcoin, ...) has one daily close chain
 * and, per trading day, one minute-by-minute path bridged between the
 * previous close and that day's close. Symbols are views of a family: ES=F is
 * the S&P family over the Globex session, SPY is the same path over RTH at
 * 1/10.05 the price, so GEX levels line up across ETF and futures charts.
 * No exchange holidays: every weekday trades.
 */
import { etOffsetMinutes } from '../backtest/time'

export const GENERATOR_VERSION = 1
const DAY = 86400

export const dayNumber = (y, m, d) => Date.UTC(y, m - 1, d) / 86400000
export const dayString = (n) => new Date(n * 86400000).toISOString().slice(0, 10)
const weekdayOf = (n) => new Date(n * 86400000).getUTCDay()

/** Earliest synthetic history; requests reaching further back are clamped. */
export const FIRST_DAY = dayNumber(2016, 1, 4)
/** Family base prices are pinned on this day; the chain walks out both ways. */
const ANCHOR_DAY = dayNumber(2025, 1, 2)

// --- seeded randomness -------------------------------------------------------

// FNV-1a: string -> 32-bit seed.
export function hash(str) {
  let h = 0x811c9dc5
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

// mulberry32: small seeded PRNG returning [0, 1).
export function rng(seed) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function gaussian(rand) {
  const u = 1 - rand()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand())
}

// --- ET calendar ---------------------------------------------------------------

/** UTC epoch seconds of New York wall time `minute` (0-1439) on day `day`. */
export function etToUtc(day, minute) {
  const wall = day * DAY + minute * 60
  const guess = wall + 300 * 60
  return wall - etOffsetMinutes(wall - etOffsetMinutes(guess) * 60) * 60
}

/** New York calendar day of an epoch second. */
export function etDay(t) {
  return Math.floor((t + etOffsetMinutes(t) * 60) / DAY)
}

// --- families and symbols ------------------------------------------------------

// session: 'globex' (18:00 ET prior day to 17:00 ET), 'rth' (09:30-16:00 ET),
// 'utc24' (crypto, every calendar day).
const FAMILY_DEFS = {
  spx: { base: 5900, vol: 0.16, drift: 0.07, session: 'globex' },
  ndx: { base: 21000, vol: 0.21, drift: 0.09, session: 'globex' },
  rut: { base: 2250, vol: 0.22, drift: 0.05, session: 'globex' },
  dji: { base: 42500, vol: 0.15, drift: 0.06, session: 'globex' },
  btc: { base: 95000, vol: 0.55, drift: 0.2, session: 'utc24' },
  eth: { base: 3400, vol: 0.7, drift: 0.15, session: 'utc24' },
  sol: { base: 190, vol: 0.9, drift: 0.1, session: 'utc24' },
  xeqt: { base: 31, vol: 0.12, drift: 0.07, session: 'rth' },
  // Tracks the S&P family's volatility regime rather than walking freely.
  vix: { base: 16, vol: 0.9, drift: 0, session: 'rth', tracks: 'spx' },
}

// [family, price scale vs family, tick, typical daily volume]
const SYMBOL_DEFS = {
  'ES=F': ['spx', 1, 0.25, 1.6e6],
  SPY: ['spx', 1 / 10.05, 0.01, 6.5e7],
  'NQ=F': ['ndx', 1, 0.25, 6e5],
  QQQ: ['ndx', 1 / 41.2, 0.01, 4.5e7],
  'RTY=F': ['rut', 1, 0.1, 1.5e5],
  IWM: ['rut', 1 / 10.2, 0.01, 3e7],
  'YM=F': ['dji', 1, 1, 1.5e5],
  DIA: ['dji', 1 / 100.3, 0.01, 3.5e6],
  'BTC-USD': ['btc', 1, 0.01, 3e10],
  'ETH-USD': ['eth', 1, 0.01, 1.5e10],
  'SOL-USD': ['sol', 1, 0.01, 3e9],
  '^VIX': ['vix', 1, 0.01, 0],
  'XEQT.TO': ['xeqt', 1, 0.01, 4e5],
}

/** Index ETF -> the futures contract that shares its family (for GEX strike conversion). */
export const FUTURES_FOR = { SPY: 'ES=F', QQQ: 'NQ=F', IWM: 'RTY=F', DIA: 'YM=F' }

const families = new Map()
const symbols = new Map()

function family(key, def) {
  let f = families.get(key)
  if (f) return f
  const r = rng(hash(`family:${key}`))
  f = { key, ...def, phases: [r() * 6.283, r() * 6.283, r() * 6.283] }
  families.set(key, f)
  return f
}

/** Session, scale and tick for any symbol. Unknown ones get a stable made-up profile. */
export function symbolSpec(raw) {
  const sym = String(raw || '').trim().toUpperCase()
  let s = symbols.get(sym)
  if (s) return s
  const known = SYMBOL_DEFS[sym]
  if (known) {
    const [famKey, scale, tick, volume] = known
    const fam = family(famKey, FAMILY_DEFS[famKey])
    const session = fam.session === 'globex' && !sym.endsWith('=F') ? 'rth' : fam.session
    s = { symbol: sym, fam, scale, tick, volume, session }
  } else {
    const r = rng(hash(`symbol:${sym}`))
    const session = /=F$/.test(sym) ? 'globex' : /-USD$/.test(sym) ? 'utc24' : 'rth'
    const fam = family(`x:${sym}`, {
      base: Math.exp(Math.log(15) + r() * Math.log(40)),
      vol: session === 'utc24' ? 0.6 + r() * 0.5 : 0.18 + r() * 0.3,
      drift: 0.05,
      session,
    })
    s = { symbol: sym, fam, scale: 1, tick: session === 'globex' ? 0.25 : 0.01, volume: 2e6 + r() * 2e7, session }
  }
  symbols.set(sym, s)
  return s
}

export const isTradingDay = (spec, day) => spec.session === 'utc24' || (weekdayOf(day) >= 1 && weekdayOf(day) <= 5)

/** Volatility regime, log-multiplier on the family's base vol. Smooth and non-recursive. */
function regime(fam, day) {
  const [a, b, c] = fam.phases
  return 0.35 * Math.sin(2 * Math.PI * day / 97 + a) + 0.25 * Math.sin(2 * Math.PI * day / 263 + b) + 0.15 * Math.sin(2 * Math.PI * day / 41 + c)
}

const daysPerYear = (fam) => (fam.session === 'utc24' ? 365 : 252)
/** Close-to-close log-return sd for `day`. */
export function dailySigma(fam, day) {
  return (fam.vol / Math.sqrt(daysPerYear(fam))) * 0.85 * Math.exp(regime(fam, day))
}

function dayShock(fam, day) {
  const r = rng(hash(`${fam.key}:d:${day}`))
  const z = gaussian(r)
  return r() < 0.03 ? z * 2.5 : z
}

// Log close per calendar day (weekends repeat Friday for weekday families).
const chains = new Map()
function chain(fam, day) {
  let c = chains.get(fam.key)
  if (!c || day >= c.start + c.log.length) {
    const start = FIRST_DAY - 7
    const end = Math.max(day + 30, etDay(Date.now() / 1000) + 30)
    const log = new Float64Array(end - start + 1)
    const ret = (d) => {
      if (fam.session !== 'utc24' && (weekdayOf(d) === 0 || weekdayOf(d) === 6)) return 0
      const s = dailySigma(fam, d)
      return (fam.drift - 0.5 * fam.vol * fam.vol) / daysPerYear(fam) + s * dayShock(fam, d)
    }
    const a = ANCHOR_DAY - start
    log[a] = Math.log(fam.base)
    for (let i = a + 1; i < log.length; i++) log[i] = log[i - 1] + ret(start + i)
    for (let i = a - 1; i >= 0; i--) log[i] = log[i + 1] - ret(start + i + 1)
    c = { start, log }
    chains.set(fam.key, c)
  }
  return c.log[Math.max(0, day - c.start)]
}

/** Family log close at the end of `day`'s session. */
export function familyLogClose(fam, day) {
  if (fam.tracks) {
    const parent = families.get(fam.tracks) || family(fam.tracks, FAMILY_DEFS[fam.tracks])
    const level = 100 * parent.vol * 0.85 * Math.exp(regime(parent, day))
    return Math.log(level) + 0.08 * dayShock(fam, day) - 0.15 * dayShock(parent, day)
  }
  return chain(fam, day)
}

// --- intraday paths --------------------------------------------------------------

/** [utc start, minutes] of a session kind on `day`. */
export function sessionWindow(session, day) {
  if (session === 'utc24') return [day * DAY, 1440]
  if (session === 'rth') return [etToUtc(day, 570), 390]
  const start = etToUtc(day - 1, 18 * 60)
  return [start, (etToUtc(day, 17 * 60) - start) / 60]
}

const RTH_OPEN = 570
const RTH_CLOSE = 960

function varianceWeight(session, etMin) {
  if (session === 'utc24') return 0.6 + (etMin >= RTH_OPEN && etMin < RTH_CLOSE ? 0.5 : 0)
  if (etMin >= RTH_OPEN && etMin < RTH_CLOSE) {
    return 1 + 2.2 * Math.exp(-(etMin - RTH_OPEN) / 20) + Math.exp(-(RTH_CLOSE - 1 - etMin) / 25)
  }
  if (etMin >= 510 && etMin < 515) return 2.5 // 08:30 ET data releases
  return 0.22
}

function volumeWeight(session, etMin) {
  if (session === 'utc24') return 0.7 + (etMin >= RTH_OPEN && etMin < RTH_CLOSE ? 0.6 : 0)
  if (etMin >= RTH_OPEN && etMin < RTH_CLOSE) {
    return 1 + 3 * Math.exp(-(etMin - RTH_OPEN) / 15) + 2.5 * Math.exp(-(RTH_CLOSE - 1 - etMin) / 12)
  }
  if (etMin >= 510 && etMin < 515) return 0.6
  return 0.06
}

const LRU_LIMIT = 256
function lru(map, key, make) {
  let v = map.get(key)
  if (v) {
    map.delete(key)
    map.set(key, v)
    return v
  }
  v = make()
  map.set(key, v)
  if (map.size > LRU_LIMIT) map.delete(map.keys().next().value)
  return v
}

const pathCache = new Map()
/** Family log-price path for `day`: x[0] = prior close, x[L] = this close. */
function familyPath(fam, day) {
  return lru(pathCache, `${fam.key}|${day}`, () => {
    const [start, L] = sessionWindow(fam.session, day)
    let prev = day - 1
    if (fam.session !== 'utc24') while (weekdayOf(prev) === 0 || weekdayOf(prev) === 6) prev--
    const x0 = familyLogClose(fam, prev)
    const x1 = familyLogClose(fam, day)
    const sigma = fam.tracks ? 0.06 : dailySigma(fam, day)
    const r = rng(hash(`${fam.key}:path:${day}`))
    const w = new Float64Array(L)
    let wSum = 0
    const etStart = Math.round((start / 60 + etOffsetMinutes(start)) % 1440 + 1440) % 1440
    for (let m = 0; m < L; m++) {
      w[m] = varianceWeight(fam.session, (etStart + m) % 1440)
      wSum += w[m]
    }
    const x = new Float64Array(L + 1)
    const sd = new Float64Array(L)
    x[0] = 0
    for (let m = 0; m < L; m += 2) {
      // Box-Muller gives two normals per draw; use both.
      const u = Math.sqrt(-2 * Math.log(1 - r()))
      const a = 2 * Math.PI * r()
      sd[m] = sigma * Math.sqrt(w[m] / wSum)
      x[m + 1] = x[m] + sd[m] * u * Math.cos(a)
      if (m + 1 < L) {
        sd[m + 1] = sigma * Math.sqrt(w[m + 1] / wSum)
        x[m + 2] = x[m + 1] + sd[m + 1] * u * Math.sin(a)
      }
    }
    // Brownian bridge so the path lands exactly on the day's close.
    const miss = x[L] - (x1 - x0)
    let v = 0
    for (let m = 1; m <= L; m++) {
      v += w[m - 1] / wSum
      x[m] = x0 + x[m] - v * miss
    }
    x[0] = x0
    return { start, L, x, sd, etStart }
  })
}

const roundTo = (p, tick) => Math.round(Math.round(p / tick) * tick * 1e6) / 1e6

const barCache = new Map()
/** Complete 1m bars of `sym` for trading day `day` (columnar). */
function fullDayBars(spec, day) {
  return lru(barCache, `${spec.symbol}|${day}`, () => {
    const path = familyPath(spec.fam, day)
    const [start, L] = sessionWindow(spec.session, day)
    const off = Math.round((start - path.start) / 60)
    const r = rng(hash(`${spec.symbol}:bars:${day}`))
    const dayVolume = spec.volume * Math.exp(0.4 * regime(spec.fam, day) + 0.2 * gaussian(r))
    const vw = new Float64Array(L)
    let vSum = 0
    for (let m = 0; m < L; m++) {
      vw[m] = volumeWeight(spec.session, (path.etStart + off + m) % 1440)
      vSum += vw[m]
    }
    const t = new Float64Array(L)
    const o = new Float64Array(L)
    const h = new Float64Array(L)
    const l = new Float64Array(L)
    const c = new Float64Array(L)
    const v = new Float64Array(L)
    for (let m = 0; m < L; m++) {
      const i = off + m
      const sd = path.sd[i]
      const lo = Math.min(path.x[i], path.x[i + 1])
      const hi = Math.max(path.x[i], path.x[i + 1])
      t[m] = start + m * 60
      o[m] = roundTo(Math.exp(path.x[i]) * spec.scale, spec.tick)
      c[m] = roundTo(Math.exp(path.x[i + 1]) * spec.scale, spec.tick)
      h[m] = Math.max(o[m], c[m], roundTo(Math.exp(hi + Math.abs(gaussian(r)) * 0.6 * sd) * spec.scale, spec.tick))
      l[m] = Math.min(o[m], c[m], roundTo(Math.exp(lo - Math.abs(gaussian(r)) * 0.6 * sd) * spec.scale, spec.tick))
      const move = sd > 0 ? Math.abs(path.x[i + 1] - path.x[i]) / sd : 0
      v[m] = Math.round(dayVolume * (vw[m] / vSum) * Math.exp(0.35 * gaussian(r)) * (0.75 + 0.35 * move))
    }
    return { start, L, t, o, h, l, c, v }
  })
}

/**
 * 1m bars of `sym` for `day` up to `now`, as an array of {t, o, h, l, c, v}.
 * The minute in progress is cut at `now` (partial close, range and volume).
 */
export function minuteBars(spec, day, now) {
  if (!isTradingDay(spec, day)) return []
  const [start, L] = sessionWindow(spec.session, day)
  if (start > now) return []
  const d = fullDayBars(spec, day)
  const out = []
  for (let m = 0; m < L; m++) {
    const t = d.t[m]
    if (t > now) break
    const frac = Math.min(1, (now - t) / 60)
    if (frac >= 1) {
      out.push({ t, o: d.o[m], h: d.h[m], l: d.l[m], c: d.c[m], v: d.v[m] })
    } else {
      const c = roundTo(d.o[m] + (d.c[m] - d.o[m]) * frac, spec.tick)
      const top = Math.max(d.o[m], c)
      const bottom = Math.min(d.o[m], c)
      out.push({
        t,
        o: d.o[m],
        h: Math.max(top, roundTo(top + (d.h[m] - Math.max(d.o[m], d.c[m])) * frac, spec.tick)),
        l: Math.min(bottom, roundTo(bottom - (Math.min(d.o[m], d.c[m]) - d.l[m]) * frac, spec.tick)),
        c,
        v: Math.round(d.v[m] * frac),
      })
    }
  }
  return out
}

function merge(bars, t) {
  let h = -Infinity
  let l = Infinity
  let v = 0
  for (const b of bars) {
    if (b.h > h) h = b.h
    if (b.l < l) l = b.l
    v += b.v
  }
  return { t, o: bars[0].o, h, l, c: bars[bars.length - 1].c, v }
}

/** Last trading day whose session has started by `now`. */
export function lastSessionDay(spec, now) {
  for (let d = etDay(now) + 1; ; d--) {
    if (isTradingDay(spec, d) && sessionWindow(spec.session, d)[0] <= now) return d
  }
}

export function previousTradingDay(spec, day) {
  let d = day - 1
  while (!isTradingDay(spec, d)) d--
  return d
}

const dayCache = new Map()
/**
 * Daily OHLCV for `day`. A session still in progress merges its 1m bars, so
 * the developing daily candle matches the intraday chart. A finished one is
 * summarised straight from the family path (10x cheaper, which keeps
 * period=max daily requests fast): same open and close as the 1m bars, with
 * high/low/volume drawn the same way but not summed minute by minute.
 */
export function dayBar(spec, day, now) {
  if (!isTradingDay(spec, day)) return null
  const [start, L] = sessionWindow(spec.session, day)
  if (start > now) return null
  if (start + L * 60 > now) {
    const bars = minuteBars(spec, day, now)
    return bars.length ? merge(bars, day) : null
  }
  return lru(dayCache, `${spec.symbol}|${day}`, () => {
    const path = familyPath(spec.fam, day)
    const off = Math.round((start - path.start) / 60)
    let hi = off
    let lo = off
    for (let i = off + 1; i <= off + L; i++) {
      if (path.x[i] > path.x[hi]) hi = i
      if (path.x[i] < path.x[lo]) lo = i
    }
    const r = rng(hash(`${spec.symbol}:bars:${day}`))
    const volume = Math.round(spec.volume * Math.exp(0.4 * regime(spec.fam, day) + 0.2 * gaussian(r)) * 0.97)
    const sdAt = (i) => path.sd[Math.min(i, off + L - 1)]
    const o = roundTo(Math.exp(path.x[off]) * spec.scale, spec.tick)
    const c = roundTo(Math.exp(path.x[off + L]) * spec.scale, spec.tick)
    return {
      t: day,
      o,
      h: Math.max(o, c, roundTo(Math.exp(path.x[hi] + Math.abs(gaussian(r)) * 0.6 * sdAt(hi)) * spec.scale, spec.tick)),
      l: Math.min(o, c, roundTo(Math.exp(path.x[lo] - Math.abs(gaussian(r)) * 0.6 * sdAt(lo)) * spec.scale, spec.tick)),
      c,
      v: volume,
    }
  })
}

const INTRADAY_STEP = { '1m': 60, '2m': 120, '5m': 300, '15m': 900, '30m': 1800, '60m': 3600, '90m': 5400, '1h': 3600, '4h': 14400 }
export const isIntraday = (interval) => interval in INTRADAY_STEP

/** Bars of one trading day aggregated to `interval`, buckets anchored on the session open. */
export function intradayBars(spec, day, interval, now) {
  const step = INTRADAY_STEP[interval] || 60
  const minutes = minuteBars(spec, day, now)
  if (step === 60) return minutes
  const [start] = sessionWindow(spec.session, day)
  const out = []
  let bucket = null
  let group = []
  for (const b of minutes) {
    const k = start + Math.floor((b.t - start) / step) * step
    if (k !== bucket && group.length) {
      out.push(merge(group, bucket))
      group = []
    }
    bucket = k
    group.push(b)
  }
  if (group.length) out.push(merge(group, bucket))
  return out
}

/** Trading days from `from` to `to` inclusive. */
export function tradingDays(spec, from, to) {
  const out = []
  for (let d = Math.max(from, FIRST_DAY); d <= to; d++) if (isTradingDay(spec, d)) out.push(d)
  return out
}

// Mirrors the backend's per-interval lookback ceiling (HistoricalDataService.maxLookbackFor).
const MAX_LOOKBACK_DAYS = { '1m': 30, '2m': 60, '5m': 183, '15m': 183, '30m': 183, '1h': 5 * 365, '60m': 5 * 365, '90m': 183, '4h': 5 * 365 }

/** First calendar day a `period` reaches back to from trading day `last`. */
export function periodStart(spec, period, last) {
  const m = /^(\d+)(d|wk|mo|y)$/.exec(period || '')
  const date = new Date(last * 86400000)
  if (period === 'max') return FIRST_DAY
  if (period === 'ytd') return dayNumber(date.getUTCFullYear(), 1, 1)
  if (!m) return periodStart(spec, '1mo', last)
  const n = Number(m[1])
  if (m[2] === 'd') {
    let d = last
    for (let k = 1; k < n; k++) d = previousTradingDay(spec, d)
    return d
  }
  if (m[2] === 'wk') return last - 7 * n + 1
  const y = date.getUTCFullYear() - (m[2] === 'y' ? n : 0)
  const mo = date.getUTCMonth() - (m[2] === 'mo' ? n : 0)
  return Date.UTC(y, mo, date.getUTCDate()) / 86400000 + 1
}

const fmt = (b, intraday) => ({
  time: intraday ? String(b.t) : dayString(b.t),
  open: b.o,
  high: b.h,
  low: b.l,
  close: b.c,
  volume: b.v,
})

/** Rows for GET /api/historical, same shape as the backend's OhlcData. */
export function historicalRows(symbol, period, interval, now = Date.now() / 1000) {
  const spec = symbolSpec(symbol)
  const last = lastSessionDay(spec, now)
  let first = periodStart(spec, period, last)
  if (MAX_LOOKBACK_DAYS[interval]) first = Math.max(first, last - MAX_LOOKBACK_DAYS[interval])
  const days = tradingDays(spec, first, last)
  if (isIntraday(interval)) return days.flatMap((d) => intradayBars(spec, d, interval, now).map((b) => fmt(b, true)))
  const daily = days.map((d) => dayBar(spec, d, now)).filter(Boolean)
  if (interval === '1wk' || interval === '1mo') {
    const out = []
    let key = null
    let group = []
    for (const b of daily) {
      const date = new Date(b.t * 86400000)
      const k = interval === '1wk' ? b.t - ((date.getUTCDay() + 6) % 7) : dayNumber(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)
      if (k !== key && group.length) {
        out.push(merge(group, key))
        group = []
      }
      key = k
      group.push(b)
    }
    if (group.length) out.push(merge(group, key))
    return out.map((b) => fmt(b, false))
  }
  return daily.map((b) => fmt(b, false))
}

/** Rows for GET /api/historical/since: intraday bars whose bucket starts at or after `since`. */
export function rowsSince(symbol, interval, since, now = Date.now() / 1000) {
  const spec = symbolSpec(symbol)
  const last = lastSessionDay(spec, now)
  const from = Math.max(etDay(since) - 1, last - 7)
  if (!isIntraday(interval)) {
    return historicalRows(symbol, '5d', interval, now).filter((r) => Date.parse(`${r.time}T00:00:00Z`) / 1000 >= since - DAY)
  }
  return tradingDays(spec, from, last)
    .flatMap((d) => intradayBars(spec, d, interval, now))
    .filter((b) => b.t >= since)
    .map((b) => fmt(b, true))
}

/** Rows for GET /api/historical/recent: the latest 1m bars of the current session. */
export function recentRows(symbol, now = Date.now() / 1000, count = 120) {
  const spec = symbolSpec(symbol)
  return minuteBars(spec, lastSessionDay(spec, now), now).slice(-count).map((b) => fmt(b, true))
}

/** Last price, prior session close and session volume, as in /api/market. */
export function quote(symbol, now = Date.now() / 1000) {
  const spec = symbolSpec(symbol)
  const day = lastSessionDay(spec, now)
  const bar = dayBar(spec, day, now)
  const prev = dayBar(spec, previousTradingDay(spec, day), now)
  return { symbol: spec.symbol, price: bar?.c ?? null, volume: bar?.v ?? null, previousClose: prev?.c ?? null }
}

/** Whether `now` is inside RTH on a trading day. */
export function marketOpen(now = Date.now() / 1000) {
  const day = etDay(now)
  if (weekdayOf(day) === 0 || weekdayOf(day) === 6) return false
  return now >= etToUtc(day, RTH_OPEN) && now < etToUtc(day, RTH_CLOSE)
}

/** Backend-style "yyyy-MM-dd HH:mm:ss" timestamp in New York time. */
export function timestamp(now = Date.now() / 1000) {
  const wall = new Date((Math.floor(now) + etOffsetMinutes(now) * 60) * 1000).toISOString()
  return `${wall.slice(0, 10)} ${wall.slice(11, 19)}`
}
