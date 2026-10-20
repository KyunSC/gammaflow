'use client'

import { useMemo } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { sweepableParams } from '../../../lib/backtest/strategies'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney } from '../../../lib/backtest/format'
import { findGaps, tradeGapSummary } from './gaps'
import Compare from './Compare'
import b from './bt.module.css'

const STATUS = {
  against: { cls: b.checkAgainst, label: 'Evidence against' },
  open: { cls: b.checkOpen, label: 'Not ruled out' },
  caveat: { cls: b.checkCaveat, label: 'Caveat' },
  notrun: { cls: b.checkNotRun, label: 'Not run' },
  none: { cls: b.checkNotRun, label: '' },
}

/**
 * The checks that can rule an edge out, each with its own number or a button
 * that runs it. The strongest thing a check says is "not ruled out" — there is
 * deliberately no "pass". This column replaces the advanced-only "honesty"
 * footnote and puts the run tally, in-sample label, sample-data label and
 * data-gap share where they are read in both views.
 */
export default function Evidence() {
  const advanced = useBacktest((s) => s.advanced)
  const checks = useChecks()

  return (
    <div className={b.rail}>
      <h2 className={b.h2}>Evidence</h2>
      <p className={b.railIntro}>
        Each check can rule an edge out. None can prove one: if every check holds up, this data simply failed to
        rule it out.
      </p>
      <ul className={b.checks}>
        {checks.map((c) => (
          <li key={c.id} className={`${b.check} ${STATUS[c.status].cls}`}>
            <div className={b.checkHead}>
              <span className={b.checkTitle}>{c.title}</span>
              <span className={b.checkStatus}>{c.statusLabel ?? STATUS[c.status].label}</span>
            </div>
            <p className={b.checkBody}>{c.body}</p>
            {c.action && <div className={b.checkAction}>{c.action}</div>}
          </li>
        ))}
      </ul>

      <details className={b.section} open={advanced || undefined}>
        <summary className={b.sectionSummary}>
          <h2 className={b.h2}>All metrics</h2>
        </summary>
        <AllMetrics />
      </details>

      {advanced && (
        <section className={b.section} aria-labelledby="v01-compare">
          <Compare headingId="v01-compare" />
        </section>
      )}
    </div>
  )
}

function useChecks() {
  const st = useBacktest()
  const { result, dataset, costCurve, sweep, wf, mc, runCount, costs, prop, strategyId, datasetLoading } = st
  const gaps = useMemo(() => findGaps(dataset), [dataset])
  const gapSum = useMemo(() => tradeGapSummary(result, gaps), [result, gaps])

  const open = (tab, fn) => () => {
    st.setAdvanced(true)
    st.setTab(tab)
    fn?.()
  }
  const runBtn = (label, key, tab, fn, disabled) => (
    <button type="button" className="btn !py-0.5" onClick={open(tab, fn)} disabled={disabled || !dataset || datasetLoading}>
      {label}{key && <span className="ml-1.5 font-mono text-[11px] text-dim">{key}</span>}
    </button>
  )

  const symbol = dataset?.symbol ?? '—'
  const out = []

  // 1 — beats holding
  if (!result) {
    out.push({ id: 'hold', title: `Beats holding ${symbol}`, status: 'notrun', body: 'Needs a run.' })
  } else {
    const bhR = result.buyHold[result.windowEnd] / result.buyHold[result.windowStart] - 1
    const d = result.metrics.totalReturn - bhR
    out.push({
      id: 'hold',
      title: `Beats holding ${symbol}`,
      status: d > 0 ? 'open' : 'against',
      body: (
        <>
          <b>{fmtPct(result.metrics.totalReturn)}</b> after costs against <b>{fmtPct(bhR)}</b> for holding over the same bars
          ({d > 0 ? 'ahead' : 'behind'} by <b>{Math.abs(d * 100).toFixed(2)} pp</b>).
        </>
      ),
    })
  }

  // 2 — survives costs
  const unit = prop.enabled ? 'tk' : 'bp'
  const slip = prop.enabled ? prop.slippageTicks : costs.slippageBps
  if (!costCurve?.length) {
    out.push({
      id: 'costs', title: 'Survives realistic costs', status: 'notrun',
      body: `Re-runs the strategy across a slippage ladder to find where Sharpe crosses zero. You currently assume ${slip} ${unit}.`,
      action: runBtn('Run cost ladder', null, 'costs', st.runCostCurve, !result),
    })
  } else {
    const be = breakEven(costCurve)
    const last = costCurve[costCurve.length - 1].slippageBps
    out.push({
      id: 'costs', title: 'Survives realistic costs',
      status: be === null || be < slip ? 'against' : 'open',
      body: be === null
        ? <>Sharpe is <b>{fmtSigned(costCurve[0].sharpe)}</b> even at 0 {unit}: there is no edge for costs to erode.</>
        : be === Infinity
          ? <>Sharpe stays above zero across the whole ladder (to <b>{last} {unit}</b>); you assume <b>{slip} {unit}</b>.</>
          : <>Break-even slippage is <b>{be.toFixed(2)} {unit}</b>; you assume <b>{slip} {unit}</b>.</>,
    })
  }

  // 3 — out of sample
  if (wf.running) {
    out.push({ id: 'wf', title: 'Holds out of sample', status: 'notrun', statusLabel: 'Running', body: `Fold ${Math.round(wf.progress * 5)} of 5…` })
  } else if (!wf.data) {
    out.push({
      id: 'wf', title: 'Holds out of sample', status: 'notrun',
      body: wf.error || 'Fits the parameters on each fold’s history and trades them on the next fold — the only number here not chosen with hindsight.',
      action: runBtn('Run walk-forward', 'W', 'wf', st.runWalkForward),
    })
  } else {
    const d = wf.data
    const bad = d.avgOosSharpe <= 0 || d.positiveFolds <= d.folds.length / 2
    out.push({
      id: 'wf', title: 'Holds out of sample', status: bad ? 'against' : 'open',
      body: <>Out-of-sample Sharpe averaged <b>{fmtSigned(d.avgOosSharpe)}</b> ({d.positiveFolds} of {d.folds.length} folds positive) against <b>{fmtSigned(d.avgIsSharpe)}</b> in-sample.</>,
    })
  }

  // 4 — parameter luck
  if (!sweepableParams(strategyId).length) {
    out.push({ id: 'sweep', title: 'Not a lucky parameter pick', status: 'none', statusLabel: 'n/a', body: 'This strategy has no numeric parameters to sweep.' })
  } else if (sweep.running) {
    out.push({ id: 'sweep', title: 'Not a lucky parameter pick', status: 'notrun', statusLabel: 'Running', body: `${(sweep.progress * 100).toFixed(0)}% of ${sweep.steps * sweep.steps} combinations…` })
  } else if (!sweep.data) {
    out.push({
      id: 'sweep', title: 'Not a lucky parameter pick', status: 'notrun',
      body: sweep.error || `Runs ${sweep.steps * sweep.steps} combinations of two parameters. The median, not the best cell, is the honest estimate.`,
      action: runBtn('Run sweep', 'S', 'sweep', st.runSweep),
    })
  } else {
    const d = sweep.data
    out.push({
      id: 'sweep', title: 'Not a lucky parameter pick', status: d.median > 0 ? 'open' : 'against',
      body: <>Median Sharpe <b>{fmtSigned(d.median)}</b> over {d.trials} combinations; the best, <b>{fmtSigned(d.best?.sharpe)}</b>, is the maximum of {d.trials} draws.</>,
    })
  }

  // 5 — ordering luck
  if (mc.running) {
    out.push({ id: 'mc', title: 'Not a lucky trade order', status: 'notrun', statusLabel: 'Running', body: 'Resampling…' })
  } else if (!mc.data) {
    out.push({
      id: 'mc', title: 'Not a lucky trade order', status: 'notrun',
      body: mc.error || `Resamples the realised trades in blocks of ${mc.blockSize}, ${mc.paths.toLocaleString()} times, to see how much of the curve was ordering luck.`,
      action: runBtn('Run Monte Carlo', 'M', 'mc', st.runMonteCarlo, !result?.trades?.length),
    })
  } else {
    const d = mc.data
    out.push({
      id: 'mc', title: 'Not a lucky trade order', status: d.finalP50 > 1 ? 'open' : 'against',
      body: <>Median resampled path ends <b>{fmtPct(d.finalP50 - 1)}</b> (5th–95th: {fmtPct(d.finalP05 - 1)} to {fmtPct(d.finalP95 - 1)}); <b>{fmtPctAbs(d.probLoss)}</b> of {d.paths.toLocaleString()} paths lose money.</>,
    })
  }

  // 6 — data coverage
  if (dataset && gaps) {
    const parts = []
    if (gaps.holes.length) {
      parts.push(<span key="h"><b>{gaps.missingBars.toLocaleString()}</b> bars are missing inside <b>{gaps.sessionsHit}</b> of {gaps.sessions} sessions. </span>)
      if (gapSum?.n) {
        parts.push(
          <span key="t">
            <b>{gapSum.n}</b> of {gapSum.total} trades were held across a hole; they carry <b>{(gapSum.share * 100).toFixed(0)}%</b> of gross trade P/L
            (net {fmtMoney(gapSum.netHit)}). Stops and exits could not fire inside the holes.{' '}
          </span>,
        )
      } else if (result) {
        parts.push(<span key="t">No trade was held across one. </span>)
      }
    } else {
      parts.push(<span key="h">No missing bars inside sessions. </span>)
    }
    if (dataset.example) parts.push(<span key="s">This is the bundled sample, not a published research dataset.</span>)
    if (dataset.plane === 'live') parts.push(<span key="l">Live bars are an exploratory snapshot; a shared link reloads current history.</span>)
    out.push({
      id: 'data', title: 'Data coverage',
      status: gapSum?.n || dataset.example || dataset.plane === 'live' ? 'caveat' : gaps.holes.length ? 'caveat' : 'open',
      statusLabel: gapSum?.n || gaps.holes.length || dataset.example ? 'Caveat' : 'Complete',
      body: parts,
    })
  }

  // 7 — how much searching
  out.push({
    id: 'runs', title: 'How much you have searched',
    status: runCount > 80 ? 'caveat' : 'none',
    statusLabel: `${runCount.toLocaleString()} run${runCount === 1 ? '' : 's'}`,
    body: runCount > 300
      ? 'Past 300 simulations on one dataset, a good Sharpe is far more likely to be the best of many draws than an edge. Test it on data you have not touched.'
      : runCount > 80
        ? 'At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'
        : 'Every run, sweep cell and walk-forward trial since the page loaded counts. The more you try, the less any one result means.',
  })

  return out
}

function breakEven(data) {
  if (data[0].sharpe <= 0) return null
  for (let i = 1; i < data.length; i++) {
    if (data[i - 1].sharpe > 0 && data[i].sharpe <= 0) {
      const a = data[i - 1]
      const c = data[i]
      const t = a.sharpe / (a.sharpe - c.sharpe)
      return a.slippageBps + t * (c.slippageBps - a.slippageBps)
    }
  }
  return Infinity
}

function AllMetrics() {
  const result = useBacktest((s) => s.result)
  if (!result) return <p className={b.railIntro}>Shown after the first run.</p>
  const m = result.metrics
  const bhR = result.buyHold[result.windowEnd] / result.buyHold[result.windowStart] - 1
  const rows = [
    ['Total return', fmtPct(m.totalReturn)],
    ['Buy and hold', fmtPct(bhR)],
    ['CAGR', fmtPct(m.cagr)],
    ['Final equity', fmtMoney(m.finalEquity)],
    ['Sharpe', fmtSigned(m.sharpe)],
    ['Sortino', fmtSigned(m.sortino)],
    ['Calmar', fmtRatio(m.calmar)],
    ['Annualised volatility', fmtPctAbs(m.volAnn)],
    ['Max drawdown', fmtPct(-m.maxDd, 1)],
    ['Longest drawdown', `${m.maxDdDuration} bars`],
    ['Profit factor', fmtRatio(m.profitFactor)],
    ['Win rate', fmtPctAbs(m.hitRate)],
    ['Expectancy per trade', fmtMoney(m.expectancy, 2)],
    ['Average win / loss', `${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`],
    ['Exposure', fmtPctAbs(m.exposure)],
    ['Turnover per year', m.turnover.toFixed(0)],
    ['Average bars held', m.avgBarsHeld.toFixed(1)],
    ['Trades', m.nTrades.toLocaleString()],
  ]
  return (
    <dl className={b.metrics}>
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}
