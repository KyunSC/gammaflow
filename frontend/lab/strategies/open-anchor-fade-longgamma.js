import { getSeries } from '../../lib/backtest/series.js'

// Entry windows in minutes_since_open. The last lab bar is 370 (15:40 ET).
const WINDOWS = { early: [30, 120], mid: [120, 240], late: [240, 330] }

/**
 * Treat the 09:30 opening print (`f:rth_open`) as the day's fair price. Once
 * price closes `thr` ATRs away from it inside the window, fade back toward it:
 * exit after taking back `tgt` of the stretch, or if the stretch grows to
 * `stop` times its size at entry (0 = no stop). One trade per day.
 * Gated on long gamma (above zero gamma) at entry.
 */
export default {
  id: 'open-anchor-fade-longgamma',
  family: 'open-anchor',
  rationale: 'Above zero gamma, dealers hedge counter-cyclically (sell rallies, buy dips), which should pull price back toward the 09:30 opening print once it is stretched thr ATRs away. On raw bars the ungated fade had no edge; this tests whether long gamma is the condition under which the open acts as fair value.',
  params: [
    { key: 'thr', values: [2, 4, 6] },
    { key: 'window', values: ['early', 'mid', 'late'] },
    { key: 'tgt', values: [0.5, 1] },
    { key: 'stop', values: [2, 0] },
  ],
  risk: { flatAtSessionEnd: true },
  warmup: () => 1,
  prepare(ds) {
    return {
      mins: getSeries(ds, 'f:minutes_since_open'),
      anchor: getSeries(ds, 'f:rth_open'),
      regime: getSeries(ds, 'f:above_zero_gamma'),
      atr: getSeries(ds, 'f:atr_14'),
      tradedDay: -1,
      entryGap: 0,
    }
  },
  signal(i, s, ds, p, prev) {
    const a = s.anchor[i]
    const atr = s.atr[i]
    if (!(a > 0) || !(atr > 0)) return 0
    const gap = ds.close[i] - a
    if (prev !== 0) {
      const stretch = -prev * gap // > 0 while price is still on the side we faded
      if (stretch <= s.entryGap * (1 - p.tgt)) return 0
      if (p.stop > 0 && stretch >= s.entryGap * p.stop) return 0
      return prev
    }
    const day = Math.floor(ds.time[i] / 86400)
    if (s.tradedDay === day) return 0
    const [lo, hi] = WINDOWS[p.window]
    const m = s.mins[i]
    if (!(m >= lo && m < hi) || !(s.regime[i] > 0)) return 0
    if (Math.abs(gap) < p.thr * atr) return 0
    s.tradedDay = day
    s.entryGap = Math.abs(gap)
    return gap > 0 ? -1 : 1
  },
}
