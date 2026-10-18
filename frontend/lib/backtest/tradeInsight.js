/**
 * Per-trade diagnostics for the trade inspector.
 *
 * The blotter says what happened; this module says why it happened and how
 * much it should be trusted. Three questions, in the order a trade usually
 * fools you:
 *
 *   1. Did the bars it was held over actually exist? A position open across a
 *      missing session is marked from the last close before the hole to the
 *      first after it, so its P&L is a gap the strategy could never have
 *      traded. One such trade once made 71% of a study's P&L.
 *   2. How much of the result is this one trade? A share of net P&L above
 *      ~20% means the run is a story about this trade, not about the rule.
 *   3. What did the strategy see? The inputs on the bar that fired the signal
 *      (orders fill one bar later, at the next open) are the "why".
 *
 * Pure functions; the inspector component only formats what comes back.
 */

import { tradingDay } from './time'

/** Weekday of a trading-day number. Day 0 (1970-01-01) was a Thursday. */
const weekday = (day) => (((day + 4) % 7) + 7) % 7

/**
 * NYSE full-day closures, 2020–2027. Bars alone cannot tell a closed exchange
 * from a hole in the data, and flagging every Memorial Day hold as a data gap
 * would teach you to ignore the flag. Outside these years a holiday does show
 * up as a missing session.
 */
const NYSE_HOLIDAYS = new Set([
  '2020-01-01', '2020-01-20', '2020-02-17', '2020-04-10', '2020-05-25', '2020-07-03', '2020-09-07', '2020-11-26', '2020-12-25',
  '2021-01-01', '2021-01-18', '2021-02-15', '2021-04-02', '2021-05-31', '2021-07-05', '2021-09-06', '2021-11-25', '2021-12-24',
  '2022-01-17', '2022-02-21', '2022-04-15', '2022-05-30', '2022-06-20', '2022-07-04', '2022-09-05', '2022-11-24', '2022-12-26',
  '2023-01-02', '2023-01-16', '2023-02-20', '2023-04-07', '2023-05-29', '2023-06-19', '2023-07-04', '2023-09-04', '2023-11-23', '2023-12-25',
  '2024-01-01', '2024-01-15', '2024-02-19', '2024-03-29', '2024-05-27', '2024-06-19', '2024-07-04', '2024-09-02', '2024-11-28', '2024-12-25',
  '2025-01-01', '2025-01-09', '2025-01-20', '2025-02-17', '2025-04-18', '2025-05-26', '2025-06-19', '2025-07-04', '2025-09-01', '2025-11-27', '2025-12-25',
  '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
  '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
])

/** UTC date of a trading-day number (the day an RTH session trades on). */
const dayDate = (day) => new Date(day * 86400000).toISOString().slice(0, 10)

/** Weekday sessions strictly between two trading days that are not exchange holidays. */
export function missingSessionsBetween(dayA, dayB) {
  let n = 0
  for (let d = dayA + 1; d < dayB; d++) {
    const w = weekday(d)
    if (w !== 0 && w !== 6 && !NYSE_HOLIDAYS.has(dayDate(d))) n++
  }
  return n
}

/** Median spacing between bars in seconds, from a sample of the series. */
export function barSeconds(time) {
  const diffs = []
  const step = Math.max(1, Math.floor(time.length / 2000))
  for (let i = step; i < time.length; i += step) {
    const d = time[i] - time[i - step]
    if (d > 0) diffs.push(d / step)
  }
  if (!diffs.length) return 0
  diffs.sort((a, b) => a - b)
  return diffs[Math.floor(diffs.length / 2)]
}

/**
 * Calendar facts about the bars a trade was held over.
 *
 *   overnight        entry and exit fall on different trading days (intraday
 *                    data only; on daily bars every hold is overnight)
 *   sessionsHeld     trading days the position was open on
 *   missingSessions  weekday, non-holiday sessions with no bars while it was open
 *   missingBars      intraday bars absent inside a session (an outage, not a
 *                    close), counted against the median bar spacing
 */
export function tradeCalendar(trade, time, spacing = barSeconds(time)) {
  const intraday = spacing > 0 && spacing < 20 * 3600
  let sessions = 1
  let missingSessions = 0
  let missingBars = 0
  for (let i = trade.entryIdx + 1; i <= trade.exitIdx; i++) {
    const a = tradingDay(time[i - 1])
    const b = tradingDay(time[i])
    if (b !== a) {
      sessions++
      missingSessions += missingSessionsBetween(a, b)
    } else if (intraday && time[i] - time[i - 1] > spacing * 1.5) {
      missingBars += Math.round((time[i] - time[i - 1]) / spacing) - 1
    }
  }
  return {
    overnight: intraday && sessions > 1,
    sessionsHeld: sessions,
    missingSessions,
    missingBars,
  }
}

/** True when a trade's P&L includes bars that were never there. */
export const isGapped = (cal) => cal.missingSessions > 0 || cal.missingBars > 0

/**
 * Run-level context for ranking a single trade: total net P&L, and each
 * trade's rank by net P&L (1 = best). Computed once per result.
 */
export function tradeContext(trades) {
  let net = 0
  for (const t of trades) net += t.pnl
  const order = trades.map((t, i) => i).sort((a, b) => trades[b].pnl - trades[a].pnl)
  const rank = new Int32Array(trades.length)
  order.forEach((idx, r) => { rank[idx] = r + 1 })
  return { net, rank }
}

/**
 * Everything the inspector shows about trade `k` of `trades`.
 *
 * `pnlShare` is the trade's net P&L over the run's net P&L. It can exceed
 * 100% (or flip sign) when the rest of the run nets out against it — which is
 * exactly the case worth seeing. Null only when the run nets to zero.
 */
export function inspectTrade(trades, k, time, ctx = tradeContext(trades), spacing) {
  const t = trades[k]
  if (!t) return null
  const cal = tradeCalendar(t, time, spacing)
  const slippage = t.slippage ?? 0
  const fees = t.fees ?? 0
  const beforeCosts = t.pnl + slippage + fees
  const risk = t.stopPrice ? Math.abs(t.entryPrice - t.stopPrice) / t.entryPrice : 0
  return {
    index: k,
    trade: t,
    calendar: cal,
    gapped: isGapped(cal),
    rank: ctx.rank[k],
    of: trades.length,
    pnlShare: Math.abs(ctx.net) > 1e-9 ? t.pnl / ctx.net : null,
    netWithout: ctx.net - t.pnl,
    beforeCosts,
    slippage,
    fees,
    // Cost as a share of what the trade made at the quote. Above 1 means
    // costs alone turned a winner into a loser.
    costShare: Math.abs(beforeCosts) > 0 ? (slippage + fees) / Math.abs(beforeCosts) : null,
    // Of the best excursion the trade saw, how much it kept at exit (gross of
    // costs, so this is about the exit rule rather than the friction).
    kept: t.mfe > 0 ? t.grossPct / t.mfe : null,
    rMultiple: risk > 0 ? t.grossPct / risk : null,
    // Orders fill at the next open, so the bar that decided is one earlier.
    entrySignalIdx: t.entryIdx - 1,
    exitSignalIdx: t.reason === 'signal' ? t.exitIdx - 1 : null,
  }
}

/**
 * The strategy's view of one bar, read generically from its prepared state:
 * numeric series give their value, compiled rule predicates (the custom
 * strategy) give true/false. Scratch fields that are not per-bar are skipped.
 */
export function readInputs(state, i, n) {
  if (!state || i < 0 || i >= n) return []
  const out = []
  for (const [key, v] of Object.entries(state)) {
    if (typeof v === 'function') {
      try {
        out.push({ key, value: Boolean(v(i)) })
      } catch {
        // A predicate that cannot evaluate this bar has nothing to report.
      }
    } else if (isSeries(v, n)) {
      out.push({ key, value: v[i] })
    }
  }
  return out
}

const isSeries = (v, n) =>
  v != null && typeof v === 'object' && typeof v.length === 'number' && v.length === n && typeof v[0] === 'number'

/**
 * State series that live on the price axis (moving averages, VWAP, bands,
 * levels) — the ones worth drawing over the candles. Decided by magnitude: a
 * series whose median sits within ±40% of the median close is a price; ATR,
 * z-scores and GEX features are not.
 */
export function priceOverlays(state, close) {
  const n = close.length
  if (!state || !n) return []
  const ref = median(close)
  if (!(ref > 0)) return []
  const out = []
  for (const [key, v] of Object.entries(state)) {
    if (!isSeries(v, n) || v === close) continue
    const m = median(v)
    if (m > ref * 0.6 && m < ref * 1.4) out.push({ key, values: v })
  }
  return out
}

function median(arr) {
  const vals = []
  const step = Math.max(1, Math.floor(arr.length / 1000))
  for (let i = 0; i < arr.length; i += step) if (Number.isFinite(arr[i])) vals.push(arr[i])
  if (!vals.length) return NaN
  vals.sort((a, b) => a - b)
  return vals[Math.floor(vals.length / 2)]
}

/** camelCase / snake_case state keys to a short readable label. */
export function inputLabel(key) {
  return String(key)
    .replace(/_/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
}
