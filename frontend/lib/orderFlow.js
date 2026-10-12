/**
 * Order flow from exact futures trade prints (lib/tickProfile.js): per-bar
 * delta bubbles and per-session POC / HVN / LVN. Nothing here is approximated:
 * bars without prints contribute nothing, and bars whose prints sit on a
 * different contract than the chart (rolls, see exactFits) are left out.
 */
import { exactFits, gaussianSmooth1D, TICK_SIZE } from './volumeProfile'
import { tradingDay } from './backtest/time'

const tickOf = (price) => Math.round(price / TICK_SIZE)

// The bar's prints, null when it has none, false when they don't fit the bar.
function barPrints(bar, exactByUtc) {
  const exact = exactByUtc?.get(bar.utc)
  if (!exact) return null
  return exactFits(exact, tickOf(bar.low), tickOf(bar.high), bar.close) ? exact : false
}

/**
 * One bubble per covered bar with side data: its net aggressor delta, placed at
 * the price where that side was most aggressive. Bars need `time` (chart time)
 * and `utc`. Only bars at or above the `minPct` percentile of |delta| are kept.
 * Returns { bubbles: [{time, price, delta, volume}], maxAbs } or null.
 */
export function deltaBubbles(bars, exactByUtc, { minPct = 80 } = {}) {
  if (!exactByUtc) return null
  const all = []
  for (const bar of bars) {
    const exact = barPrints(bar, exactByUtc)
    if (!exact?.deltas) continue
    let delta = 0, volume = 0
    for (let k = 0; k < exact.vols.length; k++) {
      delta += exact.deltas[k]
      volume += exact.vols[k]
    }
    if (delta === 0) continue
    const sign = Math.sign(delta)
    let at = 0
    for (let k = 1; k < exact.deltas.length; k++) {
      if (exact.deltas[k] * sign > exact.deltas[at] * sign) at = k
    }
    all.push({ time: bar.time, price: (exact.lo + at) * TICK_SIZE, delta, volume })
  }
  if (!all.length) return null
  const mags = all.map(b => Math.abs(b.delta)).sort((a, b) => a - b)
  const cut = mags[Math.min(mags.length - 1, Math.floor((minPct / 100) * mags.length))]
  return { bubbles: all.filter(b => Math.abs(b.delta) >= cut), maxAbs: mags[mags.length - 1] }
}

/**
 * POC, HVNs and LVNs of one volume-at-price profile (Map<tick, volume>), on a
 * grid of about `rows` rows. POC is the busiest row. HVNs are peaks of the
 * smoothed profile with prominence of at least 10% of its tallest row, the
 * `maxHvn` most prominent (the peak of the POC's own hump is the POC, not an
 * HVN: no dip of 10% or more lies between them). LVNs are
 * the thinnest row between neighbouring peaks. Prices are row midpoints.
 *
 * `zones` gives each node's price range as [{ kind, lo, hi }] (row edges,
 * ordered by price). An LVN zone is the valley rows within the bottom
 * (100 - zonePct)% of the climb to its lower neighbouring peak; a POC or HVN
 * zone is the rows around its peak at or above zonePct% of it, stopping at the
 * neighbouring LVN zones so boxes never overlap.
 */
export function profileNodesFromTicks(volumeByTick, { rows = 80, maxHvn = 3, zonePct = 70 } = {}) {
  let lo = Infinity, hi = -Infinity
  for (const t of volumeByTick.keys()) {
    if (t < lo) lo = t
    if (t > hi) hi = t
  }
  if (!Number.isFinite(lo)) return null
  const rowTicks = Math.max(1, Math.ceil((hi - lo + 1) / rows))
  const base = Math.floor(lo / rowTicks)
  const n = Math.floor(hi / rowTicks) - base + 1
  const hist = new Array(n).fill(0)
  for (const [t, v] of volumeByTick) hist[Math.floor(t / rowTicks) - base] += v
  const mid = (i) => ((base + i) * rowTicks + (rowTicks - 1) / 2) * TICK_SIZE

  let pocIdx = 0
  for (let i = 1; i < n; i++) if (hist[i] > hist[pocIdx]) pocIdx = i

  // Topographic prominence: on each side, the lowest point before a taller row
  // (or the edge); the higher of the two is the col the peak rises from.
  const s = gaussianSmooth1D(hist, 1.5)
  const top = Math.max(...s)
  const onPocHump = (i) => {
    let low = Infinity
    for (let j = Math.min(i, pocIdx); j <= Math.max(i, pocIdx); j++) low = Math.min(low, s[j])
    return low >= 0.9 * Math.min(s[i], s[pocIdx])
  }
  const peaks = []
  for (let i = 1; i < n - 1; i++) {
    if (s[i - 1] >= s[i] || s[i + 1] > s[i]) continue
    let leftMin = s[i], rightMin = s[i]
    for (let j = i - 1; j >= 0 && s[j] <= s[i]; j--) leftMin = Math.min(leftMin, s[j])
    for (let j = i + 1; j < n && s[j] <= s[i]; j++) rightMin = Math.min(rightMin, s[j])
    const prominence = s[i] - Math.max(leftMin, rightMin)
    if (prominence >= 0.1 * top) peaks.push({ i, prominence, isPoc: onPocHump(i) })
  }
  peaks.sort((a, b) => b.prominence - a.prominence)

  const kept = []
  let hvnCount = 0, pocPeak = false
  for (const p of peaks) {
    if (p.isPoc ? pocPeak : hvnCount >= maxHvn) continue
    if (p.isPoc) pocPeak = true
    else hvnCount++
    kept.push(p)
  }
  kept.sort((a, b) => a.i - b.i)

  // Rows jLo..jHi around `center` for which `keep` holds, within minRow..maxRow.
  const growZone = (center, keep, minRow, maxRow) => {
    let jLo = center, jHi = center
    while (jLo - 1 >= minRow && keep(jLo - 1)) jLo--
    while (jHi + 1 <= maxRow && keep(jHi + 1)) jHi++
    return [jLo, jHi]
  }
  const f = zonePct / 100
  const zone = (kind, [jLo, jHi]) =>
    ({ kind, lo: (base + jLo) * rowTicks * TICK_SIZE, hi: (base + jHi + 1) * rowTicks * TICK_SIZE })

  const lvn = []
  const lvnRows = []
  for (let k = 1; k < kept.length; k++) {
    const a = kept[k - 1].i, b = kept[k].i
    let v = a + 1
    for (let j = v + 1; j < b; j++) if (s[j] < s[v]) v = j
    lvn.push(mid(v))
    const ceiling = s[v] + (1 - f) * (Math.min(s[a], s[b]) - s[v])
    lvnRows.push(growZone(v, j => s[j] <= ceiling, a + 1, b - 1))
  }

  // Peak zones stop short of the LVN zones on either side.
  const peakZone = (kind, center) => {
    let minRow = 0, maxRow = n - 1
    for (const [jLo, jHi] of lvnRows) {
      if (jHi < center) minRow = Math.max(minRow, jHi + 1)
      if (jLo > center) maxRow = Math.min(maxRow, jLo - 1)
    }
    const floor = f * s[center]
    return zone(kind, growZone(center, j => s[j] >= floor, minRow, maxRow))
  }
  const hvnPeaks = kept.filter(p => !p.isPoc)
  const zones = [
    peakZone('poc', pocIdx),
    ...hvnPeaks.map(p => peakZone('hvn', p.i)),
    ...lvnRows.map(rows => zone('lvn', rows)),
  ].sort((x, y) => x.lo - y.lo)
  return { poc: mid(pocIdx), hvn: hvnPeaks.map(p => mid(p.i)), lvn, rowTicks, zones }
}

/**
 * Nodes of each covered session's own profile, built from its prints alone:
 * [{ startTime, endTime, poc, hvn: [price], lvn: [price], zones }] in time order.
 * A session with any bar off the chart's contract is skipped, since a partial
 * profile would misplace every node.
 */
export function sessionNodes(bars, exactByUtc, opts) {
  if (!exactByUtc) return []
  const sessions = []
  let cur = null
  for (const bar of bars) {
    const exact = barPrints(bar, exactByUtc)
    if (exact === null) continue
    const day = tradingDay(bar.utc)
    if (!cur || day !== cur.day) {
      cur = { day, startTime: bar.time, ok: true, volume: new Map() }
      sessions.push(cur)
    }
    cur.endTime = bar.time
    if (!exact) {
      cur.ok = false
      continue
    }
    for (let k = 0; k < exact.vols.length; k++) {
      const t = exact.lo + k
      if (exact.vols[k] > 0) cur.volume.set(t, (cur.volume.get(t) || 0) + exact.vols[k])
    }
  }
  return sessions
    .filter(s => s.ok && s.volume.size)
    .map(s => ({ startTime: s.startTime, endTime: s.endTime, ...profileNodesFromTicks(s.volume, opts) }))
}
