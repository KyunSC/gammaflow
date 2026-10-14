/**
 * Market calendars. Equities, ETFs and index futures are annualised on the
 * 252-day / 390-minute regular session; crypto trades 24/7 and uses the full
 * 365-day / 1440-minute calendar with UTC-midnight daily closes (Yahoo's
 * convention for `*-USD` daily candles).
 */

export const CRYPTO_SYMBOLS = ['BTC-USD', 'ETH-USD', 'SOL-USD']

export function isCrypto(symbol) {
  return typeof symbol === 'string' && /^[A-Z0-9]+-USD$/.test(symbol.toUpperCase())
}

export function calendarFor(symbol) {
  return isCrypto(symbol) ? { days: 365, minutesPerDay: 1440 } : { days: 252, minutesPerDay: 390 }
}

/** Below this share of expected bars the UI flags a crypto dataset as gappy. */
export const COVERAGE_WARN = 0.98

const BAR_SECONDS = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400 }

/**
 * Share of a 24/7 calendar's bars actually present between the first and
 * last bar, and the longest hole. Only meaningful for crypto: equity sessions
 * and holidays make an expected count ambiguous, so they return null. A
 * crypto series stored only during equity hours still annualises as 24/7,
 * so a low share means per-bar returns straddle gaps and the annualised
 * figures overstate the number of independent bars.
 */
export function calendarCoverage(time, interval, symbol) {
  const step = BAR_SECONDS[interval]
  const n = time?.length ?? 0
  if (!isCrypto(symbol) || !step || n < 2) return null
  let maxGap = 0
  for (let i = 1; i < n; i++) maxGap = Math.max(maxGap, time[i] - time[i - 1])
  const expected = Math.round((time[n - 1] - time[0]) / step) + 1
  return { share: Math.min(1, n / expected), expected, maxGapSeconds: maxGap }
}
