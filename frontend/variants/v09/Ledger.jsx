'use client'

import { useMemo } from 'react'
import { useBacktest } from '../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../lib/backtest/format'
import { findGaps, tradeExposure } from './gaps'

/**
 * The right rail: every metric the run produced, then the notes that say how
 * far to trust them. Same numbers and copy as the original MetricsPanel's
 * honesty block, but always on screen, not only in the advanced view.
 */
export default function Ledger() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep.data)
  const wf = useBacktest((s) => s.wf.data)
  const runCount = useBacktest((s) => s.runCount)
  const setTab = useBacktest((s) => s.setTab)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const gaps = useMemo(() => findGaps(dataset), [dataset])

  const m = result?.metrics
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const bh = result?.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : null
  const exp = tradeExposure(gaps, result?.trades)
  const prop = result?.prop ? result.prop.bootstrap || result.prop.historical : null

  return (
    <div className="flex flex-col gap-4 px-4 py-3">
      <section aria-labelledby="v9-h-metrics">
        <div className="mb-1.5 flex items-baseline gap-2">
          <h2 id="v9-h-metrics" className="v9-h">All metrics</h2>
          <span className="flex-1" />
          <span className={`text-[11.5px] ${result?.prop ? 'text-amber' : isOos ? 'text-pos' : 'text-dim'}`}>
            {result ? (result.prop ? 'prop account' : isOos ? 'out-of-sample' : 'in-sample') : ''}
          </span>
        </div>
        {!m ? (
          <p className="text-[12px] text-dim">Metrics appear after a run.</p>
        ) : (
          <dl className="text-[12px]">
            <Row label="Total return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} />
            <Row label={`Buy & hold ${dataset?.symbol ?? ''}`} value={bhReturn === null ? '—' : fmtPct(bhReturn)} tone="text-cyan" />
            <Row label="CAGR" value={fmtPct(m.cagr)} tone={signClass(m.cagr)} title="Annualised from a short window, so it exaggerates in both directions" />
            <Row label="Final equity" value={fmtMoney(m.finalEquity)} />
            <Row label="Ann. volatility" value={fmtPctAbs(m.volAnn)} />
            <Row label="Calmar" value={fmtRatio(m.calmar)} />
            <Row label="Expectancy / trade" value={fmtMoney(m.expectancy, 2)} tone={signClass(m.expectancy)} />
            <Row label="Avg win / loss" value={`${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
            <Row label="Turnover / yr" value={m.turnover.toFixed(0)} />
            <Row label="Avg bars held" value={m.avgBarsHeld.toFixed(1)} />
            <Row label="Longest drawdown" value={`${m.maxDdDuration} bars`} />
          </dl>
        )}
      </section>

      {prop && (
        <section aria-labelledby="v9-h-prop" className="border-t border-hair pt-3">
          <div className="mb-1 flex items-baseline gap-2">
            <h2 id="v9-h-prop" className="v9-h">Prop account</h2>
            <span className="flex-1" />
            <button onClick={() => { setAdvanced(true); setTab('prop') }} className="v9-link text-[11.5px]">Details</button>
          </div>
          <dl className="text-[12px]">
            <Row label="EV per purchase" value={fmtMoneySigned(prop.ev)} tone={signClass(prop.ev)} />
            <Row label="Pass rate" value={fmtPctAbs(prop.passRate)} />
          </dl>
        </section>
      )}

      <section aria-labelledby="v9-h-trust" className="border-t border-hair pt-3">
        <h2 id="v9-h-trust" className="v9-h mb-1.5">How far to trust it</h2>
        <ul className="flex flex-col gap-2 text-[12px] leading-snug text-muted">
          <li>
            <span className={`v9-num ${runCount > 300 ? 'text-neg' : runCount > 80 ? 'text-amber' : 'text-ink'}`}>{runCount.toLocaleString()}</span>{' '}
            simulation{runCount === 1 ? '' : 's'} this session, counting every sweep cell and walk-forward trial.
            {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
          </li>
          <li>
            {sweep ? (
              <>
                Sweep: best Sharpe <span className={`v9-num ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span>, median{' '}
                <span className={`v9-num ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over{' '}
                <span className="v9-num">{sweep.trials}</span> combinations. The median is the honest estimate; the best cell is the maximum
                of {sweep.trials} draws.
              </>
            ) : (
              <>Not swept yet. A sweep (S) shows how much of this Sharpe is parameter luck.</>
            )}
          </li>
          <li>
            {wf ? (
              <>
                Walk-forward: out-of-sample Sharpe <span className={`v9-num ${signClass(wf.avgOosSharpe)}`}>{fmtSigned(wf.avgOosSharpe)}</span> against{' '}
                <span className="v9-num">{fmtSigned(wf.avgIsSharpe)}</span> in-sample, {wf.positiveFolds}/{wf.folds.length} folds positive.
              </>
            ) : isOos ? (
              <>Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</>
            ) : (
              <>No out-of-sample test yet. Walk-forward (W) fits each fold on its past and trades the next.</>
            )}
          </li>
          {gaps?.supported && gaps.missingBars > 0 && exp && (
            <li className="text-amber">
              {gaps.gapDays}/{gaps.sessionCount} sessions have missing bars. {exp.affected} trade{exp.affected === 1 ? ' was' : 's were'} open across a hole (
              <span className="v9-num">{fmtMoneySigned(exp.affectedPnl)}</span>).
            </li>
          )}
          {dataset?.example && (
            <li className="text-violet">
              Bundled sample{gaps?.supported ? `: ${gaps.sessionCount} sessions of ${dataset.interval} bars` : ''}. A short window; a result here says little about other periods.
            </li>
          )}
          <li className="text-dim">Costs are the ones in Setup; buy &amp; hold is charged none.</li>
        </ul>
      </section>
    </div>
  )
}

function Row({ label, value, tone, title }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hair/60 py-[3px]" title={title}>
      <dt className="text-dim">{label}</dt>
      <dd className={`v9-num ${tone || 'text-muted'}`}>{value}</dd>
    </div>
  )
}
