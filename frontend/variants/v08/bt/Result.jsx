'use client'

import { useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import { findGaps, gapExposure } from './gaps'
import { NoRunYet } from './ui'

const bhReturnOf = (result) => {
  const bh = result?.buyHold
  return bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
}

/** The previous result for the same dataset and strategy, so each figure can
 *  say which way the last change moved it, without animating the number. */
function usePreviousResult(result) {
  const prev = useRef(null)
  const cur = useRef(null)
  if (result !== cur.current) {
    const same = cur.current && result &&
      cur.current.config?.datasetId === result.config?.datasetId &&
      cur.current.config?.strategyId === result.config?.strategyId
    prev.current = same ? cur.current : null
    cur.current = result
  }
  return prev.current
}

function costLine(result) {
  if (result.prop) {
    const inst = result.config?.costs?.instrument
    return `prop account ${result.prop.plan.planLabel} ${result.prop.plan.sizeLabel}${inst ? `, ${inst.contracts} × ${inst.contract}` : ''}, per-contract costs`
  }
  const c = result.config?.costs
  if (!c) return null
  return `${c.slippageBps} bp slippage and $${c.commissionPerTrade} commission per trade`
}

/**
 * The answer, in one sentence built from the run's own numbers, followed by
 * the headline figures and the caveats that belong next to them.
 */
export default function Result() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const runCount = useBacktest((s) => s.runCount)
  const running = useBacktest((s) => s.running)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const prev = usePreviousResult(result)

  if (!result || !dataset) {
    return (
      <section className="v8-result" aria-label="Result">
        <NoRunYet what="Results" />
      </section>
    )
  }

  const m = result.metrics
  const strat = getStrategy(result.config?.strategyId || strategyId)
  const bh = bhReturnOf(result)
  const vsHold = m.totalReturn - bh
  const isOos = strat.id === 'mlSignal' && dataset.ml
  const gaps = findGaps(dataset)
  const exposure = gapExposure(gaps, result.trades)
  const pm = prev?.metrics

  return (
    <section className="v8-result" aria-label="Result" aria-busy={running}>
      <p className="v8-verdict">
        <span className="v8-ink">{strat.label}</span> on {dataset.symbol} {dataset.interval}{' '}
        {m.nTrades === 0 ? (
          <>never entered a trade.</>
        ) : (
          <>
            returned <span className={signClass(m.totalReturn)}>{fmtPct(m.totalReturn)}</span> after costs over{' '}
            {m.nTrades.toLocaleString()} trade{m.nTrades === 1 ? '' : 's'}. Holding {dataset.symbol} over the same window returned{' '}
            <span className={signClass(bh)}>{fmtPct(bh)}</span>.
          </>
        )}
      </p>

      <ul className="v8-caveats">
        <li className={isOos ? 'text-violet' : 'v8-ink'}>
          {isOos ? 'Model positions only on walk-forward out-of-sample bars' : 'In-sample: parameters chosen on this same data'}
        </li>
        {dataset.example && <li className="v8-flag">Bundled sample data</li>}
        {costLine(result) && <li>{costLine(result)}</li>}
        {exposure && exposure.n > 0 && (
          <li className="v8-gapnote">
            {exposure.n} of {exposure.total} trades held across missing bars made{' '}
            <span className={signClass(exposure.pnl)}>{fmtMoneySigned(exposure.pnl)}</span>; the other {exposure.total - exposure.n} made{' '}
            <span className={signClass(exposure.other)}>{fmtMoneySigned(exposure.other)}</span>
          </li>
        )}
        <li>
          Run {runCount.toLocaleString()} this session
          {runCount > 80 && ': treat a good number as a hypothesis to test on other data'}
        </li>
      </ul>

      <dl className="v8-figures">
        <Figure label="Total return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} delta={pm && (m.totalReturn - pm.totalReturn) * 100} unit="pp" sub={`Buy & hold ${fmtPct(bh)}`} />
        <Figure
          label="Versus buy & hold"
          value={Number.isFinite(vsHold) ? `${fmtSigned(vsHold * 100)} pp` : '—'}
          tone={signClass(vsHold)}
          title="Strategy total return minus holding the same symbol over the same window, in percentage points"
          sub="same window, no costs on hold"
        />
        <Figure label="Sharpe" value={fmtSigned(m.sharpe)} tone={signClass(m.sharpe)} delta={pm && m.sharpe - pm.sharpe} sub={`Sortino ${fmtSigned(m.sortino)}`} title="Annualised, from per-bar returns" />
        <Figure label="Max drawdown" value={`-${fmtPctAbs(m.maxDd)}`} tone="text-neg" sub={`underwater ${m.maxDdDuration} bars`} />
        <Figure label="Win rate" value={fmtPctAbs(m.hitRate)} sub={`profit factor ${fmtRatio(m.profitFactor)}`} />
        <Figure
          label="Trades"
          value={m.nTrades.toLocaleString()}
          sub={exposure && exposure.n > 0 ? `${exposure.n} across data holes` : `avg ${m.avgBarsHeld.toFixed(1)} bars held`}
          subTone={exposure && exposure.n > 0 ? 'v8-gapnote' : undefined}
        />
      </dl>

      {!advanced && (
        <button type="button" className="v8-textbtn v8-more" onClick={() => setAdvanced(true)}>
          All metrics, sweeps, walk-forward and Monte Carlo →
        </button>
      )}
    </section>
  )
}

function Figure({ label, value, tone, sub, subTone, title, delta, unit = '' }) {
  const showDelta = Number.isFinite(delta) && Math.abs(delta) >= 0.005
  return (
    <div className="v8-figure" title={title}>
      <dt>{label}</dt>
      <dd className={`num v8-figure-value ${tone || 'v8-ink'}`}>{value}</dd>
      <dd className={`v8-figure-sub ${subTone || ''}`}>
        {sub}
        {showDelta && (
          <span className="v8-delta" title="Change from the previous run of this strategy">
            {' '}· {delta > 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(2)}{unit ? ` ${unit}` : ''}
          </span>
        )}
      </dd>
    </div>
  )
}

/** Advanced view: every metric, then the honesty notes. */
export function MetricsList() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep.data)
  const runCount = useBacktest((s) => s.runCount)
  const setTab = useBacktest((s) => s.setTab)

  if (!result) return <NoRunYet what="Metrics" />

  const m = result.metrics
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const bh = bhReturnOf(result)
  const ev = result.prop && (result.prop.bootstrap || result.prop.historical)

  return (
    <div className="v8-metrics">
      <p className="v8-metrics-scope">
        {result.prop ? (
          <span className="text-amber">Prop account · {result.prop.plan.planLabel} {result.prop.plan.sizeLabel}</span>
        ) : isOos ? (
          <span className="text-violet">Out-of-sample model positions</span>
        ) : (
          <span>In-sample</span>
        )}
      </p>
      {ev && (
        <button type="button" onClick={() => setTab('prop')} className="v8-row v8-row-btn" title="Open the prop tab">
          <span>EV per purchase</span>
          <span className={`num ${signClass(ev.ev)}`}>
            {fmtMoneySigned(ev.ev)} <span className="text-dim">· pass {fmtPctAbs(ev.passRate)}</span>
          </span>
        </button>
      )}
      <Row label="Total return" value={fmtPct(m.totalReturn)} tone={signClass(m.totalReturn)} />
      <Row label="Buy & hold" value={fmtPct(bh)} />
      <Row label="CAGR" value={fmtPct(m.cagr)} tone={signClass(m.cagr)} />
      <Row label="Final equity" value={fmtMoney(m.finalEquity)} />
      <Row label="Sharpe" value={fmtSigned(m.sharpe)} tone={signClass(m.sharpe)} />
      <Row label="Sortino" value={fmtSigned(m.sortino)} tone={signClass(m.sortino)} />
      <Row label="Calmar" value={fmtRatio(m.calmar)} />
      <Row label="Ann. volatility" value={fmtPctAbs(m.volAnn)} />
      <Row label="Max drawdown" value={`-${fmtPctAbs(m.maxDd)}`} tone="text-neg" />
      <Row label="Drawdown duration" value={`${m.maxDdDuration} bars`} />
      <Row label="Hit rate" value={fmtPctAbs(m.hitRate)} />
      <Row label="Profit factor" value={fmtRatio(m.profitFactor)} tone={m.profitFactor >= 1 ? 'text-pos' : 'text-neg'} />
      <Row label="Expectancy / trade" value={fmtMoney(m.expectancy, 2)} tone={signClass(m.expectancy)} />
      <Row label="Avg win / loss" value={`${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`} />
      <Row label="Exposure" value={fmtPctAbs(m.exposure)} title="Share of bars holding a position" />
      <Row label="Turnover / yr" value={m.turnover.toFixed(0)} />
      <Row label="Avg bars held" value={m.avgBarsHeld.toFixed(1)} />
      <Row label="Trades" value={m.nTrades.toLocaleString()} />

      <div className="v8-honesty">
        <h3>Before you believe it</h3>
        {sweep ? (
          <p>
            Sweep: best Sharpe <span className={`num ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span>, median{' '}
            <span className={`num ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over <span className="num">{sweep.trials}</span>{' '}
            combinations. Quote the median; the best cell is the maximum of {sweep.trials} draws.
          </p>
        ) : (
          <p>Run a sweep (S) to see how much of this Sharpe is parameter luck.</p>
        )}
        <p>
          <span className="num">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session.
          {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
        </p>
        {isOos && <p className="text-violet">Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</p>}
      </div>
    </div>
  )
}

function Row({ label, value, tone, title }) {
  return (
    <div className="v8-row" title={title}>
      <span>{label}</span>
      <span className={`num ${tone || 'v8-ink'}`}>{value}</span>
    </div>
  )
}
