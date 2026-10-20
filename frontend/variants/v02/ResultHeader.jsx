'use client'

import { useBacktest } from '../../lib/backtest/store'
import { getStrategy } from '../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtSigned, fmtMoneySigned, signClass } from '../../lib/backtest/format'
import { holesFor, holeExposure } from './gaps'
import s from './bt.module.css'

/**
 * The answer and its caveats, printed together.
 *
 * The original showed the headline figures with no context in the default
 * view and kept costs, in-sample status, buy & hold and the run tally behind
 * the Advanced switch. Here the caveat line sits directly under the numbers
 * it qualifies, in both modes, so a Sharpe is never read without them.
 */
export default function ResultHeader() {
  const result = useBacktest((st) => st.result)
  const dataset = useBacktest((st) => st.dataset)
  const strategyId = useBacktest((st) => st.strategyId)
  const runCount = useBacktest((st) => st.runCount)
  const running = useBacktest((st) => st.running)
  const loading = useBacktest((st) => st.datasetLoading)
  const autoRun = useBacktest((st) => st.autoRun)
  const datasetNotice = useBacktest((st) => st.datasetNotice)
  const datasetError = useBacktest((st) => st.datasetError)
  const setExample = useBacktest((st) => st.setExample)
  const advanced = useBacktest((st) => st.advanced)
  const setAdvanced = useBacktest((st) => st.setAdvanced)
  const toggleShortcuts = useBacktest((st) => st.toggleShortcuts)
  const sweep = useBacktest((st) => st.sweep.data)

  const strategy = getStrategy(result?.config?.strategyId ?? strategyId)
  const m = result?.metrics
  const bh = result?.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const vsHold = m ? m.totalReturn - bhReturn : NaN
  const isOos = strategyId === 'mlSignal' && dataset?.ml
  const gaps = holesFor(dataset)
  const exposure = holeExposure(gaps, result?.trades)

  const status = loading
    ? 'Loading bars…'
    : running && !result
      ? 'Running…'
      : !result
        ? autoRun ? 'Waiting for the first run.' : 'Press Run (R) to see results.'
        : null

  return (
    <section className={s.result} aria-label="Result">
      <div className={s.title}>
        <h1>{strategy.label}</h1>
        {dataset && (
          <span className={s.on}>
            on {dataset.symbol} {dataset.interval}
            {dataset.example ? ', bundled sample' : ''}
          </span>
        )}
        {result && (
          <span className={s.tag} title={result.prop ? 'Run under prop-firm rules, sized in whole futures contracts' : isOos ? 'Model positions are taken only on walk-forward out-of-sample bars' : 'Parameters and results come from the same bars. There is no holdout.'}>
            {result.prop ? `prop · ${result.prop.plan.planLabel} ${result.prop.plan.sizeLabel}` : isOos ? 'out-of-sample (walk-forward model)' : 'in-sample, no holdout'}
          </span>
        )}
        {status && <span className="text-[12px] text-dim">{status}</span>}
        {!advanced && (
          <button onClick={() => setAdvanced(true)} className={`${s.inlineBtn} ml-auto text-[11.5px] text-muted`} title="Every metric, sweeps, walk-forward, Monte Carlo, compare">
            all metrics
          </button>
        )}
      </div>

      <div className={s.kpis}>
        <Kpi label="Total return" value={m ? fmtPct(m.totalReturn) : '—'} tone={m && signClass(m.totalReturn)} />
        <Kpi
          label="vs buy & hold"
          value={Number.isFinite(vsHold) ? `${fmtSigned(vsHold * 100)} pp` : '—'}
          tone={signClass(vsHold)}
          sub={Number.isFinite(bhReturn) ? `hold ${fmtPct(bhReturn)}` : null}
          title="Strategy total return minus holding the same symbol over the same window, in percentage points"
        />
        <Kpi label="Sharpe" value={m ? fmtSigned(m.sharpe) : '—'} tone={m && signClass(m.sharpe)} sub={m ? `Sortino ${fmtSigned(m.sortino)}` : null} title="Annualised, from per-bar returns" />
        <Kpi label="Max drawdown" value={m ? `−${fmtPctAbs(m.maxDd)}` : '—'} tone={m ? 'text-neg' : undefined} sub={m ? `${m.maxDdDuration} bars under water` : null} />
        <Kpi label="Win rate" value={m ? fmtPctAbs(m.hitRate) : '—'} sub={m && Number.isFinite(m.profitFactor) ? `profit factor ${m.profitFactor.toFixed(2)}` : null} />
        <Kpi label="Trades" value={m ? String(m.nTrades) : '—'} sub={m ? `in market ${fmtPctAbs(m.exposure, 0)} of bars` : null} />
      </div>

      <div className={s.caveats}>
        {dataset?.example && (
          <span className={`${s.caveat} text-violet`}>
            Bundled sample, not the live dataset
            {datasetNotice && !datasetError && (
              <>
                {' '}({noticeReason(datasetNotice)}){' '}
                <button onClick={() => setExample(false)} className={s.inlineBtn}>
                  retry server
                </button>
              </>
            )}
          </span>
        )}
        {result && <span className={s.caveat}>{costLine(result.config.costs)}</span>}
        {gaps && gaps.holes.length > 0 && (
          <span className={`${s.caveat} ${s.warn}`} title="Consecutive bars inside one session that are further apart than the bar interval. The chart draws straight across them; they are striped on the price chart and ticked under the equity curve.">
            {gaps.sessions} of {gaps.days} sessions have missing bars ({gaps.missing.toLocaleString()} × {dataset.interval} absent)
            {result && exposure.n > 0 && (
              <>
                ; {exposure.n} of {result.trades.length} trades are held across a hole, net{' '}
                <span className={signClass(exposure.pnl)}>{fmtMoneySigned(exposure.pnl)}</span> of{' '}
                <span className={signClass(exposure.total)}>{fmtMoneySigned(exposure.total)}</span>
              </>
            )}
          </span>
        )}
        {sweep && (
          <span className={s.caveat}>
            sweep median Sharpe <span className={signClass(sweep.median)}>{fmtSigned(sweep.median)}</span> over {sweep.trials} combinations
          </span>
        )}
        <span className={`${s.caveat} ${runCount > 300 ? s.bad : runCount > 80 ? s.warn : ''}`}>
          <button onClick={() => toggleShortcuts(true)} className={s.inlineBtn} title="What the run tally means">
            {runCount.toLocaleString()} simulation{runCount === 1 ? '' : 's'} this session
          </button>
          {runCount > 80 && ': treat a good Sharpe here as a hypothesis to test on other data'}
        </span>
      </div>
    </section>
  )
}

function Kpi({ label, value, tone, sub, title }) {
  return (
    <div className={s.kpi} title={title}>
      <span className={s.kpiLabel}>{label}</span>
      <span className={`${s.kpiValue} ${tone || 'text-ink'}`}>{value}</span>
      <span className={s.kpiSub}>{sub || ' '}</span>
    </div>
  )
}

/** "Dataset service unavailable (500) — showing bundled…" → "dataset service unavailable (500)". */
function noticeReason(notice) {
  const head = notice.split(' — ')[0] || notice
  return head.charAt(0).toLowerCase() + head.slice(1)
}

function costLine(costs) {
  const inst = costs?.instrument
  if (inst) {
    return `Net of $${Number(inst.commissionPerSide).toFixed(2)} commission and ${inst.slippageTicks} tick${inst.slippageTicks === 1 ? '' : 's'} slippage per contract on every fill, ${inst.contracts} contract${inst.contracts === 1 ? '' : 's'}`
  }
  if (!costs) return null
  const free = !costs.slippageBps && !costs.commissionPerTrade
  return free
    ? 'No costs applied: slippage and commission are both zero'
    : `Net of ${costs.slippageBps} bp slippage and $${Number(costs.commissionPerTrade).toFixed(2)} commission on every fill`
}
