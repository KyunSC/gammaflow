/**
 * Coin-flip twins: the question a prop result cannot answer on its own.
 *
 * A prop account can pay a strategy with no edge at all. On MyFundedPerps
 * Elite a fair coin with few, large trades is worth a few hundred dollars per
 * evaluation before costs, so "EV > 0" says nothing about the entries. Each
 * twin replays the strategy with the same entry and exit timing, the same
 * size, stop, target and session rules, and only the direction drawn by a
 * seeded coin. The strategy beats a coin flip when it beats the twins.
 *
 * The coin's P(long) defaults to the strategy's own long share, so a
 * long-leaning rule cannot win on a market's drift alone (BTC rose more than
 * tenfold 2020–2026). `pLong: 0.5` gives the fair coin.
 *
 * p = (1 + #twins ≥ strategy) / (1 + n), on mean net trade P&L and on EV per
 * purchase. Both use the same bootstrap seed, so twins and strategy are
 * scored on the same resampled day sequences.
 */

import { runBacktest } from '../engine'
import { mulberry32 } from '../metrics'
import { runProp } from './stats'

/** Wraps a strategy: same timing, direction from the coin at every new entry. */
export function twinStrategy(strategy, { seed, pLong = 0.5 }) {
  const rng = mulberry32(seed)
  let prevRaw = 0
  let dir = 0
  return {
    ...strategy,
    id: `${strategy.id}~coin`,
    signal(i, state, ds, params, enginePrev) {
      // The wrapped strategy sees its own previous target, not the twin's, so
      // hysteresis rules keep their timing. The engine zeroes its previous
      // target after a stop, target or session exit; so does this.
      const prev = enginePrev === 0 ? 0 : prevRaw
      let raw = strategy.signal(i, state, ds, params, prev)
      if (!Number.isFinite(raw)) raw = prev
      raw = Math.max(-1, Math.min(1, Math.round(raw)))
      if (raw === 0) dir = 0
      else if (Math.sign(raw) !== Math.sign(prev)) dir = rng() < pLong ? 1 : -1
      prevRaw = raw
      return raw === 0 ? 0 : dir
    },
  }
}

const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : Number.NaN)

/**
 * `plan` is the resolved prop plan; `costs` / `risk` are the prop setup's.
 * Shorts are always allowed for twins: a long-only engine would turn every
 * short draw into "no trade", which is a different control.
 */
export function coinFlipTwins({ dataset, strategy, params, costs, risk, window, plan, n = 100, seed = 7, pLong = null, paths = 200, blockSize = 5, horizon = 250 }) {
  const replay = (result) =>
    runProp({ result, time: dataset.time, plan, initialCapital: costs.initialCapital, historical: false, paths, blockSize, horizon, seed: 42, keepAttempts: false })
  const base = runBacktest({ dataset, strategy, params, costs, risk, window })
  const trades = base.trades
  const longShare = trades.length ? trades.filter((t) => t.side === 'long').length / trades.length : 0.5
  const pl = pLong === null ? longShare : pLong
  const self = { trades: trades.length, meanTradePnl: mean(trades.map((t) => t.pnl)), ev: replay(base).bootstrap?.ev ?? Number.NaN }

  const twinRisk = { ...risk, allowShort: true }
  const meanTradePnl = []
  const ev = []
  for (let k = 0; k < n; k++) {
    const r = runBacktest({ dataset, strategy: twinStrategy(strategy, { seed: seed * 1000003 + k, pLong: pl }), params, costs, risk: twinRisk, window })
    meanTradePnl.push(r.trades.length ? mean(r.trades.map((t) => t.pnl)) : 0)
    ev.push(replay(r).bootstrap?.ev ?? Number.NaN)
  }
  const pOf = (x, list) => (1 + list.filter((v) => v >= x).length) / (1 + list.length)
  const sorted = (a) => [...a].sort((x, y) => x - y)
  return {
    n,
    pLong: pl,
    longShare,
    strategy: self,
    twins: {
      meanTradePnl: sorted(meanTradePnl),
      ev: sorted(ev),
      meanEv: mean(ev),
    },
    pMeanTrade: pOf(self.meanTradePnl, meanTradePnl),
    pEv: pOf(self.ev, ev),
    // The edge over what the account would have paid a coin.
    evOverTwins: self.ev - mean(ev),
  }
}
