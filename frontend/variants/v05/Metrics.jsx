'use client'

import { useBacktest } from '../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../lib/backtest/format'
import { NoRunYet } from '../../components/backtest/Panel'
import Block from './Block'

/**
 * Variant 05 version of components/backtest/MetricsPanel.jsx. The headline
 * numbers moved to the record above the charts, so this column holds the
 * rest of the statistics as one aligned list, followed by the trust notes the
 * original kept in its "honesty" box, with the same wording and conditions.
 */
export default function Metrics() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep.data)
  const runCount = useBacktest((s) => s.runCount)
  const setTab = useBacktest((s) => s.setTab)

  if (!result) {
    return (
      <Block title="Statistics" className="h-full">
        <NoRunYet what="Metrics" />
      </Block>
    )
  }

  const m = result.metrics
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const ps = result.prop ? result.prop.bootstrap || result.prop.historical : null

  return (
    <Block title="Statistics" meta={isOos ? 'out-of-sample' : 'in-sample'} className="h-full" bodyClassName="overflow-auto">
      {ps && (
        <button onClick={() => setTab('prop')} className="v05-rule-b flex w-full items-baseline justify-between gap-2 px-3 pt-1 pb-2 text-left hover:bg-panel-2" title="Open the prop account tab">
          <span className="text-[12px] text-muted">EV per account purchase</span>
          <span className={`num text-[15px] ${signClass(ps.ev)}`}>
            {fmtMoneySigned(ps.ev)}
            <span className="ml-1.5 text-[11px] text-dim">pass {fmtPctAbs(ps.passRate)}</span>
          </span>
        </button>
      )}

      <dl className="py-1">
        <Row label="Sortino" value={fmtSigned(m.sortino)} tone={signClass(m.sortino)} />
        <Row label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} />
        <Row label="CAGR" value={fmtPct(m.cagr)} tone={signClass(m.cagr)} />
        <Row label="Final equity" value={fmtMoney(m.finalEquity)} />
        <Row label="Annualised vol" value={fmtPctAbs(m.volAnn)} />
        <Row label="Calmar" value={fmtRatio(m.calmar)} />
        <Row label="Expectancy per trade" value={fmtMoney(m.expectancy, 2)} tone={signClass(m.expectancy)} />
        <Row label="Avg win / avg loss" value={`${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
        <Row label="Exposure" value={fmtPctAbs(m.exposure)} title="Share of bars holding a position" />
        <Row label="Turnover per year" value={m.turnover.toFixed(0)} />
        <Row label="Avg bars held" value={m.avgBarsHeld.toFixed(1)} />
        <Row label="Longest drawdown" value={`${m.maxDdDuration} bars`} />
      </dl>

      <div className="v05-rule-t px-3 pt-2 pb-3">
        <h3 className="text-[12px] font-semibold text-ink">How much to trust this</h3>
        <div className="mt-1.5 flex flex-col gap-1.5 text-[11.5px] leading-snug text-muted">
          {sweep ? (
            <p>
              Sweep best Sharpe <span className={`num ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span> vs
              median <span className={`num ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over{' '}
              <span className="num">{sweep.trials}</span> combinations. The median is the honest estimate;
              the best cell is the maximum of {sweep.trials} draws.
            </p>
          ) : (
            <p>Run a sweep (S) to see how much of this number is parameter luck.</p>
          )}
          <p>
            <span className="num text-ink">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session.
            {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
          </p>
          {isOos && (
            <p className="text-pos/80">
              ML positions are taken only on walk-forward out-of-sample bars — the training stretches
              produce no trades.
            </p>
          )}
        </div>
      </div>
    </Block>
  )
}

function Row({ label, value, tone, title }) {
  return (
    <div className="flex items-baseline justify-between gap-2 px-3 py-[3px]" title={title}>
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className={`num text-[12px] ${tone || 'text-ink'}`}>{value}</dd>
    </div>
  )
}
