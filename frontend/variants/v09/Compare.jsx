'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, signClass } from '../../lib/backtest/format'
import useSize from '../../components/backtest/useSize'
import BenchmarkComparison from '../../components/backtest/BenchmarkComparison'

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#e8b339', B: '#5aa3b8', C: '#9a8cf0' }

/** Pinned runs side by side (same store slots as the original ComparePanel),
 *  plus the cross-asset buy & hold benchmark. */
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
    return { series, x: scaleLinear({ domain: [0, 1], range: [0, width - 4] }), y: scaleLinear({ domain: [lo - pad, hi + pad], range: [height - 4, 4] }) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filled.join(''), slots, width, height])

  return (
    <div className="grid h-full min-h-0 grid-cols-1 overflow-y-auto md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="min-w-0 px-4 py-2.5" aria-labelledby="v9-h-slots">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 id="v9-h-slots" className="v9-h">Pinned runs</h2>
          <span className="flex-1" />
          {SLOTS.map((k) => (
            <button key={k} onClick={() => saveSlot(k)} disabled={!result} className="v9-btn" title={`Pin the current run to slot ${k} (key ${k.toLowerCase()})`}>
              Pin to {k}
            </button>
          ))}
        </div>
        {!filled.length ? (
          <p className="text-[12px] leading-snug text-dim">
            Pin a run to A, B or C (keys a, b, c) to hold it while you change parameters. Curves are rebased to their own start, so
            different capital settings still compare.
          </p>
        ) : (
          <>
            <div ref={ref} className="h-[80px] w-full">
              {geom && (
                <svg width={width} height={height} role="img" aria-label="Pinned equity curves, rebased to 1">
                  <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#2c3138" strokeDasharray="3,3" />
                  {geom.series.map((s) => (
                    <LinePath key={s.key} data={s.pts} x={(d) => geom.x(d.t)} y={(d) => geom.y(d.v)} stroke={SLOT_COLORS[s.key]} strokeWidth={1.3} />
                  ))}
                </svg>
              )}
            </div>
            <table className="mt-2 w-full text-[12px]">
              <thead className="text-[11.5px] text-dim">
                <tr className="border-b border-hair">
                  <th scope="col" className="w-6 py-1 text-left font-normal">Slot</th>
                  <th scope="col" className="py-1 text-left font-normal">Strategy</th>
                  <th scope="col" className="py-1 text-right font-normal">Sharpe</th>
                  <th scope="col" className="py-1 text-right font-normal">Return</th>
                  <th scope="col" className="py-1 text-right font-normal">Max DD</th>
                  <th scope="col" className="w-12" />
                </tr>
              </thead>
              <tbody>
                {filled.map((k) => {
                  const s = slots[k]
                  return (
                    <tr key={k} className="border-b border-hair">
                      <td className="py-1 font-semibold" style={{ color: SLOT_COLORS[k] }}>{k}</td>
                      <td className="max-w-0 truncate py-1">
                        <button onClick={() => loadSlot(k)} className="v9-link" title="Load these settings">{s.label}</button>
                        <span className="text-dim"> · {s.symbol}</span>
                      </td>
                      <td className={`v9-num py-1 text-right ${signClass(s.metrics.sharpe)}`}>{fmtSigned(s.metrics.sharpe)}</td>
                      <td className={`v9-num py-1 text-right ${signClass(s.metrics.totalReturn)}`}>{fmtPct(s.metrics.totalReturn, 1)}</td>
                      <td className="v9-num py-1 text-right text-neg">{fmtPctAbs(s.metrics.maxDd)}</td>
                      <td className="py-1 text-right">
                        <button onClick={() => clearSlot(k)} className="text-[11.5px] text-dim hover:text-neg" aria-label={`Clear slot ${k}`}>Clear</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </>
        )}
      </section>
      <section className="min-w-0 border-t border-hair md:border-t-0 md:border-l" aria-label="Buy and hold benchmark">
        <BenchmarkComparison />
      </section>
    </div>
  )
}
