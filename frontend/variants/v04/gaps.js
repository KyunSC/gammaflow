/**
 * Intraday data holes.
 *
 * lightweight-charts closes up time, so a session with twenty missing 5m bars
 * draws exactly like a complete one. The bundled QQQ sample has holes on 37
 * sessions, and trades held across a hole are marked at prices nobody could
 * have traded between. This finds them from the timestamps alone: two
 * consecutive bars on the same New York date further apart than one interval.
 * Overnight and weekend closes are not holes.
 */

const STEP = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }
const cache = new WeakMap()

export function findHoles(ds) {
  if (!ds) return null
  if (cache.has(ds)) return cache.get(ds)
  const step = STEP[ds.interval]
  const n = ds.n
  const cum = new Int32Array(n)
  const holes = []
  const days = new Set()
  let missing = 0
  if (step && n > 1) {
    const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' })
    let prevDay = fmt.format(ds.time[0] * 1000)
    for (let i = 1; i < n; i++) {
      const day = fmt.format(ds.time[i] * 1000)
      const dt = ds.time[i] - ds.time[i - 1]
      cum[i] = cum[i - 1]
      if (day === prevDay && dt > step * 1.5) {
        const m = Math.round(dt / step) - 1
        holes.push({ i, missing: m, day })
        days.add(day)
        missing += m
        cum[i]++
      }
      prevDay = day
    }
  }
  const out = { step, holes, sessions: days.size, missing, cum }
  cache.set(ds, out)
  return out
}

/** True when the position was open across at least one hole. */
export const crossesHole = (h, t) => Boolean(h && h.holes.length && h.cum[t.exitIdx] - h.cum[t.entryIdx] > 0)

/** Trades held across a hole and the net P&L they account for. */
export function holeExposure(h, trades) {
  if (!h || !trades) return null
  let count = 0
  let pnl = 0
  let total = 0
  for (const t of trades) {
    total += t.pnl
    if (crossesHole(h, t)) {
      count++
      pnl += t.pnl
    }
  }
  return { count, pnl, total, n: trades.length }
}
