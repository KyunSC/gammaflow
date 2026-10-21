'use client'

import { useRef } from 'react'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy } from '../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtSigned, fmtMoneySigned, fmtDateRange, signClass } from '../../lib/backtest/format'
import { holesFor, holeExposure } from './gaps'

/**
 * The record at the top of the results: one sentence naming what ran, the
 * handful of numbers that answer "did it make money, and versus what", and a
 * line of caveats that is never hidden — in-sample or not, how many runs this
 * session, the costs, the data source and its holes.
 *
 * Replaces the original KPI strip's count-up animation with the previous
 * run's value printed under each number: the direction a nudge moved things,
 * without hiding the current value while it animates.
 */
export default function Record() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const runCount = useBacktest((s) => s.runCount)
  const running = useBacktest((s) => s.running)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const costs = useBacktest((s) => s.costs)

  // Last two non-null results. Params changes clear `result` before the next
  // run lands, so nulls are skipped rather than treated as "no previous".
  const hist = useRef({ cur: null, prev: null })
  if (result && result !== hist.current.cur) hist.current = { prev: hist.current.cur, cur: result }
  const prev = result ? hist.current.prev : null

  const strategy = getStrategy(result?.config?.strategyId || strategyId)
  const m = result?.metrics
  const bhRet = result ? result.buyHold[result.windowEnd] / result.buyHold[result.windowStart] - 1 : NaN
  const pm = prev?.metrics
  const prevBh = prev ? prev.buyHold[prev.windowEnd] / prev.buyHold[prev.windowStart] - 1 : NaN

  const holes = holesFor(dataset)
  const exposure = result ? holeExposure(holes, result.trades) : null
  const ci = m?.inference?.ci
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const window = result && dataset ? fmtDateRange(dataset.time[result.windowStart] * 1000, dataset.time[result.windowEnd] * 1000) : null

  const tally = runCount > 300 ? 'text-neg' : runCount > 80 ? 'text-amber' : 'text-muted'

  return (
    <section aria-label="Result" className="px-3 pt-3 pb-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="v05-title">
          {strategy.label}
          <span className="font-normal text-muted">
            {dataset ? ` on ${dataset.symbol} ${dataset.interval}` : ''}
            {window ? `, ${window} ET` : ''}
          </span>
        </h2>
        <span className="v05-tag" title={isOos ? 'Positions only on walk-forward out-of-sample bars' : 'Parameters were chosen on the same bars they are scored on'}>
          {result?.prop ? (
            <span className="text-amber">prop account · {result.prop.plan.planLabel} {result.prop.plan.sizeLabel}</span>
          ) : isOos ? (
            <span className="text-pos">out-of-sample</span>
          ) : (
            <span className="text-dim">in-sample</span>
          )}
        </span>
      </div>

      {!m ? (
        <p className="mt-3 mb-1 font-mono text-[12px] text-dim" role="status">
          {datasetLoading ? 'Loading bars…' : running ? 'Running…' : 'No result yet. Press R or Run backtest.'}
        </p>
      ) : (
        <dl className="v05-figs mt-2.5">
          <Fig label="Return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} prev={pm && fmtPct(pm.totalReturn)} />
          <Fig label={`Buy & hold ${dataset?.symbol ?? ''}`} value={fmtPct(bhRet)} tone="text-muted" prev={prev && fmtPct(prevBh)} title="Holding the same symbol over the same window, same capital, no costs" />
          <Fig
            label="Difference"
            value={`${fmtSigned((m.totalReturn - bhRet) * 100)} pp`}
            tone={signClass(m.totalReturn - bhRet)}
            prev={pm && `${fmtSigned((pm.totalReturn - prevBh) * 100)} pp`}
            title="Strategy return minus buy & hold, in percentage points"
          />
          <Fig
            label="Sharpe"
            value={fmtSigned(m.sharpe)}
            tone={signClass(m.sharpe)}
            prev={pm && fmtSigned(pm.sharpe)}
            sub={ci && Number.isFinite(ci[0]) ? `95% CI ${fmtSigned(ci[0], 1)} to ${fmtSigned(ci[1], 1)}` : null}
            title="Annualised from per-bar returns. The interval is the engine's standard-error band, adjusted for skew and kurtosis"
          />
          <Fig label="Max drawdown" value={`−${fmtPctAbs(m.maxDd)}`} tone="text-neg" prev={pm && `−${fmtPctAbs(pm.maxDd)}`} sub={`${m.maxDdDuration.toLocaleString()} bars underwater`} />
          <Fig label="Trades" value={m.nTrades.toLocaleString()} prev={pm && pm.nTrades.toLocaleString()} sub={`${fmtPctAbs(m.hitRate)} won`} />
        </dl>
      )}

      <p className="v05-caveats mt-2.5">
        <button onClick={() => toggleShortcuts(true)} className={`${tally} underline decoration-hair-bright underline-offset-2 hover:text-ink`} title="Every run, sweep cell and walk-forward trial counts. The more you try on one dataset, the more a good Sharpe is the best of many draws.">
          {runCount.toLocaleString()} {runCount === 1 ? 'run' : 'runs'} this session
        </button>
        <span>{costLine(result, costs)}</span>
        {dataset?.example && <span className="text-violet">bundled sample, not the live dataset</span>}
        {dataset?.cached && <span>offline cache (≤24h old)</span>}
      </p>
      {dataset && (
        <p className="v05-caveats">
          <HoleNote holes={holes} exposure={exposure} />
        </p>
      )}
    </section>
  )
}

function Fig({ label, value, tone = 'text-ink', prev, sub, title }) {
  const changed = prev && prev !== value
  return (
    <div className="min-w-0" title={title}>
      <dt className="v05-fig-label">{label}</dt>
      <dd className={`v05-fig ${tone}`}>{value}</dd>
      <dd className="v05-fig-sub">
        {sub}
        {sub && changed ? ' · ' : ''}
        {changed ? `was ${prev}` : !sub ? ' ' : ''}
      </dd>
    </div>
  )
}

function costLine(result, costs) {
  const c = result?.config?.costs || costs
  const inst = c.instrument
  if (inst) {
    return `costs: ${inst.contracts} × ${inst.contract}, $${inst.commissionPerSide}/side, ${inst.slippageTicks} tick slippage per fill`
  }
  return `costs: ${c.slippageBps} bp slippage + $${c.commissionPerTrade} per fill`
}

function HoleNote({ holes, exposure }) {
  if (!holes.checked) return <span className="text-dim">daily bars: missing sessions not checked</span>
  if (!holes.holes.length) return <span>no missing bars inside sessions</span>
  return (
    <span className="text-amber" title="Consecutive bars in the same session spaced more than one interval apart. The charts space bars evenly, so these holes are marked under the price and equity charts.">
      {holes.sessions} sessions with missing bars ({holes.missingBars.toLocaleString()} bars)
      {exposure && exposure.n > 0 && (
        <>
          {'; '}
          {exposure.n} of {exposure.total} trades were open across one: {fmtMoneySigned(exposure.pnl)} of {fmtMoneySigned(exposure.net)} net,{' '}
          {fmtPctAbs(exposure.grossShare, 0)} of gross P&amp;L
        </>
      )}
    </span>
  )
}
