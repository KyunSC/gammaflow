'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, fmtRatio, fmtMoney, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import BenchmarkComparison from '../../../components/backtest/BenchmarkComparison'
import useSize from '../../../components/backtest/useSize'
import { Heading, NoRunYet, minus } from './ui'

const tone = (v) => {
  const c = signClass(v)
  return c === 'text-pos' ? 'v7-pos' : c === 'text-neg' ? 'v7-neg' : ''
}

/**
 * Research-tools column: every metric as a ruled list, the caveats that go
 * with them, then the A/B/C compare slots and the daily benchmark.
 */
export default function Ledger() {
  return (
    <aside className="v7-ledger" aria-label="Metrics and comparison">
      <Metrics />
      <Caveats />
      <Compare />
    </aside>
  )
}

function Metrics() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)

  if (!result) {
    return (
      <section className="v7-ledger-sec">
        <Heading>All metrics</Heading>
        <NoRunYet what="Metrics" />
      </section>
    )
  }
  const m = result.metrics
  const inf = m.inference || {}
  const bh = result.buyHold
  const bhReturn = bh ? bh[result.windowEnd] / bh[result.windowStart] - 1 : NaN
  const oos = strategyId === 'mlSignal' && dataset?.ml
  const rows = [
    ['Total return', minus(fmtPct(m.totalReturn)), tone(m.totalReturn)],
    [`${dataset?.symbol} buy & hold`, minus(fmtPct(bhReturn)), 'v7-cyan'],
    ['CAGR', minus(fmtPct(m.cagr)), tone(m.cagr)],
    ['Final equity', fmtMoney(m.finalEquity)],
    null,
    ['Sharpe', minus(fmtSigned(m.sharpe)), tone(m.sharpe), 'Annualised, from per-bar returns'],
    ['Sharpe 95% CI', inf.ci && Number.isFinite(inf.ci[0]) ? `${minus(fmtSigned(inf.ci[0], 1))} to ${minus(fmtSigned(inf.ci[1], 1))}` : '—', '', 'Adjusted for skew and kurtosis of per-bar returns'],
    ['P(Sharpe > 0)', fmtPctAbs(inf.psr), '', 'Probabilistic Sharpe ratio against zero, for this one configuration — it does not account for how many you tried'],
    ['Sortino', minus(fmtSigned(m.sortino)), tone(m.sortino)],
    ['Calmar', minus(fmtRatio(m.calmar))],
    ['Ann. volatility', fmtPctAbs(m.volAnn)],
    ['Max drawdown', m.maxDd > 0 ? `−${(m.maxDd * 100).toFixed(1)}%` : '0.0%', m.maxDd > 0 ? 'v7-neg' : ''],
    ['Longest drawdown', `${m.maxDdDuration.toLocaleString()} bars`],
    null,
    ['Trades', m.nTrades.toLocaleString()],
    ['Win rate', fmtPctAbs(m.hitRate)],
    ['Profit factor', minus(fmtRatio(m.profitFactor)), m.profitFactor >= 1 ? 'v7-pos' : 'v7-neg'],
    ['Expectancy / trade', minus(fmtMoney(m.expectancy, 2)), tone(m.expectancy)],
    ['Avg win / avg loss', `${fmtMoney(m.avgWin, 0)} / ${fmtMoney(m.avgLoss, 0)}`],
    ['Avg bars held', m.avgBarsHeld.toFixed(1)],
    ['Exposure', fmtPctAbs(m.exposure), '', 'Share of bars holding a position'],
    ['Turnover / year', m.turnover.toFixed(0)],
  ]

  return (
    <section className="v7-ledger-sec">
      <Heading right={<span className={oos ? 'v7-tag v7-tag-oos' : 'v7-tag'}>{oos ? 'out-of-sample' : 'in-sample'}</span>}>All metrics</Heading>
      <dl className="v7-rows">
        {rows.map((r, i) =>
          r === null ? (
            <div key={i} className="v7-rows-gap" aria-hidden="true" />
          ) : (
            <div key={r[0]} className="v7-row" title={r[3]}>
              <dt>{r[0]}</dt>
              <dd className={r[2] || ''}>{r[1]}</dd>
            </div>
          ),
        )}
      </dl>
      {result.prop && <PropLine prop={result.prop} />}
    </section>
  )
}

function PropLine({ prop }) {
  const setTab = useBacktest((s) => s.setTab)
  const s = prop.bootstrap || prop.historical
  return (
    <button type="button" className="v7-row v7-row-btn" onClick={() => setTab('prop')} title="Open the prop account tab">
      <dt>EV per account ({prop.plan.planLabel} {prop.plan.sizeLabel})</dt>
      <dd className={tone(s.ev)}>{minus(fmtMoneySigned(s.ev))} · pass {fmtPctAbs(s.passRate)}</dd>
    </button>
  )
}

function Caveats() {
  const sweep = useBacktest((s) => s.sweep.data)
  const runCount = useBacktest((s) => s.runCount)
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  if (!result) return null
  const oos = strategyId === 'mlSignal' && dataset?.ml
  return (
    <section className="v7-ledger-sec v7-caveats">
      <Heading>Before trusting the Sharpe</Heading>
      <ul>
        <li>
          {sweep ? (
            <>
              Sweep: best <span className={`v7-num ${tone(sweep.best?.sharpe)}`}>{minus(fmtSigned(sweep.best?.sharpe))}</span>, median{' '}
              <span className={`v7-num ${tone(sweep.median)}`}>{minus(fmtSigned(sweep.median))}</span> over {sweep.trials} combinations. The median is
              the honest estimate; the best cell is the maximum of {sweep.trials} draws.
            </>
          ) : (
            'No sweep yet — run one (S) to see how much of this number is parameter luck.'
          )}
        </li>
        <li>
          <span className="v7-num">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session.
          {runCount > 80 && ' At this count, treat a single good Sharpe as a hypothesis to test elsewhere.'}
        </li>
        {oos && <li>Model positions are taken only on walk-forward out-of-sample bars; the training stretches produce no trades.</li>}
      </ul>
    </section>
  )
}

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#e8b339', B: '#4a90a4', C: '#8f80e0' }

function Compare() {
  const slots = useBacktest((s) => s.slots)
  const saveSlot = useBacktest((s) => s.saveSlot)
  const clearSlot = useBacktest((s) => s.clearSlot)
  const loadSlot = useBacktest((s) => s.loadSlot)
  const result = useBacktest((s) => s.result)
  const [ref, { width, height }] = useSize()
  const filled = SLOTS.filter((k) => slots[k])

  const geom = useMemo(() => {
    if (!filled.length || width < 60 || height < 40) return null
    let lo = Infinity
    let hi = -Infinity
    const series = filled.map((k) => {
      const s = slots[k]
      const start = s.windowStart
      const n = s.equity.length
      const stride = Math.max(1, Math.floor((n - start) / Math.max(60, width)))
      const pts = []
      for (let i = start; i < n; i += stride) {
        const v = s.equity[i] / s.equity[start]
        lo = Math.min(lo, v)
        hi = Math.max(hi, v)
        pts.push({ t: (i - start) / (n - start), v })
      }
      return { key: k, pts }
    })
    const pad = (hi - lo) * 0.06 || 0.01
    return {
      series,
      x: scaleLinear({ domain: [0, 1], range: [0, width - 4] }),
      y: scaleLinear({ domain: [lo - pad, hi + pad], range: [height - 4, 4] }),
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filled.join(''), slots, width, height])

  return (
    <section className="v7-ledger-sec">
      <Heading
        right={
          <span className="v7-slot-btns" role="group" aria-label="Pin the current run">
            {SLOTS.map((k) => (
              <button key={k} type="button" onClick={() => saveSlot(k)} disabled={!result} className={slots[k] ? 'is-filled' : ''}
                title={`Pin the current run to slot ${k} (key ${k})`} aria-label={`Pin current run to slot ${k}`}>
                {k}
              </button>
            ))}
          </span>
        }
      >
        Compare runs
      </Heading>
      {/* Always mounted so the size observer has an element from the start. */}
      <div ref={ref} className={`v7-compare-chart${filled.length ? '' : ' is-empty'}`}>
        {geom && (
          <svg width={width} height={height} role="img" aria-label="Pinned runs, equity rebased to 1">
            <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#3a3e46" strokeDasharray="3,3" />
            {geom.series.map((s) => (
              <LinePath key={s.key} data={s.pts} x={(d) => geom.x(d.t)} y={(d) => geom.y(d.v)} stroke={SLOT_COLORS[s.key]} strokeWidth={1.3} />
            ))}
          </svg>
        )}
      </div>
      {!filled.length ? (
        <p className="v7-note">
          Pin a run to A, B or C (keys A B C) to hold it while you change parameters. Curves are rebased to their own start, so
          different capital settings still compare.
        </p>
      ) : (
        <>
          <table className="v7-compare-table">
            <thead>
              <tr><th scope="col">Slot</th><th scope="col">Strategy</th><th scope="col">Sharpe</th><th scope="col">Return</th><th scope="col">Max DD</th></tr>
            </thead>
            <tbody>
              {filled.map((k) => {
                const s = slots[k]
                return (
                  <tr key={k}>
                    <th scope="row">
                      <span style={{ color: SLOT_COLORS[k] }}>{k}</span>{' '}
                      <button type="button" className="v7-link v7-x" onClick={() => clearSlot(k)} aria-label={`Clear slot ${k}`} title="Clear slot">×</button>
                    </th>
                    <td>
                      <button type="button" className="v7-link" onClick={() => loadSlot(k)} title="Load these settings">
                        {s.label} <span className="v7-dim">· {s.symbol}</span>
                      </button>
                    </td>
                    <td className={tone(s.metrics.sharpe)}>{minus(fmtSigned(s.metrics.sharpe))}</td>
                    <td className={tone(s.metrics.totalReturn)}>{minus(fmtPct(s.metrics.totalReturn, 1))}</td>
                    <td className="v7-neg">−{fmtPctAbs(s.metrics.maxDd)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}
      <div className="v7-bench">
        <BenchmarkComparison />
      </div>
    </section>
  )
}
