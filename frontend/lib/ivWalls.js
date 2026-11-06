/**
 * IV walls: prior RTH close ± one expected daily move, with the break trade frozen in
 * functions/ml/iv_wall_grid_prereg.json (picked: enter on touch, stop 0.4σ back inside, 2R target, flat 15:55).
 *
 *   σ_implied = prior close × VOL / 100 / √252   VOL = prior close of ^VXN (NQ) or ^VIX (ES)
 *   σ_hist    = prior close × stdev(last 20 RTH close-to-close log returns)
 *   σ         = (σ_implied + σ_hist) / 2,  walls = prior close ± σ
 *
 * Inputs are plain sorted arrays [{ d: 'YYYY-MM-DD', c }] keyed by ET session date, so the math is causal by
 * construction: a session's walls only read closes dated before it. Signals replay the backtest's rules on the
 * chart's own bars; the differences (decisions on every bar instead of every 5-minute close, Yahoo's
 * continuous contract, roll days from the calendar) are listed in the panel.
 */

import { etMinuteOfDay } from './backtest/time'

export const IV_WALL_VOL_INDEX = { 'NQ=F': '^VXN', 'ES=F': '^VIX' }
export const IV_WALL_DEFAULTS = { stopSigma: 0.4, targetR: 2, hvDays: 20 }

const RTH_OPEN = 9 * 60 + 30
const RTH_CLOSE = 16 * 60
const FIRST_ORDER = 9 * 60 + 35   // first order rests after the 09:30 bar closes
const ORDER_END = 15 * 60 + 35    // the last order (placed at 15:30) lives until 15:35
const HALF_CLOSE = 13 * 60        // NYSE early close; CME holiday sessions halt at 13:00 too, but end before it
const GLOBEX_OPEN = 18 * 60

const dateFmt = typeof Intl !== 'undefined'
  ? new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' })
  : null
const dateCache = new Map()

/** ET calendar date 'YYYY-MM-DD' of an epoch second. */
export function etDateKey(t) {
  const hour = Math.floor(t / 3600)
  let hit = dateCache.get(hour)
  if (hit === undefined) {
    hit = dateFmt.format(new Date(hour * 3600 * 1000))
    dateCache.set(hour, hit)
  }
  return hit
}

/** ET date of the RTH session a bar belongs to: Globex bars from 18:00 ET count toward the next day. */
export function sessionKey(t) {
  return etMinuteOfDay(t) >= GLOBEX_OPEN ? etDateKey(t + 6 * 3600) : etDateKey(t)
}

/** Third Friday of a quarterly month (Mar/Jun/Sep/Dec) for the ET date `key`, else null. */
export function quarterlyExpiry(key) {
  const [y, m] = key.split('-').map(Number)
  if (m % 3 !== 0) return null
  const dow1 = new Date(Date.UTC(y, m - 1, 1)).getUTCDay()
  const d = 1 + ((5 - dow1 + 7) % 7) + 14
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** True when session `key` is the first one on a new contract. Yahoo's NQ=F / ES=F switch to the next
 *  contract on the first session after the quarterly third Friday (checked against NQZ26 in Sep 2026), so
 *  that session's prior close is the old contract's. The backtest skipped its own roll day the same way. */
export function isRollSession(key, prevKey) {
  const f = quarterlyExpiry(key)
  return !!f && !!prevKey && prevKey <= f && f < key
}

/** NYSE 13:00 early close, as the backtest: the day after Thanksgiving, and Jul 3 / Dec 24 on Mon–Thu. */
export function isHalfDay(key) {
  const [y, m, d] = key.split('-').map(Number)
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay()
  if (m === 11 && dow === 5) {
    const thanksgiving = 1 + ((4 - new Date(Date.UTC(y, 10, 1)).getUTCDay() + 7) % 7) + 21
    return d === thanksgiving + 1
  }
  return ((m === 7 && d === 3) || (m === 12 && d === 24)) && dow >= 1 && dow <= 4
}

/** RTH close minute (ET) of session `key`: 13:00 on half days, else 16:00. */
export const rthCloseMinute = key => (isHalfDay(key) ? HALF_CLOSE : RTH_CLOSE)

const isWeekend = key => { const [y, m, d] = key.split('-').map(Number); const w = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); return w === 0 || w === 6 }

/** ET date whose RTH is still in progress: the feed's last bar is inside that date's 09:30–16:00, else null. */
function liveRthDay(time) {
  let t = -Infinity
  for (const x of time) if (Number.isFinite(x) && x > t) t = x
  if (!Number.isFinite(t)) return null
  const m = etMinuteOfDay(t)
  return m >= RTH_OPEN && m < RTH_CLOSE ? etDateKey(t) : null
}

/**
 * Last RTH bar close of each ET date from intraday bars ({ time: utc[], close: [] }). Like the backtest, weekend
 * dates and CME holiday sessions (Globex halts at 13:00 ET, so the last RTH bar starts before 13:00) are not
 * sessions, and a half day closes at 13:00. A date still in its RTH (the feed's last bar) is kept as is.
 */
export function rthCloses(time, close) {
  const byDay = new Map()
  for (let i = 0; i < time.length; i++) {
    const t = time[i]
    if (!Number.isFinite(t) || !Number.isFinite(close[i])) continue
    const m = etMinuteOfDay(t)
    if (m < RTH_OPEN || m >= RTH_CLOSE) continue
    const d = etDateKey(t)
    const prev = byDay.get(d)
    if (!prev || m >= prev.last) byDay.set(d, { c: m < rthCloseMinute(d) ? close[i] : prev?.c ?? NaN, last: m })
  }
  const live = liveRthDay(time)
  return [...byDay.keys()].sort()
    .filter(d => !isWeekend(d) && (d === live || byDay.get(d).last >= HALF_CLOSE) && Number.isFinite(byDay.get(d).c))
    .map(d => ({ d, c: byDay.get(d).c }))
}

/** Daily closes ({ time: utc[], close: [] }) keyed by ET date. */
export function dailyCloses(time, close) {
  const out = []
  for (let i = 0; i < time.length; i++) {
    if (Number.isFinite(time[i]) && Number.isFinite(close[i])) out.push({ d: etDateKey(time[i]), c: close[i] })
  }
  return out.sort((a, b) => (a.d < b.d ? -1 : 1))
}

const daysBetween = (a, b) => (Date.parse(b) - Date.parse(a)) / 86400000

/**
 * Walls for session `key`, or { skip } when the inputs can't give them. Like the backtest, a roll session gets
 * no walls, and a daily return is left out of σ_hist when it ends on a roll session or on the session just
 * before one. `rollSessions` (a Set of keys) replaces the calendar rule, e.g. with Databento's own roll days.
 */
export function wallsFor(key, closes, vols, { hvDays = IV_WALL_DEFAULTS.hvDays, rollSessions = null } = {}) {
  const prior = closes.filter(x => x.d < key)
  if (!prior.length) return { date: key, skip: 'no prior close' }
  const isRoll = (d, prev) => (rollSessions ? rollSessions.has(d) : isRollSession(d, prev))
  if (isRoll(key, prior.at(-1).d)) return { date: key, skip: 'contract roll' }
  const rets = []
  for (let i = 1; i < prior.length; i++) {
    const next = i + 1 < prior.length ? prior[i + 1].d : key
    if (isRoll(prior[i].d, prior[i - 1].d) || isRoll(next, prior[i].d)) continue
    rets.push(Math.log(prior[i].c / prior[i - 1].c))
  }
  if (rets.length < hvDays) return { date: key, skip: `needs ${hvDays} daily returns` }
  const last = rets.slice(-hvDays)
  const mean = last.reduce((s, x) => s + x, 0) / hvDays
  const sd = Math.sqrt(last.reduce((s, x) => s + (x - mean) ** 2, 0) / (hvDays - 1))
  const pcRow = prior[prior.length - 1]
  const volRow = vols.filter(x => x.d < key).at(-1)
  if (!volRow || daysBetween(volRow.d, key) > 7) return { date: key, skip: 'no recent vol-index close' }
  const pc = pcRow.c
  const sigmaIv = pc * volRow.c / 100 / Math.sqrt(252)
  const sigmaHv = pc * sd
  const sigma = (sigmaIv + sigmaHv) / 2
  return {
    date: key, pc, pcDate: pcRow.d, vol: volRow.c, volDate: volRow.d,
    sigmaIv, sigmaHv, sigma, upper: pc + sigma, lower: pc - sigma,
  }
}

/** Long / short break orders for a session's walls. */
export function breakOrders(w, { stopSigma = IV_WALL_DEFAULTS.stopSigma, targetR = IV_WALL_DEFAULTS.targetR } = {}) {
  const risk = stopSigma * w.sigma
  return {
    long: { entry: w.upper, stop: w.upper - risk, target: w.upper + targetR * risk },
    short: { entry: w.lower, stop: w.lower + risk, target: w.lower - targetR * risk },
  }
}

/**
 * Per-bar wall levels and the break signals on chart bars ({ time: utc[], open, high, low, close }).
 * Returns { upper, lower, pc } (Float64Array, NaN off-session), `sessions` (key → walls) and `signals`.
 */
export function ivWallSeries(cols, closes, vols, opts = {}) {
  const { time, open, high, low, close } = cols
  const n = close.length
  const upper = new Float64Array(n).fill(NaN)
  const lower = new Float64Array(n).fill(NaN)
  const pcLine = new Float64Array(n).fill(NaN)
  const sessions = new Map()
  const byKey = new Map()
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(time[i])) continue
    const k = sessionKey(time[i])
    if (!byKey.has(k)) byKey.set(k, [])
    byKey.get(k).push(i)
  }
  const signals = []
  const live = liveRthDay(time)
  for (const [key, idx] of byKey) {
    const closeMin = rthCloseMinute(key)
    const rthAll = idx.filter(i => { const m = etMinuteOfDay(time[i]); return m >= RTH_OPEN && m < RTH_CLOSE })
    // A finished date whose RTH bars stop before 13:00 is a CME holiday session (the backtest drops it).
    const lastMin = rthAll.length ? etMinuteOfDay(time[rthAll.at(-1)]) : -1
    if (isWeekend(key) || (rthAll.length && key !== live && lastMin < HALF_CLOSE)) {
      sessions.set(key, { date: key, skip: 'market holiday' })
      continue
    }
    const w = wallsFor(key, closes, vols, opts)
    sessions.set(key, w)
    if (w.skip) continue
    for (const i of idx) { upper[i] = w.upper; lower[i] = w.lower; pcLine[i] = w.pc }
    const rth = rthAll.filter(i => etMinuteOfDay(time[i]) < closeMin)
    if (!rth.length) continue
    w.halfDay = closeMin !== RTH_CLOSE
    w.openedOutside = !(open[rth[0]] > w.lower && open[rth[0]] < w.upper)
    if (w.openedOutside) continue
    signals.push(...sessionSignals(key, rth, cols, w, opts))
  }
  return { upper, lower, pc: pcLine, sessions, signals }
}

function sessionSignals(key, rth, cols, w, opts) {
  const { time, open, high, low, close } = cols
  const orders = breakOrders(w, opts)
  const flatMin = rthCloseMinute(key) - 5   // flat at the open of the last 5-minute bar (15:55, or 12:55 on half days)
  const used = { U: false, L: false }
  const out = []
  let pos = null
  let prevClose = NaN
  for (const i of rth) {
    const m = etMinuteOfDay(time[i])
    if (pos) {
      if (m >= flatMin) {
        closePos(pos, i, open[i], 'flat', time); out.push(pos); pos = null
      } else if (pos.side > 0 ? low[i] <= pos.stop : high[i] >= pos.stop) {
        const px = pos.side > 0 ? Math.min(open[i], pos.stop) : Math.max(open[i], pos.stop)
        closePos(pos, i, px, 'stop', time); out.push(pos); pos = null
      } else if (pos.side > 0 ? high[i] >= pos.target : low[i] <= pos.target) {
        closePos(pos, i, pos.target, 'target', time); out.push(pos); pos = null
      }
    } else if (m >= FIRST_ORDER && m < ORDER_END && m < flatMin && Number.isFinite(prevClose)) {
      // One resting order, at the nearer untouched wall to the last close (the backtest re-places it on each
      // 5-minute close).
      const cand = []
      if (!used.U && prevClose < w.upper) cand.push([w.upper - prevClose, 'U'])
      if (!used.L && prevClose > w.lower) cand.push([prevClose - w.lower, 'L'])
      cand.sort((a, b) => a[0] - b[0])
      const wall = cand[0]?.[1]
      const hit = wall === 'U' ? high[i] >= w.upper : wall === 'L' ? low[i] <= w.lower : false
      if (hit) {
        const o = wall === 'U' ? orders.long : orders.short
        const side = wall === 'U' ? 1 : -1
        const entry = side > 0 ? Math.max(open[i], o.entry) : Math.min(open[i], o.entry)
        pos = { date: key, side, wall, entryIndex: i, entryTime: time[i], entry, stop: o.stop, target: o.target, risk: Math.abs(entry - o.stop) }
        used[wall] = true
        // The fill bar can stop the trade out but not reach the target (unknown order inside the bar).
        if (side > 0 ? low[i] <= pos.stop : high[i] >= pos.stop) {
          closePos(pos, i, pos.stop, 'stop', time); out.push(pos); pos = null
        }
      }
    }
    if (high[i] >= w.upper) used.U = true
    if (low[i] <= w.lower) used.L = true
    prevClose = close[i]
  }
  if (pos) { pos.exitKind = 'open'; pos.r = pos.side * (close[rth.at(-1)] - pos.entry) / pos.risk; out.push(pos) }
  return out
}

function closePos(pos, i, px, kind, time) {
  pos.exitIndex = i
  pos.exitTime = time[i]
  pos.exit = px
  pos.exitKind = kind
  pos.r = pos.side * (px - pos.entry) / pos.risk
}
