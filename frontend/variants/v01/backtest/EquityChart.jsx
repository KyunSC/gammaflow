'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../../lib/backtest/format'
import useSize from '../../../components/backtest/useSize'
import { findGaps } from './gaps'
import { NotYet } from './Empty'
import b from './bt.module.css'

const MARGIN = { top: 8, right: 50, bottom: 18, left: 4 }
const DD_SHARE = 0.3
const GAP = '#b3a6ff'
const TICK = { fill: '#808891', fontSize: 10, fontFamily: 'var(--v01-mono), var(--font-jetbrains-mono), monospace' }

/**
 * Copy of components/backtest/EquityPanel.jsx without the gradient fills and
 * the line-draw animation (it replayed on every parameter nudge). Added: a rug
 * of data holes under the curve and the selected trade's span.
 */
export default function EquityChart() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const selected = useBacktest((s) => s.selectedTrade)
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)
  const gaps = useMemo(() => findGaps(dataset), [dataset])

  const geom = useMemo(() => {
    if (!result || !dataset || width < 60 || height < 60) return null
    const start = result.windowStart
    const end = result.windowEnd
    const n = end - start + 1
    if (n < 2) return null
    const innerW = Math.max(10, width - MARGIN.left - MARGIN.right)
    const innerH = Math.max(10, height - MARGIN.top - MARGIN.bottom)
    const eqH = innerH * (1 - DD_SHARE) - 8
    const ddH = innerH * DD_SHARE
    const stride = Math.max(1, Math.floor(n / Math.max(80, innerW)))
    const pts = []
    let lo = Infinity
    let hi = -Infinity
    for (let i = start; i <= end; i += stride) {
      const e = result.equity[i]
      const bh = result.buyHold[i]
      lo = Math.min(lo, e, bh)
      hi = Math.max(hi, e, bh)
      pts.push({ i, e, b: bh, dd: result.metrics.ddCurve[i - start] ?? 0 })
    }
    if (pts[pts.length - 1].i !== end) {
      pts.push({ i: end, e: result.equity[end], b: result.buyHold[end], dd: result.metrics.ddCurve[end - start] ?? 0 })
    }
    const x = scaleLinear({ domain: [start, end], range: [0, innerW] })
    const pad = (hi - lo) * 0.06 || 1
    const y = scaleLinear({ domain: [lo - pad, hi + pad], range: [eqH, 0] })
    const yDd = scaleLinear({ domain: [Math.min(-0.0001, -result.metrics.maxDd * 1.05), 0], range: [ddH, 0] })
    const stitched = wf?.stitched ? pts.map((p) => ({ i: p.i, v: wf.stitched[p.i] })).filter((p) => Number.isFinite(p.v)) : null
    const holes = gaps ? gaps.holes.filter((h) => h.idx >= start && h.idx <= end) : []
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, stitched, holes }
  }, [result, dataset, width, height, wf, gaps])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - MARGIN.left
    const idx = Math.round(geom.x.invert(Math.max(0, Math.min(geom.innerW, px))))
    setHover(geom.pts.reduce((a, c) => (Math.abs(c.i - idx) < Math.abs(a.i - idx) ? c : a), geom.pts[0]))
  }

  return (
    <section className={b.region} aria-label="Equity and drawdown">
      <header className={b.regionHead}>
        <h2 className={b.regionTitle}>Equity and drawdown</h2>
        {result && (
          <span className={b.regionRight}>
            <Legend color="#E8B339" label="strategy" />
            <Legend color="#808891" label={`hold ${dataset?.symbol ?? ''}`} dashed />
            {geom?.stitched && <Legend color="#9d90e8" label="walk-forward OOS" />}
            {geom?.holes.length > 0 && (
              <span className={b.legend}><span style={{ color: GAP }}>|</span> data holes</span>
            )}
          </span>
        )}
      </header>
      <div ref={ref} className={b.regionBody}>
        {!result ? (
          <NotYet what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="cursor-crosshair" role="img"
              aria-label={`Equity from ${fmtMoney(result.equity[result.windowStart])} to ${fmtMoney(result.metrics.finalEquity)}; holding ${dataset.symbol} ends at ${fmtMoney(result.buyHold[result.windowEnd])}; max drawdown ${fmtPct(-result.metrics.maxDd, 1)}`}>
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                {selected && selected.exitIdx >= result.windowStart && (
                  <rect
                    x={geom.x(Math.max(result.windowStart, selected.entryIdx))}
                    width={Math.max(2, geom.x(selected.exitIdx) - geom.x(Math.max(result.windowStart, selected.entryIdx)))}
                    y={0}
                    height={geom.innerH}
                    fill="#E8B339"
                    fillOpacity={0.14}
                  />
                )}
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#2E343D" strokeWidth={1} />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke="#808891" strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && (
                  <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke="#9d90e8" strokeWidth={1.25} />
                )}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke="#E8B339" strokeWidth={1.5} />
                <AxisLeft scale={geom.y} left={geom.innerW} numTicks={3} hideAxisLine hideTicks
                  tickLabelProps={() => ({ ...TICK, dx: 6, textAnchor: 'start' })}
                  tickFormat={(v) => `${(v / 1000).toFixed(0)}k`} />

                {/* Rug: one tick per hole, between the equity and drawdown panes. */}
                {geom.holes.map((h) => (
                  <line key={h.idx} x1={geom.x(h.idx)} x2={geom.x(h.idx)} y1={geom.eqH + 1} y2={geom.eqH + 7} stroke={GAP} strokeWidth={1} />
                ))}

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} yScale={geom.yDd}
                    fill="#ff6b6b" fillOpacity={0.16} stroke="#ff6b6b" strokeWidth={0.75} strokeOpacity={0.7} />
                  <AxisLeft scale={geom.yDd} left={geom.innerW} numTicks={2} hideAxisLine hideTicks
                    tickLabelProps={() => ({ ...TICK, dx: 6, textAnchor: 'start' })}
                    tickFormat={(v) => `${(v * 100).toFixed(0)}%`} />
                </g>

                <AxisBottom top={geom.innerH} scale={geom.x} numTicks={Math.max(2, Math.floor(geom.innerW / 110))}
                  stroke="#22262D" tickStroke="#22262D"
                  tickLabelProps={() => ({ ...TICK, textAnchor: 'middle' })}
                  tickFormat={(v) => fmtDate(dataset.time[Math.round(v)])} />

                {hover && <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#5aa3b8" strokeWidth={1} strokeDasharray="2,3" />}
              </g>
            </svg>
            {hover && (
              <div className="pointer-events-none absolute top-1 left-1 border border-hair-bright bg-panel-2 px-2 py-1 font-mono text-[11px]">
                <div className="text-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div className="text-amber">strategy {fmtMoney(hover.e)}</div>
                <div className="text-muted">hold {fmtMoney(hover.b)} · drawdown <span className="text-neg">{fmtPct(hover.dd)}</span></div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

function Legend({ color, label, dashed }) {
  return (
    <span className={b.legend}>
      <svg width="14" height="4" aria-hidden="true">
        <line x1="0" y1="2" x2="14" y2="2" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
      </svg>
      {label}
    </span>
  )
}
