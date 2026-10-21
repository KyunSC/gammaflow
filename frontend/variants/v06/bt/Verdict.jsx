'use client'

import { useEffect, useRef, useState } from 'react'
import { animate } from 'framer-motion'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtMoneySigned, fmtDateRange, signClass } from '../../../lib/backtest/format'
import { useReducedMotion } from './ui'

/** Counts from the previous reading to the new one, so a parameter nudge shows
 *  which way the number moved. Skipped under reduced motion. */
function useCountUp(value, dp) {
  const reduced = useReducedMotion()
  const [display, setDisplay] = useState(Number.isFinite(value) ? value : 0)
  const prev = useRef(Number.isFinite(value) ? value : 0)
  useEffect(() => {
    if (!Number.isFinite(value) || reduced) {
      setDisplay(value)
      if (Number.isFinite(value)) prev.current = value
      return
    }
    const controls = animate(prev.current, value, { duration: 0.35, ease: 'easeOut', onUpdate: setDisplay })
    prev.current = value
    return () => controls.stop()
  }, [value, reduced])
  return Number.isFinite(display) ? display : NaN
}

function Kpi({ label, value, dp = 2, suffix = '', sign = false, tone, title }) {
  const v = useCountUp(value, dp)
  const text = Number.isFinite(v) ? `${sign && v > 0 ? '+' : ''}${v.toFixed(dp)}${suffix}` : '—'
  return (
    <div className="v6-kpi" title={title}>
      <dt>{label}</dt>
      <dd className={`num ${Number.isFinite(value) ? tone || '' : 'v6-dim'}`}>{text.replace('-', '−')}</dd>
    </div>
  )
}

/**
 * The answer, in a sentence, then the six numbers it rests on. The sentence
 * names the scope (in-sample or out-of-sample) and the comparison (holding the
 * same symbol), because a return quoted without either says nothing.
 */
export default function Verdict() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const strategyId = useBacktest((s) => s.strategyId)
  const setTab = useBacktest((s) => s.setTab)
  const setAdvanced = useBacktest((s) => s.setAdvanced)

  const m = result?.metrics
  const bh = result?.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const vsHold = m ? m.totalReturn - bhReturn : NaN
  const strategy = getStrategy(result?.config?.strategyId || strategyId)
  const isOos = strategy.id === 'mlSignal' && dataset?.ml
  const prop = result?.prop
  const propEst = prop ? prop.bootstrap || prop.historical : null

  let sentence
  if (loading && !dataset) sentence = <span className="v6-dim">Loading bars…</span>
  else if (!result && running) sentence = <span className="v6-dim">Running {strategy.label}…</span>
  else if (!result) sentence = <span className="v6-dim">{autoRun ? 'Results appear here once the strategy runs.' : 'Press Run (or R) to score this setup.'}</span>
  else {
    const start = dataset?.time?.[result.windowStart]
    const end = dataset?.time?.[result.windowEnd]
    sentence = (
      <>
        <span className="v6-scope">{isOos ? 'Out-of-sample' : 'In-sample'}</span>{' '}
        <strong>{strategy.label}</strong> on {dataset?.symbol} {dataset?.interval}{' '}
        <span className="v6-dim">({fmtDateRange(start * 1000, end * 1000)})</span>{' '}
        returned <span className={`num ${signClass(m.totalReturn)}`}>{fmtPct(m.totalReturn)}</span> after costs, against{' '}
        <span className={`num ${signClass(bhReturn)}`}>{fmtPct(bhReturn)}</span> for holding {dataset?.symbol}
        {propEst ? (
          <>
            ; as a {prop.plan.planLabel} {prop.plan.sizeLabel} account, expected value per purchase{' '}
            <span className={`num ${signClass(propEst.ev)}`}>{fmtMoneySigned(propEst.ev)}</span> with a{' '}
            <span className="num">{fmtPctAbs(propEst.passRate)}</span> pass rate
          </>
        ) : null}
        .
        {running && <span className="v6-dim"> Re-running…</span>}
      </>
    )
  }

  return (
    <div className="v6-verdict" aria-live="polite">
      <p className="v6-verdict-line">{sentence}</p>
      <dl className="v6-kpis">
        <Kpi label="Total return" value={m ? m.totalReturn * 100 : NaN} suffix="%" sign tone={m && signClass(m.totalReturn)} />
        <Kpi
          label="vs buy & hold, pp"
          value={vsHold * 100}
          sign
          tone={signClass(vsHold)}
          title="Strategy total return minus holding the same symbol over the same window, in percentage points"
        />
        <Kpi label="Sharpe" value={m ? m.sharpe : NaN} sign tone={m && signClass(m.sharpe)} title="Annualised, from per-bar returns" />
        <Kpi label="Max drawdown" value={m ? -m.maxDd * 100 : NaN} dp={1} suffix="%" tone={m && m.maxDd > 0 ? 'text-neg' : ''} title={m ? `Longest underwater stretch: ${m.maxDdDuration} bars` : undefined} />
        <Kpi label="Win rate" value={m ? m.hitRate * 100 : NaN} dp={1} suffix="%" />
        <Kpi label="Trades" value={m ? m.nTrades : NaN} dp={0} />
      </dl>
      {prop && (
        <button
          type="button"
          className="v6-link v6-verdict-prop"
          onClick={() => {
            setAdvanced(true)
            setTab('prop')
          }}
        >
          Prop account details
        </button>
      )}
    </div>
  )
}
