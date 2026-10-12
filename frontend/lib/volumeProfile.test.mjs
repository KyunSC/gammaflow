import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { computeVolumeProfile } = await jiti.import('./volumeProfile.js')
const { coveredRuns } = await jiti.import('./tickProfile.js')

const T0 = Date.parse('2026-07-06T13:25:00Z') / 1000
const bar = (utc, o, h, l, c, volume) => ({ utc, open: o, high: h, low: l, close: c, volume })
const byPrice = (vp) => Object.fromEntries(vp.buckets.filter(b => b.volume > 0).map(b => [b.priceBottom, b.volume]))

test('covered runs keep only bars wholly inside a session and merge equal steps', () => {
  const sessions = [[T0, T0 + 600]]
  // 5m bars from 10 minutes before the session to its end; the 13:30 bar is missing.
  const utc = [T0 - 600, T0 - 300, T0, T0 + 600]
  assert.deepEqual(coveredRuns(utc, sessions), [[T0, 600, 1]])
  const oneMinute = Array.from({ length: 12 }, (_, i) => T0 - 60 + i * 60)
  assert.deepEqual(coveredRuns(oneMinute, sessions), [[T0, 60, 10]])
  assert.deepEqual(coveredRuns(oneMinute, []), [])
})

test('exact bars plot traded volume unsmoothed and report their share', () => {
  const bars = [bar(T0, 98, 104, 98, 104, 999), bar(T0 + 60, 101, 101, 101, 101, 10)]
  // Exact prints at 98.00 (5) and 104.00 (7); the second bar's 10 contracts are
  // approximated at 101.00 and smoothed across neighbours, well clear of either edge.
  const vols = new Array(25).fill(0)
  vols[0] = 5
  vols[24] = 7
  const vp = computeVolumeProfile(bars, 1, new Map([[T0, { lo: 392, vols }]]))
  const total = vp.buckets.reduce((s, b) => s + b.volume, 0)
  assert.ok(Math.abs(total - 22) < 1e-9) // the exact bar's yfinance volume (999) is ignored
  assert.ok(Math.abs(vp.exactShare - 12 / 22) < 1e-9)
  assert.equal(byPrice(vp)[98], 5)
  assert.equal(byPrice(vp)[104], 7)
  assert.ok(byPrice(vp)[101] < 10 && byPrice(vp)[100.75] > 0)
})

test('exact prints far outside the bar fall back to the approximation', () => {
  const bars = [bar(T0, 100, 101, 100, 101, 40)]
  const offContract = new Map([[T0, { lo: 400 + 1000, vols: [40] }]])
  const vp = computeVolumeProfile(bars, 1, offContract)
  assert.equal(vp.exactShare, 0)
  assert.deepEqual(vp, computeVolumeProfile(bars, 1))
})
