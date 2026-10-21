/**
 * Data-hole scan for a loaded dataset.
 *
 * The bundled 5m samples are missing bars inside many sessions, and a few
 * sessions stop hours before the close. The chart library closes those holes
 * visually and the engine simply steps to the next bar, so a position held
 * "for 3 bars" can really have been held across 40 minutes nobody recorded.
 * This module finds the holes so the UI can show them next to the trades
 * they touch. It never alters the data or the result.
 */

import { tradingDay, etMinuteOfDay } from '../../lib/backtest/time'

const STEP_SECONDS = { '1m': 60, '2m': 120, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '60m': 3600, '4h': 14400 }

const cache = new WeakMap()

/** Returns null for daily and slower data (weekends are not holes). */
export function scanGaps(ds) {
  if (!ds || !ds.time) return null
  if (cache.has(ds)) return cache.get(ds)
  const step = STEP_SECONDS[ds.interval]
  if (!step) {
    cache.set(ds, null)
    return null
  }
  const n = ds.n
  const t = ds.time
  // after[i] = number of bars missing between bar i-1 and bar i (same session).
  const after = new Int32Array(n)
  const holePrefix = new Int32Array(n + 1)
  const missingPrefix = new Int32Array(n + 1)
  const sessions = new Map()
  let holes = 0
  let missingBars = 0

  for (let i = 0; i < n; i++) {
    const day = tradingDay(t[i])
    let s = sessions.get(day)
    if (!s) {
      s = { day, first: i, last: i, holes: 0, missing: 0 }
      sessions.set(day, s)
    }
    s.last = i
    if (i > 0 && tradingDay(t[i - 1]) === day) {
      const dt = t[i] - t[i - 1]
      if (dt > step * 1.5) {
        const miss = Math.max(1, Math.round(dt / step) - 1)
        after[i] = miss
        holes++
        missingBars += miss
        s.holes++
        s.missing += miss
      }
    }
    holePrefix[i + 1] = holePrefix[i] + (after[i] ? 1 : 0)
    missingPrefix[i + 1] = missingPrefix[i] + after[i]
  }

  // Sessions that open late or stop early, judged against the most common
  // first/last bar time of this dataset. The first and last sessions are
  // skipped: the dataset may simply start or end inside them.
  const list = [...sessions.values()]
  const mode = (vals) => {
    const c = new Map()
    for (const v of vals) c.set(v, (c.get(v) || 0) + 1)
    let best = null
    let bestN = -1
    for (const [v, k] of c) if (k > bestN) { best = v; bestN = k }
    return best
  }
  const firstMin = list.map((s) => etMinuteOfDay(t[s.first]))
  const lastMin = list.map((s) => etMinuteOfDay(t[s.last]))
  const usualOpen = mode(firstMin)
  const usualClose = mode(lastMin)
  const tolerance = (2 * step) / 60
  let shortSessions = 0
  list.forEach((s, k) => {
    if (k === 0 || k === list.length - 1) return
    const late = firstMin[k] > usualOpen + tolerance
    const early = lastMin[k] < usualClose - tolerance
    s.short = late || early
    if (s.short) shortSessions++
  })
  const holeSessions = list.filter((s) => s.holes > 0).length

  const out = {
    step,
    sessions: list.length,
    holeSessions,
    shortSessions,
    holes,
    missingBars,
    after,
    holePrefix,
    missingPrefix,
  }
  cache.set(ds, out)
  return out
}

/** Missing bars between a trade's entry bar and its exit bar. */
export function tradeMissing(g, trade) {
  if (!g || !trade) return 0
  return g.missingPrefix[trade.exitIdx + 1] - g.missingPrefix[trade.entryIdx + 1]
}

/** P&L split between trades held across a hole and the rest. */
export function holeExposure(g, trades) {
  if (!g || !trades) return null
  let n = 0
  let pnl = 0
  let total = 0
  for (const tr of trades) {
    total += tr.pnl
    if (tradeMissing(g, tr) > 0) {
      n++
      pnl += tr.pnl
    }
  }
  return { n, pnl, total, rest: total - pnl, restN: trades.length - n }
}
