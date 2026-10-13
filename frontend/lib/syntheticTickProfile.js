/**
 * Simulated trade prints for the public site, where the real (licensed)
 * Databento prints are never served. Built only from the chart's own OHLCV
 * bars, in the same shape lib/tickProfile.js returns for real prints, so the
 * volume profile and order flow (delta bubbles, POC/HVN/LVN) still demo. Every
 * place that shows them labels them simulated.
 *
 * Deterministic per symbol and bar, so polling doesn't make the profile flicker.
 */
import { TICK_SIZE } from './volumeProfile'
import { barStep, barUtc, isTickProfileSymbol } from './tickProfile'
import { etMinuteOfDay } from './backtest/time'

// Same RTH window the real prints are published for (09:25–16:00 ET).
const RTH_OPEN = 9 * 60 + 25
const RTH_CLOSE = 16 * 60
// A bar wider than this many ticks isn't worth simulating (bad print or wrong symbol).
const MAX_TICKS = 4000

// FNV-1a: string -> 32-bit seed.
function hash(str) {
  let h = 0x811c9dc5
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

// mulberry32: small seeded PRNG returning [0, 1).
function mulberry32(seed) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x))

// Integer split of `total` in proportion to `weights` (largest remainder),
// giving every tick at least one contract when there is enough to go round so
// the bar's high and low actually trade.
function allocate(total, weights) {
  const n = weights.length
  const out = new Array(n).fill(0)
  let left = total
  if (left >= n) {
    out.fill(1)
    left -= n
  }
  const sum = weights.reduce((a, b) => a + b, 0)
  const rem = []
  let given = 0
  for (let k = 0; k < n; k++) {
    const share = (left * weights[k]) / sum
    const whole = Math.floor(share)
    out[k] += whole
    given += whole
    rem.push([share - whole, k])
  }
  rem.sort((a, b) => b[0] - a[0] || a[1] - b[1])
  for (let i = 0; i < left - given; i++) out[rem[i][1]]++
  return out
}

// One bar's simulated prints: {lo, vols, deltas}, or null when it has none.
function simulateBar(symbol, utc, bar) {
  const { open, high, low, close } = bar
  const volume = Math.round(Number(bar.volume))
  if (![open, high, low, close].every(Number.isFinite) || !(volume > 0) || high < low) return null
  const lo = Math.round(low / TICK_SIZE)
  const n = Math.round(high / TICK_SIZE) - lo + 1
  if (n < 1 || n > MAX_TICKS) return null
  const rand = mulberry32(hash(`${symbol}|${utc}`))

  // Volume: a hump centred somewhere in the body, wider on bigger bars, with
  // per-tick noise so neighbouring bars don't look stamped out of one mould.
  const bodyLo = Math.round(Math.min(open, close) / TICK_SIZE) - lo
  const bodyHi = Math.round(Math.max(open, close) / TICK_SIZE) - lo
  const centre = bodyLo + (bodyHi - bodyLo) * rand()
  const sigma = Math.max(1, n / (3 + 2 * rand()))
  const weights = new Array(n)
  for (let k = 0; k < n; k++) {
    const inBody = k >= bodyLo && k <= bodyHi
    weights[k] = (Math.exp(-0.5 * ((k - centre) / sigma) ** 2) * (inBody ? 1 : 0.6) + 0.05) * (0.5 + rand())
  }
  const vols = allocate(volume, weights)

  // Delta: leans with the bar's direction (buyers lifting the upper ticks of an
  // up bar, sellers hitting the lower ticks of a down bar), plus noise.
  const lean = high > low ? (close - open) / (high - low) : 0
  const deltas = new Array(n)
  for (let k = 0; k < n; k++) {
    const pos = n > 1 ? (2 * k) / (n - 1) - 1 : 0 // -1 at the low, +1 at the high
    const frac = clamp(0.5 * lean + 0.25 * Math.abs(lean) * pos + (rand() - 0.5) * 0.9, -1, 1)
    deltas[k] = clamp(Math.round(vols[k] * frac), -vols[k], vols[k])
  }
  return { lo, vols, deltas }
}

/**
 * Simulated prints for the chart's raw bars: Map<utc bar start, {lo, vols, deltas}>,
 * the same contract as useTickVolume's real path, or null when nothing is
 * covered. Only futures symbols, and only intraday bars lying wholly inside
 * RTH, mirroring real coverage; all other bars keep the OHLC approximation.
 * Ticks stay inside each bar's low..high, so exactFits always accepts them.
 */
export function synthesizeTickVolume(symbol, data) {
  if (!isTickProfileSymbol(symbol) || !data?.length) return null
  const bars = []
  for (const d of data) {
    const utc = barUtc(d)
    if (Number.isFinite(utc)) bars.push([utc, d])
  }
  bars.sort((a, b) => a[0] - b[0])
  const step = barStep(bars.map(b => b[0]))
  if (step < 60 || step % 60 !== 0) return null
  const map = new Map()
  for (const [utc, d] of bars) {
    if (utc % 60 !== 0) continue
    const start = etMinuteOfDay(utc)
    if (start < RTH_OPEN || start + step / 60 > RTH_CLOSE) continue
    const prints = simulateBar(symbol, utc, d)
    if (prints) map.set(utc, prints)
  }
  return map.size ? map : null
}
