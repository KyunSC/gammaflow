import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { synthesizeTickVolume } = await jiti.import('./syntheticTickProfile.js')
const { TICK_SOURCE } = await jiti.import('./tickProfile.js')
const { exactFits, TICK_SIZE } = await jiti.import('./volumeProfile.js')

// 2026-07-06 09:25 EDT = 13:25 UTC.
const RTH_OPEN = 1_783_344_300
const tick = (p) => Math.round(p / TICK_SIZE)

// 5m bars from `start` (epoch s), as the chart receives them (time as a numeric string).
function bars(start, count, step = 300) {
  const out = []
  let price = 20000
  for (let i = 0; i < count; i++) {
    const open = price
    const close = open + ((i * 7) % 11 - 5) * TICK_SIZE * 3
    const high = Math.max(open, close) + (i % 4 + 1) * TICK_SIZE * 2
    const low = Math.min(open, close) - (i % 3 + 1) * TICK_SIZE * 2
    out.push({ time: String(start + i * step), open, high, low, close, volume: 500 + i * 37 })
    price = close
  }
  return out
}

test('defaults to simulated prints unless the build asks for real ones', () => {
  assert.equal(TICK_SOURCE, process.env.NEXT_PUBLIC_TICK_SOURCE === 'real' ? 'real' : 'synthetic')
})

test('the same bars give the same prints', () => {
  const data = bars(RTH_OPEN, 20)
  const a = synthesizeTickVolume('NQ=F', data)
  const b = synthesizeTickVolume('NQ=F', data.map(d => ({ ...d })))
  assert.equal(a.size, 20)
  assert.deepEqual([...a.entries()], [...b.entries()])
  // Another symbol gets its own shape.
  assert.notDeepEqual([...synthesizeTickVolume('ES=F', data).values()], [...a.values()])
})

test('prints stay inside each bar, sum to its volume and never exceed it in delta', () => {
  const data = bars(RTH_OPEN, 60)
  const map = synthesizeTickVolume('NQ=F', data)
  for (const d of data) {
    const p = map.get(Number(d.time))
    assert.ok(p, `bar ${d.time} simulated`)
    assert.ok(p.lo >= tick(d.low))
    assert.ok(p.lo + p.vols.length - 1 <= tick(d.high))
    assert.equal(p.vols.reduce((s, v) => s + v, 0), d.volume)
    assert.equal(p.deltas.length, p.vols.length)
    p.vols.forEach((v, k) => {
      assert.ok(Number.isInteger(v) && v >= 0)
      assert.ok(Number.isInteger(p.deltas[k]) && Math.abs(p.deltas[k]) <= v)
    })
    assert.ok(exactFits(p, tick(d.low), tick(d.high), d.close))
  }
})

test('net delta leans with the bar direction', () => {
  const up = { time: String(RTH_OPEN), open: 20000, high: 20010, low: 19999, close: 20009.5, volume: 5000 }
  const down = { time: String(RTH_OPEN + 300), open: 20009.5, high: 20010, low: 19999, close: 20000, volume: 5000 }
  const map = synthesizeTickVolume('NQ=F', [up, down])
  const net = (p) => p.deltas.reduce((s, d) => s + d, 0)
  assert.ok(net(map.get(RTH_OPEN)) > 0)
  assert.ok(net(map.get(RTH_OPEN + 300)) < 0)
})

test('skips bars outside RTH, daily bars and non-futures symbols', () => {
  // 09:00–09:25 ET (before the open) and 15:55 onward with 10m bars (straddles 16:00).
  const early = bars(RTH_OPEN - 25 * 60, 5)
  const map = synthesizeTickVolume('NQ=F', [...early, ...bars(RTH_OPEN, 2)])
  for (const d of early) assert.equal(map.has(Number(d.time)), false)
  assert.equal(map.has(RTH_OPEN), true)

  const close = RTH_OPEN + (6 * 60 + 30) * 60 // 15:55 ET
  const late = synthesizeTickVolume('NQ=F', bars(close - 600, 3, 600))
  assert.deepEqual([...late.keys()], [close - 600]) // 15:45–15:55 fits; 15:55–16:05 doesn't
  // Overnight Globex bars.
  assert.equal(synthesizeTickVolume('NQ=F', bars(RTH_OPEN - 10 * 3600, 12)), null)

  const daily = bars(RTH_OPEN, 5).map((d, i) => ({ ...d, time: `2026-07-0${6 + i}` }))
  assert.equal(synthesizeTickVolume('NQ=F', daily), null)
  // Daily bars carrying epoch times are still too wide for a session.
  assert.equal(synthesizeTickVolume('NQ=F', bars(RTH_OPEN, 5, 86400)), null)

  assert.equal(synthesizeTickVolume('QQQ', bars(RTH_OPEN, 5)), null)
  assert.equal(synthesizeTickVolume('BTC-USD', bars(RTH_OPEN, 5)), null)
})

test('bars with no volume or bad prices are skipped', () => {
  const data = bars(RTH_OPEN, 3)
  data[0].volume = 0
  data[1].high = NaN
  const map = synthesizeTickVolume('NQ=F', data)
  assert.deepEqual([...map.keys()], [Number(data[2].time)])
})
