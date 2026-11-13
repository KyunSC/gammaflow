import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { runBacktest } = await jiti.import('./engine.js')
const { flatByFlags, etMinuteOfDay } = await jiti.import('./series.js')
const { simulateAccount } = await jiti.import('./prop/account.js')
const { resolvePlan, sizesFor, firmPreset, fundedMinis, FIRMS } = await jiti.import('./prop/firms.js')
const { attemptCost, summarizeAttempts } = await jiti.import('./prop/stats.js')
const { propSetup, attachProp } = await jiti.import('./prop/index.js')

const T0 = Date.parse('2026-06-01T14:00:00Z') / 1000
const DAY = 86400

function dataset(rows, time) {
  const col = k => rows.map(r => r[k])
  return { id: 't', symbol: 'NQ=F', interval: '5m', time: time || rows.map((_, i) => T0 + i * 300), open: col(0), high: col(1), low: col(2), close: col(3), volume: rows.map(() => 1) }
}
const always = dir => ({ id: 'always', signal: () => dir })
const mnq = (extra = {}) => ({ initialCapital: 50000, instrument: { pointValue: 2, tickSize: 0.25, contracts: 2, commissionPerSide: 0, slippageTicks: 0, priceScale: 1, ...extra } })

test('futures sizing: 10 points on 2 MNQ is $40, less per-side commission and tick slippage', () => {
  const rows = [[100, 100, 100, 100], [100, 100, 100, 100], [110, 110, 110, 110], [110, 110, 110, 110]]
  const gross = runBacktest({ dataset: dataset(rows), strategy: always(1), params: {}, costs: mnq(), risk: {} })
  assert.equal(gross.trades[0].pnl, 40)
  const net = runBacktest({ dataset: dataset(rows), strategy: always(1), params: {}, costs: mnq({ commissionPerSide: 0.5, slippageTicks: 1 }), risk: {} })
  // 1 tick each side = 0.5 pt × $2 × 2 contracts = $2; commission $0.50 × 2 × 2 legs = $2.
  assert.equal(net.trades[0].pnl, 36)
  assert.equal(net.metrics.finalEquity, 50036)
})

test('priceScale turns ETF points into futures points linearly', () => {
  const rows = [[100, 100, 100, 100], [100, 100, 100, 100], [101, 101, 101, 101], [101, 101, 101, 101]]
  const r = runBacktest({ dataset: dataset(rows), strategy: always(1), params: {}, costs: mnq({ priceScale: 40 }), risk: {} })
  assert.equal(r.trades[0].pnl, 40 * 2 * 2)
})

test('without an instrument the engine result is unchanged and carries no bar extremes', () => {
  const rows = Array.from({ length: 12 }, (_, i) => [100 + i, 101 + i, 99 + i, 100.5 + i])
  const r = runBacktest({ dataset: dataset(rows), strategy: always(1), params: {}, costs: { slippageBps: 1, commissionPerTrade: 1 }, risk: {} })
  assert.equal(r.barLo, null)
  assert.ok(r.metrics.finalEquity > 100000)
})

test('bar extremes: long equity dips to the low and peaks at the high', () => {
  const rows = [[100, 100, 100, 100], [100, 105, 95, 100], [100, 100, 100, 100]]
  const r = runBacktest({ dataset: dataset(rows), strategy: always(1), params: {}, costs: mnq(), risk: {} })
  assert.equal(r.barLo[1], 50000 - 5 * 4)
  assert.equal(r.barHi[1], 50000 + 5 * 4)
})

test('flat-by cutoff is 16:45 New York time in both EDT and EST', () => {
  const edt = Date.parse('2026-07-15T20:45:00Z') / 1000 // 16:45 EDT
  const est = Date.parse('2026-01-15T21:45:00Z') / 1000 // 16:45 EST
  assert.equal(etMinuteOfDay(edt), 1005)
  assert.equal(etMinuteOfDay(est), 1005)
  const times = [-2, -1, 0, 1].map(k => edt + k * 300) // 16:35, 16:40, 16:45, 16:50
  const { end, blocked } = flatByFlags(times, 1005)
  assert.deepEqual(Array.from(end), [0, 1, 0, 0])
  assert.deepEqual(Array.from(blocked), [0, 0, 1, 1])
})

// ── account replay ────────────────────────────────────────────────────────

/** Day table from per-day [lo, hi, close] P&L (relative to the day's open),
 *  one bar per day, every day active. */
function days(list) {
  const n = list.length
  return {
    n,
    start: Int32Array.from(list.map((_, i) => i)),
    end: Int32Array.from(list.map((_, i) => i)),
    active: new Uint8Array(n).fill(1),
    time: new Float64Array(n),
    lo: Float64Array.from(list.map(d => d[0])),
    hi: Float64Array.from(list.map(d => d[1])),
    open: new Float64Array(n),
    close: Float64Array.from(list.map(d => d[2])),
  }
}
const seq = (t) => (k) => (k < t.n ? k : -1)
const run = (t, plan) => simulateAccount({ days: t, next: seq(t), plan })
const firmPlan = (firm, dllDefault = true) => (p, size = '50k', extra = {}, dll = dllDefault) => ({ ...resolvePlan({ firm, plan: p, size, dll }), ...extra })
const lucid = firmPlan('lucid')
const plan = (p, extra = {}) => lucid(p, '50k', extra)

test('EOD trailing: an intraday high does not move the threshold, the close does', () => {
  // 50K, $2,000 max loss. Day 1 runs up $1,500 intraday but closes flat;
  // day 2 dips $1,900 — inside the original $2,000 even though it is $3,400
  // below the intraday peak.
  const t = days([[0, 1500, 0], [-1900, 0, -1900], [-200, 0, -200]])
  const a = run(t, plan('pro', { dailyLossLimit: null }))
  assert.equal(a.outcome, 'failed')
  assert.equal(a.evalDays, 3) // breached on day 3: 50,000 − 1,900 − 200 ≤ 48,000
})

test('EOD trailing locks at start + $100', () => {
  // +2,500 EOD → threshold would be 50,500 but stops at 50,100.
  const t = days([[0, 2500, 2500], [-2350, 0, -2350], [-100, 0, -100]])
  const a = run(t, plan('pro', { dailyLossLimit: null, profitTarget: 1e9 }))
  assert.equal(a.outcome, 'failed')
  assert.equal(a.evalDays, 3) // 52,500 − 2,350 = 50,150 survives; −100 → 50,050 ≤ 50,100
})

test('intraday trailing (Daily funded) trails the intraday peak', () => {
  const t = days([[0, 1500, 0], [-600, 0, -600]])
  const p = plan('daily', { hasEval: false, dailyLossLimit: null })
  const a = run(t, p)
  assert.equal(a.outcome, 'funded-breached') // peak 51,500 → threshold 49,500; 49,400 breaches
  const eod = run(t, { ...p, fundedDrawdown: 'eod' })
  assert.equal(eod.outcome, 'funded-open')
})

test('intraday-trailing evaluation: an unrealised peak raises the floor, touching it fails', () => {
  // 50K, $2,000. Day 1 peaks +$1,500 unrealised and closes flat: floor 49,500.
  // Day 2's low of −$500 touches it exactly. An EOD evaluation survives both days.
  const t = days([[0, 1500, 0], [-500, 0, -500]])
  const p = plan('pro', { dailyLossLimit: null, evalDrawdown: 'intraday' })
  const a = run(t, p)
  assert.equal(a.outcome, 'failed')
  assert.equal(a.evalDays, 2)
  assert.equal(run(t, { ...p, evalDrawdown: 'eod' }).outcome, 'eval-open')
})

test('evaluation floor stops at evalLockOffset; null keeps trailing', () => {
  // Target out of reach. Three +$1,900 days peak at 55,700, then a −$2,650 day
  // closes at 53,050. (A one-bar day credits its high first, so a bar spanning
  // the whole $2,000 would breach at its own open.)
  const t = days([[0, 1900, 1900], [0, 1900, 1900], [0, 1900, 1900], [-2650, 0, -2650]])
  const p = plan('pro', { dailyLossLimit: null, evalDrawdown: 'intraday', profitTarget: 1e9 })
  const capped = run(t, { ...p, evalLockOffset: 3000 })
  assert.equal(capped.outcome, 'eval-open') // floor stops at 53,000; 53,050 survives
  const open = run(t, { ...p, evalLockOffset: null })
  assert.equal(open.outcome, 'failed') // floor 55,700 − 2,000 = 53,700; 53,050 breaches
  assert.equal(open.evalDays, 4)
  // Default: the firm lockOffset (+$100), as before this option existed.
  assert.equal(resolvePlan({ plan: 'pro', size: '50k' }).evalLockOffset, resolvePlan({ plan: 'pro', size: '50k' }).lockOffset)
  assert.equal(resolvePlan({ plan: 'pro', size: '50k' }).evalDrawdown, 'eod')
})

test('soft daily loss limit freezes the day at the limit and trading resumes', () => {
  // DLL $1,200 on 50K Flex. Day 1's low is −1,500 but it would have closed −100:
  // the limit flattens it at −1,200. Max loss $2,000 is never touched.
  const t = days([[-1500, 0, -100], [0, 3000, 3000], [0, 1500, 1500]])
  const a = run(t, plan('flex', { evalConsistency: 0 }))
  assert.equal(a.dllHits, 1)
  assert.equal(a.outcome, 'funded-open')
  assert.equal(a.evalDays, 3) // −1,200 + 3,000 + 1,500 = 3,300 ≥ 3,000 target
})

test('eval consistency postpones the pass instead of failing it', () => {
  // Flex 50%: one +3,000 day is 100% of profit; passes once a second day dilutes it.
  const t = days([[0, 3000, 3000], [0, 500, 500], [0, 2600, 2600], [0, 0, 0]])
  const a = run(t, plan('flex'))
  assert.equal(a.evalDays, 3)
  assert.notEqual(a.outcome, 'failed')
})

test('funded payouts are capped, split 90/10, reduce the balance and graduate', () => {
  // Pro 50K funded: buffer 52,100, 40% consistency, first cap 2,000 then 2,500.
  const p = plan('pro', { hasEval: false, dailyLossLimit: null, maxPayouts: 2 })
  const t = days(Array.from({ length: 20 }, () => [0, 1000, 1000]))
  const a = run(t, p)
  assert.equal(a.outcome, 'graduated')
  assert.deepEqual(a.payouts, [900, 2500])
  assert.equal(a.take, 0.9 * 3400)
})

test('propSetup clamps contracts to the plan limit and scales ETF bars', () => {
  const s = propSetup({ prop: { plan: 'flex', size: '50k', dll: true, contract: 'NQ', contracts: 99, ratio: { QQQ: 40 } }, symbol: 'QQQ', costs: {}, risk: {} })
  assert.equal(s.contracts, 4)
  assert.equal(s.costs.instrument.priceScale, 40)
  assert.equal(s.costs.initialCapital, 50000)
  assert.equal(s.risk.flatByEt, 1005)
  assert.ok(propSetup({ prop: { contract: 'MNQ' }, symbol: 'BTC-USD', costs: {}, risk: {} }).error)
})

test('end-to-end: a steady winner passes evaluations; the fee bounds the loss of a loser', () => {
  const time = []
  const rows = []
  for (let d = 0; d < 30; d++) {
    for (let b = 0; b < 6; b++) {
      time.push(T0 + d * DAY + b * 300)
      const p = 20000 + d * 60 + b * 10
      rows.push([p, p + 5, p - 5, p + 10])
    }
  }
  const ds = dataset(rows, time)
  for (const [dir, check] of [[1, (h) => h.passRate > 0.5], [-1, (h) => h.passRate === 0 && h.ev === -h.cost]]) {
    const s = propSetup({ prop: { plan: 'flex', size: '50k', dll: true, contract: 'NQ', contracts: 2 }, symbol: 'NQ=F', costs: {}, risk: {} })
    const r = runBacktest({ dataset: ds, strategy: always(dir), params: {}, costs: s.costs, risk: s.risk })
    attachProp(r, ds, { prop: s.plan, costs: s.costs }, { paths: 50 })
    assert.ok(check(r.prop.historical), JSON.stringify(r.prop.historical.outcomes))
    assert.equal(r.prop.days, 30)
  }
})

// Topstep's own worked examples, from its help centre, as the acceptance test for the preset.
const topstep = firmPlan('topstep', false)

test('Topstep sells 50K to 150K and a stale size falls back to one it sells', () => {
  assert.deepEqual(sizesFor(FIRMS.topstep).map((s) => s.id), ['50k', '100k', '150k'])
  assert.equal(resolvePlan({ firm: 'topstep', plan: 'standard', size: '25k' }).startBalance, 50000)
  assert.equal(resolvePlan({ size: '25k' }).startBalance, 25000)
})

test('firmPreset does not carry a plan, size, commission or edits across firms', () => {
  assert.deepEqual(firmPreset('topstep'), { firm: 'topstep', plan: 'standard', size: '50k', dll: true, commissionPerSide: 0.61, overrides: {} })
  assert.equal(firmPreset('lucid').commissionPerSide, 0.5)
  // A daily limit switched off at one firm must not follow to a firm where it is mandatory.
  assert.equal(resolvePlan({ firm: 'lucid', dll: false, ...firmPreset('alpha') }).dailyLossLimit, 1000)
})

test('funded scaling plan: a 50K XFA trades 2 of 5 minis until $1,500, 3 until $2,000, then all 5', () => {
  const xfa = topstep('standard', '50k', { hasEval: false, tradedMinis: 5, fundedMinDays: 99 })
  assert.equal(fundedMinis(xfa, 0), 2)
  assert.equal(fundedMinis(xfa, 1500), 3)
  assert.equal(fundedMinis(xfa, 2000), 5)
  // A -$4,000 day at 5 minis is -$1,600 at 2: inside the $2,000 max loss. Unscaled it ends the account.
  const loss = days([[-4000, 0, -4000]])
  assert.equal(run(loss, xfa).outcome, 'funded-open')
  assert.equal(run(loss, { ...xfa, tradedMinis: 2 }).outcome, 'funded-breached')
  assert.equal(run(loss, { ...xfa, tradedMinis: undefined }).outcome, 'funded-breached')
  // +$3,750 at 2/5 is +$1,500, which opens the next session at 3 minis: -$4,000 is then -$2,400.
  assert.equal(run(days([[0, 3750, 3750], [-4000, 0, -4000]]), xfa).outcome, 'funded-breached')
  assert.equal(run(days([[0, 3740, 3740], [-4000, 0, -4000]]), xfa).outcome, 'funded-open')
  // The evaluation always runs at full size.
  assert.equal(run(days([[0, 3000, 3000]]), topstep('standard', '50k', { tradedMinis: 5, evalMinDays: 1, evalConsistency: 0, hasEval: true, fundedMinDays: 99 })).evalDays, 1)
  // propSetup hands the replay the traded size in minis.
  assert.equal(propSetup({ prop: { firm: 'topstep', plan: 'standard', size: '50k', dll: true, contract: 'MNQ', contracts: 30 }, symbol: 'NQ=F', costs: {}, risk: {} }).plan.tradedMinis, 3)
  assert.equal(resolvePlan({ firm: 'lucid' }).fundedScaling, null)
})

test('Topstep Combine MLL: +$500 lifts it to $48,500 and a losing day never lowers it', () => {
  // Balance 50,500 then 50,000 leaves the MLL at 48,500, so a further -$1,500 closes the account.
  const t = days([[0, 500, 500], [-500, 0, -500], [-1500, 0, -1500]])
  const a = run(t, topstep('standard', '50k', { profitTarget: 1e9 }))
  assert.equal(a.outcome, 'failed')
  assert.equal(a.evalDays, 3)
})

test('Topstep MLL locks at the starting balance, with no $100 offset', () => {
  const t = days([[0, 2000, 2000], [-1999, 0, -1999], [-1, 0, -1]])
  const a = run(t, topstep('standard', '50k', { profitTarget: 1e9 }))
  assert.equal(a.outcome, 'failed')
  assert.equal(a.evalDays, 3) // 52,000 − 2,000 = 50,000 hits the locked MLL only on day 3
})

test('Topstep Combine: a $1,800 best day raises the $3,000 target to $3,273', () => {
  const combine = topstep('standard', '50k')
  // $3,000 total with a $1,800 best day does not pass; $3,273 does.
  const short = [[0, 1800, 1800], [0, 1200, 1200]]
  assert.equal(run(days(short), combine).outcome, 'eval-open')
  assert.equal(run(days([...short, [0, 273, 273]]), combine).evalDays, 3)
})

test('Topstep Standard payout: five $150+ days, 50% of balance, then the MLL sits at $0', () => {
  // XFA from balance 0: five $400 days make $2,000, so the request is $1,000. The balance left
  // is the whole cushion, and one $1,000 loss closes the account at $0.
  const t = days([...Array(5).fill([0, 400, 400]), [-1000, 0, -1000]])
  const a = run(t, topstep('standard', '50k', { hasEval: false }))
  assert.deepEqual(a.payouts, [1000])
  assert.equal(a.outcome, 'funded-breached')
  assert.equal(a.take, 900)
})

test('Topstep Standard: a $149 day does not count toward the five', () => {
  const t = days([...Array(4).fill([0, 400, 400]), [0, 149, 149]])
  const a = run(t, topstep('standard', '50k', { hasEval: false }))
  assert.deepEqual(a.payouts, [])
})

test('Topstep Consistency: three days, paid only once the best day is at or below 40%', () => {
  const xfa = topstep('consistency', '50k', { hasEval: false })
  const ok = days([[0, 400, 400], [0, 400, 400], [0, 400, 400]])
  assert.deepEqual(run(ok, xfa).payouts, [600])
  const lumpy = days([[0, 1000, 1000], [0, 100, 100], [0, 100, 100]])
  assert.deepEqual(run(lumpy, xfa).payouts, [])
})

test('Topstep caps are per size and path, and double with an optional DLL', () => {
  assert.deepEqual(topstep('standard', '50k').payoutCap, [2000])
  assert.deepEqual(topstep('consistency', '150k').payoutCap, [6000])
  assert.deepEqual(topstep('standard', '50k', {}, true).payoutCap, [4000])
  assert.deepEqual(topstep('consistency', '150k', {}, true).payoutCap, [12000])
  assert.deepEqual(resolvePlan({ plan: 'flex', size: '50k' }).payoutCap, [2000])
})

test('attemptCost bills each started cycle and activation only on a pass', () => {
  const p = topstep('standard', '50k')
  assert.equal(attemptCost({ evalDays: 3, outcome: 'failed' }, p), 49)
  assert.equal(attemptCost({ evalDays: 21, outcome: 'failed' }, p), 49)
  assert.equal(attemptCost({ evalDays: 22, outcome: 'failed' }, p), 98)
  assert.equal(attemptCost({ evalDays: 3, outcome: 'graduated' }, p), 198)
  assert.equal(attemptCost({ evalDays: 3, outcome: 'funded-breached' }, topstep('standardNoFee', '50k')), 95)
  assert.equal(attemptCost({ evalDays: 3, outcome: 'funded-breached' }, topstep('standardNoFee', '50k', {}, true)), 85)
})

test('one-time plans cost the same flat fee whether or not the attempt passed', () => {
  const p = plan('flex')
  assert.equal(attemptCost({ evalDays: 40, outcome: 'failed' }, p), 115)
  assert.equal(attemptCost({ evalDays: 40, outcome: 'graduated' }, p), 115)
  assert.equal(summarizeAttempts([{ evalDays: 3, outcome: 'failed', take: 0, payouts: [], daysUsed: 3, dllHits: 0 }], p).cost, 115)
})

// Alpha Futures' own worked examples, from its help centre.
const alpha = firmPlan('alpha')
const funded = (p, extra = {}) => alpha(p, '50k', { hasEval: false, dailyLossLimit: null, ...extra })

test('Alpha sizes differ by plan, and a stale size falls back to one that plan sells', () => {
  assert.deepEqual(sizesFor(FIRMS.alpha, FIRMS.alpha.plans.zero).map((s) => s.id), ['25k', '50k', '100k'])
  assert.deepEqual(sizesFor(FIRMS.alpha, FIRMS.alpha.plans.direct).map((s) => s.id), ['25k', '50k', '100k', '150k'])
  assert.equal(resolvePlan({ firm: 'alpha', plan: 'zero', size: '150k' }).startBalance, 25000)
  assert.equal(resolvePlan({ firm: 'alpha', plan: 'standard', size: '25k' }).startBalance, 50000)
})

test('Alpha minimum payout is per plan', () => {
  assert.deepEqual(['zero', 'standard', 'advanced', 'direct'].map((p) => alpha(p).minPayout), [200, 500, 1000, 500])
})

test('Alpha MLL: stays at $48,500 after a give-back, and stops at $50,000 once EOD reaches $52,000', () => {
  const noTarget = alpha('standard', '50k', { profitTarget: 1e9 })
  const backOff = days([[0, 500, 500], [-500, 0, -500], [-1500, 0, -1500]])
  const a = run(backOff, noTarget)
  assert.equal(a.outcome, 'failed')
  assert.equal(a.evalDays, 3)
  const lock = days([[0, 2000, 2000], [0, 1000, 1000], [-2999, 0, -2999], [-1, 0, -1]])
  const b = run(lock, noTarget)
  assert.equal(b.outcome, 'failed')
  assert.equal(b.evalDays, 4) // 53,000 − 3,000 reaches the locked 50,000 only on day 4
})

test('Alpha: "if MLL was at $49,200 before payout, it will be after as well"', () => {
  // Five $240 days: balance 51,200, MLL 49,200, request $600, balance 50,600.
  const wins = Array.from({ length: 5 }, () => [0, 240, 240])
  const survives = days([...wins, [-1399, 0, -1399]])
  const a = run(survives, funded('standard'))
  assert.deepEqual(a.payouts, [600])
  assert.equal(a.outcome, 'funded-open') // 49,201 is above the unchanged MLL
  const breaches = days([...wins, [-1400, 0, -1400]])
  assert.equal(run(breaches, funded('standard')).outcome, 'funded-breached')
  // The same path under Topstep's rule would lock the MLL at the starting balance.
  assert.equal(run(survives, funded('standard', { payoutKeepsMll: false })).outcome, 'funded-breached')
})

test('Alpha: the MLL resumes trailing only above the old high after a payout', () => {
  // High 51,200 then a $600 request, so 51,000 EOD is no new high; 51,300 is.
  const t = days([...Array.from({ length: 5 }, () => [0, 240, 240]), [0, 400, 400], [0, 300, 300], [-2000, 0, -2000]])
  const a = run(t, funded('standard'))
  assert.equal(a.outcome, 'funded-breached') // 51,300 − 2,000 = 49,300 is the new MLL
  assert.equal(a.fundedDays, 8)
})

test('Alpha Qualified consistency is strict: exactly 40% of net is blocked, 26.7% is not', () => {
  // $1,000 net with a $400 best day is blocked; $1,500 with the same best day pays.
  const at40 = days([[0, 400, 400], [0, 200, 200], [0, 200, 200], [0, 200, 200]])
  assert.deepEqual(run(at40, funded('standard', { minProfitDays: 4, fundedMinDays: 4 })).payouts, [])
  const below = days([[0, 400, 400], [0, 300, 300], [0, 300, 300], [0, 300, 300], [0, 200, 200]])
  assert.deepEqual(run(below, funded('standard')).payouts, [750])
})

test('Alpha Direct: five equal $600 wins sit at exactly 20% and are blocked until net grows', () => {
  const five = days(Array.from({ length: 5 }, () => [0, 600, 600]))
  assert.deepEqual(run(five, funded('direct')).payouts, [])
  const six = days([...Array.from({ length: 5 }, () => [0, 600, 600]), [0, 100, 100]])
  assert.deepEqual(run(six, funded('direct')).payouts, [1550])
})

test('Alpha Direct: the profit target resets after a withdrawal and leftover profit does not carry', () => {
  const first = Array.from({ length: 6 }, (_, i) => [0, i === 5 ? 100 : 600, i === 5 ? 100 : 600])
  const t = days([...first, ...Array.from({ length: 6 }, () => [0, 300, 300])])
  // $1,800 of fresh profit is under the second $2,000 target even with $1,550 left on the account.
  assert.deepEqual(run(t, funded('direct')).payouts, [1550])
})

test('Alpha evaluation consistency is at-or-below, per its examples', () => {
  const std = days([[0, 1500, 1500], [0, 1500, 1500]])
  assert.equal(run(std, alpha('standard')).evalDays >= 2, true)
  const passes = days([[0, 1600, 1600], [0, 1200, 1200], [0, 1200, 1200]])
  assert.equal(run(passes, alpha('advanced', '50k', { fundedMinDays: 99 })).outcome, 'funded-open')
  const blocked = days([[0, 1800, 1800], [0, 1100, 1100], [0, 1100, 1100]])
  assert.equal(run(blocked, alpha('advanced')).outcome, 'eval-open')
})

test('Alpha Zero can pass in one day; Standard has no daily guard until Qualified', () => {
  const big = days([[0, 3000, 3000]])
  assert.equal(run(big, alpha('zero')).evalDays, 1)
  // A -$1,500 day: Standard's evaluation carries it in full, a funded Standard stops at -$1,000.
  const t = days([[-1500, 0, -1500], [-400, 0, -400], [-200, 0, -200]])
  const ev = run(t, alpha('standard'))
  assert.equal(ev.dllHits, 0)
  assert.equal(ev.outcome, 'failed')
  assert.equal(ev.evalDays, 3)
  const fu = run(t, alpha('standard', '50k', { hasEval: false }))
  assert.equal(fu.dllHits, 1)
  assert.equal(fu.outcome, 'funded-open')
})

test('Alpha monthly billing stops on a pass, with no activation fee', () => {
  assert.equal(attemptCost({ evalDays: 3, outcome: 'graduated' }, alpha('standard')), 129)
  assert.equal(attemptCost({ evalDays: 22, outcome: 'failed' }, alpha('standard')), 258)
  assert.equal(attemptCost({ evalDays: 0, outcome: 'funded-breached' }, alpha('direct')), 519)
})

// MyFundedFutures' own worked examples, from its help centre and plan pages.
const mff = firmPlan('mff')
const mffFunded = (p, size = '50k', extra = {}) => mff(p, size, { hasEval: false, ...extra })
const flatDays = (list) => days(list.map((v) => [Math.min(0, v), Math.max(0, v), v]))

test('MFF: Builder pays $1,500 of $3,600, above the $2,100 buffer, and the trader keeps $1,200', () => {
  const t = flatDays([1800, 1800])
  const a = run(t, mffFunded('builder'))
  assert.deepEqual(a.payouts, [1500])
  assert.ok(Math.abs(a.take - 1200) < 1e-9)
})

test('MFF: Builder needs $2,600 for a first payout and caps a cycle at $2,000', () => {
  const short = flatDays([1300, 1299])
  assert.deepEqual(run(short, mffFunded('builder')).payouts, [])
  const enough = flatDays([1300, 1300])
  assert.deepEqual(run(enough, mffFunded('builder')).payouts, [500])
  const big = flatDays([3000, 3000])
  assert.deepEqual(run(big, mffFunded('builder')).payouts, [2000])
})

test('MFF: Builder cycle consistency allows exactly 50% and blocks more', () => {
  const lumpy = flatDays([2000, 800])
  assert.deepEqual(run(lumpy, mffFunded('builder')).payouts, [])
  assert.equal(run(flatDays([1800, 1800]), mffFunded('builder')).payouts.length, 1)
})

test('MFF: Builder graduates at the fifth payout', () => {
  const t = flatDays([1800, 1800, ...Array.from({ length: 16 }, () => 500)])
  const a = run(t, mffFunded('builder'))
  assert.equal(a.payouts.length, 5)
  assert.equal(a.outcome, 'graduated')
})

test('MFF: minimum payout and split come from the plan and size', () => {
  assert.deepEqual(['25k', '50k', '100k', '150k'].map((z) => mff('builder', z).minPayout), [250, 500, 1000, 1500])
  assert.equal(mff('pro').minPayout, 1000)
  assert.equal(mff('rapid').minPayout, 500)
  assert.deepEqual(['rapid', 'rapidEod', 'builder', 'pro'].map((p) => mff(p).split), [0.9, 0.9, 0.8, 0.8])
})

test('MFF sizes differ by plan', () => {
  assert.deepEqual(sizesFor(FIRMS.mff, FIRMS.mff.plans.rapidEod).map((s) => s.id), ['25k', '50k'])
  assert.deepEqual(sizesFor(FIRMS.mff, FIRMS.mff.plans.pro).map((s) => s.id), ['50k', '100k', '150k'])
  assert.equal(sizesFor(FIRMS.mff, FIRMS.mff.plans.rapid).length, 4)
})

test('MFF Rapid funded: the max loss trails the intraday high and stops at +$100', () => {
  // A day up $1,500 that closes flat raises the floor to -$500, so a -$500 day breaches.
  const t = days([[0, 1500, 0], [-500, 0, -500]])
  assert.equal(run(t, mffFunded('rapid')).outcome, 'funded-breached')
  // Rapid EOD doesn't trail that intraday high.
  assert.equal(run(t, mffFunded('rapidEod')).outcome, 'funded-open')
  // Past +$2,100 the floor sits at +$100, so $2,600 can give back $2,499 without a breach.
  const lock = days([[2600, 2600, 2600], [-2499, 0, -2499]])
  const a = run(lock, mffFunded('rapid', '50k', { buffer: 0, minPayout: 1e9 }))
  assert.equal(a.outcome, 'funded-open')
  const worse = days([[2600, 2600, 2600], [-2500, 0, -2500]])
  assert.equal(run(worse, mffFunded('rapid', '50k', { buffer: 0, minPayout: 1e9 })).outcome, 'funded-breached')
})

test('MFF Rapid pays daily above the buffer with no consistency rule', () => {
  const t = days([2600, 500, 499].map((v) => [v, v, v])) // whole-day bars with no dip below the close
  assert.deepEqual(run(t, mffFunded('rapid')).payouts, [500, 500])
})

test('MFF Rapid EOD evaluation needs four days and a 30% best day', () => {
  const quick = flatDays([1000, 1000, 1000])
  assert.equal(run(quick, mff('rapidEod')).outcome, 'eval-open')
  const ok = flatDays([800, 800, 800, 800])
  assert.equal(run(ok, mff('rapidEod')).evalDays, 4)
  const lumpy = flatDays([1000, 700, 700, 700])
  assert.equal(run(lumpy, mff('rapidEod')).outcome, 'eval-open')
})

test('MFF Pro waits about 14 calendar days, then pays above the buffer and locks at +$100', () => {
  const nine = flatDays(Array.from({ length: 9 }, () => 500))
  assert.deepEqual(run(nine, mffFunded('pro')).payouts, [])
  const ten = flatDays([...Array.from({ length: 10 }, () => 500), -1400])
  const a = run(ten, mffFunded('pro'))
  assert.deepEqual(a.payouts, [2900])
  assert.equal(a.take, 2320)
  assert.equal(a.outcome, 'funded-open') // $2,100 − $1,400 stays above the +$100 floor
  const over = flatDays([...Array.from({ length: 10 }, () => 500), -2000])
  assert.equal(run(over, mffFunded('pro')).outcome, 'funded-breached')
})

