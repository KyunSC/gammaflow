'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, signClass } from '../../lib/backtest/format'
import useSize from '../../components/backtest/useSize'
import BenchmarkComparison from '../../components/backtest/BenchmarkComparison'
import s from './bt.module.css'

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#e8b339', B: '#5a9fb3', C: '#8b7ce0' }

/**
 * A/B/C pinned runs plus the external buy & hold benchmark. Same behaviour
 * as ComparePanel; the sparkline container is always mounted here so it is
 * measured even when the first slot is pinned after load.
 */
export default function Compare() {
  const slots = useBacktest((st) => st.slots)
  const saveSlot = useBacktest((st) => st.saveSlot)
  const clearSlot = useBacktest((st) => st.clearSlot)
  const loadSlot = useBacktest((st) => st.loadSlot)
  const result = useBacktest((st) => st.result)
  const [ref, { width, height }] = useSize()

  const filled = SLOTS.filter((k) => slots[k])

  const geom = useMemo(() => {
    if (!filled.length || width < 60 || height < 30) return null
    let lo = Infinity
    let hi = -Infinity
    const series = filled.map((k) => {
      const sl = slots[k]
      const start = sl.windowStart
      const n = sl.equity.length
      const stride = Math.max(1, Math.floor((n - start) / Math.max(60, width)))
      const pts = []
      for (let i = start; i < n; i += stride) {
        const v = sl.equity[i] / sl.equity[start]
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
  }, [filled.join(''), slots, width, height])

  return (
    <div className={s.pane}>
      <div className={s.paneHead}>
        <span className={s.paneTitle}>Compare</span>
        <span className="ml-auto flex items-center gap-1">
          pin to
          {SLOTS.map((k) => (
            <button key={k} onClick={() => saveSlot(k)} disabled={!result} className={`kbd ${slots[k] ? '!text-amber' : ''}`} title={`Pin the current run to slot ${k} (key ${k})`}>
              {k}
            </button>
          ))}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!filled.length && (
          <p className="px-4 pb-2 text-[11.5px] leading-snug text-dim">
            Pin a run to A, B or C (or press the letter) to keep it while you change parameters. Curves are rebased to their own start.
          </p>
        )}
        <div ref={ref} className={filled.length ? 'mx-4 h-[64px]' : 'h-0'}>
          {geom && (
            <svg width={width} height={height} role="img" aria-label="Pinned equity curves, rebased to 1">
              <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#2d323a" strokeDasharray="3,3" />
              {geom.series.map((sr) => (
                <LinePath key={sr.key} data={sr.pts} x={(d) => geom.x(d.t)} y={(d) => geom.y(d.v)} stroke={SLOT_COLORS[sr.key]} strokeWidth={1.25} />
              ))}
            </svg>
          )}
        </div>
        {filled.length > 0 && (
          <table className="mt-1 w-full font-mono text-[11px]">
            <thead>
              <tr className="text-dim">
                <th className="w-6 pl-4 text-left font-normal" />
                <th className="text-left font-sans font-normal">Run</th>
                <th className="text-right font-sans font-normal">Sharpe</th>
                <th className="text-right font-sans font-normal">Return</th>
                <th className="pr-4 text-right font-sans font-normal">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {filled.map((k) => {
                const sl = slots[k]
                return (
                  <tr key={k} className="hover:bg-panel-2">
                    <td className="pl-4">
                      <button onClick={() => clearSlot(k)} style={{ color: SLOT_COLORS[k] }} title={`Clear slot ${k}`} aria-label={`Clear slot ${k}`}>
                        {k}
                      </button>
                    </td>
                    <td className="max-w-0 truncate">
                      <button onClick={() => loadSlot(k)} className="max-w-full truncate text-left text-muted hover:text-ink" title="Load these settings">
                        {sl.label} <span className="text-dim">· {sl.symbol}</span>
                      </button>
                    </td>
                    <td className={`text-right ${signClass(sl.metrics.sharpe)}`}>{fmtSigned(sl.metrics.sharpe)}</td>
                    <td className={`text-right ${signClass(sl.metrics.totalReturn)}`}>{fmtPct(sl.metrics.totalReturn, 1)}</td>
                    <td className="pr-4 text-right text-neg">−{fmtPctAbs(sl.metrics.maxDd)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <div className="mt-2 border-t border-hair px-2">
          <BenchmarkComparison />
        </div>
      </div>
    </div>
  )
}
