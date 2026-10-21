'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtSigned, signClass } from '../../../lib/backtest/format'
import { NoRunYet } from '../../../components/backtest/Panel'
import Section from './Section'

function Row({ label, value, tone, title }) {
  return (
    <div className="v6-row" title={title}>
      <dt>{label}</dt>
      <dd className={`num ${tone || ''}`}>{value}</dd>
    </div>
  )
}

/** Advanced view's full metric list. The headline six are in the verdict
 *  above, and the honesty notes are in Caveats, so this is just the table. */
export default function Metrics() {
  const result = useBacktest((s) => s.result)
  const strategyId = useBacktest((s) => s.strategyId)
  const dataset = useBacktest((s) => s.dataset)

  if (!result) {
    return (
      <Section title="All metrics" scroll={false}>
        <div className="h-24"><NoRunYet what="Metrics" /></div>
      </Section>
    )
  }
  const m = result.metrics
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : null
  const isOos = strategyId === 'mlSignal' && dataset?.ml

  return (
    <Section title="All metrics" meta={result.prop ? `prop · ${result.prop.plan.planLabel} ${result.prop.plan.sizeLabel}` : isOos ? 'out-of-sample' : 'in-sample'} scroll={false}>
      <dl className="v6-rows">
        <Row label="Total return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} />
        <Row label="Buy & hold" value={bhReturn === null ? '—' : fmtPct(bhReturn)} />
        <Row label="CAGR" value={fmtPct(m.cagr)} tone={signClass(m.cagr)} title="Annualised from a short window; treat as a rate, not a forecast" />
        <Row label="Final equity" value={fmtMoney(m.finalEquity)} />
        <Row label="Sortino" value={fmtSigned(m.sortino)} tone={signClass(m.sortino)} />
        <Row label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} />
        <Row label="Ann. volatility" value={fmtPctAbs(m.volAnn)} />
        <Row label="Calmar" value={fmtRatio(m.calmar)} />
        <Row label="Expectancy / trade" value={fmtMoney(m.expectancy, 2)} tone={signClass(m.expectancy)} />
        <Row label="Avg win / loss" value={`${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
        <Row label="Exposure" value={fmtPctAbs(m.exposure)} title="Share of bars holding a position" />
        <Row label="Turnover / yr" value={m.turnover.toFixed(0)} />
        <Row label="Avg bars held" value={m.avgBarsHeld.toFixed(1)} />
        <Row label="Drawdown duration" value={`${m.maxDdDuration} bars`} />
      </dl>
    </Section>
  )
}
