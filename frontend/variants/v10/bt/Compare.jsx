'use client'

import { useMemo } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath } from '@visx/shape'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPct, fmtPctAbs, signClass } from '../../../lib/backtest/format'
import Section from './Section'
import useSize from '../../../components/backtest/useSize'
import BenchmarkComparison from '../../../components/backtest/BenchmarkComparison'

const SLOTS = ['A', 'B', 'C']
const SLOT_COLORS = { A: '#E8B339', B: '#5AA3B8', C: '#9385E0' }

/**
 * Three pinned runs, side by side.
 *
 * Comparison is the only way to read a Sharpe: 1.4 means nothing alone, and
 * means quite a lot next to the same strategy without the GEX regime gate.
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
    let maxLen = 0
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
      maxLen = Math.max(maxLen, pts.length)
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
    <Section
      title="Compare"
      meta="pinned runs A, B, C"
      right={
        <span className="flex gap-1">
          {SLOTS.map((k) => (
            <button
              type="button"
              key={k}
              aria-label={`Pin the current run to slot ${k}`}
              onClick={() => saveSlot(k)}
              disabled={!result}
              className={`kbd ${slots[k] ? 'text-amber' : ''}`}
              title={`Pin the current run to slot ${k}`}
            >
              {k}
            </button>
          ))}
        </span>
      }
    >
      <BenchmarkComparison />
      {!filled.length ? (
        <p className="px-3 py-2 text-[11px] leading-snug text-dim">
          Pin a run to A, B or C to hold it while you change parameters. Curves are normalised to their
          own start, so different capital settings still compare.
        </p>
      ) : (
        <>
          <div ref={ref} className="h-[70px] w-full px-0.5">
            {geom && (
              <svg width={width} height={height}>
                {geom.series.map((s) => (
                  <LinePath
                    key={s.key}
                    data={s.pts}
                    x={(d) => geom.x(d.t)}
                    y={(d) => geom.y(d.v)}
                    stroke={SLOT_COLORS[s.key]}
                    strokeWidth={1.2}
                  />
                ))}
                <line x1={0} x2={width} y1={geom.y(1)} y2={geom.y(1)} stroke="#2E343D" strokeDasharray="3,3" />
              </svg>
            )}
          </div>

          <div className="hair-t">
            <div className="flex px-3 py-1 text-[11px] text-dim">
              <span className="w-5" />
              <span className="flex-1">Strategy (click to load)</span>
              <span className="w-12 text-right">Sharpe</span>
              <span className="w-12 text-right">Return</span>
              <span className="w-12 text-right">Max DD</span>
            </div>
            {filled.map((k) => {
              const s = slots[k]
              return (
                <div key={k} className="flex items-center px-3 py-1 font-mono text-[11px] hover:bg-panel-2">
                  <button
                    type="button"
                    aria-label={`Clear slot ${k}`}
                    onClick={() => clearSlot(k)}
                    className="w-5 text-left"
                    style={{ color: SLOT_COLORS[k] }}
                    title="Clear slot"
                  >
                    {k}
                  </button>
                  <button type="button" onClick={() => loadSlot(k)} className="flex-1 truncate text-left text-muted hover:text-ink" title="Load these parameters">
                    {s.label} <span className="text-dim">· {s.symbol}</span>
                  </button>
                  <span className={`w-12 text-right ${signClass(s.metrics.sharpe)}`}>{fmtSigned(s.metrics.sharpe)}</span>
                  <span className={`w-12 text-right ${signClass(s.metrics.totalReturn)}`}>{fmtPct(s.metrics.totalReturn, 1)}</span>
                  <span className="w-12 text-right text-neg">{fmtPctAbs(s.metrics.maxDd)}</span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </Section>
  )
}
