import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { runBacktest } = await jiti.import('./engine.js')
const { simulateAccount, buildDayTable } = await jiti.import('./prop/account.js')
const { resolvePlan, sizesFor } = await jiti.import('./prop/firms.js')
const { propSetup, attachProp } = await jiti.import('./prop/index.js')
const { perpMarket } = await jiti.import('./prop/perps.js')
const { twinStrategy, coinFlipTwins } = await jiti.import('./prop/twins.js')
const { mulberry32 } = await jiti.import('./metrics.js')

const elite = (extra = {}, opts = {}) => ({ ...resolvePlan({ firm: 'mfp', plan: 'elite', size: '50k', dll: true, ...opts }), ...extra })

/** Day table from per-day [lo, hi, close] (relative to the day's open). `fills`
 *  / `flat` default to 1, `span` to 1 calendar day. */
function days(list, { fills, flat, span } = {}) {
  const n = list.length
  return {
    n,
    start: Int32Array.from(list.map((_, i) => i)),
    end: Int32Array.from(list.map((_, i) => i)),
    active: new Uint8Array(n).fill(1),
    time: new Float64Array(n),
    lo: Float64Array.from(list.map((d) => d[0])),
    hi: Float64Array.from(list.map((d) => d[1])),
    open: new Float64Array(n),
    close: Float64Array.from(list.map((d) => d[2])),
    fills: fills ? Uint8Array.from(fills) : new Uint8Array(n).fill(1),
    flat: flat ? Uint8Array.from(flat) : new Uint8Array(n).fill(1),
    span: span ? Int32Array.from(span) : new Int32Array(n).fill(1),
  }
}
const seq = (t) => (k) => (k < t.n ? k : -1)

// ── plans ─────────────────────────────────────────────────────────────────

test('MFP Elite 50K resolves to the published rules', () => {
  const p = elite()
  assert.equal(p.startBalance, 50000)
  assert.equal(p.profitTarget, 5000)
  assert.equal(p.maxLoss, 2500)
  assert.equal(p.dailyLossLimit, 1500)
  assert.equal(p.price, 495)
  assert.equal(p.minPayout, 500)
  assert.equal(p.split, 0.8)
  assert.equal(p.lockOnPayout, false)
  assert.equal(p.dayBoundary, 'ny')
  const noDll = resolvePlan({ firm: 'mfp', plan: 'elite', size: '50k', dll: false })
  assert.equal(noDll.dailyLossLimit, null)
  assert.equal(noDll.price, 889)
})

test('Select / Prime / Signature always carry the 3% DLL and sell 10K–100K', () => {
  const s = resolvePlan({ firm: 'mfp', plan: 'select', size: '100k', dll: false })
  assert.equal(s.dailyLossLimit, 3000)
  assert.equal(s.dll, true)
  assert.equal(s.maxLoss, 3000)
  assert.equal(s.profitTarget, 9000)
  assert.deepEqual(sizesFor('mfp', 'select').map((z) => z.id), ['10k', '25k', '50k', '100k'])
  assert.deepEqual(sizesFor('mfp', 'elite').map((z) => z.id), ['5k', '10k', '25k', '50k'])
  // A size the plan does not sell falls back to 50K rather than a null rule set.
  assert.equal(resolvePlan({ firm: 'mfp', plan: 'prime', size: '5k' }).size, '50k')
})

test('Lucid presets keep their own sizes and modes', () => {
  const p = resolvePlan({ plan: 'flex', size: '50k' })
  assert.equal(p.dllMode, 'flatten')
  assert.equal(p.dayBoundary, 'globex')
  assert.equal(p.evalDrawdown, 'eod')
  assert.equal(p.lockOnPayout, true)
  assert.equal(p.lifetimeCap, null)
})

// ── replay rules ──────────────────────────────────────────────────────────

test('static floor does not trail: a run-up then a 5,400 drop survives without a DLL', () => {
  const t = days([[0, 3000, 3000], [-5400, 0, -5400], [0, 0, 0]])
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({}, { dll: false }) })
  assert.equal(a.outcome, 'eval-open') // 47,600 > 47,500
  const b = simulateAccount({ days: t, next: seq(t), plan: elite({ evalDrawdown: 'eod' }, { dll: false }) })
  assert.equal(b.outcome, 'failed') // the same path under an EOD trailing floor
})

test('touching the 3% daily floor fails the account; one dollar short does not', () => {
  const hit = days([[-1500, 0, -200]])
  const a = simulateAccount({ days: hit, next: seq(hit), plan: elite() })
  assert.equal(a.outcome, 'failed')
  assert.equal(a.reason, 'daily-loss')
  const near = days([[-1499, 0, -200], [0, 0, 0]])
  assert.equal(simulateAccount({ days: near, next: seq(near), plan: elite() }).outcome, 'eval-open')
})

test('the daily floor is measured from the day\'s opening equity', () => {
  // +1,000, then a day down 1,400 (above its own floor), then down 1,400 again.
  const t = days([[0, 1000, 1000], [-1400, 0, -1400], [-1400, 0, -1400], [0, 0, 0]])
  const a = simulateAccount({ days: t, next: seq(t), plan: elite() })
  assert.equal(a.outcome, 'eval-open') // 50,000 − 1,800 = 48,200 > 47,500 and no day lost 1,500
})

test('the evaluation passes the moment equity touches the target, even if the day closes lower', () => {
  const t = days([[0, 5000, 100], [-3000, 0, -3000]])
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({}, { dll: false }) })
  assert.equal(a.evalDays, 1)
  assert.notEqual(a.outcome, 'failed')
})

test('a bar that touches both the target and the floor counts as a breach', () => {
  const t = days([[-2500, 5000, 0]])
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({}, { dll: false }) })
  assert.equal(a.outcome, 'failed')
})

test('Elite pays all profit on demand and its floor never moves; Select locks at the start', () => {
  const t = days([[0, 600, 600], [-2400, 0, -2400], [0, 0, 0]])
  const e = simulateAccount({ days: t, next: seq(t), plan: elite({ hasEval: false }, { dll: false }) })
  assert.deepEqual(e.payouts, [600])
  assert.equal(e.take, 480)
  assert.equal(e.outcome, 'funded-open') // 47,600 after paying out
  const s = simulateAccount({ days: t, next: seq(t), plan: { ...resolvePlan({ firm: 'mfp', plan: 'select', size: '50k' }), hasEval: false, dailyLossLimit: null } })
  assert.deepEqual(s.payouts, [600])
  assert.equal(s.outcome, 'funded-breached') // floor locked at 50,000 after the first payout
})

test('no payout below the minimum or on a day that ends with a position open', () => {
  const t = days([[0, 400, 400], [0, 400, 400], [0, 100, 100]], { flat: [1, 0, 1] })
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({ hasEval: false }) })
  assert.deepEqual(a.payouts, [900]) // day 1: 400 < 500; day 2: not flat; day 3: 900
})

test('profit is counted from the balance after the last payout', () => {
  const t = days([[0, 600, 600], [-300, 0, -300], [0, 700, 700]])
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({ hasEval: false }) })
  assert.deepEqual(a.payouts, [600]) // cycle profit −300 + 700 = 400 < 500
})

test('seven calendar days without a fill close a funded account; a weekend counts', () => {
  const quiet = Array.from({ length: 10 }, () => [0, 0, 0])
  const t = days(quiet, { fills: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0] })
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({ hasEval: false }) })
  assert.equal(a.outcome, 'funded-breached')
  assert.equal(a.reason, 'inactivity')
  assert.equal(a.fundedDays, 8) // day 1 fills, then 7 idle days
  const weekdays = days(quiet.slice(0, 4), { fills: [1, 0, 0, 0], span: [1, 1, 3, 1] })
  const b = simulateAccount({ days: weekdays, next: seq(weekdays), plan: elite({ hasEval: false }) })
  assert.equal(b.outcome, 'funded-open') // 1 + 3 + 1 = 5 idle calendar days
})

test('the lifetime cap ends the account at $100,000 of trader take', () => {
  const t = days(Array.from({ length: 40 }, () => [0, 5000, 5000]))
  const a = simulateAccount({ days: t, next: seq(t), plan: elite({ hasEval: false }) })
  assert.equal(a.outcome, 'graduated')
  assert.equal(a.reason, 'lifetime-cap')
  assert.ok(Math.abs(a.take - 100000) < 1, String(a.take))
})

test('NY-midnight days split where the Globex day does not', () => {
  // 23:30 and 00:30 New York (EDT) are one Globex day but two NY days.
  const time = [Date.parse('2026-07-15T03:30:00Z') / 1000, Date.parse('2026-07-15T04:30:00Z') / 1000]
  const flatArr = [50000, 50000]
  const base = { equity: flatArr, barLo: flatArr, barHi: flatArr, barOpen: flatArr, time, initialCapital: 50000 }
  assert.equal(buildDayTable({ ...base, dayBoundary: 'ny' }).n, 2)
  assert.equal(buildDayTable({ ...base, dayBoundary: 'globex' }).n, 1)
  const t = buildDayTable({ ...base, dayBoundary: 'ny', trades: [{ entryIdx: 1, exitIdx: 1 }], positions: [0, 1] })
  assert.deepEqual(Array.from(t.fills), [0, 1])
  assert.deepEqual(Array.from(t.flat), [1, 0])
  assert.deepEqual(Array.from(t.span), [1, 1])
})

// ── perp instrument ───────────────────────────────────────────────────────

const H0 = Date.parse('2026-06-01T12:00:00Z') / 1000
function ds(rows, { symbol = 'BTC-USD', interval = '5m', step = 300 } = {}) {
  const col = (k) => rows.map((r) => r[k])
  return { id: 't', symbol, interval, time: rows.map((_, i) => H0 + i * step), open: col(0), high: col(1), low: col(2), close: col(3), volume: rows.map(() => 1) }
}
const always = (dir) => ({ id: 'always', signal: () => dir })
const perp = (extra = {}) => ({ initialCapital: 50000, instrument: { kind: 'perp', riskUsd: 500, commissionBps: 0, slippageBps: 0, swapDailyBps: 0, maxNotional: 0, ...extra } })

test('perp risk sizing: $500 at a 1% stop is $50,000 of notional; commission is bps of each fill', () => {
  const rows = [[100, 100, 100, 100], [100, 100, 100, 100], [102, 102, 102, 102], [102, 102, 102, 102]]
  const g = runBacktest({ dataset: ds(rows), strategy: always(1), params: {}, costs: perp(), risk: { stopPct: 1 } })
  assert.equal(g.trades[0].qty, 500) // 50,000 / 100
  assert.equal(g.trades[0].pnl, 1000)
  const c = runBacktest({ dataset: ds(rows), strategy: always(1), params: {}, costs: perp({ commissionBps: 3 }), risk: { stopPct: 1 } })
  // 3 bp of 50,000 in, 3 bp of 51,000 out.
  assert.ok(Math.abs(c.trades[0].pnl - (1000 - 15 - 15.3)) < 1e-9)
})

test('perp notional is capped at the leverage limit', () => {
  const rows = [[100, 100, 100, 100], [100, 100, 100, 100], [101, 101, 101, 101]]
  const r = runBacktest({ dataset: ds(rows), strategy: always(1), params: {}, costs: perp({ riskUsd: 5000, maxNotional: 100000 }), risk: { stopPct: 1 } })
  assert.equal(r.trades[0].qty, 1000)
})

test('swap is charged once per UTC hour boundary the position is open across', () => {
  // 15 bars of 5m from 12:00 = 12:00–13:15: one boundary (13:00) crossed while open.
  const rows = Array.from({ length: 16 }, () => [100, 100, 100, 100])
  const r = runBacktest({ dataset: ds(rows), strategy: always(1), params: {}, costs: perp({ notional: 0, riskUsd: 0 }), risk: {} })
  assert.equal(r.trades.length, 0) // no size, no trade
  const s = runBacktest({ dataset: ds(rows), strategy: always(1), params: {}, costs: perp({ riskUsd: 0, notional: 24000, swapDailyBps: 3 }), risk: {} })
  // 24,000 × 3 bp ÷ 24 = $0.30 per hour; the position is open from 12:05 to the
  // last bar's close, crossing 13:00 once (the last bar closes at the end of data).
  assert.ok(Math.abs(s.trades[0].fees - 0.3) < 1e-9, String(s.trades[0].fees))
  assert.ok(Math.abs(s.trades[0].pnl + 0.3) < 1e-9)
})

test('perpSetup prices BTC at crypto rates and NAS100 at Elite rates, with leverage caps', () => {
  const prop = { firm: 'mfp', plan: 'elite', size: '50k', dll: true, perpSizing: 'risk', riskPct: 1 }
  const btc = propSetup({ prop, symbol: 'BTC-USD', costs: {}, risk: { stopPct: 1 } })
  assert.equal(btc.perp, true)
  assert.equal(btc.notional, 50000)
  assert.equal(btc.costs.instrument.commissionBps, 3)
  assert.equal(btc.costs.instrument.swapDailyBps, 3)
  assert.equal(btc.costs.instrument.slippageBps, 0.8)
  assert.equal(btc.costs.instrument.maxNotional, 500000) // 10×
  const nq = propSetup({ prop, symbol: 'QQQ', costs: {}, risk: { stopPct: 0.25 } })
  assert.equal(nq.costs.instrument.commissionBps, 0.1)
  assert.equal(nq.costs.instrument.swapDailyBps, 1)
  assert.equal(nq.costs.instrument.maxNotional, 2000000) // 40×
  assert.equal(nq.proxy, true)
  const wide = propSetup({ prop: { ...prop, riskPct: 2 }, symbol: 'BTC-USD', costs: {}, risk: { stopPct: 0.1 } })
  assert.equal(wide.capped, true)
  assert.equal(wide.notional, 500000)
  assert.ok(propSetup({ prop, symbol: 'BTC-USD', costs: {}, risk: {} }).error) // risk sizing needs a stop
  assert.ok(propSetup({ prop, symbol: 'AAPL', costs: {}, risk: { stopPct: 1 } }).error)
  assert.equal(perpMarket('DOGE-USD').maxLeverage, 3)
  assert.equal(perpMarket('PEPE-USD').slippage[0][1], 6) // unknown OI → worst band
})

test('end-to-end: an MFP run replays on NY days and 24/7 bars with no forced flat', () => {
  const rows = []
  for (let i = 0; i < 288 * 6; i++) {
    const p = 100 + i * 0.002
    rows.push([p, p + 0.01, p - 0.01, p + 0.002])
  }
  const d = ds(rows)
  const s = propSetup({ prop: { firm: 'mfp', plan: 'elite', size: '50k', dll: true, perpSizing: 'notional', leverage: 1 }, symbol: 'BTC-USD', costs: {}, risk: {} })
  assert.equal(s.risk.flatByEt, 0)
  const r = runBacktest({ dataset: d, strategy: always(1), params: {}, costs: s.costs, risk: s.risk })
  assert.equal(r.trades.length, 1) // held across days
  attachProp(r, d, { prop: s.plan, costs: s.costs }, { paths: 20 })
  assert.equal(r.prop.days, 7) // 6 × 24h from 08:00 ET spans 7 NY dates
})

// ── coin-flip twins ───────────────────────────────────────────────────────

function walk(nBars, seed) {
  const rng = mulberry32(seed)
  const rows = []
  let p = 100
  for (let i = 0; i < nBars; i++) {
    const o = p
    p *= 1 + (rng() - 0.5) * 0.004
    rows.push([o, Math.max(o, p) * 1.0005, Math.min(o, p) * 0.9995, p])
  }
  return rows
}

/** Enters every 12th bar for 6 bars; direction from `pick`. */
const periodic = (pick) => ({
  id: 'periodic',
  signal: (i, state, ds) => (i % 12 < 6 ? pick(i, ds) : 0),
})

test('twins keep the strategy\'s entry and exit bars and only change direction', () => {
  const d = ds(walk(600, 3))
  const strat = periodic(() => 1)
  const costs = perp({ riskUsd: 0, notional: 50000 })
  const base = runBacktest({ dataset: d, strategy: strat, params: {}, costs, risk: {} })
  const twin = runBacktest({ dataset: d, strategy: twinStrategy(strat, { seed: 1, pLong: 0.5 }), params: {}, costs, risk: { allowShort: true } })
  assert.deepEqual(twin.trades.map((t) => [t.entryIdx, t.exitIdx]), base.trades.map((t) => [t.entryIdx, t.exitIdx]))
  const longs = twin.trades.filter((t) => t.side === 'long').length
  assert.ok(longs > 0 && longs < twin.trades.length)
})

test('a look-ahead strategy beats its twins; a coin does not', () => {
  const d = ds(walk(2400, 11))
  // Peeks at the close six bars ahead: the planted edge the test must detect.
  const peek = periodic((i, x) => (x.close[Math.min(i + 7, x.close.length - 1)] > x.open[i + 1] ? 1 : -1))
  const rng = mulberry32(5)
  const coins = new Map()
  const coin = periodic((i) => {
    const k = i - (i % 12)
    if (!coins.has(k)) coins.set(k, rng() < 0.5 ? 1 : -1)
    return coins.get(k)
  })
  const prop = { firm: 'mfp', plan: 'elite', size: '50k', dll: true, perpSizing: 'notional', leverage: 1, slippageBps: 0, commissionBps: 0, swapDailyBps: 0 }
  const setup = propSetup({ prop, symbol: 'BTC-USD', costs: {}, risk: {} })
  const args = { dataset: d, params: {}, costs: setup.costs, risk: setup.risk, plan: setup.plan, n: 39, paths: 40 }
  const good = coinFlipTwins({ ...args, strategy: peek })
  assert.ok(good.pMeanTrade <= 0.05, String(good.pMeanTrade))
  assert.ok(good.evOverTwins > 0)
  const bad = coinFlipTwins({ ...args, strategy: coin })
  assert.ok(bad.pMeanTrade > 0.05, String(bad.pMeanTrade))
})
