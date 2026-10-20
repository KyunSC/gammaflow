'use client'

import { useEffect, useState } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtSigned, fmtRatio, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import b from './bt.module.css'

/**
 * The answer to "did it beat just holding the symbol, after costs?" — the
 * strategy's return beside buy-and-hold over the same bars, with the costs
 * that were applied written out. Everything else is one size smaller.
 * Replaces KpiStrip (six equal cells) and the count-up animation: numbers
 * change instantly, and the change from the previous run is printed instead.
 */
export default function Verdict() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const running = useBacktest((s) => s.running)
  const loading = useBacktest((s) => s.datasetLoading)
  const runCount = useBacktest((s) => s.runCount)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const autoRun = useBacktest((s) => s.autoRun)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const setTab = useBacktest((s) => s.setTab)
  const prev = usePrevious(result)

  const strategy = getStrategy(result?.config?.strategyId ?? strategyId)
  const errors = (
    <>
      {runError && <p className={b.alert} role="alert">Run failed: {runError}</p>}
      {configError && <p className={b.alert} role="alert">{configError}</p>}
    </>
  )

  if (!result) {
    return (
      <section className={b.verdict} aria-label="Result">
        <p className={b.verdictLine}>
          <strong>{strategy.label}</strong>
          <span>
            {loading ? 'Loading bars…' : running ? 'Running…' : !dataset ? 'No data loaded.' : autoRun ? 'Waiting for the first run…' : 'Press Run (R) to see the result.'}
          </span>
        </p>
        {errors}
      </section>
    )
  }

  const m = result.metrics
  const bh = result.buyHold
  const bhReturn = bh[result.windowEnd] / bh[result.windowStart] - 1
  const diff = m.totalReturn - bhReturn
  const isOos = result.config?.strategyId === 'mlSignal' && dataset?.ml
  const bars = result.windowEnd - result.windowStart + 1
  const pr = result.prop
  const prs = pr ? pr.bootstrap || pr.historical : null

  return (
    <section className={b.verdict} aria-label="Result">
      <p className={b.verdictLine}>
        <strong>{strategy.label}</strong>
        <span>{dataset?.symbol} {dataset?.interval} · {bars.toLocaleString()} bars traded</span>
        <span className={isOos ? 'text-pos' : 'text-amber'} title={isOos ? 'Model positions are taken only on walk-forward out-of-sample bars' : 'Parameters were chosen on this same data; nothing here is out of sample'}>
          {isOos ? 'Out-of-sample model bars' : 'In-sample'}
        </span>
        <span>Run {runCount.toLocaleString()} this session</span>
      </p>

      <div className={b.figures}>
        <div className={b.figure}>
          <span className={b.figureLabel}>Strategy return</span>
          <span className={`${b.figureValue} ${signClass(m.totalReturn)}`}>{fmtPct(m.totalReturn)}</span>
          <span className={b.figureNote}>
            <CostNote config={result.config} />
            <Delta now={m.totalReturn} before={prev?.metrics?.totalReturn} fmt={(v) => `${fmtSigned(v * 100)} pp`} />
          </span>
        </div>
        <div className={b.figure}>
          <span className={b.figureLabel}>Holding {dataset?.symbol}</span>
          <span className={`${b.figureValue} ${signClass(bhReturn)}`}>{fmtPct(bhReturn)}</span>
          <span className={b.figureNote}>same bars, no costs</span>
        </div>
        <div className={b.figure}>
          <span className={b.figureLabel}>Difference</span>
          <span className={`${b.figureValue} ${b.figureValueSm} ${signClass(diff)}`}>{fmtSigned(diff * 100)} pp</span>
          <span className={b.figureNote}>{diff > 0 ? 'ahead of holding' : 'behind holding'}</span>
        </div>
        {pr && prs && (
          <div className={b.figure}>
            <span className={b.figureLabel}>Prop account · {pr.plan.planLabel} {pr.plan.sizeLabel}</span>
            <button type="button" onClick={() => { setAdvanced(true); setTab('prop') }} className={`${b.figureValue} ${b.figureValueSm} ${signClass(prs.ev)} text-left`} title="Open the prop tab">
              {fmtMoneySigned(prs.ev)}
            </button>
            <span className={b.figureNote}>EV per purchase · pass {fmtPctAbs(prs.passRate)}</span>
          </div>
        )}
      </div>

      <div className={b.stats}>
        <Stat label="Sharpe" value={fmtSigned(m.sharpe)} tone={signClass(m.sharpe)} title="Annualised, from per-bar returns">
          <Delta now={m.sharpe} before={prev?.metrics?.sharpe} fmt={fmtSigned} />
        </Stat>
        <Stat label="Max drawdown" value={fmtPct(-m.maxDd, 1)} tone="text-neg" title={`Longest underwater stretch: ${m.maxDdDuration} bars`} />
        <Stat label="Win rate" value={fmtPctAbs(m.hitRate)} />
        <Stat label="Trades" value={m.nTrades.toLocaleString()} />
        <Stat label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} />
        <Stat label="Exposure" value={fmtPctAbs(m.exposure)} title="Share of bars holding a position" />
      </div>
      {errors}
    </section>
  )
}

function CostNote({ config }) {
  const prop = useBacktest((s) => s.prop)
  if (!config) return null
  if (config.prop) {
    const inst = config.costs?.instrument
    return (
      <span>
        {inst ? `${inst.contracts} × ${inst.contract}, ` : ''}${prop.commissionPerSide}/side, {prop.slippageTicks} tk slippage
      </span>
    )
  }
  const c = config.costs
  if (!c.slippageBps && !c.commissionPerTrade) return <span className="text-amber">no costs applied</span>
  return <span>after {c.slippageBps} bp slippage, ${c.commissionPerTrade}/trade</span>
}

function Stat({ label, value, tone, title, children }) {
  return (
    <span className={b.stat} title={title}>
      {label}
      <span className={`${b.statValue} ${tone || ''}`}>{value}</span>
      {children}
    </span>
  )
}

function Delta({ now, before, fmt }) {
  if (!Number.isFinite(now) || !Number.isFinite(before)) return null
  const d = now - before
  if (Math.abs(d) < 1e-9) return null
  return <span className={b.delta}> · {fmt(d)} vs previous run</span>
}

/** The result before the current one, so a parameter nudge shows which way it moved. */
function usePrevious(result) {
  const [pair, setPair] = useState({ cur: null, prev: null })
  useEffect(() => {
    if (result && result !== pair.cur) setPair((p) => ({ cur: result, prev: p.cur }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result])
  const prev = pair.prev
  // Only compare like with like: same symbol and the same strategy family of numbers.
  if (!prev || !result || prev.config?.datasetId !== result.config?.datasetId) return null
  return prev
}
