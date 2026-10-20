import { tradingDay } from '../../lib/backtest/time'

const STEP = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600 }

/**
 * Intraday holes: two consecutive bars inside one trading day that are further
 * apart than the bar interval. The chart plots bars by index, so without this
 * a missing half hour is drawn as if price moved straight across it.
 *
 * Returns `{ holes: [{ idx, missing, day }], sessions, days, missing, prefix }`, where
 * `idx` is the first bar after the hole and `prefix[i]` counts holes at or
 * before bar i (so a trade spans a hole iff prefix[exit] > prefix[entry]).
 */
export function findHoles(ds) {
  const empty = { holes: [], sessions: 0, days: 0, missing: 0, prefix: null, step: null }
  if (!ds) return empty
  const step = STEP[ds.interval]
  if (!step) return empty
  const t = ds.time
  const holes = []
  const prefix = new Uint32Array(ds.n)
  const days = new Set()
  const all = new Set([tradingDay(t[0])])
  let missing = 0
  for (let i = 1; i < ds.n; i++) {
    all.add(tradingDay(t[i]))
    prefix[i] = prefix[i - 1]
    const dt = t[i] - t[i - 1]
    if (dt > step * 1.5) {
      const day = tradingDay(t[i])
      if (day === tradingDay(t[i - 1])) {
        const m = Math.round(dt / step) - 1
        holes.push({ idx: i, missing: m, day })
        days.add(day)
        missing += m
        prefix[i]++
      }
    }
  }
  return { holes, sessions: days.size, days: all.size, missing, prefix, step }
}

export const spansHole = (gaps, trade) =>
  Boolean(gaps?.prefix) && gaps.prefix[trade.exitIdx] > gaps.prefix[trade.entryIdx]

/** How much of the result rides on bars that are not in the data. */
export function holeExposure(gaps, trades) {
  if (!gaps?.prefix || !trades?.length) return { n: 0, pnl: 0, total: 0 }
  let n = 0
  let pnl = 0
  let total = 0
  for (const t of trades) {
    total += t.pnl
    if (spansHole(gaps, t)) {
      n++
      pnl += t.pnl
    }
  }
  return { n, pnl, total }
}

const cache = new WeakMap()
/** Memoised per dataset object — the store swaps the object on every load. */
export function holesFor(ds) {
  if (!ds) return null
  let g = cache.get(ds)
  if (!g) {
    g = findHoles(ds)
    cache.set(ds, g)
  }
  return g
}
