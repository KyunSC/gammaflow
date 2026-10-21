'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, signClass } from '../../lib/backtest/format'
import useSize from '../../components/backtest/useSize'
import BenchmarkComparison from '../../components/backtest/BenchmarkComparison'
import Block from './Block'

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#E8B339', B: '#4A90A4', C: '#7C6BD6' }

/**
 * Variant 05 copy of components/backtest/ComparePanel.jsx: the same three
 * slots and benchmark block, with pin buttons that say what they do and a
 * slot list that is a plain table.
 */
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
  }, [filled.join(''), slots, width, height]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Block
      title="Compare"
      right={
        <span className="flex items-center gap-1 font-mono text-[11px] text-dim">
          pin to
          {SLOTS.map((k) => (
            <button
              key={k}
              onClick={() => saveSlot(k)}
              disabled={!result}
              className={`kbd ${slots[k] ? '!text-amber' : ''}`}
              title={`Pin the current run to slot ${k} (key ${k.toLowerCase()})`}
              aria-label={`Pin current run to slot ${k}`}
            >
              {k}
            </button>
          ))}
        </span>
      }
      className="h-full"
      bodyClassName="overflow-auto"
    >
      <BenchmarkComparison />
      {!filled.length ? (
        <p className="px-3 py-2 text-[11.5px] leading-snug text-dim">
          Pin a run to A, B or C to hold it while you change parameters. Curves are normalised to their
          own start, so different capital settings still compare.
        </p>
      ) : (
        <>
          <div ref={ref} className="h-[70px] w-full px-0.5">
            {geom && (
              <svg width={width} height={height} role="img" aria-label="Pinned equity curves, normalised to 1">
                {geom.series.map((s) => (
                  <LinePath key={s.key} data={s.pts} x={(d) => geom.x(d.t)} y={(d) => geom.y(d.v)} stroke={SLOT_COLORS[s.key]} strokeWidth={1.2} />
                ))}
                <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#2E343D" strokeDasharray="3,3" />
              </svg>
            )}
          </div>
          <table className="v05-rule-t w-full font-mono text-[11px]">
            <thead>
              <tr className="v05-colhead">
                <th className="w-6 px-3 py-1 text-left font-normal" />
                <th className="py-1 text-left font-normal">strategy</th>
                <th className="py-1 text-right font-normal">sharpe</th>
                <th className="py-1 text-right font-normal">ret</th>
                <th className="py-1 pr-3 text-right font-normal">dd</th>
              </tr>
            </thead>
            <tbody>
              {filled.map((k) => {
                const s = slots[k]
                return (
                  <tr key={k} className="hover:bg-panel-2">
                    <td className="px-3 py-1">
                      <button onClick={() => clearSlot(k)} style={{ color: SLOT_COLORS[k] }} title={`Clear slot ${k}`} aria-label={`Clear slot ${k}`}>
                        {k}
                      </button>
                    </td>
                    <td className="max-w-0 truncate py-1">
                      <button onClick={() => loadSlot(k)} className="truncate text-left text-muted hover:text-ink" title="Load these settings">
                        {s.label} <span className="text-dim">· {s.symbol}</span>
                      </button>
                    </td>
                    <td className={`py-1 text-right ${signClass(s.metrics.sharpe)}`}>{fmtSigned(s.metrics.sharpe)}</td>
                    <td className={`py-1 text-right ${signClass(s.metrics.totalReturn)}`}>{fmtPct(s.metrics.totalReturn, 1)}</td>
                    <td className="py-1 pr-3 text-right text-neg">−{fmtPctAbs(s.metrics.maxDd)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="px-3 py-1.5 text-[11px] text-dim">Click a slot letter to clear it, a name to load its settings.</p>
        </>
      )}
    </Block>
  )
}
