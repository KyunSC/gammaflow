/**
 * Data holes: places inside one trading session where the loaded bars skip
 * one or more intervals. lightweight-charts and the equity chart both space
 * bars by index, so a 40-minute hole looks like two adjacent candles unless
 * something marks it. Everything here is measured from the loaded bars; there
 * are no assumptions about how many bars a session ought to have.
 */

import { tradingDay } from '../../lib/backtest/time'

const STEP = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }

/** Holes in `ds`, or `{ checked: false }` for daily (or unknown) intervals,
 *  where a missing bar is a missing day and cannot be told from a holiday. */
export function findHoles(ds) {
  const step = STEP[ds?.interval]
  if (!ds || !step) return { checked: false, holes: [], sessions: 0, missingBars: 0, flags: null }
  const n = ds.n
  const time = ds.time
  const holes = []
  const sessions = new Set()
  // flags[i] = 1 when a hole sits between bar i-1 and bar i.
  const flags = new Uint8Array(n)
  let missingBars = 0
  for (let i = 1; i < n; i++) {
    const dt = time[i] - time[i - 1]
    if (dt <= step * 1.5) continue
    const day = tradingDay(time[i])
    if (day !== tradingDay(time[i - 1])) continue
    const missing = Math.round(dt / step) - 1
    holes.push({ idx: i, missing, from: time[i - 1], to: time[i] })
    sessions.add(day)
    missingBars += missing
    flags[i] = 1
  }
  // Prefix sums so "was a trade open across a hole" is O(1) per trade.
  const prefix = new Uint32Array(n + 1)
  for (let i = 0; i < n; i++) prefix[i + 1] = prefix[i] + flags[i]
  return { checked: true, holes, sessions: sessions.size, missingBars, flags, prefix }
}

/** Holes strictly inside a trade: between its entry bar and its exit bar. */
export function holesInTrade(info, t) {
  if (!info?.checked || !info.prefix) return 0
  return info.prefix[t.exitIdx + 1] - info.prefix[t.entryIdx + 1]
}

/** How much of the run's P&L came from trades that were open across a hole. */
export function holeExposure(info, trades) {
  if (!info?.checked || !trades?.length) return null
  let n = 0
  let pnl = 0
  let gross = 0
  let grossAcross = 0
  let net = 0
  for (const t of trades) {
    const a = Math.abs(t.pnl)
    gross += a
    net += t.pnl
    if (holesInTrade(info, t) > 0) {
      n++
      pnl += t.pnl
      grossAcross += a
    }
  }
  return { n, total: trades.length, pnl, net, grossShare: gross > 0 ? grossAcross / gross : 0 }
}

const cache = new WeakMap()

/** `findHoles`, computed once per loaded dataset object. */
export function holesFor(ds) {
  if (!ds) return findHoles(null)
  let v = cache.get(ds)
  if (!v) {
    v = findHoles(ds)
    cache.set(ds, v)
  }
  return v
}
