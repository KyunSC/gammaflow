'use client'

import { useMemo } from 'react'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy } from '../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtRatio, fmtMoneySigned, signClass } from '../../lib/backtest/format'
import { findGaps, sessionsInWindow, tradeExposure } from './gaps'

/**
 * The result, said once in a sentence with its caveats attached, then the
 * numbers. Everything in the sentence is computed from the run: the costs it
 * was charged, buy & hold over the same window, whether any of it is out of
 * sample, how many runs this session has burned, and how much of the P&L came
 * from trades held across missing bars.
 */
export default function Claim({ onShowGaps }) {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const strategyId = useBacktest((s) => s.strategyId)
  const costs = useBacktest((s) => s.costs)
  const prop = useBacktest((s) => s.prop)
  const runCount = useBacktest((s) => s.runCount)
  const researchSymbol = useBacktest((s) => s.researchSymbol)
  const liveSymbol = useBacktest((s) => s.liveSymbol)
  const plane = useBacktest((s) => s.plane)

  const gaps = useMemo(() => findGaps(dataset), [dataset])
  const label = getStrategy(strategyId).label
  const symbol = dataset?.symbol ?? (plane === 'live' ? liveSymbol : researchSymbol)

  let body
  if (!result) {
    const msg = datasetError
      ? 'No data loaded, so nothing has run. The message above says why.'
      : datasetLoading
        ? `Loading ${symbol} bars…`
        : running
          ? `Running ${label} on ${symbol}…`
          : autoRun
            ? `${label} will run as soon as the data is ready.`
            : `Press Run backtest (R) to test ${label} on ${symbol}.`
    body = <p className="text-[15px] leading-snug text-muted" role="status">{msg}</p>
  } else {
    body = <Sentence result={result} dataset={dataset} gaps={gaps} label={label} costs={costs} prop={prop} runCount={runCount} strategyId={strategyId} onShowGaps={onShowGaps} />
  }

  const m = result?.metrics
  return (
    <section className="px-4 pt-3 pb-3" aria-label="Result" aria-busy={running || datasetLoading}>
      <div className="min-h-[64px]">{body}</div>
      <dl className="mt-2.5 flex flex-wrap gap-x-7 gap-y-2">
        <Kpi label="Sharpe" title="Annualised, from per-bar returns" value={m ? fmtRatio(m.sharpe) : '—'} tone={m && signClass(m.sharpe)} />
        <Kpi label="Sortino" value={m ? fmtRatio(m.sortino) : '—'} tone={m && signClass(m.sortino)} />
        <Kpi label="Max drawdown" value={m ? `−${(m.maxDd * 100).toFixed(1)}%` : '—'} tone={m && m.maxDd > 0 ? 'text-neg' : undefined} title={m ? `Longest underwater stretch: ${m.maxDdDuration} bars` : undefined} />
        <Kpi label="Win rate" value={m ? fmtPctAbs(m.hitRate) : '—'} />
        <Kpi label="Profit factor" value={m ? fmtRatio(m.profitFactor) : '—'} tone={m && (m.profitFactor >= 1 ? 'text-pos' : 'text-neg')} />
        <Kpi label="Trades" value={m ? m.nTrades.toLocaleString() : '—'} />
        <Kpi label="Time in market" value={m ? fmtPctAbs(m.exposure) : '—'} title="Share of bars holding a position" />
      </dl>
    </section>
  )
}

function Kpi({ label, value, tone, title }) {
  return (
    <div title={title}>
      <dt className="text-[11.5px] text-dim">{label}</dt>
      <dd className={`v9-num text-[19px] leading-tight ${tone || 'text-ink'}`}>{value}</dd>
    </div>
  )
}

const Num = ({ children, tone }) => <span className={`v9-num font-medium ${tone || 'text-ink'}`}>{children}</span>

function Sentence({ result, dataset, gaps, label, costs, prop, runCount, strategyId, onShowGaps }) {
  const m = result.metrics
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const diff = (m.totalReturn - bhReturn) * 100
  const sessions = sessionsInWindow(gaps, result.windowStart, result.windowEnd)
  const exposure = tradeExposure(gaps, result.trades)
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const inst = result.config?.costs?.instrument

  const costPhrase = result.prop
    ? `${inst ? `${inst.contracts} × ${inst.contract}, ` : ''}${prop.slippageTicks} tick${prop.slippageTicks === 1 ? '' : 's'} slippage and $${Number(prop.commissionPerSide).toFixed(2)}/side commission`
    : `${costs.slippageBps} bp slippage and $${Number(costs.commissionPerTrade).toFixed(2)} commission per trade`

  const caveats = []
  if (result.prop) caveats.push(<span key="p" className="text-amber">Prop account: {result.prop.plan.planLabel} {result.prop.plan.sizeLabel}, in-sample</span>)
  else if (isOos) caveats.push(<span key="o" className="text-pos">Out-of-sample: the model only trades its walk-forward test bars</span>)
  else caveats.push(<span key="i">In-sample: no held-out data in this run</span>)
  if (dataset?.example) caveats.push(<span key="s" className="text-violet">Bundled sample data</span>)
  if (dataset?.plane === 'live') caveats.push(<span key="l" className="text-cyan">Live prices, exploratory snapshot</span>)
  caveats.push(
    runCount > 80 ? (
      <span key="r" className={runCount > 300 ? 'text-neg' : 'text-amber'}>
        {runCount.toLocaleString()} runs this session: treat a good Sharpe as a hypothesis to test elsewhere
      </span>
    ) : (
      <span key="r">Run {runCount.toLocaleString()} this session</span>
    ),
  )

  let gapLine = null
  if (gaps && !gaps.supported) {
    gapLine = <span>Missing-bar check not run on {dataset?.interval} bars</span>
  } else if (gaps && gaps.gapDays === 0) {
    gapLine = <span>No missing bars inside sessions</span>
  } else if (gaps && exposure) {
    gapLine = (
      <span className="text-amber">
        {gaps.gapDays} of {gaps.sessionCount} sessions have missing bars ({gaps.missingBars.toLocaleString()} bars).{' '}
        {exposure.affected > 0 ? (
          <>
            {exposure.affected} of {exposure.trades} trades were held across a hole and made{' '}
            <span className="v9-num">{fmtMoneySigned(exposure.affectedPnl)}</span> of the{' '}
            <span className="v9-num">{fmtMoneySigned(exposure.totalPnl)}</span> net.
          </>
        ) : (
          'No trade was held across one.'
        )}{' '}
        {onShowGaps && (
          <button onClick={onShowGaps} className="v9-link">Show the gaps</button>
        )}
      </span>
    )
  }

  return (
    <>
      <p className="max-w-[92ch] text-[15px] leading-snug text-muted">
        <span className="font-semibold text-ink">{label}</span> on {dataset.symbol} {dataset.interval}{' '}
        {m.totalReturn >= 0 ? 'returned' : 'lost'} <Num tone={signClass(m.totalReturn)}>{fmtPct(m.totalReturn)}</Num> after {costPhrase}.
        {Number.isFinite(bhReturn) && (
          <>
            {' '}Holding {dataset.symbol} over the same {sessions ? `${sessions} sessions` : 'window'} returned{' '}
            <Num tone="text-cyan">{fmtPct(bhReturn)}</Num>, so the strategy finished{' '}
            <Num tone={signClass(diff)}>{Math.abs(diff).toFixed(2)} pts</Num> {diff >= 0 ? 'ahead' : 'behind'}.
          </>
        )}
      </p>
      <p className="mt-1.5 flex max-w-[110ch] flex-wrap gap-x-1.5 gap-y-0.5 text-[12px] leading-snug text-dim">
        {caveats.map((c, i) => (
          <span key={i}>
            {c}
            <span aria-hidden="true" className="text-hair-bright"> ·</span>
          </span>
        ))}
        {gapLine}
      </p>
    </>
  )
}
