/**
 * Exact volume-at-price from futures trade prints (GET /api/volume-profile/*).
 * The backend only answers bars that published tick data fully covers (RTH
 * sessions, see functions/ml/publish_tick_profiles.py); every other bar keeps
 * the OHLC approximation in volumeProfile.js.
 */
import { useEffect, useMemo, useState } from 'react'
import { TICK_SIZE } from './volumeProfile'

const coverageCache = new Map() // symbol -> { promise: Promise<[[start, end], ...]>, at }
const barsCache = new Map() // symbol|runs -> Promise<Map<utc, {lo, vols, deltas}>>
const BARS_CACHE_SIZE = 8
// Matches the backend's index cache, so newly published sessions show up without a reload.
const COVERAGE_TTL_MS = 10 * 60 * 1000

export const isTickProfileSymbol = (symbol) => /^[A-Z]{1,4}=F$/.test(symbol || '')

// Test hook: forget cached coverage and bars.
export function __resetTickProfileCaches() {
  coverageCache.clear()
  barsCache.clear()
}

/**
 * Published sessions for the symbol as [[start, end], ...] (UTC epoch s), cached
 * for COVERAGE_TTL_MS. A failed lookup (cold backend, 429/503, network) rejects
 * and is evicted, so the next poll retries; an incompatible tick size is a real
 * answer and caches as [].
 */
export function fetchCoverage(symbol) {
  const hit = coverageCache.get(symbol)
  if (hit && Date.now() - hit.at <= COVERAGE_TTL_MS) return hit.promise
  const promise = fetch(`/api/volume-profile/coverage?symbol=${encodeURIComponent(symbol)}`)
    .then(res => {
      if (!res.ok) throw new Error(`volume-profile coverage ${res.status}`)
      return res.json()
    })
    .then(body => (body.tickSize === TICK_SIZE ? body.sessions || [] : []))
  const entry = { promise, at: Date.now() }
  promise.catch(() => {
    if (coverageCache.get(symbol) === entry) coverageCache.delete(symbol)
  })
  coverageCache.set(symbol, entry)
  return promise
}

/**
 * Bars (UTC bar-start epochs, ascending) that sit wholly inside a covered
 * session, as runs of equal-width consecutive bars: [[start, step, count], ...].
 * A bar spans until the next bar starts, so a bar followed by missing bars
 * claims their prints too; the last bar reuses the previous spacing.
 */
export function coveredRuns(utcTimes, sessions) {
  const runs = []
  if (!sessions?.length) return runs
  let s = 0
  for (let i = 0; i < utcTimes.length; i++) {
    const start = utcTimes[i]
    const end = i + 1 < utcTimes.length ? utcTimes[i + 1] : (i > 0 ? start + (start - utcTimes[i - 1]) : NaN)
    const step = end - start
    if (!Number.isFinite(step) || step < 60 || step % 60 !== 0 || start % 60 !== 0) continue
    while (s < sessions.length && sessions[s][1] <= start) s++
    if (s >= sessions.length) break
    if (sessions[s][0] > start || end > sessions[s][1]) continue
    const last = runs[runs.length - 1]
    if (last && last[1] === step && last[0] + last[1] * last[2] === start) last[2]++
    else runs.push([start, step, 1])
  }
  return runs
}

const encodeRuns = (runs) => runs.map(r => r.join(':')).join(',')

function fetchBars(symbol, runs) {
  const key = `${symbol}|${encodeRuns(runs)}`
  if (!barsCache.has(key)) {
    const p = fetch(`/api/volume-profile/bars?symbol=${encodeURIComponent(symbol)}&runs=${encodeRuns(runs)}`)
      .then(res => {
        if (!res.ok) throw new Error(`volume-profile ${res.status}`)
        return res.json()
      })
      .then(body => {
        const map = new Map()
        if (body.tickSize !== TICK_SIZE) return map
        const deltas = body.deltas || []
        ;(body.bars || []).forEach((row, i) => {
          map.set(row[0], { lo: row[1], vols: row.slice(2), deltas: deltas[i] || null })
        })
        return map
      })
    p.catch(() => barsCache.delete(key))
    barsCache.set(key, p)
    if (barsCache.size > BARS_CACHE_SIZE) barsCache.delete(barsCache.keys().next().value)
  }
  return barsCache.get(key)
}

const barUtc = (d) => (/^\d+$/.test(String(d.time)) ? Number(d.time) : NaN)

// Most common gap between consecutive bars: the chart's interval, ignoring session gaps.
function barStep(utc) {
  const counts = new Map()
  let best = 0
  let bestN = 0
  for (let i = 1; i < utc.length; i++) {
    const gap = utc[i] - utc[i - 1]
    const n = (counts.get(gap) || 0) + 1
    counts.set(gap, n)
    if (n > bestN) {
      best = gap
      bestN = n
    }
  }
  return best
}

/**
 * Exact per-bar volume for the chart's raw bars: Map<utc bar start, {lo, vols, deltas}>
 * where vols[k] is the volume at tick index lo + k and deltas[k] its buy-minus-
 * sell aggressor volume (null when the session has no side data). null until loaded or when
 * the symbol has no tick data. Live polling re-derives the same runs, so the
 * request is cached and only fires again when coverage of the window changes.
 * A loaded map is only returned while the symbol and bar spacing it was fetched
 * for still match, so an interval or symbol switch falls back to the
 * approximation at once instead of applying another interval's volumes.
 */
export function useTickVolume(symbol, data) {
  const [state, setState] = useState({ key: null, sig: null, map: null })
  const { utc, sig } = useMemo(() => {
    const utc = (data || []).map(barUtc).filter(Number.isFinite).sort((a, b) => a - b)
    return { utc, sig: `${symbol}|${barStep(utc)}` }
  }, [symbol, data])
  useEffect(() => {
    if (!isTickProfileSymbol(symbol) || !utc.length) {
      setState(prev => (prev.map ? { key: null, sig: null, map: null } : prev))
      return
    }
    let cancelled = false
    fetchCoverage(symbol)
      .then(sessions => {
        const runs = coveredRuns(utc, sessions)
        const key = `${symbol}|${encodeRuns(runs)}`
        if (!runs.length) return { key, sig, map: null }
        return fetchBars(symbol, runs).then(map => ({ key, sig, map: map.size ? map : null }))
      })
      .then(next => {
        if (!cancelled) setState(prev => (prev.key === next.key && prev.sig === next.sig ? prev : next))
      })
      .catch(() => {
        // Keep the approximation (and a same-spacing map); the next poll retries.
        if (!cancelled) setState(prev => (prev.sig === sig ? prev : { key: null, sig, map: null }))
      })
    return () => { cancelled = true }
  }, [symbol, utc, sig])
  return state.sig === sig ? state.map : null
}
