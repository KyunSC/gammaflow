/**
 * Synthetic research datasets: the columnar 5m RTH artifact that
 * functions/ml/export_backtest_data.py produces (bars, the baseline and GEX
 * feature columns, walk-forward predictions), built from lib/synthetic prices
 * and GEX instead of real data. Used for the bundled example under
 * public/backtest (scripts/generate-synthetic-sample.mjs) and for the public
 * site's /api/backtest/datasets.
 *
 * The "model" is a seeded random number per bar, so ML strategies run but have
 * no skill by construction. Feature formulas follow build_dataset.py.
 */
import { etMinuteOfDay } from '../backtest/time'
import { GENERATOR_VERSION, dayString, etDay, gaussian, hash, intradayBars, rng, symbolSpec, tradingDays } from './market'
import { gexLadder, keyLevels } from './gex'

export const HORIZON_BARS = 3
const BASELINE = ['log_return_5m', 'log_return_15m', 'log_return_30m', 'log_return_60m', 'realized_vol_60m', 'atr_14', 'volume_zscore_20', 'log_dollar_volume', 'close_position', 'rsi_14', 'hour_sin', 'hour_cos']
const GEX = ['dist_call_wall_atr', 'dist_put_wall_atr', 'dist_zero_gamma_atr', 'above_zero_gamma', 'gamma_regime_strength', 'net_gex', 'abs_gex_total', 'gex_concentration', 'gex_age_minutes', 'call_wall_strength', 'put_wall_strength']
const EXTRA = ['close_vs_sma20', 'minutes_since_open']

const r6 = (x) => (x === null || !Number.isFinite(x) ? null : Math.round(x * 1e6) / 1e6)
const iso = (t) => new Date(t * 1000).toISOString().replace('.000Z', '+00:00')

function rolling(values, n, fn) {
  return values.map((_, i) => (i + 1 < n ? null : fn(values.slice(i + 1 - n, i + 1))))
}
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length
const std = (a) => {
  const m = mean(a)
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1))
}

function pearson(x, y) {
  const mx = mean(x)
  const my = mean(y)
  let sxy = 0
  let sxx = 0
  let syy = 0
  for (let i = 0; i < x.length; i++) {
    sxy += (x[i] - mx) * (y[i] - my)
    sxx += (x[i] - mx) ** 2
    syy += (y[i] - my) ** 2
  }
  return sxx && syy ? sxy / Math.sqrt(sxx * syy) : 0
}
const ranks = (a) => {
  const order = a.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0])
  const out = new Array(a.length)
  order.forEach(([, i], r) => { out[i] = r })
  return out
}

function scorePredictions(pred, target, idx) {
  const p = idx.map((i) => pred[i])
  const t = idx.map((i) => target[i])
  const pnl = p.map((v, k) => Math.sign(v) * t[k])
  const sd = std(pnl)
  return {
    ic_pearson: r6(pearson(p, t)),
    ic_spearman: r6(pearson(ranks(p), ranks(t))),
    directional_acc: r6(p.filter((v, k) => Math.sign(v) === Math.sign(t[k])).length / p.length),
    strategy_sharpe_ann: r6(sd ? (mean(pnl) / sd) * Math.sqrt((252 * 78) / HORIZON_BARS) : 0),
    n_obs: p.length,
  }
}

/** Dataset for `symbol` covering trading days `from`..`to` (day numbers), 5m RTH bars. */
export function researchDataset(symbol, from, to) {
  const spec = symbolSpec(symbol)
  const end = (to + 1) * 86400 + 6 * 3600 // well after the last session closes
  const bars = tradingDays(spec, from, to).flatMap((d) => intradayBars({ ...spec, session: 'rth' }, d, '5m', end))
  const n = bars.length
  const time = bars.map((b) => b.t)
  const open = bars.map((b) => b.o)
  const high = bars.map((b) => b.h)
  const low = bars.map((b) => b.l)
  const close = bars.map((b) => b.c)
  const volume = bars.map((b) => b.v)
  const logc = close.map(Math.log)
  const ret = (k) => logc.map((v, i) => (i >= k ? v - logc[i - k] : null))
  const f = {}
  f.log_return_5m = ret(1)
  f.log_return_15m = ret(3)
  f.log_return_30m = ret(6)
  f.log_return_60m = ret(12)
  f.realized_vol_60m = f.log_return_5m.map((_, i) => (i >= 12 ? std(f.log_return_5m.slice(i - 11, i + 1)) : null))
  const tr = bars.map((b, i) => (i ? Math.max(b.h - b.l, Math.abs(b.h - close[i - 1]), Math.abs(b.l - close[i - 1])) : b.h - b.l))
  f.atr_14 = rolling(tr, 14, mean)
  f.volume_zscore_20 = rolling(volume, 20, (w) => (std(w) ? (w[w.length - 1] - mean(w)) / std(w) : 0))
  f.log_dollar_volume = bars.map((b) => Math.log1p(b.c * b.v))
  f.close_position = bars.map((b) => (b.h > b.l ? (b.c - b.l) / (b.h - b.l) : 0.5))
  f.close_vs_sma20 = rolling(close, 20, (w) => w[w.length - 1] / mean(w) - 1)
  const diff = close.map((c, i) => (i ? c - close[i - 1] : 0))
  f.rsi_14 = rolling(diff, 14, (w) => {
    const gain = mean(w.map((x) => Math.max(x, 0)))
    const loss = mean(w.map((x) => Math.max(-x, 0)))
    return loss ? 100 - 100 / (1 + gain / loss) : 100
  })
  f.minutes_since_open = time.map((t) => etMinuteOfDay(t) - 570)
  f.hour_sin = time.map((t) => Math.sin((2 * Math.PI * (Math.floor(t / 60) % 1440)) / 1440))
  f.hour_cos = time.map((t) => Math.cos((2 * Math.PI * (Math.floor(t / 60) % 1440)) / 1440))
  for (const k of GEX) f[k] = new Array(n).fill(null)
  for (let i = 0; i < n; i++) {
    // Snapshot from five minutes before the bar opens, as the 5-min scheduler would have it.
    const ladder = gexLadder(symbol, time[i] - 300)
    const atr = f.atr_14[i]
    if (!ladder.strikes.length) continue
    const lv = Object.fromEntries(keyLevels(ladder.strikes, ladder.spot).map((l) => [l.label, l]))
    let net = 0
    let abs = 0
    let sq = 0
    for (const s of ladder.strikes) {
      net += s.gex
      abs += Math.abs(s.gex)
      sq += s.gex * s.gex
    }
    f.net_gex[i] = net
    f.abs_gex_total[i] = abs
    f.gex_concentration[i] = abs ? sq / (abs * abs) : null
    f.gamma_regime_strength[i] = net / (abs + 1e-8)
    f.gex_age_minutes[i] = 5
    f.call_wall_strength[i] = lv.call_wall && abs ? Math.abs(lv.call_wall.gex) / abs : null
    f.put_wall_strength[i] = lv.put_wall && abs ? Math.abs(lv.put_wall.gex) / abs : null
    if (lv.zero_gamma) f.above_zero_gamma[i] = Math.sign(close[i] - lv.zero_gamma.strike)
    if (atr) {
      if (lv.call_wall) f.dist_call_wall_atr[i] = (close[i] - lv.call_wall.strike) / atr
      if (lv.put_wall) f.dist_put_wall_atr[i] = (close[i] - lv.put_wall.strike) / atr
      if (lv.zero_gamma) f.dist_zero_gamma_atr[i] = (close[i] - lv.zero_gamma.strike) / atr
    }
  }
  const features = {}
  for (const k of [...BASELINE, ...GEX, ...EXTRA]) features[k] = f[k].map(r6)

  // No-skill "model": walk-forward layout like the real export, random predictions.
  const target = close.map((c, i) => (i + HORIZON_BARS < n && etDay(time[i + HORIZON_BARS]) === etDay(time[i]) ? Math.log(close[i + HORIZON_BARS] / c) : null))
  const oosStart = Math.floor(n / 2)
  const foldSize = Math.floor((n - oosStart) / 5)
  const r = rng(hash(`ml:${spec.symbol}:${from}:${to}`))
  const tsd = std(target.filter((x) => x !== null))
  const pred = new Array(n).fill(null)
  const fold = new Array(n).fill(null)
  const folds = []
  for (let k = 0; k < 5; k++) {
    const testStart = oosStart + k * foldSize
    const testEnd = k === 4 ? n - 1 : testStart + foldSize - 1
    const idx = []
    for (let i = testStart; i <= testEnd; i++) {
      fold[i] = k + 1
      if (target[i] !== null) {
        pred[i] = 0.3 * tsd * gaussian(r)
        idx.push(i)
      }
    }
    const s = scorePredictions(pred, target, idx)
    folds.push({ fold: k + 1, trainStart: 0, trainEnd: testStart - 1, testStart, testEnd, nTrain: testStart, nTest: testEnd - testStart + 1, isSharpe: null, oosSharpe: s.strategy_sharpe_ann, isIc: null, oosIc: s.ic_pearson, oosDirAcc: s.directional_acc })
  }
  const scored = pred.map((p, i) => i).filter((i) => pred[i] !== null)
  return {
    symbol: spec.symbol,
    interval: '5m',
    horizonBars: HORIZON_BARS,
    horizonMinutes: HORIZON_BARS * 5,
    generatedAt: `${dayString(to + 1)}T00:00:00+00:00`,
    source: `synthetic v${GENERATOR_VERSION} (frontend/lib/synthetic): seeded random walk, not market data`,
    synthetic: true,
    bars: n,
    start: iso(time[0]),
    end: iso(time[n - 1]),
    time,
    open,
    high,
    low,
    close,
    volume,
    features,
    featureGroups: { baseline: BASELINE, gex: GEX },
    ml: {
      model: 'none: seeded random predictions with no skill (synthetic)',
      target: `forward log return, ${HORIZON_BARS * 5}m`,
      pred: pred.map(r6),
      target_return: target.map(r6),
      fold,
      folds,
      overall: scorePredictions(pred, target, scored),
      oosStart,
    },
  }
}

/** Counts publish_backtest_data.validate() would report. */
export function datasetQuality(ds) {
  let missing = 0
  for (const col of Object.values(ds.features)) for (const v of col) if (v === null) missing++
  let gaps = 0
  for (let i = 1; i < ds.time.length; i++) if (ds.time[i] - ds.time[i - 1] > 300) gaps++
  return { missingFeatureValues: missing, gapsOver5Minutes: gaps, predictionValidation: 'synthetic-random', completedBarsOnly: true }
}
