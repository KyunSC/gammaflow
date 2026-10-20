'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs } from '../../../lib/backtest/format'
import useSize from '../../../components/backtest/useSize'
import BenchmarkComparison from '../../../components/backtest/BenchmarkComparison'
import { Region } from './ui'

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#E8B339', B: '#5aa3b8', C: '#9a8ce6' }
const tone = (v) => (v > 0 ? 'v3-pos' : v < 0 ? 'v3-neg' : '')

/** A/B/C pinned runs plus the external buy & hold benchmark (shared component). */
export default function Compare() {
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
    <Region
      title="Compare"
      className="v3-fill"
      scroll
      aside={
        <span className="v3-slot-btns">
          <span className="v3-dim">Pin to</span>
          {SLOTS.map((k) => (
            <button
              type="button"
              key={k}
              onClick={() => saveSlot(k)}
              disabled={!result}
              className={`kbd ${slots[k] ? 'is-filled' : ''}`}
              style={slots[k] ? { color: SLOT_COLORS[k], borderColor: SLOT_COLORS[k] } : undefined}
              title={`Pin the current run to slot ${k} (key ${k.toLowerCase()})`}
            >
              {k}
            </button>
          ))}
        </span>
      }
    >
      {!filled.length ? (
        <p className="v3-note v3-pad">
          Pin a run to A, B or C (keys a, b, c) to hold it while you change parameters. Curves are normalised to their own
          start, so different capital settings still compare.
        </p>
      ) : (
        <>
          <div ref={ref} className="v3-compare-chart">
            {geom && (
              <svg width={width} height={height} role="img" aria-label="Pinned equity curves, each starting at 1">
                <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#323841" strokeDasharray="3,3" />
                {geom.series.map((s) => (
                  <LinePath key={s.key} data={s.pts} x={(d) => geom.x(d.t)} y={(d) => geom.y(d.v)} stroke={SLOT_COLORS[s.key]} strokeWidth={1.3} />
                ))}
              </svg>
            )}
          </div>
          <table className="v3-metrics v3-compare-table">
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
                      <button type="button" className="v3-link v3-small" onClick={() => clearSlot(k)} aria-label={`Clear slot ${k}`}>clear</button>
                    </th>
                    <td className="v3-left">
                      <button type="button" className="v3-link" onClick={() => loadSlot(k)} title="Load these settings">
                        {s.label} · {s.symbol}
                      </button>
                    </td>
                    <td className={tone(s.metrics.sharpe)}>{fmtSigned(s.metrics.sharpe)}</td>
                    <td className={tone(s.metrics.totalReturn)}>{fmtPct(s.metrics.totalReturn, 1)}</td>
                    <td className="v3-neg">{fmtPctAbs(s.metrics.maxDd)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}
      <div className="v3-bench">
        <BenchmarkComparison />
      </div>
    </Region>
  )
}
