'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtDateRange, fmtMoneySigned, fmtPctAbs } from '../../../lib/backtest/format'
import { gapExposure } from '../gaps'
import useGaps from './useGaps'

const pct = (v, dp = 2) => (Number.isFinite(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(dp)}%` : '—')
const num = (v, dp = 2) => (Number.isFinite(v) ? `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(dp)}` : '—')
const tone = (v) => (v > 0 ? 'v3-pos' : v < 0 ? 'v3-neg' : '')

/**
 * The result, said once, with what it is conditional on printed directly under
 * it. Replaces the six equal KPI boxes: return after costs and the same-window
 * buy & hold lead, the rest follow at reading size, and the caveats (sample,
 * runs, costs, data holes) are never more than one line away from the number.
 */
export default function Verdict() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const running = useBacktest((s) => s.running)
  const loading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)
  const strategyId = useBacktest((s) => s.strategyId)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const autoRun = useBacktest((s) => s.autoRun)

  const strategy = getStrategy(result?.provenance?.strategyId || strategyId)
  const m = result?.metrics
  const bh = result?.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const diff = m ? m.totalReturn - bhReturn : NaN

  const context = dataset
    ? `${strategy.label} on ${dataset.symbol} ${dataset.interval}, ${fmtDateRange(dataset.start, dataset.end)}`
    : strategy.label

  return (
    <section className="v3-verdict" aria-label="Result" aria-busy={running || loading}>
      <div className="v3-verdict-top">
        <h1 className="v3-verdict-context">{context}</h1>
        <span className="v3-verdict-state" aria-live="polite">
          {loading ? 'Loading data…' : running ? 'Running…' : null}
        </span>
        {!advanced && (
          <button type="button" className="v3-link v3-verdict-more" onClick={() => setAdvanced(true)} title="Open the advanced view: every metric, sweeps, walk-forward, Monte Carlo, costs, prop, rules, compare">
            All metrics and checks
          </button>
        )}
      </div>

      {!m ? (
        <p className="v3-verdict-empty">
          {datasetError
            ? 'No data loaded. See the message above.'
            : loading
              ? 'Bars are loading; the first run starts as soon as they arrive.'
              : running
                ? 'Running…'
                : autoRun
                  ? 'The first run will appear here.'
                  : 'Press Run (R) to backtest this setup.'}
        </p>
      ) : (
        <>
          <dl className={`v3-lead ${running ? 'is-stale' : ''}`}>
            <div>
              <dt>Strategy, after costs</dt>
              <dd className={tone(m.totalReturn)}>{pct(m.totalReturn)}</dd>
            </div>
            <div>
              <dt>Holding {dataset?.symbol}, no costs</dt>
              <dd className="v3-hold">{pct(bhReturn)}</dd>
            </div>
            <div>
              <dt>Difference</dt>
              <dd className={tone(diff)}>{Number.isFinite(diff) ? `${diff > 0 ? '+' : diff < 0 ? '−' : ''}${Math.abs(diff * 100).toFixed(2)} pp` : '—'}</dd>
            </div>
          </dl>
          <dl className={`v3-second ${running ? 'is-stale' : ''}`}>
            <div title="Annualised, from per-bar returns"><dt>Sharpe</dt><dd className={tone(m.sharpe)}>{num(m.sharpe)}</dd></div>
            <div title={`Longest underwater stretch: ${m.maxDdDuration} bars`}><dt>Max drawdown</dt><dd className="v3-neg">{m.maxDd > 0 ? `−${(m.maxDd * 100).toFixed(1)}%` : '0.0%'}</dd></div>
            <div><dt>Win rate</dt><dd>{fmtPctAbs(m.hitRate)}</dd></div>
            <div><dt>Trades</dt><dd>{m.nTrades.toLocaleString()}</dd></div>
          </dl>
          <Caveats result={result} />
        </>
      )}
    </section>
  )
}

function Caveats({ result }) {
  const dataset = useBacktest((s) => s.dataset)
  const runCount = useBacktest((s) => s.runCount)
  const strategyId = useBacktest((s) => s.strategyId)
  const prop = useBacktest((s) => s.prop)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const gaps = useGaps()
  const exposure = gapExposure(gaps, result)

  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const c = result.config?.costs || result.provenance?.costs
  const snoop = runCount > 300 ? 'v3-neg' : runCount > 80 ? 'v3-amber' : ''

  return (
    <ul className="v3-caveats" aria-label="What this result depends on">
      <li>
        {isOos ? (
          <span className="v3-pos">Out-of-sample bars only</span>
        ) : (
          <span>In-sample: no held-out data in this run</span>
        )}
      </li>
      <li>
        <button type="button" className={`v3-link ${snoop}`} onClick={() => toggleShortcuts(true)} title="Every run, sweep cell and walk-forward trial counts. Click for what this tally means.">
          {runCount.toLocaleString()} simulation{runCount === 1 ? '' : 's'} this session
        </button>
        {runCount > 80 && <span className={snoop}>: treat a good Sharpe as a hypothesis</span>}
      </li>
      {dataset?.example && <li className="v3-violet">Bundled sample file, not the published dataset</li>}
      {dataset?.plane === 'live' && <li className="v3-cyan">Live price snapshot, no historical GEX</li>}
      {(dataset?.cached) && <li>Offline cache, up to 24h old</li>}
      <li>
        {result.prop
          ? `Prop ${result.prop.plan.planLabel} ${result.prop.plan.sizeLabel}: $${prop.commissionPerSide}/side, ${prop.slippageTicks} tick slippage per fill`
          : c
            ? `Costs: ${c.slippageBps} bp slippage + $${c.commissionPerTrade} per trade`
            : 'Costs as configured'}
      </li>
      {gaps?.holes?.length > 0 && exposure && (
        <li className="v3-gapnote">
          <span className="v3-gap-swatch" aria-hidden="true" />
          {exposure.n > 0 ? (
            <span>
              {exposure.n} of {result.trades.length} trades were open across a data hole. They made{' '}
              <b className={tone(exposure.pnl)}>{fmtMoneySigned(exposure.pnl)}</b> of the{' '}
              <b className={tone(exposure.total)}>{fmtMoneySigned(exposure.total)}</b> net trade P&amp;L ({Math.round(exposure.grossShare * 100)}% of gross)
            </span>
          ) : (
            <span>No trade was open across any of the {gaps.holes.length} data holes</span>
          )}
        </li>
      )}
    </ul>
  )
}
