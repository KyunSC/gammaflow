import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const ivWallsMod = await jiti.import('./ivWalls.js')
const { wallsFor, isRollSession, rthCloses, dailyCloses, ivWallSeries, breakOrders, sessionKey } = ivWallsMod

// October 2026 is EDT: ET = UTC − 4h.
const et = (day, hh, mm, month = 10) => Date.UTC(2026, month - 1, day, hh + 4, mm) / 1000
const key = (day, month = 10) => `2026-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`

// 21 weekday closes ending 2026-10-30, alternating ±1% so σ_hist ≈ 1% of price.
function history(lastDay = 30) {
  const days = []
  for (let d = 1; d <= lastDay; d++) {
    const dow = new Date(Date.UTC(2026, 9, d)).getUTCDay()
    if (dow !== 0 && dow !== 6) days.push(d)
  }
  let c = 20000
  const closes = days.map((d, i) => { if (i) c *= i % 2 ? 1.01 : 1 / 1.01; return { d: key(d), c } })
  return closes
}
const vols = [{ d: key(29), c: 20 }, { d: key(30), c: 20 }]

test('isRollSession marks the first session after the quarterly third Friday', () => {
  assert.equal(isRollSession('2026-09-21', '2026-09-18'), true)   // Mon after the Sep 18 expiry
  assert.equal(isRollSession('2026-09-18', '2026-09-17'), false)  // expiry day itself
  assert.equal(isRollSession('2026-06-22', '2026-06-18'), true)   // Jun 19 holiday: expiry session was Jun 18
  assert.equal(isRollSession('2026-10-19', '2026-10-16'), false)  // October is not a quarterly month
})

test('wallsFor blends implied and historical σ around the prior close', () => {
  const closes = history()
  const w = wallsFor('2026-11-02', closes, vols)
  const pc = closes.at(-1).c
  assert.equal(w.pc, pc)
  assert.ok(Math.abs(w.sigmaIv - pc * 0.20 / Math.sqrt(252)) < 1e-9)
  assert.ok(Math.abs(w.sigmaHv / pc - 0.0102) < 0.0005, `hv ${w.sigmaHv / pc}`)
  assert.ok(Math.abs(w.sigma - (w.sigmaIv + w.sigmaHv) / 2) < 1e-9)
  assert.ok(Math.abs(w.upper - (pc + w.sigma)) < 1e-9 && Math.abs(w.lower - (pc - w.sigma)) < 1e-9)
})

test('wallsFor is causal and skips what the backtest skipped', () => {
  const closes = history()
  const a = wallsFor('2026-10-30', closes, vols)
  const b = wallsFor('2026-10-30', closes.map(x => (x.d >= '2026-10-30' ? { ...x, c: x.c * 2 } : x)), vols)
  assert.equal(a.skip, undefined)
  assert.deepEqual(a, b)
  assert.equal(wallsFor('2026-10-05', closes, vols).skip, 'needs 20 daily returns')
  assert.equal(wallsFor('2026-12-21', [...closes, { d: '2026-12-18', c: 20000 }], vols).skip, 'contract roll')
  assert.equal(wallsFor('2026-11-20', closes, vols).skip, 'no recent vol-index close')
})

test('rthCloses keeps the last 09:30–16:00 close of each ET day; dailyCloses keys by ET date', () => {
  const time = [et(5, 9, 0), et(5, 15, 0), et(5, 16, 0), et(6, 15, 0)]
  const close = [1, 2, 3, 4]
  assert.deepEqual(rthCloses(time, close), [{ d: key(5), c: 2 }, { d: key(6), c: 4 }])
  assert.deepEqual(dailyCloses([et(6, 9, 30), et(5, 9, 30)], [11, 10]), [{ d: key(5), c: 10 }, { d: key(6), c: 11 }])
  assert.equal(sessionKey(et(5, 18, 0)), key(6))  // Globex evening counts toward the next session
  assert.equal(sessionKey(et(5, 17, 0)), key(5))
})

// One session of 5m bars on 2026-11-02 (EST from Nov 1: ET = UTC − 5h).
const etNov = (hh, mm) => Date.UTC(2026, 10, 2, hh + 5, mm) / 1000
function session(path) {
  const cols = { time: [], open: [], high: [], low: [], close: [] }
  for (let t = etNov(9, 30), k = 0; t < etNov(16, 0); t += 300, k++) {
    const p = path(k)
    cols.time.push(t); cols.open.push(p.o); cols.high.push(p.h); cols.low.push(p.l); cols.close.push(p.c)
  }
  return cols
}

test('break long fills on the upper-wall touch and books 2R at the target', () => {
  const closes = history()
  const w = wallsFor('2026-11-02', closes, vols)
  const o = breakOrders(w)
  const flat = w.pc
  const cols = session(k => (k < 5 ? { o: flat, h: flat + 1, l: flat - 1, c: flat }
    : k === 5 ? { o: flat, h: w.upper - 1, l: flat, c: w.upper - 1 }
    : k === 6 ? { o: w.upper - 1, h: w.upper + 2, l: w.upper - 1, c: w.upper + 1 }
      : { o: w.upper + 1, h: o.long.target + 1, l: w.upper, c: o.long.target }))
  const s = ivWallSeries(cols, closes, vols).signals
  assert.equal(s.length, 1)
  assert.equal(s[0].side, 1)
  assert.equal(s[0].entry, w.upper)
  assert.equal(s[0].exitKind, 'target')
  assert.ok(Math.abs(s[0].r - 2) < 1e-9)
})

test('break short stops out at −1R; a touch before 09:35 uses the wall up', () => {
  const closes = history()
  const w = wallsFor('2026-11-02', closes, vols)
  const o = breakOrders(w)
  const flat = w.pc
  const cols = session(k => (k === 0 ? { o: flat, h: w.upper + 1, l: flat, c: flat }   // upper touched at 09:30–09:35
    : k < 10 ? { o: flat, h: flat + 1, l: flat - 1, c: flat }
      : k === 10 ? { o: flat, h: flat, l: w.lower - 1, c: w.lower }
        : { o: w.lower, h: o.short.stop + 1, l: w.lower - 1, c: o.short.stop }))
  const s = ivWallSeries(cols, closes, vols).signals
  assert.equal(s.length, 1)
  assert.equal(s[0].side, -1)
  assert.equal(s[0].exitKind, 'stop')
  assert.ok(Math.abs(s[0].r + 1) < 1e-9)
})

test('no trades on a session that opens outside the band', () => {
  const closes = history()
  const w = wallsFor('2026-11-02', closes, vols)
  const hi = w.upper + 5
  const cols = session(() => ({ o: hi, h: hi + 50, l: hi - 1, c: hi }))
  const r = ivWallSeries(cols, closes, vols)
  assert.equal(r.signals.length, 0)
  assert.equal(r.sessions.get('2026-11-02').openedOutside, true)
})

test('holiday sessions are dropped and half days close at 13:00, as the backtest', () => {
  const { isHalfDay } = ivWallsMod
  assert.equal(isHalfDay('2026-11-27'), true)    // day after Thanksgiving
  assert.equal(isHalfDay('2026-12-24'), true)    // Thursday
  assert.equal(isHalfDay('2027-12-24'), false)   // Friday: NYSE is closed for Christmas observed
  assert.equal(isHalfDay('2026-07-03'), false)   // Friday (Independence Day observed)
  // Labor Day 2026-09-07 (EDT): CME trades to 13:00, so the last RTH bar starts at 12:55.
  const time = [], close = []
  const add = (day, hh, mm, c) => { time.push(et(day, hh, mm, 9)); close.push(c) }
  add(4, 15, 55, 100); add(7, 12, 55, 200); add(8, 15, 55, 300)
  assert.deepEqual(rthCloses(time, close).map(x => x.d), ['2026-09-04', '2026-09-08'])
  // ...but a date whose RTH is still in progress is kept.
  assert.deepEqual(rthCloses(time.slice(0, 2), close.slice(0, 2)).map(x => x.d), ['2026-09-04', '2026-09-07'])
  // Half day: the 13:05 bar is after the close.
  const t2 = [Date.UTC(2026, 10, 27, 17, 55) / 1000, Date.UTC(2026, 10, 27, 18, 5) / 1000, Date.UTC(2026, 10, 30, 20, 55) / 1000]
  assert.deepEqual(rthCloses(t2, [1, 2, 3]), [{ d: '2026-11-27', c: 1 }, { d: '2026-11-30', c: 3 }])
})

test('a holiday session gets no walls or trades', () => {
  const closes = history()
  // 2026-11-02 bars that stop at 12:55, then the next session's Globex open: a holiday-hours session.
  const cols = session(k => ({ o: 1, h: 1, l: 1, c: 1 }))
  const cut = cols.time.findIndex(t => t >= etNov(13, 0))
  for (const k of Object.keys(cols)) cols[k] = cols[k].slice(0, cut)
  cols.time.push(etNov(18, 0)); cols.open.push(1); cols.high.push(1); cols.low.push(1); cols.close.push(1)
  const r = ivWallSeries(cols, closes, vols)
  assert.equal(r.sessions.get('2026-11-02').skip, 'market holiday')
  assert.equal(r.signals.length, 0)
})
