/**
 * Missing bars inside a trading session.
 *
 * lightweight-charts and the equity curve both draw bars by index, so a hole
 * in the feed (a 5m bar that was never stored) disappears from every picture.
 * A trade held across one is priced on a jump nobody could have traded, so the
 * holes are found once per dataset and shown wherever a number depends on them.
 *
 * Only holes between two bars of the same New York calendar day count — the
 * overnight and weekend closes are not missing data.
 */

const STEP = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }

let dayFmt
const etDay = (sec) => {
  dayFmt ||= new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' })
  return dayFmt.format(new Date(sec * 1000))
}

const cache = new WeakMap()

/** `{ holes: [{ idx, missing, from, to }], missingBars, sessions, sessionsHit, step }`.
 *  `idx` is the first bar after the hole. */
export function findGaps(ds) {
  if (!ds) return null
  if (cache.has(ds)) return cache.get(ds)
  const step = STEP[ds.interval]
  const out = { holes: [], missingBars: 0, sessions: 0, sessionsHit: 0, step: step || null }
  if (!step) {
    cache.set(ds, out)
    return out
  }
  const t = ds.time
  const days = new Set()
  const hitDays = new Set()
  let prevDay = ds.n ? etDay(t[0]) : null
  if (prevDay) days.add(prevDay)
  for (let i = 1; i < ds.n; i++) {
    const day = etDay(t[i])
    days.add(day)
    const dt = t[i] - t[i - 1]
    if (day === prevDay && dt > step * 1.5) {
      const missing = Math.round(dt / step) - 1
      out.holes.push({ idx: i, missing, from: t[i - 1], to: t[i] })
      out.missingBars += missing
      hitDays.add(day)
    }
    prevDay = day
  }
  out.sessions = days.size
  out.sessionsHit = hitDays.size
  cache.set(ds, out)
  return out
}

/** Holes a trade was exposed to: any hole whose first bar falls inside (entry, exit]. */
export function holesInTrade(trade, holes) {
  let count = 0
  let missing = 0
  for (const h of holes) {
    if (h.idx > trade.exitIdx) break
    if (h.idx > trade.entryIdx) {
      count++
      missing += h.missing
    }
  }
  return { count, missing }
}

/** Per-result summary: which trades span holes and how much P&L they carry. */
export function tradeGapSummary(result, gaps) {
  if (!result || !gaps) return null
  const byEntry = new Map()
  let n = 0
  let gross = 0
  let grossHit = 0
  let netHit = 0
  for (const t of result.trades) {
    const g = holesInTrade(t, gaps.holes)
    gross += Math.abs(t.pnl)
    if (g.count) {
      byEntry.set(t.entryIdx, g)
      n++
      grossHit += Math.abs(t.pnl)
      netHit += t.pnl
    }
  }
  return { byEntry, n, total: result.trades.length, netHit, share: gross > 0 ? grossHit / gross : 0 }
}
