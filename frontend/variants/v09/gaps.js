/**
 * Missing-bar analysis for intraday datasets.
 *
 * A "hole" is two consecutive bars on the same New York trading day that are
 * further apart than one bar interval. Overnight and weekend breaks are not
 * holes. Nothing here fills or smooths anything: the numbers are counted from
 * the timestamps the dataset actually has, and the UI shows them as they are.
 */

const INTERVAL_SEC = { '1m': 60, '2m': 120, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }

const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' })

export function intervalSeconds(interval) {
  return INTERVAL_SEC[interval] || null
}

const cache = new WeakMap()

export function findGaps(ds) {
  if (!ds) return null
  if (cache.has(ds)) return cache.get(ds)
  const step = intervalSeconds(ds.interval)
  const n = ds.n
  if (!step || n < 2) {
    const out = { supported: false, interval: ds.interval }
    cache.set(ds, out)
    return out
  }
  const time = ds.time
  const dayOf = new Array(n)
  for (let i = 0; i < n; i++) dayOf[i] = dayFmt.format(new Date(time[i] * 1000))

  // cum[i] = missing bars between bar 0 and bar i (inclusive of the hole just before i).
  const cum = new Int32Array(n)
  const holes = []
  const days = new Map()
  for (let i = 0; i < n; i++) {
    const d = dayOf[i]
    if (!days.has(d)) days.set(d, { day: d, first: i, last: i, bars: 0, missing: 0, holes: [] })
    const rec = days.get(d)
    rec.bars++
    rec.last = i
    cum[i] = i ? cum[i - 1] : 0
    if (i && dayOf[i - 1] === d) {
      const dt = time[i] - time[i - 1]
      if (dt > step * 1.5) {
        const missing = Math.round(dt / step) - 1
        const hole = { i, missing, from: time[i - 1], to: time[i], day: d }
        holes.push(hole)
        rec.holes.push(hole)
        rec.missing += missing
        cum[i] += missing
      }
    }
  }

  const list = [...days.values()]
  const out = {
    supported: true,
    step,
    holes,
    cum,
    dayOf,
    days: list,
    sessionCount: list.length,
    gapDays: list.filter((d) => d.missing > 0).length,
    missingBars: holes.reduce((s, h) => s + h.missing, 0),
  }
  cache.set(ds, out)
  return out
}

/** Missing bars inside a trade's holding period (entry bar to exit bar). */
export function missingInTrade(gaps, t) {
  if (!gaps?.supported) return 0
  return gaps.cum[t.exitIdx] - gaps.cum[t.entryIdx]
}

/** Sessions that fall inside the traded window [start, end]. */
export function sessionsInWindow(gaps, start, end) {
  if (!gaps?.supported) return null
  let n = 0
  for (const d of gaps.days) if (d.last >= start && d.first <= end) n++
  return n
}

/** How much of the run's P&L came from trades held across a hole. */
export function tradeExposure(gaps, trades) {
  if (!gaps?.supported || !trades) return null
  let affected = 0
  let affectedPnl = 0
  let totalPnl = 0
  for (const t of trades) {
    totalPnl += t.pnl
    if (missingInTrade(gaps, t) > 0) {
      affected++
      affectedPnl += t.pnl
    }
  }
  return { affected, affectedPnl, totalPnl, trades: trades.length }
}
