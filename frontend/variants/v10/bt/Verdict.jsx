'use client'

import { useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtSigned, fmtMoney, fmtMoneySigned, fmtRatio, signClass } from '../../../lib/backtest/format'
import { gapsFor, gapExposure } from './gaps'

/**
 * The answer first: one sentence comparing the run with holding the symbol,
 * then the figures, then the conditions the figures were produced under.
 * Numbers swap immediately; the previous run's value sits underneath so a
 * parameter nudge still shows which way things moved.
 */
export default function Verdict({ compact = false }) {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const running = useBacktest((s) => s.running)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const strategyId = useBacktest((s) => s.strategyId)
  const costs = useBacktest((s) => s.costs)
  const risk = useBacktest((s) => s.risk)
  const prop = useBacktest((s) => s.prop)
  const runCount = useBacktest((s) => s.runCount)
  const sweep = useBacktest((s) => s.sweep.data)
  const setTab = useBacktest((s) => s.setTab)
  const setAdvanced = useBacktest((s) => s.setAdvanced)

  // The run before this one, for the "was" line under a figure.
  const histRef = useRef({ cur: null, prev: null })
  if (result && histRef.current.cur !== result) histRef.current = { cur: result, prev: histRef.current.cur }
  const prev = result ? histRef.current.prev?.metrics : null

  const strategy = getStrategy(strategyId)

  if (!result) {
    return (
      <div className="l10-verdict" aria-live="polite">
        <p className="l10-verdict-line text-muted">
          {datasetLoading ? 'Loading bars…' : running ? `Running ${strategy.label}…` : 'No result yet. Press Run (R).'}
        </p>
        <Conditions dataset={dataset} costs={costs} risk={risk} prop={prop} result={null} strategyId={strategyId} runCount={runCount} sweep={sweep} />
      </div>
    )
  }

  const m = result.metrics
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const vsHold = m.totalReturn - bhReturn
  const ci = m.inference?.ci
  const symbol = dataset?.symbol ?? result.config.symbol

  const was = (cur, old, fmt) => (old === undefined || old === null || !Number.isFinite(old) || old === cur ? null : `was ${fmt(old)}`)

  return (
    <div className="l10-verdict" aria-live="polite">
      <p className="l10-verdict-line">
        <span className="l10-strat">{strategy.label}</span>{' '}
        {m.totalReturn >= 0 ? 'made' : 'lost'}{' '}
        <span className={`l10-num ${signClass(m.totalReturn)}`}>{fmtPctAbs(Math.abs(m.totalReturn), 2)}</span> after costs.{' '}
        <span className="l10-hold">Holding {symbol}</span> over the same bars:{' '}
        <span className={`l10-num ${signClass(bhReturn)}`}>{fmtPct(bhReturn)}</span>
        {Number.isFinite(vsHold) && (
          <span className="text-dim">
            {' '}({vsHold >= 0 ? 'ahead by' : 'behind by'} <span className="l10-num">{Math.abs(vsHold * 100).toFixed(2)}</span> pts)
          </span>
        )}
        {running && <span className="text-dim"> · re-running…</span>}
      </p>

      {!compact && (
        <dl className="l10-figs">
          <Fig label="Net return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} sub={was(m.totalReturn, prev?.totalReturn, fmtPct) || 'after costs'} />
          <Fig label="vs buy & hold" value={`${fmtSigned(vsHold * 100)} pts`} tone={signClass(vsHold)} sub={`hold ${fmtPct(bhReturn)}, no costs`} title="Strategy return minus holding the same symbol over the same window. Holding pays no costs and keeps overnight moves." />
          <Fig
            label="Sharpe"
            value={fmtSigned(m.sharpe)}
            tone={signClass(m.sharpe)}
            sub={ci && Number.isFinite(ci[0]) ? `95% CI ${fmtSigned(ci[0], 1)} to ${fmtSigned(ci[1], 1)}` : was(m.sharpe, prev?.sharpe, fmtSigned)}
            title="Annualised from per-bar returns. The interval folds in skew and fat tails (Mertens) but treats bars as independent, so it is if anything too narrow."
          />
          <Fig label="Max drawdown" value={`−${fmtPctAbs(m.maxDd)}`} tone="text-neg" sub={`longest ${m.maxDdDuration.toLocaleString()} bars`} />
          <Fig label="Win rate" value={fmtPctAbs(m.hitRate)} sub={`avg ${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
          <Fig label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} sub={`${fmtMoneySigned(m.expectancy, 0)} per trade`} />
          <Fig label="Trades" value={m.nTrades.toLocaleString()} sub={was(m.nTrades, prev?.nTrades, (v) => v.toLocaleString()) || `in market ${fmtPctAbs(m.exposure, 0)}`} />
        </dl>
      )}

      <Conditions dataset={dataset} costs={costs} risk={risk} prop={prop} result={result} strategyId={strategyId} runCount={runCount} sweep={sweep} onProp={() => { setAdvanced(true); setTab('prop') }} />
    </div>
  )
}

function Fig({ label, value, tone, sub, title }) {
  return (
    <div className="l10-fig" title={title}>
      <dt>{label}</dt>
      <dd className={tone || ''}>
        {value}
        {sub && <span className="l10-fig-sub">{sub}</span>}
      </dd>
    </div>
  )
}

/** The conditions a result was produced under, always in view. */
function Conditions({ dataset, costs, risk, prop, result, strategyId, runCount, sweep, onProp }) {
  const items = []
  const isOos = strategyId === 'mlSignal' && dataset?.ml

  if (dataset?.example) items.push(<span key="s" className="is-warn">Bundled sample data</span>)
  items.push(
    isOos ? (
      <span key="is" className="is-ok">Model trades only on walk-forward out-of-sample bars</span>
    ) : (
      <span key="is" title="Parameters are chosen and scored on the same bars. Use walk-forward (W) to score on bars the parameters never saw.">
        In-sample
      </span>
    ),
  )

  if (prop.enabled) {
    const info = useBacktest.getState().propInfo()
    if (info && !info.error) {
      items.push(
        <span key="c">
          Prop: <span className="l10-num">{info.contracts}</span> × {info.contract.label}, <span className="l10-num">${prop.commissionPerSide}</span>/side,{' '}
          <span className="l10-num">{prop.slippageTicks}</span> tick slippage
        </span>,
      )
      if (result?.prop && onProp) {
        const pr = result.prop.bootstrap || result.prop.historical
        items.push(
          <span key="ev">
            <button type="button" className="l10-link" onClick={onProp}>EV per account bought</button>{' '}
            <span className={`l10-num ${signClass(pr.ev)}`}>{fmtMoneySigned(pr.ev)}</span>, pass rate <span className="l10-num">{fmtPctAbs(pr.passRate)}</span>
          </span>,
        )
      }
    }
  } else {
    items.push(
      <span key="c">
        Costs <span className="l10-num">{costs.slippageBps}</span> bp slippage per fill, <span className="l10-num">{fmtMoney(costs.commissionPerTrade, 2)}</span> commission per side, sized{' '}
        <span className="l10-num">{costs.sizePct}</span>× of <span className="l10-num">{fmtMoney(costs.initialCapital)}</span>
      </span>,
    )
  }
  if (prop.enabled || risk.flatAtSessionEnd) items.push(<span key="f">Flat at session close</span>)

  const gaps = gapsFor(dataset)
  if (result && gaps.idx.length) {
    const g = gapExposure(gaps, result.trades)
    items.push(
      g.n ? (
        <span key="g" className="is-warn" title="Trades whose holding period contains missing bars. Their fill-to-fill move includes price change the data never showed bar by bar.">
          <span className="l10-num">{g.n}</span> of <span className="l10-num">{result.trades.length}</span> trades held across missing bars: net{' '}
          <span className="l10-num">{fmtMoneySigned(g.pnl)}</span> of <span className="l10-num">{fmtMoneySigned(g.total)}</span>
          {' '}(<span className="l10-num">{fmtPctAbs(g.absShare, 0)}</span> of absolute P&amp;L)
        </span>
      ) : (
        <span key="g">No trade held across missing bars</span>
      ),
    )
  }

  if (sweep) {
    items.push(
      <span key="sw">
        Sweep median Sharpe <span className={`l10-num ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over{' '}
        <span className="l10-num">{sweep.trials}</span> combinations (best is a maximum, not an estimate)
      </span>,
    )
  }
  if (runCount > 80) {
    items.push(
      <span key="rc" className={runCount > 300 ? 'text-neg' : 'is-warn'}>
        <span className="l10-num">{runCount.toLocaleString()}</span> simulations on this data: treat a good Sharpe as a hypothesis to test elsewhere
      </span>,
    )
  }

  return <p className="l10-conds">{items}</p>
}
