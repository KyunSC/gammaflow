'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import Section, { NotYet } from './Section'
import { gapsFor, gapExposure } from './gaps'

function Row({ label, value, tone, title }) {
  return (
    <div className="l10-mrow" title={title}>
      <span>{label}</span>
      <span className={tone || ''}>{value}</span>
    </div>
  )
}

/** Every metric the engine reports, plus the notes that qualify them. */
export default function Metrics() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep.data)
  const runCount = useBacktest((s) => s.runCount)
  const setTab = useBacktest((s) => s.setTab)

  if (!result) {
    return (
      <Section title="All metrics">
        <NotYet what="Metrics" />
      </Section>
    )
  }

  const m = result.metrics
  const inf = m.inference || {}
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : null
  const gaps = gapsFor(dataset)
  const g = gaps.idx.length ? gapExposure(gaps, result.trades) : null

  return (
    <Section
      title="All metrics"
      meta={result.prop ? `Prop · ${result.prop.plan.planLabel} ${result.prop.plan.sizeLabel}` : isOos ? 'out-of-sample' : 'in-sample'}
    >
      <div className="py-1">
        <Row label="Sharpe" value={fmtSigned(m.sharpe)} tone={signClass(m.sharpe)} title="Annualised, from per-bar returns" />
        <Row label="Sharpe 95% CI" value={inf.ci && Number.isFinite(inf.ci[0]) ? `${fmtSigned(inf.ci[0])} to ${fmtSigned(inf.ci[1])}` : '—'}
          title="Mertens standard error with skew and kurtosis. Treats bars as independent, so it is optimistic." />
        <Row label="P(true Sharpe > 0)" value={Number.isFinite(inf.psr) ? fmtPctAbs(inf.psr) : '—'} title="Probabilistic Sharpe ratio for this one configuration. It does not account for how many configurations were tried." />
        <Row label="Sortino" value={fmtSigned(m.sortino)} tone={signClass(m.sortino)} />
        <Row label="Total return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} />
        <Row label="Buy & hold" value={bhReturn === null ? '—' : fmtPct(bhReturn)} tone="text-cyan" />
        <Row label="CAGR" value={fmtPct(m.cagr)} tone={signClass(m.cagr)} title="Annualised from a short window; extrapolates heavily" />
        <Row label="Final equity" value={fmtMoney(m.finalEquity)} />
        <Row label="Max drawdown" value={`−${fmtPctAbs(m.maxDd)}`} tone="text-neg" />
        <Row label="Drawdown duration" value={`${m.maxDdDuration.toLocaleString()} bars`} />
        <Row label="Ann. volatility" value={fmtPctAbs(m.volAnn)} />
        <Row label="Calmar" value={fmtRatio(m.calmar)} />
        <Row label="Hit rate" value={fmtPctAbs(m.hitRate)} />
        <Row label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} />
        <Row label="Expectancy / trade" value={fmtMoney(m.expectancy, 2)} tone={signClass(m.expectancy)} />
        <Row label="Avg win / loss" value={`${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
        <Row label="Trades" value={m.nTrades.toLocaleString()} />
        <Row label="Exposure" value={fmtPctAbs(m.exposure)} title="Share of bars holding a position" />
        <Row label="Turnover / yr" value={m.turnover.toFixed(0)} />
        <Row label="Avg bars held" value={m.avgBarsHeld.toFixed(1)} />
      </div>

      {result.prop && (
        <button type="button" onClick={() => setTab('prop')} className="l10-mrow w-full text-left hover:bg-panel-2" title="Open the prop tab">
          <span>EV per account bought</span>
          <span className={signClass((result.prop.bootstrap || result.prop.historical).ev)}>
            {fmtMoneySigned((result.prop.bootstrap || result.prop.historical).ev)} · pass {fmtPctAbs((result.prop.bootstrap || result.prop.historical).passRate)}
          </span>
        </button>
      )}

      <div className="l10-note">
        <h3>How much to trust this</h3>
        {sweep ? (
          <p>
            Sweep best Sharpe <span className={`l10-num ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span>, median{' '}
            <span className={`l10-num ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over <span className="l10-num">{sweep.trials}</span> combinations.
            The median is the honest estimate; the best cell is the maximum of {sweep.trials} draws.
          </p>
        ) : (
          <p>Run a sweep (S) to see how much of this number is parameter luck.</p>
        )}
        <p>
          <span className="l10-num">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session.
          {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
        </p>
        {g && g.n > 0 && (
          <p className="text-amber">
            {g.n} trade{g.n === 1 ? '' : 's'} held across missing bars ({fmtPctAbs(g.absShare, 0)} of absolute P&amp;L). Their fills are real
            prices, but the path between them was never seen bar by bar, so stops and targets inside a hole were not checked.
          </p>
        )}
        {dataset?.example && <p>Bundled sample data: about eleven weeks of 5m bars, not a published research dataset.</p>}
        {isOos && <p className="text-pos">Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</p>}
      </div>
    </Section>
  )
}
