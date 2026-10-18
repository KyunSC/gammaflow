import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { missingSessionsBetween, tradeCalendar, inspectTrade, tradeContext, readInputs, priceOverlays, inputLabel } = await jiti.import('./tradeInsight.js')
const { tradingDay } = await jiti.import('./time.js')
const { runBacktest } = await jiti.import('./engine.js')

const at = (iso) => Date.parse(iso) / 1000
/** RTH 5m bars for each listed date, `per` bars a day from 13:30 UTC (09:30 EDT). */
function sessions(dates, per = 4) {
  const t = []
  for (const d of dates) for (let k = 0; k < per; k++) t.push(at(`${d}T13:30:00Z`) + k * 300)
  return t
}

test('weekends are not missing sessions; a skipped weekday is', () => {
  const fri = tradingDay(at('2026-06-12T15:00:00Z'))
  const mon = tradingDay(at('2026-06-15T15:00:00Z'))
  const wed = tradingDay(at('2026-06-17T15:00:00Z'))
  assert.equal(missingSessionsBetween(fri, mon), 0)
  assert.equal(missingSessionsBetween(mon, wed), 1)
})

test('exchange holidays are not missing sessions', () => {
  // Memorial Day 2026 (May 25) and the July 3 Independence Day closure.
  const fri = tradingDay(at('2026-05-22T15:00:00Z'))
  const tue = tradingDay(at('2026-05-26T15:00:00Z'))
  assert.equal(missingSessionsBetween(fri, tue), 0)
  assert.equal(missingSessionsBetween(tradingDay(at('2026-07-02T15:00:00Z')), tradingDay(at('2026-07-06T15:00:00Z'))), 0)
})

test('a hold across a missing session is flagged; a normal overnight is not', () => {
  // June 23 is absent from the data, like the gap that once made 71% of a study's P&L.
  const time = sessions(['2026-06-18', '2026-06-22', '2026-06-24'])
  const overnight = tradeCalendar({ entryIdx: 2, exitIdx: 5 }, time)
  assert.deepEqual(overnight, { overnight: true, sessionsHeld: 2, missingSessions: 0, missingBars: 0 })
  const gapped = tradeCalendar({ entryIdx: 6, exitIdx: 9 }, time)
  assert.equal(gapped.missingSessions, 1)
  const intraday = tradeCalendar({ entryIdx: 0, exitIdx: 3 }, time)
  assert.equal(intraday.overnight, false)
})

test('missing bars inside a session are counted', () => {
  const time = sessions(['2026-06-22'], 6)
  time.splice(2, 2) // drop two bars mid-session
  const cal = tradeCalendar({ entryIdx: 0, exitIdx: 3 }, time, 300)
  assert.equal(cal.missingBars, 2)
  assert.equal(cal.missingSessions, 0)
})

test('inspectTrade ranks, shares and decomposes costs', () => {
  const time = sessions(['2026-06-22'], 10)
  const trades = [
    { entryIdx: 0, exitIdx: 2, entryPrice: 100, pnl: 300, fees: 2, slippage: 8, grossPct: 0.031, mfe: 0.04, reason: 'signal', stopPrice: 99 },
    { entryIdx: 3, exitIdx: 5, entryPrice: 100, pnl: -100, fees: 2, slippage: 8, grossPct: -0.009, mfe: 0, reason: 'stop' },
    { entryIdx: 6, exitIdx: 8, entryPrice: 100, pnl: 0, fees: 2, slippage: 8, grossPct: 0.001, mfe: 0.002, reason: 'target' },
  ]
  const ctx = tradeContext(trades)
  const best = inspectTrade(trades, 0, time, ctx)
  assert.equal(best.rank, 1)
  assert.equal(best.pnlShare, 1.5)
  assert.equal(best.netWithout, -100)
  assert.equal(best.beforeCosts, 310)
  assert.ok(Math.abs(best.kept - 0.775) < 1e-12)
  assert.ok(Math.abs(best.rMultiple - 3.1) < 1e-12)
  assert.equal(best.entrySignalIdx, -1)
  assert.equal(best.exitSignalIdx, 1)
  const worst = inspectTrade(trades, 1, time, ctx)
  assert.equal(worst.rank, 3)
  assert.equal(worst.kept, null)
  assert.equal(worst.exitSignalIdx, null)
  // Costs bigger than the move: a winner at the quote, flat after costs.
  assert.equal(inspectTrade(trades, 2, time, ctx).costShare, 1)
})

test('readInputs reads series and predicates, skips scratch fields', () => {
  const n = 3
  const state = { fast: Float64Array.from([1, 2, 3]), entryLong: (i) => i === 1, zone: null, entryBar: -1, short: [1, 2] }
  assert.deepEqual(readInputs(state, 1, n), [{ key: 'fast', value: 2 }, { key: 'entryLong', value: true }])
  assert.deepEqual(readInputs(state, -1, n), [])
})

test('priceOverlays keeps price-scale series and drops oscillators', () => {
  const close = Float64Array.from({ length: 50 }, (_, i) => 400 + i)
  const state = { vwap: close.map((v) => v - 1), atr: close.map(() => 1.2), regime: close.map(() => 1) }
  assert.deepEqual(priceOverlays(state, close).map((o) => o.key), ['vwap'])
})

test('engine trades carry stop, target and slippage', () => {
  const T0 = at('2026-06-01T14:00:00Z')
  const rows = Array.from({ length: 8 }, () => [100, 101, 99, 100])
  const ds = { id: 't', symbol: 'T', interval: '5m', time: rows.map((_, i) => T0 + i * 300), open: rows.map((r) => r[0]), high: rows.map((r) => r[1]), low: rows.map((r) => r[2]), close: rows.map((r) => r[3]), volume: rows.map(() => 1) }
  const r = runBacktest({ dataset: ds, strategy: { id: 'a', signal: () => 1 }, params: {}, costs: { slippageBps: 10, commissionPerTrade: 1 }, risk: { stopPct: 5, targetPct: 5 } })
  const t = r.trades[0]
  assert.ok(Math.abs(t.stopPrice - t.entryPrice * 0.95) < 1e-9)
  assert.ok(Math.abs(t.targetPrice - t.entryPrice * 1.05) < 1e-9)
  // 10 bp each side on ~$100k notional is ~$200 of slippage in total.
  assert.ok(t.slippage > 190 && t.slippage < 210, String(t.slippage))
  const grossAtQuote = (100 - 100) * t.qty
  assert.ok(Math.abs(t.pnl + t.slippage + t.fees - grossAtQuote) < 1e-6)
})

test('inputLabel', () => {
  assert.equal(inputLabel('callStrength'), 'call strength')
  assert.equal(inputLabel('dist_call_wall_atr'), 'dist call wall atr')
})
