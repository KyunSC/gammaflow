'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../../lib/backtest/format'
import Section, { NotYet, Legend } from './Section'
import useSize from '../../../components/backtest/useSize'
import { gapsFor } from './gaps'

const MARGIN = { top: 8, right: 50, bottom: 18, left: 6 }
const DD_SHARE = 0.28
const AMBER = '#E8B339'
const HOLD = '#5AA3B8'
const VIOLET = '#9385E0'
const AXIS = { fill: '#7A828D', fontSize: 10, fontFamily: 'var(--font-jetbrains-mono), monospace' }

/**
 * Equity against holding the symbol, with the drawdown underneath on its own
 * scale. Flat fills, no draw-in animation: the line is where it is the moment
 * the run finishes. Missing-bar ticks sit on the equity baseline.
 */
export default function EquityChart({ id }) {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)
  const gaps = gapsFor(dataset)

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
      const b = result.buyHold[i]
      lo = Math.min(lo, e, b)
      hi = Math.max(hi, e, b)
      pts.push({ i, e, b, dd: result.metrics.ddCurve[i - start] ?? 0 })
    }
    if (pts[pts.length - 1].i !== end) {
      pts.push({ i: end, e: result.equity[end], b: result.buyHold[end], dd: result.metrics.ddCurve[end - start] ?? 0 })
    }
    const x = scaleLinear({ domain: [start, end], range: [0, innerW] })
    const pad = (hi - lo) * 0.06 || 1
    const y = scaleLinear({ domain: [lo - pad, hi + pad], range: [eqH, 0] })
    const yDd = scaleLinear({ domain: [Math.min(-0.0001, -result.metrics.maxDd * 1.05), 0], range: [ddH, 0] })
    const stitched = wf?.stitched ? pts.map((p) => ({ i: p.i, v: wf.stitched[p.i] })).filter((p) => Number.isFinite(p.v)) : null
    const gapXs = gaps.idx.filter((g) => g > start && g <= end).map((g) => x(g - 0.5))
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, stitched, gapXs }
  }, [result, dataset, width, height, wf, gaps])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - MARGIN.left
    const idx = Math.round(geom.x.invert(Math.max(0, Math.min(geom.innerW, px))))
    setHover(geom.pts.reduce((a, b) => (Math.abs(b.i - idx) < Math.abs(a.i - idx) ? b : a), geom.pts[0]))
  }

  return (
    <Section
      id={id}
      title="Equity and drawdown"
      meta={result ? 'by bar, same axis as price' : null}
      right={
        result ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Legend color={AMBER} label="strategy" />
            <Legend color={HOLD} label={`hold ${dataset?.symbol ?? ''}`} dashed />
            {geom?.stitched && <Legend color={VIOLET} label="walk-forward out-of-sample" />}
            {geom?.gapXs.length > 0 && <Legend color={AMBER} label="missing bars" tick />}
          </span>
        ) : null
      }
      scroll={false}
    >
      <div ref={ref} className="relative h-full w-full">
        {!result ? (
          <NotYet what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="cursor-crosshair" role="img"
              aria-label={`Equity from ${fmtMoney(result.equity[result.windowStart])} to ${fmtMoney(result.metrics.finalEquity)}, maximum drawdown ${(result.metrics.maxDd * 100).toFixed(1)}%`}>
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} yScale={geom.y} fill={AMBER} fillOpacity={0.06} stroke="none" />
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#2E343D" strokeWidth={1} />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke={HOLD} strokeOpacity={0.75} strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke={VIOLET} strokeWidth={1.25} />}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke={AMBER} strokeWidth={1.5} />
                <AxisLeft scale={geom.y} left={geom.innerW} numTicks={3} hideAxisLine hideTicks
                  tickLabelProps={() => ({ ...AXIS, dx: 6, textAnchor: 'start' })} tickFormat={(v) => `${(v / 1000).toFixed(0)}k`} />

                {geom.gapXs.map((gx, k) => (
                  <rect key={k} x={gx - 1} y={geom.eqH + 1} width={2} height={6} fill={AMBER} opacity={0.85} />
                ))}

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <line x1={0} x2={geom.innerW} y1={0} y2={0} stroke="#22262D" />
                  <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} yScale={geom.yDd} fill="#ff6b6b" fillOpacity={0.16} stroke="#ff6b6b" strokeWidth={0.75} strokeOpacity={0.6} />
                  <AxisLeft scale={geom.yDd} left={geom.innerW} numTicks={2} hideAxisLine hideTicks
                    tickLabelProps={() => ({ ...AXIS, dx: 6, textAnchor: 'start' })} tickFormat={(v) => `${(v * 100).toFixed(0)}%`} />
                </g>

                <AxisBottom top={geom.innerH} scale={geom.x} numTicks={Math.max(2, Math.floor(geom.innerW / 110))} stroke="#22262D" tickStroke="#22262D"
                  tickLabelProps={(v, i, all) => ({ ...AXIS, textAnchor: i === 0 ? 'start' : i === all.length - 1 ? 'end' : 'middle' })}
                  tickFormat={(v) => fmtDate(dataset.time[Math.round(v)])} />

                {hover && <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#5AA3B8" strokeWidth={1} strokeDasharray="2,3" />}
              </g>
            </svg>
            {hover && (
              <div className="pointer-events-none absolute top-1 left-2 border border-hair bg-panel-2 px-2 py-1 font-mono text-[11px] leading-snug">
                <div className="text-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div className="text-amber">strategy {fmtMoney(hover.e)}</div>
                <div className="text-cyan">hold {fmtMoney(hover.b)}</div>
                <div className="text-dim">drawdown <span className="text-neg">{fmtPct(hover.dd)}</span></div>
              </div>
            )}
          </>
        )}
      </div>
    </Section>
  )
}
