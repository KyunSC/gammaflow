// Runs lib/ivWalls.js unchanged on bars from a JSON file and prints the sessions and break signals as JSON, so
// functions/ml/iv_wall_paper.py can keep a paper journal that follows exactly what the chart shows.
//
//   node scripts/iv-walls-replay.mjs input.json > output.json
//
// input:  { time: [utc s], open: [], high: [], low: [], close: [], vols: [{ d: 'YYYY-MM-DD', c }],
//           rollSessions: ['YYYY-MM-DD', ...] | null,   (null → the Yahoo calendar roll rule)
//           targets: ['YYYY-MM-DD', ...] }               (optional: walls + orders for sessions not in the bars yet)
// output: { sessions: [{ date, skip?, pc, vol, sigma, upper, lower, openedOutside, ... }], signals: [...],
//           targets: { 'YYYY-MM-DD': { walls, orders } } }
import { readFileSync } from 'node:fs'
import { createJiti } from 'jiti'

const jiti = createJiti(import.meta.url)
const { ivWallSeries, rthCloses, wallsFor, breakOrders, isHalfDay } = await jiti.import('../lib/ivWalls.js')

const inp = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const cols = { time: inp.time, open: inp.open, high: inp.high, low: inp.low, close: inp.close }
const opts = inp.rollSessions ? { rollSessions: new Set(inp.rollSessions) } : {}
const closes = rthCloses(cols.time, cols.close)
const res = ivWallSeries(cols, closes, inp.vols, opts)
const sessions = [...res.sessions.values()]
const signals = res.signals.map(({ entryIndex, exitIndex, ...s }) => s)
const targets = {}
for (const key of inp.targets || []) {
  const walls = wallsFor(key, closes, inp.vols, opts)
  targets[key] = { walls, halfDay: isHalfDay(key), orders: walls.skip ? null : breakOrders(walls) }
}
process.stdout.write(JSON.stringify({ sessions, signals, targets }))
