'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import { NoRunYet } from './Empty'

/**
 * Advanced view's full metric sheet. The headline figures already sit above
 * the charts, so this is the long table plus the notes that qualify it.
 * Copied from components/backtest/MetricsPanel.jsx without the count-up.
 */
export default function Metrics() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep.data)
  const runCount = useBacktest((s) => s.runCount)
  const setTab = useBacktest((s) => s.setTab)

  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const tag = result?.prop ? (
    <span className="text-amber">Prop · {result.prop.plan.planLabel} {result.prop.plan.sizeLabel}</span>
  ) : isOos ? (
    <span className="text-pos">Out-of-sample</span>
  ) : result ? (
    <span>In-sample</span>
  ) : null

  return (
    <section className="v4-region" aria-label="All metrics">
      <div className="v4-rh">
        <h2>All metrics</h2>
        <span className="v4-rh-right">{tag}</span>
      </div>
      <div className="v4-region-body overflow-auto">
        {!result ? (
          <NoRunYet what="Metrics" />
        ) : (
          <MetricBody result={result} sweep={sweep} runCount={runCount} isOos={isOos} setTab={setTab} />
        )}
      </div>
    </section>
  )
}

function MetricBody({ result, sweep, runCount, isOos, setTab }) {
  const m = result.metrics
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : null
  const inf = m.inference || {}
  const prop = result.prop && (result.prop.bootstrap || result.prop.historical)

  const rows = [
    ['Sharpe', fmtSigned(m.sharpe), signClass(m.sharpe)],
    ['Sharpe 95% CI', Number.isFinite(inf.ci?.[0]) ? `${fmtSigned(inf.ci[0])} to ${fmtSigned(inf.ci[1])}` : '—', '', 'Adjusted for skew and kurtosis of per-bar returns; not for the number of runs tried'],
    ['P(Sharpe > 0)', Number.isFinite(inf.psr) ? fmtPctAbs(inf.psr) : '—', '', 'Probabilistic Sharpe ratio for this one configuration. Ignores multiple testing.'],
    ['Sortino', fmtSigned(m.sortino), signClass(m.sortino)],
    ['Total return', fmtPct(m.totalReturn), signClass(m.totalReturn)],
    ['Buy & hold', bhReturn === null ? '—' : fmtPct(bhReturn), 'text-dim'],
    ['CAGR', fmtPct(m.cagr), signClass(m.cagr)],
    ['Final equity', fmtMoney(m.finalEquity)],
    ['Max drawdown', fmtPct(-m.maxDd, 1), 'text-neg'],
    ['Drawdown duration', `${m.maxDdDuration} bars`],
    ['Ann. volatility', fmtPctAbs(m.volAnn)],
    ['Calmar', fmtRatio(m.calmar)],
    ['Hit rate', fmtPctAbs(m.hitRate)],
    ['Profit factor', fmtRatio(m.profitFactor), m.profitFactor >= 1 ? 'text-pos' : 'text-neg'],
    ['Expectancy / trade', fmtMoney(m.expectancy, 2), signClass(m.expectancy)],
    ['Avg win / loss', `${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`],
    ['Trades', m.nTrades.toLocaleString()],
    ['Exposure', fmtPctAbs(m.exposure), '', 'Share of bars holding a position'],
    ['Turnover / yr', m.turnover.toFixed(0)],
    ['Avg bars held', m.avgBarsHeld.toFixed(1)],
  ]

  return (
    <>
      {prop && (
        <button onClick={() => setTab('prop')} className="flex w-full items-baseline justify-between gap-2 px-3 pb-2 text-left hover:text-ink" title="Open the prop tab">
          <span className="text-[12px] text-muted">EV per purchase</span>
          <span className={`v4-mono text-[14px] ${signClass(prop.ev)}`}>
            {fmtMoneySigned(prop.ev)} <span className="text-[11px] text-dim">pass {fmtPctAbs(prop.passRate)}</span>
          </span>
        </button>
      )}
      <dl className="v4-dl">
        {rows.map(([k, v, cls, title]) => (
          <div key={k} className="contents">
            <dt title={title}>{k}</dt>
            <dd className={cls || ''}>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="v4-honesty">
        {sweep ? (
          <p>
            Sweep best Sharpe <span className={`v4-mono ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span>, median{' '}
            <span className={`v4-mono ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over{' '}
            <span className="v4-mono">{sweep.trials}</span> combinations. The median is the honest estimate; the best cell is
            the maximum of {sweep.trials} draws.
          </p>
        ) : (
          <p>
            <button className="v4-textbtn" onClick={() => setTab('sweep')}>Run a sweep</button> to see how much of this number is
            parameter luck.
          </p>
        )}
        <p>
          <span className="v4-mono">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session.
          {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
        </p>
        {isOos && (
          <p className="text-pos">ML positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</p>
        )}
      </div>
    </>
  )
}
