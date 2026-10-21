import { tradingDay } from '../../../lib/backtest/time'

/**
 * Holes in the loaded bars.
 *
 * Both charts here are index-based, so a missing stretch of 5m bars is drawn as
 * two adjacent candles and simply disappears. That matters: the bundled QQQ
 * sample has holes on 37 of its 53 sessions, and a trade held across one is
 * marked to a price nobody could have traded in between. This finds every jump
 * longer than one bar inside a trading day (overnight and weekend closes are
 * not holes) so the UI can show them instead of smoothing them over.
 */

const INTERVAL_SECONDS = {
  '1m': 60, '2m': 120, '5m': 300, '15m': 900, '30m': 1800,
  '1h': 3600, '60m': 3600, '90m': 5400, '4h': 14400,
}

const cache = new WeakMap()

/** null for daily/weekly data or when the interval is unknown. */
export function findGaps(ds) {
  if (!ds) return null
  if (cache.has(ds)) return cache.get(ds)
  const step = INTERVAL_SECONDS[ds.interval]
  if (!step) {
    cache.set(ds, null)
    return null
  }
  const n = ds.n
  const t = ds.time
  // cum[i] = bars missing between bar 0 and bar i, so a trade's share is
  // cum[exit] - cum[entry] in O(1).
  const cumMissing = new Float64Array(n)
  const cumHoles = new Float64Array(n)
  const holes = []
  const days = new Map()
  const sessions = new Set()
  for (let i = 0; i < n; i++) {
    const day = tradingDay(t[i])
    sessions.add(day)
    let missing = 0
    if (i > 0 && tradingDay(t[i - 1]) === day) {
      const dt = t[i] - t[i - 1]
      if (dt > step * 1.5) missing = Math.round(dt / step) - 1
    }
    cumMissing[i] = (i ? cumMissing[i - 1] : 0) + missing
    cumHoles[i] = (i ? cumHoles[i - 1] : 0) + (missing ? 1 : 0)
    if (missing) {
      holes.push({ idx: i, from: t[i - 1], to: t[i], missing, day })
      const d = days.get(day) || { day, holes: 0, missing: 0, firstIdx: i, start: t[i - 1] }
      d.holes++
      d.missing += missing
      days.set(day, d)
    }
  }
  const out = {
    step,
    holes,
    days: [...days.values()],
    sessions: sessions.size,
    missingBars: holes.reduce((a, h) => a + h.missing, 0),
    cumMissing,
    cumHoles,
  }
  cache.set(ds, out)
  return out
}

/** Bars missing strictly inside a trade's holding span. */
export function missingInSpan(gaps, entryIdx, exitIdx) {
  if (!gaps || exitIdx <= entryIdx) return 0
  return gaps.cumMissing[exitIdx] - gaps.cumMissing[entryIdx]
}

/** How many trades were held across a hole, and what they made next to the rest. */
export function gapExposure(gaps, trades) {
  if (!gaps || !trades) return null
  let n = 0
  let pnl = 0
  let other = 0
  for (const tr of trades) {
    if (missingInSpan(gaps, tr.entryIdx, tr.exitIdx) > 0) {
      n++
      pnl += tr.pnl
    } else other += tr.pnl
  }
  return { n, pnl, other, total: trades.length }
}
