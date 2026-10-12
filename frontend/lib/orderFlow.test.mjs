import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { deltaBubbles, profileNodesFromTicks, sessionNodes } = await jiti.import('./orderFlow.js')

const T0 = Date.parse('2026-07-06T13:30:00Z') / 1000
const bar = (utc, low, high) => ({ utc, time: utc - 4 * 3600, open: low, high, low, close: high, volume: 1 })

// Two humps on a 1-tick grid: a big one at tick 420 (105.00), a smaller one at 460 (115.00).
function twoHumps() {
  const m = new Map()
  for (let t = 400; t < 480; t++) {
    const v = 100 * Math.exp(-0.5 * ((t - 420) / 5) ** 2) + 60 * Math.exp(-0.5 * ((t - 460) / 5) ** 2)
    m.set(t, Math.round(v))
  }
  return m
}

test('POC is the busiest row, HVN the other peak, LVN the trough between', () => {
  const nodes = profileNodesFromTicks(twoHumps(), { rows: 80, maxHvn: 3 })
  assert.equal(nodes.rowTicks, 1)
  assert.equal(nodes.poc, 105)
  assert.deepEqual(nodes.hvn, [115])
  assert.equal(nodes.lvn.length, 1)
  assert.ok(nodes.lvn[0] > 108 && nodes.lvn[0] < 113, `LVN at ${nodes.lvn[0]}`)
  // No HVNs requested: the POC alone, so no LVN either.
  assert.deepEqual(profileNodesFromTicks(twoHumps(), { maxHvn: 0 }).hvn, [])
  assert.deepEqual(profileNodesFromTicks(twoHumps(), { maxHvn: 0 }).lvn, [])
})

test('zones cover each node, in price order, without overlapping', () => {
  const nodes = profileNodesFromTicks(twoHumps(), { rows: 80, maxHvn: 3 })
  assert.deepEqual(nodes.zones.map(z => z.kind), ['poc', 'lvn', 'hvn'])
  const [poc, lvn, hvn] = nodes.zones
  const contains = (z, price) => z.lo <= price && price < z.hi
  assert.ok(contains(poc, nodes.poc), JSON.stringify(poc))
  assert.ok(contains(lvn, nodes.lvn[0]), JSON.stringify(lvn))
  assert.ok(contains(hvn, nodes.hvn[0]), JSON.stringify(hvn))
  assert.ok(poc.hi <= lvn.lo && lvn.hi <= hvn.lo)
  // A stricter threshold keeps the POC zone no wider.
  const [tight] = profileNodesFromTicks(twoHumps(), { zonePct: 90 }).zones
  assert.ok(tight.hi - tight.lo <= poc.hi - poc.lo)
  // Even a loose threshold never lets the boxes overlap.
  const loose = profileNodesFromTicks(twoHumps(), { zonePct: 10 }).zones
  for (let k = 1; k < loose.length; k++) assert.ok(loose[k - 1].hi <= loose[k].lo, JSON.stringify(loose))
})

test('coarser rows report row midpoints', () => {
  const nodes = profileNodesFromTicks(twoHumps(), { rows: 20 })
  assert.equal(nodes.rowTicks, 4)
  assert.equal(nodes.poc, 105.375) // row of ticks 420..423
})

test('delta bubbles sit where the winning side was most aggressive and keep the biggest', () => {
  const bars = [bar(T0, 100, 101), bar(T0 + 60, 100, 101), bar(T0 + 120, 100, 101)]
  const exact = new Map([
    [T0, { lo: 400, vols: [10, 10, 10, 10, 10], deltas: [-2, 8, 1, 0, -1] }], // +6 at 100.25
    [T0 + 60, { lo: 400, vols: [30, 30], deltas: [-20, 5] }], // -15 at 100.00
    [T0 + 120, { lo: 400, vols: [4], deltas: [0] }], // flat: no bubble
  ])
  const all = deltaBubbles(bars, exact, { minPct: 0 })
  assert.deepEqual(all.bubbles.map(b => [b.time, b.price, b.delta, b.volume]), [
    [bars[0].time, 100.25, 6, 50],
    [bars[1].time, 100, -15, 60],
  ])
  assert.equal(all.maxAbs, 15)
  assert.deepEqual(deltaBubbles(bars, exact, { minPct: 50 }).bubbles.map(b => b.delta), [-15])
  // Without side data there is nothing to plot.
  assert.equal(deltaBubbles(bars, new Map([[T0, { lo: 400, vols: [5], deltas: null }]])), null)
})

test('sessions split on overnight gaps and drop when any bar is off-contract', () => {
  const day2 = T0 + 24 * 3600
  const bars = [bar(T0, 100, 101), bar(T0 + 60, 100, 101), bar(day2, 100, 101), bar(day2 + 60, 100, 101)]
  const exact = new Map([
    [T0, { lo: 400, vols: [5, 1], deltas: null }],
    [T0 + 60, { lo: 401, vols: [1, 9], deltas: null }],
    [day2, { lo: 400, vols: [5], deltas: null }],
    [day2 + 60, { lo: 400 + 1000, vols: [5], deltas: null }], // other contract
  ])
  const sessions = sessionNodes(bars, exact, { rows: 80 })
  assert.equal(sessions.length, 1)
  assert.equal(sessions[0].startTime, bars[0].time)
  assert.equal(sessions[0].endTime, bars[1].time)
  assert.equal(sessions[0].poc, 100.5) // tick 402 holds 9
})
