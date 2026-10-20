'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned } from '../../../lib/backtest/format'
import { Region, NoResult } from './ui'

const tone = (v) => (v > 0 ? 'v3-pos' : v < 0 ? 'v3-neg' : '')

/**
 * The full metric list as one ruled table (components/backtest/MetricsPanel
 * as numbers that don't animate), with the sweep-vs-median note kept.
 */
export default function Metrics() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep.data)
  const runCount = useBacktest((s) => s.runCount)
  const setTab = useBacktest((s) => s.setTab)

  const isOos = strategyId === 'mlSignal' && dataset?.ml

  if (!result) {
    return (
      <Region title="Metrics" className="v3-fill" scroll>
        <NoResult what="Metrics" />
      </Region>
    )
  }

  const m = result.metrics
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : null
  const pr = result.prop ? result.prop.bootstrap || result.prop.historical : null

  const rows = [
    ['Sharpe', fmtSigned(m.sharpe), tone(m.sharpe), 'Annualised, from per-bar returns'],
    ['Sortino', fmtSigned(m.sortino), tone(m.sortino)],
    ['Profit factor', Number.isFinite(m.profitFactor) ? m.profitFactor.toFixed(2) : '—', m.profitFactor >= 1 ? 'v3-pos' : 'v3-neg'],
    ['Total return', fmtPct(m.totalReturn), tone(m.totalReturn)],
    ['Buy & hold', bhReturn === null ? '—' : fmtPct(bhReturn), 'v3-dim'],
    ['CAGR', fmtPct(m.cagr), tone(m.cagr)],
    ['Final equity', fmtMoney(m.finalEquity)],
    ['Max drawdown', m.maxDd > 0 ? `−${(m.maxDd * 100).toFixed(1)}%` : '0.0%', 'v3-neg'],
    ['Drawdown length', `${m.maxDdDuration} bars`, '', 'Longest underwater stretch'],
    ['Ann. volatility', fmtPctAbs(m.volAnn)],
    ['Calmar', fmtRatio(m.calmar)],
    ['Hit rate', fmtPctAbs(m.hitRate)],
    ['Trades', m.nTrades.toLocaleString()],
    ['Expectancy / trade', fmtMoney(m.expectancy, 2), tone(m.expectancy)],
    ['Avg win / loss', `${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`],
    ['Exposure', fmtPctAbs(m.exposure), '', 'Share of bars holding a position'],
    ['Turnover / yr', m.turnover.toFixed(0)],
    ['Avg bars held', m.avgBarsHeld.toFixed(1)],
  ]

  return (
    <Region
      title="Metrics"
      className="v3-fill"
      scroll
      aside={
        result.prop ? (
          <span className="v3-tag">Prop · {result.prop.plan.planLabel} {result.prop.plan.sizeLabel}</span>
        ) : isOos ? (
          <span className="v3-tag v3-tag-pos">Out-of-sample</span>
        ) : (
          <span className="v3-tag">In-sample</span>
        )
      }
    >
      {pr && (
        <button type="button" onClick={() => setTab('prop')} className="v3-prop-ev" title="Open the prop tab">
          <span>EV per account purchase</span>
          <span className={tone(pr.ev)}>{fmtMoneySigned(pr.ev)}</span>
          <span className="v3-dim">pass rate {fmtPctAbs(pr.passRate)}</span>
        </button>
      )}
      <table className="v3-metrics">
        <tbody>
          {rows.map(([label, value, cls, title]) => (
            <tr key={label} title={title}>
              <th scope="row">{label}</th>
              <td className={cls}>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="v3-honesty">
        <h3>Reading these numbers</h3>
        {sweep ? (
          <p>
            Sweep best Sharpe <b className={tone(sweep.best?.sharpe)}>{fmtSigned(sweep.best?.sharpe)}</b>, median{' '}
            <b className={tone(sweep.median)}>{fmtSigned(sweep.median)}</b> over {sweep.trials} combinations. The median is
            the honest estimate; the best cell is the maximum of {sweep.trials} draws.
          </p>
        ) : (
          <p>Run a sweep (S) to see how much of this number is parameter luck.</p>
        )}
        <p>
          {runCount.toLocaleString()} simulation{runCount === 1 ? '' : 's'} this session.
          {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
        </p>
        {isOos && <p className="v3-pos">Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</p>}
      </div>
    </Region>
  )
}
