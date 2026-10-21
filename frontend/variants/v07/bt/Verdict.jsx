'use client'

import { useMemo } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy } from '../../../lib/backtest/strategies'
import { fmtPct, fmtPctAbs, fmtSigned, fmtMoney, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import { scanGaps, holeExposure } from '../gaps'
import { useV7 } from './uiStore'
import { minus } from './ui'

const tone = (v) => {
  const c = signClass(v)
  return c === 'text-pos' ? 'v7-pos' : c === 'text-neg' ? 'v7-neg' : 'v7-flat'
}

/**
 * The answer, written out: what the strategy returned next to simply holding
 * the symbol, after which costs, on which data, and how much of it sits on
 * bars that are not there. Replaces a strip of six equal-weight tiles.
 */
export default function Verdict() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const runCount = useBacktest((s) => s.runCount)
  const running = useBacktest((s) => s.running)
  const loading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)
  const autoRun = useBacktest((s) => s.autoRun)
  const researchSymbol = useBacktest((s) => s.researchSymbol)
  const liveSymbol = useBacktest((s) => s.liveSymbol)
  const plane = useBacktest((s) => s.plane)
  const gaps = useMemo(() => scanGaps(dataset), [dataset])

  if (!result) {
    const symbol = dataset?.symbol || (plane === 'live' ? liveSymbol : researchSymbol)
    return (
      <section className="v7-verdict" aria-label="Result">
        <p className="v7-verdict-wait" role="status">
          {datasetError
            ? 'No data loaded, so there is no result.'
            : loading
              ? `Loading ${symbol} bars…`
              : running
                ? `Running ${getStrategy(strategyId).label}…`
                : autoRun
                  ? 'The result appears here once the strategy runs.'
                  : 'Press Run (R) to see the result.'}
        </p>
        {dataset && <Coverage gaps={gaps} dataset={dataset} />}
      </section>
    )
  }

  const m = result.metrics
  const cfg = result.config || result.provenance || {}
  const strategy = getStrategy(cfg.strategyId || strategyId)
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const diff = m.totalReturn - bhReturn
  const oos = strategy.id === 'mlSignal' && dataset?.ml
  const ci = m.inference?.ci
  const hasCi = ci && Number.isFinite(ci[0]) && Number.isFinite(ci[1])
  const propStats = result.prop ? result.prop.bootstrap || result.prop.historical : null

  return (
    <section className={`v7-verdict${running ? ' is-stale' : ''}`} aria-labelledby="v7-verdict-title" aria-busy={running}>
      <h2 id="v7-verdict-title" className="v7-eyebrow">
        {strategy.label} on {dataset?.symbol} {dataset?.interval}
        <span className={oos ? 'v7-tag v7-tag-oos' : 'v7-tag'}>{oos ? 'out-of-sample' : 'in-sample'}</span>
        <span className={`v7-eyebrow-run${runCount > 300 ? ' is-high' : runCount > 80 ? ' is-mid' : ''}`}
          title={runCount > 80 ? 'At this count the best-looking result is more likely the maximum of many draws than an edge. Test it on data you have not touched.' : undefined}>
          simulation {runCount.toLocaleString()} this session
          {runCount > 80 ? ' — at this count, a good result is more likely luck than edge' : ''}
          {running ? ' · re-running…' : ''}
        </span>
      </h2>

      <dl className="v7-figures">
        <Fig lead label="Strategy return" value={minus(fmtPct(m.totalReturn))} cls={tone(m.totalReturn)} />
        <Fig label={`${dataset?.symbol} buy & hold`} value={minus(fmtPct(bhReturn))} cls="v7-cyan" title="Holding the same symbol over the same bars, no costs" />
        <Fig label="Difference" value={Number.isFinite(diff) ? `${minus(fmtSigned(diff * 100))} pp` : '—'} cls={tone(diff)} title="Strategy return minus buy & hold, in percentage points" />
        <Fig
          label="Sharpe"
          value={minus(fmtSigned(m.sharpe))}
          cls={tone(m.sharpe)}
          sub={hasCi ? `95% CI ${minus(fmtSigned(ci[0], 1))} to ${minus(fmtSigned(ci[1], 1))}` : null}
          title="Annualised from per-bar returns. The interval is adjusted for skew and fat tails."
        />
        <Fig label="Max drawdown" value={m.maxDd > 0 ? `−${(m.maxDd * 100).toFixed(1)}%` : '0.0%'} cls={m.maxDd > 0 ? 'v7-neg' : 'v7-flat'} sub={`${m.maxDdDuration.toLocaleString()} bars under water`} />
        <Fig label="Trades" value={m.nTrades.toLocaleString()} sub={m.nTrades ? `${fmtPctAbs(m.hitRate)} winners` : 'never entered'} />
        {propStats && (
          <Fig
            label="EV per account"
            value={minus(fmtMoneySigned(propStats.ev))}
            cls={tone(propStats.ev)}
            sub={`pass ${fmtPctAbs(propStats.passRate)} · ${result.prop.plan.planLabel} ${result.prop.plan.sizeLabel}`}
          />
        )}
      </dl>

      <p className="v7-conditions">
        {costSentence(cfg)} {exitSentence(cfg.risk)} {sampleSentence(dataset, oos)}
      </p>

      <Coverage gaps={gaps} dataset={dataset} trades={result.trades} />

    </section>
  )
}

function Fig({ label, value, cls = '', sub, lead, title }) {
  return (
    <div className={`v7-fig${lead ? ' is-lead' : ''}`} title={title}>
      <dt>{label}</dt>
      <dd className={`v7-fig-value ${cls}`}>{value}</dd>
      {sub && <dd className="v7-fig-sub">{sub}</dd>}
    </div>
  )
}

function costSentence(cfg) {
  const c = cfg.costs || {}
  const inst = c.instrument
  if (inst) {
    return `Net of ${inst.slippageTicks ?? 0} tick${inst.slippageTicks === 1 ? '' : 's'} slippage and $${(inst.commissionPerSide ?? 0).toFixed(2)} commission per contract per side, ${inst.contracts} × ${inst.contract}.`
  }
  return `Net of ${c.slippageBps ?? 0} bp slippage and ${fmtMoney(c.commissionPerTrade ?? 0, 2)} commission on every fill, sized ${c.sizePct ?? 1}× equity from ${fmtMoney(c.initialCapital)}.`
}

function exitSentence(r = {}) {
  const parts = []
  if (r.stopPct) parts.push(`${r.stopPct}% stop`)
  if (r.targetPct) parts.push(`${r.targetPct}% target`)
  if (r.maxBars) parts.push(`${r.maxBars}-bar time exit`)
  const head = parts.length ? `Exits: strategy signal, ${parts.join(', ')}` : 'Exits: strategy signal only'
  const flat = r.flatAtSessionEnd || r.flatByEt ? ', flat at session close' : ', positions may be held overnight'
  return `${head}${flat}; ${r.allowShort === false ? 'long only' : 'longs and shorts'}.`
}

function sampleSentence(ds, oos) {
  const bits = []
  if (oos) bits.push('Model positions are taken only on walk-forward test bars.')
  else bits.push('Scored on the same bars any tuning was done on.')
  if (ds?.example) bits.push('Bundled sample data, not the published research dataset.')
  if (ds?.plane === 'live') bits.push('Live-plane snapshot: reloading later can return different bars.')
  if (ds?.cached) bits.push('Served from the offline cache (up to 24 h old).')
  return bits.join(' ')
}

/** Holes in the data, and how much of this run's P&L was earned across them. */
function Coverage({ gaps, dataset, trades }) {
  const holesOnly = useV7((s) => s.holesOnly)
  const setHolesOnly = useV7((s) => s.setHolesOnly)
  const setTab = useBacktest((s) => s.setTab)
  const exposure = useMemo(() => holeExposure(gaps, trades), [gaps, trades])
  if (!gaps) return null
  if (!gaps.holes && !gaps.shortSessions) {
    return <p className="v7-coverage is-clean">No missing {dataset.interval} bars inside any of the {gaps.sessions} sessions.</p>
  }
  return (
    <p className="v7-coverage">
      <span className="v7-coverage-mark" aria-hidden="true" />
      <strong>Data holes.</strong>{' '}
      {gaps.holeSessions} of {gaps.sessions} sessions are missing {dataset.interval} bars ({gaps.missingBars.toLocaleString()} bars in{' '}
      {gaps.holes} holes){gaps.shortSessions ? `; ${gaps.shortSessions} sessions open late or stop early` : ''}.
      {exposure && trades?.length > 0 && (
        <>
          {' '}
          {exposure.n
            ? <>
                <span className="v7-num">{exposure.n}</span> of {trades.length} trades were held across a hole and account for{' '}
                <span className={`v7-num ${tone(exposure.pnl)}`}>{minus(fmtMoneySigned(exposure.pnl))}</span> of the{' '}
                <span className={`v7-num ${tone(exposure.total)}`}>{minus(fmtMoneySigned(exposure.total))}</span> net; the other {exposure.restN} made{' '}
                <span className={`v7-num ${tone(exposure.rest)}`}>{minus(fmtMoneySigned(exposure.rest))}</span>.{' '}
                <button
                  type="button"
                  className="v7-link v7-link-inline"
                  aria-pressed={holesOnly}
                  onClick={() => {
                    setTab('blotter')
                    setHolesOnly(!holesOnly)
                  }}
                >
                  {holesOnly ? 'Show all trades' : 'List those trades'}
                </button>
              </>
            : 'No trade in this run was held across a hole.'}
        </>
      )}
    </p>
  )
}
