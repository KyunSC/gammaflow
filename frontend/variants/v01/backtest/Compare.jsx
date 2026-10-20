'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, signClass } from '../../../lib/backtest/format'
import useSize from '../../../components/backtest/useSize'
import BenchmarkComparison from '../../../components/backtest/BenchmarkComparison'
import b from './bt.module.css'

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#E8B339', B: '#5aa3b8', C: '#9d90e8' }

/** Copy of components/backtest/ComparePanel.jsx without the panel shell. */
export default function Compare({ headingId }) {
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
    <>
      <div className="flex items-baseline gap-2">
        <h2 id={headingId} className={`${b.h2} flex-1`}>Compare runs</h2>
        <span className="flex gap-1">
          {SLOTS.map((k) => (
            <button key={k} type="button" onClick={() => saveSlot(k)} disabled={!result} className={`btn !px-2 !py-0 font-mono ${slots[k] ? 'btn-active' : ''}`} title={`Pin the current run to slot ${k} (key ${k})`}>
              {k}
            </button>
          ))}
        </span>
      </div>

      {!filled.length ? (
        <p className={b.railIntro}>
          Pin a run to A, B or C (or press the letter) to hold it while you change settings. Curves start at 1, so
          different capital settings still compare.
        </p>
      ) : (
        <>
          <div ref={ref} className="mt-2 h-[72px] w-full">
            {geom && (
              <svg width={width} height={height} role="img" aria-label="Pinned equity curves, each starting at 1">
                {geom.series.map((s) => (
                  <LinePath key={s.key} data={s.pts} x={(d) => geom.x(d.t)} y={(d) => geom.y(d.v)} stroke={SLOT_COLORS[s.key]} strokeWidth={1.3} />
                ))}
                <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#2E343D" strokeDasharray="3,3" />
              </svg>
            )}
          </div>
          <table className="mt-1 w-full text-[12px]">
            <thead className="text-dim">
              <tr>
                <th className="w-5" />
                <th className="py-1 text-left font-normal">Run</th>
                <th className="text-right font-normal">Sharpe</th>
                <th className="text-right font-normal">Return</th>
                <th className="text-right font-normal">Max DD</th>
                <th className="w-5" />
              </tr>
            </thead>
            <tbody className="font-mono">
              {filled.map((k) => {
                const s = slots[k]
                return (
                  <tr key={k} className="border-t border-hair">
                    <td style={{ color: SLOT_COLORS[k] }}>{k}</td>
                    <td className="py-1">
                      <button type="button" onClick={() => loadSlot(k)} className="max-w-[120px] truncate text-left font-sans text-muted hover:text-ink" title="Load these settings">
                        {s.label} · {s.symbol}
                      </button>
                    </td>
                    <td className={`text-right ${signClass(s.metrics.sharpe)}`}>{fmtSigned(s.metrics.sharpe)}</td>
                    <td className={`text-right ${signClass(s.metrics.totalReturn)}`}>{fmtPct(s.metrics.totalReturn, 1)}</td>
                    <td className="text-right text-neg">{fmtPct(-s.metrics.maxDd, 1)}</td>
                    <td className="text-right">
                      <button type="button" onClick={() => clearSlot(k)} className="text-dim hover:text-neg" aria-label={`Clear slot ${k}`} title="Clear slot">×</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}

      <div className="mt-4 -mx-2 border-t border-hair">
        <BenchmarkComparison />
      </div>
    </>
  )
}
