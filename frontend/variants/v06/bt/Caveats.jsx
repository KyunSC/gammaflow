'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtMoneySigned, fmtPctAbs, signClass } from '../../../lib/backtest/format'
import { gapExposure } from '../gaps'
import { useGaps, useV6 } from './ui'

/**
 * Everything that qualifies the headline numbers, in one list beside them.
 * Each line is a fact about this run (where the bars came from, how many runs
 * this session, which costs are in, where the data has holes), not advice.
 * The left rule carries the severity: amber to read, red when the caveat can
 * change the conclusion.
 */
export default function Caveats() {
  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const strategyId = useBacktest((s) => s.strategyId)
  const runCount = useBacktest((s) => s.runCount)
  const sweep = useBacktest((s) => s.sweep.data)
  const wf = useBacktest((s) => s.wf.data)
  const costs = useBacktest((s) => s.costs)
  const prop = useBacktest((s) => s.prop)
  const advanced = useBacktest((s) => s.advanced)
  const gaps = useGaps()
  const gapOnly = useV6((s) => s.gapOnly)
  const setGapOnly = useV6((s) => s.setGapOnly)

  if (!dataset) return null

  const items = []

  // 1. Where the bars came from.
  if (dataset.plane === 'research' && dataset.example) {
    items.push({
      key: 'source',
      tone: 'warn',
      title: 'Bundled sample',
      body: `${dataset.symbol} ${dataset.interval} file shipped with the app${dataset.generatedAt ? `, generated ${String(dataset.generatedAt).slice(0, 10)}` : ''}; not the published research dataset.`,
    })
  } else if (dataset.plane === 'live') {
    items.push({
      key: 'source',
      tone: 'info',
      title: 'Live prices',
      body: 'Stored OHLCV only, with no historical GEX. A shared link reloads whatever history exists then, so results can drift.',
    })
  } else {
    items.push({
      key: 'source',
      tone: 'info',
      title: 'Published history',
      body: `${dataset.symbol} ${dataset.interval}${dataset.version ? `, version ${String(dataset.version).slice(0, 8)}` : ''}${dataset.cached ? ', from the offline cache (up to 24 h old)' : ''}.`,
    })
  }

  // 2. In-sample or out-of-sample.
  const isOos = strategyId === 'mlSignal' && dataset.ml
  items.push(
    isOos
      ? { key: 'scope', tone: 'info', title: 'Out-of-sample', body: 'Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.' }
      : {
          key: 'scope',
          tone: 'warn',
          title: 'In-sample',
          body: wf
            ? 'Parameters are scored on the bars they were tuned on. The walk-forward out-of-sample line is on the equity chart.'
            : 'Parameters are scored on the bars they were tuned on. Walk-forward (W) scores them on bars they never saw.',
        },
  )

  // 3. Holes in the data.
  if (gaps) {
    const exp = result ? gapExposure(gaps, result.trades) : null
    if (gaps.holes.length) {
      const share = exp?.share ?? 0
      items.push({
        key: 'gaps',
        tone: share >= 0.2 ? 'bad' : 'warn',
        title: 'Data gaps',
        body: (
          <>
            <span className="num">{gaps.holes.length}</span> holes (<span className="num">{gaps.missingBars.toLocaleString()}</span> missing bars) inside{' '}
            <span className="num">{gaps.holeSessions}</span> of <span className="num">{gaps.sessions}</span> sessions
            {gaps.thinSessions.length > 0 && (
              <>
                ; <span className="num">{gaps.thinSessions.length}</span> sessions have under half the usual <span className="num">{gaps.usualBars}</span> bars
              </>
            )}
            . The chart closes them up, so they are drawn as grey lines.
            {exp && exp.n > 0 && (
              <>
                {' '}
                <span className="num">{exp.n}</span> of <span className="num">{result.trades.length}</span> trades were held across a hole and carry{' '}
                <span className="num v6-ink">{fmtPctAbs(share, 0)}</span> of gross P&amp;L (net{' '}
                <span className={`num ${signClass(exp.net)}`}>{fmtMoneySigned(exp.net)}</span>).
              </>
            )}
            {exp && exp.n === 0 && ' No trade in this run was held across one.'}
          </>
        ),
        action:
          exp && exp.n > 0 ? (
            <button
              type="button"
              className="v6-link"
              aria-pressed={gapOnly}
              onClick={() => {
                setGapOnly(!gapOnly)
                if (advanced) useBacktest.getState().setTab('blotter')
              }}
            >
              {gapOnly ? 'Show all trades' : 'List those trades'}
            </button>
          ) : null,
      })
    } else {
      items.push({ key: 'gaps', tone: 'info', title: 'No data gaps', body: `No missing bars inside any of the ${gaps.sessions} sessions.` })
    }
  }

  // 4. The data-snooping tally.
  items.push({
    key: 'runs',
    tone: runCount > 300 ? 'bad' : runCount > 80 ? 'warn' : 'info',
    title: `Run ${runCount.toLocaleString()} this session`,
    body:
      runCount > 80
        ? 'Every run, sweep cell and walk-forward trial counts. At this count a good Sharpe is the best of many draws: a hypothesis to test on other data.'
        : 'Every run, sweep cell and walk-forward trial counts toward this tally.',
  })

  // 5. Parameter luck.
  items.push(
    sweep
      ? {
          key: 'sweep',
          tone: 'info',
          title: 'Parameter sweep',
          body: (
            <>
              Best Sharpe <span className={`num ${signClass(sweep.best?.sharpe)}`}>{fmtSigned(sweep.best?.sharpe)}</span>, median{' '}
              <span className={`num ${signClass(sweep.median)}`}>{fmtSigned(sweep.median)}</span> over <span className="num">{sweep.trials}</span> combinations.
              The median is the honest estimate.
            </>
          ),
        }
      : { key: 'sweep', tone: 'info', title: 'No sweep yet', body: 'A sweep (S) shows how much of this Sharpe depends on the exact parameter values.' },
  )

  // 6. What the costs are.
  items.push({
    key: 'costs',
    tone: 'info',
    title: 'Costs included',
    body: prop.enabled
      ? `Per contract: $${prop.commissionPerSide} commission per side and ${prop.slippageTicks} ticks of slippage per fill. Buy & hold pays none.`
      : `${costs.slippageBps} bp slippage and $${costs.commissionPerTrade} commission per trade, sized at ${costs.sizePct}× equity. Buy & hold pays none.`,
  })

  return (
    <ul className="v6-caveats" aria-label="Caveats for this run">
      {items.map((it) => (
        <li key={it.key} data-tone={it.tone}>
          <strong>{it.title}</strong>
          <span className="v6-cav-body">{it.body}</span>
          {it.action && <span className="v6-cav-action">{it.action}</span>}
        </li>
      ))}
    </ul>
  )
}
