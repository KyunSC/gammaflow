/**
 * Prop-account replay.
 *
 * With a fixed contract count a strategy's orders never depend on the account
 * balance, so the engine runs once and every firm rule becomes a read of its
 * per-bar equity extremes (`barLo` / `barHi` / `barOpen`):
 *   - max-loss breach   an intrabar low at or below the trailing threshold ends
 *                       the account
 *   - daily loss limit  flattens for the rest of the day, so the day's P&L
 *                       freezes at the limit (or at the open, if gapped through)
 *   - flat-by time      already applied by the engine (`risk.flatByEt`)
 *
 * Days are replayed relative to their opening balance, so the same day table
 * serves a start on any historical session and any bootstrapped sequence.
 *
 * Fixed-risk perp sizing (MyFundedPerps) keeps that property: the size comes
 * from the starting balance and the stop, never from the running balance.
 * Those accounts may hold overnight, so day values are marked to market and
 * a payout is only allowed on a day that ends flat.
 */

import { tradingDay } from '../series'
import { nyDay } from '../time'
import { nth } from './firms'

const EPS = 1e-9

/**
 * Engine result → day table. Every per-bar value is relative to the equity the
 * day opened with. Under Lucid's forced flat-at-close that is realised cash;
 * an account that holds overnight opens the day marked to market, which is
 * how MyFundedPerps measures its daily limit.
 *
 * `dayBoundary` 'globex' rolls at 22:00 UTC (`tradingDay`), 'ny' at midnight
 * New York. With `trades` and `positions` the table also carries, per day,
 * whether anything filled (`fills`), whether it ended flat (`flat`), and how
 * many calendar days it stands for until the next day in the data (`span`:
 * a Friday of equity bars covers the weekend) — what an inactivity rule counts.
 */
export function buildDayTable({ equity, barLo, barHi, barOpen, windowStart = 0, windowEnd, time, initialCapital, dayBoundary = 'globex', trades = null, positions = null }) {
  const end = windowEnd ?? equity.length - 1
  const n = end - windowStart + 1
  const dayOf = dayBoundary === 'ny' ? nyDay : tradingDay
  const lo = new Float64Array(n)
  const hi = new Float64Array(n)
  const open = new Float64Array(n)
  const close = new Float64Array(n)
  const starts = []
  const ends = []
  const active = []
  const dayTime = []
  const dayNum = []
  let base = initialCapital
  let dayActive = 0

  for (let i = windowStart; i <= end; i++) {
    const j = i - windowStart
    if (i === windowStart || dayOf(time[i]) !== dayOf(time[i - 1])) {
      if (i !== windowStart) {
        ends.push(j - 1)
        active.push(dayActive)
        base = equity[i - 1]
      }
      starts.push(j)
      dayTime.push(time[i])
      dayNum.push(dayOf(time[i]))
      dayActive = 0
    }
    lo[j] = barLo[i] - base
    hi[j] = barHi[i] - base
    open[j] = barOpen[i] - base
    close[j] = equity[i] - base
    if (Math.abs(hi[j] - lo[j]) > EPS || Math.abs(close[j]) > EPS || Math.abs(open[j]) > EPS) dayActive = 1
  }
  ends.push(n - 1)
  active.push(dayActive)

  const table = {
    n: starts.length,
    start: Int32Array.from(starts),
    end: Int32Array.from(ends),
    active: Uint8Array.from(active),
    time: Float64Array.from(dayTime),
    lo,
    hi,
    open,
    close,
  }
  if (trades) {
    // Bar → day index, to mark the days an order actually filled.
    const dayIdx = new Int32Array(n)
    for (let d = 0; d < table.n; d++) dayIdx.fill(d, table.start[d], table.end[d] + 1)
    const fills = new Uint8Array(table.n)
    for (const t of trades) {
      for (const b of [t.entryIdx, t.exitIdx]) {
        if (b >= windowStart && b <= end) fills[dayIdx[b - windowStart]] = 1
      }
    }
    table.fills = fills
    table.span = Int32Array.from(dayNum, (v, d) => (d + 1 < dayNum.length ? Math.max(1, dayNum[d + 1] - v) : 1))
  }
  if (positions) table.flat = Uint8Array.from(ends, (j) => (positions[j + windowStart] === 0 ? 1 : 0))
  return table
}

/** One stage — an evaluation or a funded account — from day `k0` of the attempt. */
function runStage(days, next, k0, plan, stage) {
  const start = plan.startBalance
  const lockAt = start + plan.lockOffset
  const mode = stage === 'funded' ? plan.fundedDrawdown : plan.evalDrawdown || 'eod'
  const intraday = mode === 'intraday'
  const fixed = mode === 'static'
  const dll = plan.dailyLossLimit > 0 ? plan.dailyLossLimit : 0
  const dllFails = plan.dllMode === 'fail'
  const target = start + (plan.profitTarget || 0)
  // A target touched intrabar can only pass on the spot when no day count or
  // consistency check is still owed at the close.
  const passNow = stage === 'eval' && plan.passIntrabar && !plan.evalMinDays && !plan.evalConsistency
  const idleLimit = days.fills ? (stage === 'funded' ? plan.fundedInactivityDays : plan.evalInactivityDays) || 0 : 0
  const grossCap = plan.lifetimeCap > 0 && plan.split > 0 ? plan.lifetimeCap / plan.split : Infinity
  let bal = start
  let peak = start
  let locked = false
  let threshold = fixed ? start - plan.maxLoss : Math.min(peak - plan.maxLoss, lockAt)
  let activeDays = 0
  let bestDay = 0
  let dllHits = 0
  let idle = 0
  let paid = 0
  let cycleStart = start
  let cycleActive = 0
  let cycleProfitDays = 0
  let cycleBest = 0
  const payouts = []
  const done = (status, reason, k) => ({ status, reason, days: k - k0, payouts, dllHits, balance: bal })

  for (let k = k0; ; k++) {
    const d = next(k)
    if (d < 0) return done('open', 'end-of-data', k)
    const s = days.start[d]
    const e = days.end[d]
    const dayBase = bal
    const dllLevel = dll ? dayBase - dll : -Infinity
    let pnl = null

    for (let i = s; i <= e; i++) {
      // Intraday trailing: credit the bar's high before its low. The order
      // inside a bar is unknown, and this is the order that breaches soonest.
      if (intraday && !locked) {
        peak = Math.max(peak, dayBase + days.hi[i])
        threshold = Math.min(peak - plan.maxLoss, lockAt)
      }
      const worst = dayBase + days.lo[i]
      if (dllFails && worst <= dllLevel && dllLevel > threshold) {
        dllHits++
        bal = Math.min(dllLevel, dayBase + days.open[i])
        return done('breached', 'daily-loss', k + 1)
      }
      if (!dllFails && dll && worst <= dllLevel && dllLevel > threshold) {
        const frozen = Math.min(dllLevel, dayBase + days.open[i])
        dllHits++
        if (frozen <= threshold) {
          bal = frozen
          return done('breached', 'max-loss', k + 1)
        }
        pnl = frozen - dayBase
        break
      }
      if (worst <= threshold) {
        bal = Math.min(threshold, dayBase + days.open[i])
        return done('breached', 'max-loss', k + 1)
      }
      // Checked after the floors: a bar that touches both is a breach.
      if (passNow && dayBase + days.hi[i] >= target) {
        bal = target
        return done('passed', 'target', k + 1)
      }
    }
    if (pnl === null) pnl = days.close[e]
    bal = dayBase + pnl
    const act = days.active[d] === 1
    if (act) activeDays++
    if (!locked && !fixed) {
      peak = Math.max(peak, bal)
      threshold = Math.min(peak - plan.maxLoss, lockAt)
    }

    if (stage === 'eval') {
      bestDay = Math.max(bestDay, pnl)
      const profit = bal - start
      if (
        activeDays >= plan.evalMinDays &&
        profit >= plan.profitTarget &&
        (!plan.evalConsistency || bestDay <= plan.evalConsistency * profit + EPS)
      ) {
        return done('passed', 'target', k + 1)
      }
    }

    // Calendar days without a fill; reaching the limit closes the account
    // before it can request a payout that day.
    if (idleLimit) {
      if (days.fills[d]) idle = 0
      else if ((idle += days.span[d]) >= idleLimit) return done('breached', 'inactivity', k + 1)
    }
    if (stage === 'eval') continue

    if (act) cycleActive++
    if (act && pnl > 0 && pnl >= plan.minDayProfit) cycleProfitDays++
    cycleBest = Math.max(cycleBest, pnl)
    const cycleProfit = bal - cycleStart
    const idx = payouts.length
    const goal = nth(plan.profitGoal, idx) || 0
    const eligible =
      cycleActive >= plan.fundedMinDays &&
      cycleProfitDays >= plan.minProfitDays &&
      cycleProfit > 0 &&
      cycleProfit >= goal &&
      (!plan.fundedConsistency || cycleBest <= plan.fundedConsistency * cycleProfit + EPS) &&
      (!plan.buffer || bal > plan.buffer) &&
      (!days.flat || days.flat[d] === 1)
    if (!eligible) continue

    const from = plan.payoutFrom === 'cycle' ? cycleStart : start
    let amount = plan.payoutFraction != null
      ? plan.payoutFraction * (bal - start)
      : bal - Math.max(plan.buffer || 0, from)
    const cap = nth(plan.payoutCap, idx)
    if (cap > 0) amount = Math.min(amount, cap)
    amount = Math.floor(Math.min(amount, grossCap - paid))
    if (amount < plan.minPayout) continue

    payouts.push(amount)
    paid += amount
    bal -= amount
    locked = true
    if (plan.lockOnPayout !== false) threshold = lockAt
    cycleStart = bal
    cycleActive = 0
    cycleProfitDays = 0
    cycleBest = 0
    if (plan.maxPayouts && payouts.length >= plan.maxPayouts) return done('graduated', 'max-payouts', k + 1)
    if (paid >= grossCap - 1) return done('graduated', 'lifetime-cap', k + 1)
  }
}

/**
 * One purchase: evaluation (if the plan has one) then the funded account.
 * `next(k)` gives the day-table index of the attempt's k-th day, or -1 when
 * the data runs out.
 *
 * Outcomes: `failed` (eval breached), `eval-open` (data ended mid-eval —
 * censored), `funded-breached`, `graduated` (hit the payout count that moves
 * the trader to a live account, which is not simulated), `funded-open`
 * (data ended while funded; payouts so far are a lower bound).
 */
export function simulateAccount({ days, next, plan }) {
  const out = { outcome: null, reason: null, evalDays: 0, fundedDays: 0, payouts: [], take: 0, daysUsed: 0, dllHits: 0 }
  let k = 0
  if (plan.hasEval) {
    const ev = runStage(days, next, 0, plan, 'eval')
    out.evalDays = ev.days
    out.dllHits += ev.dllHits
    k = ev.days
    if (ev.status !== 'passed') {
      out.outcome = ev.status === 'breached' ? 'failed' : 'eval-open'
      out.reason = ev.reason
      out.daysUsed = k
      return out
    }
  }
  const fu = runStage(days, next, k, plan, 'funded')
  out.fundedDays = fu.days
  out.dllHits += fu.dllHits
  out.payouts = fu.payouts
  out.outcome = fu.status === 'breached' ? 'funded-breached' : fu.status === 'graduated' ? 'graduated' : 'funded-open'
  out.reason = fu.reason
  out.take = plan.split * fu.payouts.reduce((a, b) => a + b, 0)
  out.daysUsed = k + fu.days
  return out
}
