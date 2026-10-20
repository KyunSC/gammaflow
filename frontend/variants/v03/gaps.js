import { tradingDay } from '../../lib/backtest/time'

const INTERVAL_SECONDS = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400 }

/**
 * Holes in the bar series: two consecutive bars on the same trading day that
 * are further apart than one interval. The charts draw bars edge to edge, so
 * without this a missing half hour looks like continuous price.
 *
 * `holes[k].idx` is the bar *after* the hole. A trade is "across a hole" when
 * it is open over that boundary: entryIdx < idx <= exitIdx.
 */
export function findGaps(dataset) {
  if (!dataset || dataset.n < 2) return null
  const step = INTERVAL_SECONDS[dataset.interval]
  if (!step || step >= 86400) return { holes: [], days: 0, missingBars: 0, shortDays: [], prefix: null, step }
  const t = dataset.time
  const holes = []
  const perDay = new Map()
  for (let i = 0; i < dataset.n; i++) {
    const d = tradingDay(t[i])
    perDay.set(d, (perDay.get(d) || 0) + 1)
    if (i === 0) continue
    const dt = t[i] - t[i - 1]
    if (dt > step * 1.5 && tradingDay(t[i - 1]) === d) {
      holes.push({ idx: i, day: d, missing: Math.round(dt / step) - 1, from: t[i - 1], to: t[i] })
    }
  }
  // prefix[k] = number of holes whose boundary bar index is <= k
  const prefix = new Int32Array(dataset.n)
  let h = 0
  for (let i = 0, k = 0; i < dataset.n; i++) {
    while (k < holes.length && holes[k].idx === i) { h++; k++ }
    prefix[i] = h
  }
  // Sessions with under half the median bar count: partial days, whether a
  // real early close or missing data. Reported, not interpreted.
  const counts = [...perDay.values()].sort((a, b) => a - b)
  const median = counts[Math.floor(counts.length / 2)] || 0
  const shortDays = [...perDay.entries()].filter(([, c]) => c < median / 2).map(([d, c]) => ({ day: d, bars: c }))
  return {
    holes,
    days: new Set(holes.map((x) => x.day)).size,
    missingBars: holes.reduce((s, x) => s + x.missing, 0),
    sessions: perDay.size,
    medianBars: median,
    shortDays,
    prefix,
    step,
  }
}

/** Holes a trade was open across (0 when none). */
export function holesInTrade(gaps, trade) {
  if (!gaps?.prefix) return 0
  return gaps.prefix[trade.exitIdx] - gaps.prefix[trade.entryIdx]
}

/** How much of the run's P&L came from trades held across a hole. */
export function gapExposure(gaps, result) {
  if (!gaps?.prefix || !result?.trades?.length) return null
  let n = 0
  let pnl = 0
  let absAcross = 0
  let absAll = 0
  let total = 0
  for (const tr of result.trades) {
    total += tr.pnl
    absAll += Math.abs(tr.pnl)
    if (holesInTrade(gaps, tr) > 0) {
      n++
      pnl += tr.pnl
      absAcross += Math.abs(tr.pnl)
    }
  }
  return { n, pnl, total, grossShare: absAll > 0 ? absAcross / absAll : 0 }
}

/** Trading-day number → 'MM/DD' in New York. tradingDay rolls at 22:00 UTC. */
export function dayLabel(day) {
  return new Date((day * 86400 - 7200 + 43200) * 1000).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', timeZone: 'America/New_York' })
}

const cache = new WeakMap()
/** findGaps, computed once per loaded dataset object. */
export function gapsFor(dataset) {
  if (!dataset) return null
  if (!cache.has(dataset)) cache.set(dataset, findGaps(dataset))
  return cache.get(dataset)
}
