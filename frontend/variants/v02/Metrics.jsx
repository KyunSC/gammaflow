'use client'

import { useBacktest } from '../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../lib/backtest/format'
import s from './bt.module.css'

/**
 * Everything the original MetricsPanel reported, as a plain definition list
 * grouped by question. The six headline figures already lead the page, so
 * they are not repeated as big tiles here.
 */
export default function Metrics() {
  const result = useBacktest((st) => st.result)
  const dataset = useBacktest((st) => st.dataset)
  const strategyId = useBacktest((st) => st.strategyId)
  const sweep = useBacktest((st) => st.sweep.data)
  const runCount = useBacktest((st) => st.runCount)
  const setTab = useBacktest((st) => st.setTab)

  if (!result) {
    return (
      <div className={s.pane}>
        <div className={s.paneHead}><span className={s.paneTitle}>All metrics</span></div>
        <p className="px-4 py-3 text-[12px] text-dim">Metrics are listed after the first run.</p>
      </div>
    )
  }

  const m = result.metrics
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : null
  const prop = result.prop ? result.prop.bootstrap || result.prop.historical : null

  return (
    <div className={s.pane}>
      <div className={s.paneHead}>
        <span className={s.paneTitle}>All metrics</span>
        <span className="ml-auto">{result.prop ? 'prop account' : isOos ? 'out-of-sample' : 'in-sample'}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-3">
        {prop && (
          <button onClick={() => setTab('prop')} className="mx-4 mb-1 flex w-[calc(100%-2rem)] items-baseline justify-between gap-2 border-b border-hair py-1.5 text-left hover:text-ink" title="Open the prop tab">
            <span className="text-[11.5px] text-dim">EV per account bought</span>
            <span className={`font-mono text-[14px] ${signClass(prop.ev)}`}>
              {fmtMoneySigned(prop.ev)}
              <span className="ml-1.5 text-[10.5px] text-dim">pass {fmtPctAbs(prop.passRate)}</span>
            </span>
          </button>
        )}

        <Group title="Return">
          <Row label="Total return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} />
          <Row label="Buy & hold" value={bhReturn === null ? '—' : fmtPct(bhReturn)} />
          <Row label="CAGR" value={fmtPct(m.cagr)} tone={signClass(m.cagr)} title="Annualised from a short window: very sensitive to its length" />
          <Row label="Final equity" value={fmtMoney(m.finalEquity)} />
        </Group>
        <Group title="Risk">
          <Row label="Sharpe" value={fmtSigned(m.sharpe)} tone={signClass(m.sharpe)} title="Annualised, from per-bar returns" />
          <Row label="Sortino" value={fmtSigned(m.sortino)} tone={signClass(m.sortino)} />
          <Row label="Calmar" value={fmtRatio(m.calmar)} />
          <Row label="Ann. volatility" value={fmtPctAbs(m.volAnn)} />
          <Row label="Max drawdown" value={`−${fmtPctAbs(m.maxDd)}`} tone="text-neg" />
          <Row label="Longest drawdown" value={`${m.maxDdDuration} bars`} />
        </Group>
        <Group title="Trades">
          <Row label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} />
          <Row label="Expectancy / trade" value={fmtMoney(m.expectancy, 2)} tone={signClass(m.expectancy)} />
          <Row label="Avg win / loss" value={`${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
          <Row label="Exposure" value={fmtPctAbs(m.exposure)} title="Share of bars holding a position" />
          <Row label="Turnover / yr" value={m.turnover.toFixed(0)} />
          <Row label="Avg bars held" value={m.avgBarsHeld.toFixed(1)} />
        </Group>

        <h3 className={s.mgroup}>How far to trust it</h3>
        <div className="flex flex-col gap-1.5 px-4 pt-1 text-[11.5px] leading-snug text-muted">
          {sweep ? (
            <p>
              Sweep best Sharpe <span className={`font-mono ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span>, median{' '}
              <span className={`font-mono ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over {sweep.trials} combinations. The median is the honest
              estimate; the best cell is the maximum of {sweep.trials} draws.
            </p>
          ) : (
            <p>
              No sweep yet. Run one (S) to see how much of this number is parameter luck.
            </p>
          )}
          <p>
            {runCount.toLocaleString()} simulation{runCount === 1 ? '' : 's'} this session.
            {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
          </p>
          {isOos && <p className="text-pos">Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</p>}
        </div>
      </div>
    </div>
  )
}

function Group({ title, children }) {
  return (
    <>
      <h3 className={s.mgroup}>{title}</h3>
      <dl>{children}</dl>
    </>
  )
}

function Row({ label, value, tone, title }) {
  return (
    <div className={s.mrow} title={title}>
      <dt>{label}</dt>
      <dd className={tone || ''}>{value}</dd>
    </div>
  )
}
