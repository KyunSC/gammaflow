/**
 * Missing-bar detection for the loaded dataset.
 *
 * Both charts on /backtest plot by bar index, so a hole in the data is drawn
 * as two ordinary adjacent candles. The bundled QQQ/SPY sample has dozens of
 * intraday holes, and a trade held across one books the whole price move of
 * the missing bars in a single fill. This module finds the holes so the UI can
 * mark them instead of letting the index axis smooth them over.
 *
 * A gap is two consecutive bars on the same trading day that are further apart
 * than one interval. Whole missing sessions (holidays look identical) and gaps
 * between sessions are not counted.
 */

import { tradingDay } from '../../../lib/backtest/time'

const INTERVAL_SECONDS = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }

export function findGaps(ds) {
  const step = ds ? INTERVAL_SECONDS[ds.interval] : null
  const empty = { supported: Boolean(step), idx: [], missing: [], totalMissing: 0, days: 0, sessions: 0 }
  if (!ds || !step) return empty
  const idx = []
  const missing = []
  const gapDays = new Set()
  const allDays = new Set()
  let total = 0
  for (let i = 0; i < ds.n; i++) {
    const day = tradingDay(ds.time[i])
    allDays.add(day)
    if (i === 0) continue
    const dt = ds.time[i] - ds.time[i - 1]
    if (dt > step * 1.5 && day === tradingDay(ds.time[i - 1])) {
      const m = Math.round(dt / step) - 1
      idx.push(i)
      missing.push(m)
      total += m
      gapDays.add(day)
    }
  }
  return { supported: true, idx, missing, totalMissing: total, days: gapDays.size, sessions: allDays.size }
}

/** Gaps strictly inside a trade: a hole between entry bar and exit bar. */
export function gapsInTrade(gaps, trade) {
  if (!gaps.idx.length) return null
  // First gap index > entryIdx (binary search), then walk while <= exitIdx.
  let lo = 0
  let hi = gaps.idx.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (gaps.idx[mid] <= trade.entryIdx) lo = mid + 1
    else hi = mid
  }
  let count = 0
  let bars = 0
  for (let k = lo; k < gaps.idx.length && gaps.idx[k] <= trade.exitIdx; k++) {
    count++
    bars += gaps.missing[k]
  }
  return count ? { count, bars } : null
}

/** How much of the run's P&L sits in trades that were held across a hole. */
export function gapExposure(gaps, trades) {
  let n = 0
  let pnl = 0
  let total = 0
  let absGap = 0
  let absAll = 0
  for (const t of trades) {
    total += t.pnl
    absAll += Math.abs(t.pnl)
    if (gapsInTrade(gaps, t)) {
      n++
      pnl += t.pnl
      absGap += Math.abs(t.pnl)
    }
  }
  return { n, pnl, total, absShare: absAll > 0 ? absGap / absAll : 0 }
}

const cache = new WeakMap()
/** findGaps, memoised per dataset object (datasets are immutable once loaded). */
export function gapsFor(ds) {
  if (!ds) return findGaps(null)
  let g = cache.get(ds)
  if (!g) {
    g = findGaps(ds)
    cache.set(ds, g)
  }
  return g
}
