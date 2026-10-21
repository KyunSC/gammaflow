'use client'

import { useEffect, useRef, useState } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtSigned, fmtMoneySigned } from '../../../lib/backtest/format'
import { findHoles, holeExposure } from '../gaps'

const tone = (v) => (v > 0 ? 'v4-pos' : v < 0 ? 'v4-neg' : 'v4-flat')
const pct = (v, dp = 2) => (Number.isFinite(v) ? `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(dp)}%` : '—')

/**
 * The answer, then what qualifies it, in one line of sight.
 *
 * Values change instantly (no count-up). Instead, each figure that moves when
 * you nudge a parameter shows its change against the previous run on the
 * same data, so the direction of a nudge is still visible.
 */
export default function Result() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const running = useBacktest((s) => s.running)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const delta = usePreviousDelta(result, dataset)

  const m = result?.metrics
  const bh = result?.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const vsHold = m ? m.totalReturn - bhReturn : NaN
  const ci = m?.inference?.ci
  const pf = m ? (m.profitFactor === Infinity ? '∞' : Number.isFinite(m.profitFactor) ? m.profitFactor.toFixed(2) : '—') : '—'

  return (
    <section className="v4-result" aria-label="Result" aria-busy={running || datasetLoading || undefined}>
      <div className="v4-figs">
        <Fig
          lead
          label="Total return, after costs"
          value={m ? pct(m.totalReturn) : '—'}
          cls={m && tone(m.totalReturn)}
          sub={delta && Number.isFinite(delta.totalReturn) ? `${fmtSigned(delta.totalReturn * 100, 2)} pp vs last run` : ''}
        />
        <Fig
          label={dataset ? `vs holding ${dataset.symbol}` : 'vs buy & hold'}
          value={m ? `${fmtSigned(vsHold * 100, 2)} pp` : '—'}
          cls={m && tone(vsHold)}
          sub={m && Number.isFinite(bhReturn) ? `hold ${pct(bhReturn)}` : ''}
          title="Strategy total return minus holding the same symbol over the same window"
        />
        <Fig
          label="Sharpe, annualised"
          value={m ? fmtSigned(m.sharpe) : '—'}
          cls={m && tone(m.sharpe)}
          sub={ci && Number.isFinite(ci[0]) ? `95% CI ${fmtSigned(ci[0], 1)} to ${fmtSigned(ci[1], 1)}` : ''}
          title="From per-bar returns. The interval accounts for skew and fat tails but not for how many runs you have tried."
        />
        <Fig
          label="Max drawdown"
          value={m ? `−${(m.maxDd * 100).toFixed(1)}%` : '—'}
          cls={m ? 'v4-neg' : undefined}
          sub={m ? `${m.maxDdDuration.toLocaleString()} bars underwater` : ''}
        />
        <Fig label="Win rate" value={m ? `${(m.hitRate * 100).toFixed(1)}%` : '—'} sub={m ? `profit factor ${pf}` : ''} />
        <Fig
          label="Trades"
          value={m ? m.nTrades.toLocaleString() : '—'}
          sub={delta && delta.nTrades ? `${delta.nTrades > 0 ? '+' : ''}${delta.nTrades} vs last run` : ''}
        />
      </div>
      <Caveats />
    </section>
  )
}

function Fig({ label, value, cls, sub, lead, title }) {
  return (
    <div className={`v4-fig ${lead ? 'v4-fig-lead' : ''}`} title={title}>
      <span className="v4-fig-label">{label}</span>
      <span className={`v4-fig-val ${cls || ''}`}>{value}</span>
      <span className="v4-fig-sub">{sub}</span>
    </div>
  )
}

/** Change against the previous result on the same dataset, or null. */
function usePreviousDelta(result, dataset) {
  const prev = useRef(null)
  const [delta, setDelta] = useState(null)
  useEffect(() => {
    if (!result) return
    const p = prev.current
    if (p && p.datasetId === dataset?.id && p.result !== result) {
      setDelta({
        totalReturn: result.metrics.totalReturn - p.result.metrics.totalReturn,
        nTrades: result.metrics.nTrades - p.result.metrics.nTrades,
      })
    } else if (!p || p.datasetId !== dataset?.id) {
      setDelta(null)
    }
    prev.current = { result, datasetId: dataset?.id }
  }, [result, dataset])
  return result ? delta : null
}

/**
 * The honesty line. Each clause is computed from what is loaded; nothing here
 * is a fixed disclaimer.
 */
function Caveats() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const runCount = useBacktest((s) => s.runCount)
  const costs = useBacktest((s) => s.costs)
  const prop = useBacktest((s) => s.prop)
  const sweep = useBacktest((s) => s.sweep.data)
  const wf = useBacktest((s) => s.wf.data)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const setTab = useBacktest((s) => s.setTab)

  if (!dataset) return <div className="v4-caveats"><span>Caveats appear here once data loads.</span></div>

  const holes = findHoles(dataset)
  const exp = result ? holeExposure(holes, result.trades) : null
  const isOos = strategyId === 'mlSignal' && dataset.ml
  const open = (tab) => {
    setAdvanced(true)
    setTab(tab)
  }

  const items = []

  items.push(
    isOos ? (
      <span key="oos">Model positions are taken only on walk-forward out-of-sample bars.</span>
    ) : (
      <span key="is">
        <b className="v4-ink">In-sample:</b> parameters were picked on these same bars.{' '}
        {wf ? (
          <>Walk-forward OOS Sharpe <span className={`v4-mono ${tone(wf.avgOosSharpe)}`}>{fmtSigned(wf.avgOosSharpe)}</span>.</>
        ) : (
          <button onClick={() => open('wf')}>Run walk-forward</button>
        )}
      </span>
    ),
  )

  items.push(
    <span key="runs">
      <button onClick={() => toggleShortcuts(true)} className={runCount > 300 ? 'v4-neg' : runCount > 80 ? 'v4-amber' : ''}>
        {runCount.toLocaleString()} {runCount === 1 ? 'simulation' : 'simulations'} this session
      </button>
      {sweep && (
        <>
          ; sweep median Sharpe <span className={`v4-mono ${tone(sweep.median)}`}>{fmtSigned(sweep.median)}</span> vs best{' '}
          <span className="v4-mono">{fmtSigned(sweep.best?.sharpe)}</span>
        </>
      )}
      {!sweep && runCount > 80 && '; treat a good Sharpe as a hypothesis to test elsewhere'}
    </span>,
  )

  if (holes?.holes.length) {
    const share = exp && exp.count && Math.abs(exp.total) > 1 && Math.sign(exp.pnl) === Math.sign(exp.total) ? Math.abs(exp.pnl / exp.total) : null
    items.push(
      <span key="holes" className="v4-amber">
        {holes.missing.toLocaleString()} missing bars on {holes.sessions} sessions
        {exp && (
          <>
            ; {exp.count} of {exp.n} trades held across a gap, netting{' '}
            <span className="v4-mono">{fmtMoneySigned(exp.pnl)}</span> of the run&apos;s{' '}
            <span className="v4-mono">{fmtMoneySigned(exp.total)}</span>
            {share !== null && ` (${(share * 100).toFixed(0)}%)`}
          </>
        )}
      </span>,
    )
  }

  items.push(
    <span key="costs">
      {prop.enabled ? (
        <>
          Costs: {prop.slippageTicks} tick slippage per fill, ${prop.commissionPerSide.toFixed(2)} per contract per side.{' '}
        </>
      ) : (
        <>
          Costs: {costs.slippageBps} bp slippage per fill, ${costs.commissionPerTrade.toFixed(2)} commission per side.{' '}
        </>
      )}
      <button onClick={() => open('costs')}>Cost ladder</button>
    </span>,
  )

  if (getStrategy(strategyId).family === 'ml' && dataset.quality?.predictionValidation === 'legacy-unverified') {
    items.push(<span key="legacy" className="v4-amber">Legacy model predictions; training overlap unverified.</span>)
  }

  return <div className="v4-caveats">{items}</div>
}
