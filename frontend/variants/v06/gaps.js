/**
 * Data holes, found from the timestamps alone.
 *
 * The bundled 5m samples are missing bars inside many sessions, and the price
 * chart's index-based time axis closes those holes up so they look like normal
 * candles. A trade held across one is priced on a jump nobody could have
 * traded through, so the page counts them and says how much P&L they carry.
 *
 * A hole is two consecutive bars in the same ET session whose spacing is
 * larger than the bar interval. Overnight and weekend breaks are not holes.
 * Daily and weekly data are skipped: there is no intraday spacing to check.
 */

const INTERVAL_SECONDS = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 }

const etDay = (() => {
  let fmt
  return (epochSeconds) => {
    fmt ||= new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' })
    return fmt.format(new Date(epochSeconds * 1000))
  }
})()

/** Holes in a columnar dataset, or null when the interval has no intraday
 *  spacing to check. `cum[i]` is the number of missing bars before bar i, so a
 *  span's missing bars are `cum[b] - cum[a]`. */
export function findGaps(dataset) {
  if (!dataset?.time || !dataset.n) return null
  const step = INTERVAL_SECONDS[dataset.interval]
  if (!step) return null

  const { time, n } = dataset
  const cum = new Float64Array(n)
  const holes = [] // { idx, missing } — idx is the first bar after the hole
  const perSession = new Map()
  const holeSessions = new Set()
  let prevDay = etDay(time[0])
  perSession.set(prevDay, 1)

  for (let i = 1; i < n; i++) {
    const day = etDay(time[i])
    perSession.set(day, (perSession.get(day) || 0) + 1)
    let missing = 0
    if (day === prevDay) {
      const dt = time[i] - time[i - 1]
      // Tolerate a few seconds of clock jitter in the source timestamps.
      if (dt > step * 1.5) missing = Math.round(dt / step) - 1
    }
    cum[i] = cum[i - 1] + missing
    if (missing > 0) {
      holes.push({ idx: i, missing })
      holeSessions.add(day)
    }
    prevDay = day
  }

  // The usual bar count of a full session, as the most common count.
  const counts = new Map()
  for (const c of perSession.values()) counts.set(c, (counts.get(c) || 0) + 1)
  let usual = 0
  let usualFreq = 0
  for (const [c, f] of counts) if (f > usualFreq || (f === usualFreq && c > usual)) { usual = c; usualFreq = f }
  const thinSessions = [...perSession.entries()].filter(([, c]) => c < usual / 2).map(([d]) => d)

  return {
    holes,
    cum,
    missingBars: cum[n - 1],
    sessions: perSession.size,
    holeSessions: holeSessions.size,
    usualBars: usual,
    thinSessions,
  }
}

/** Missing bars inside a trade's holding span (0 if none). */
export const tradeMissing = (gaps, t) => (gaps ? gaps.cum[t.exitIdx] - gaps.cum[t.entryIdx] : 0)

/** How much of the result rides on trades held across a hole. */
export function gapExposure(gaps, trades) {
  if (!gaps || !trades?.length) return null
  let n = 0
  let gross = 0
  let grossAcross = 0
  let netAcross = 0
  for (const t of trades) {
    const a = Math.abs(t.pnl)
    gross += a
    if (tradeMissing(gaps, t) > 0) {
      n++
      grossAcross += a
      netAcross += t.pnl
    }
  }
  return { n, share: gross > 0 ? grossAcross / gross : 0, net: netAcross }
}
