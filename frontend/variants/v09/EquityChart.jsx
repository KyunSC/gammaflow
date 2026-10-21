'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../lib/backtest/format'
import useSize from '../../components/backtest/useSize'
import { findGaps } from './gaps'

const MARGIN = { top: 4, right: 50, bottom: 30, left: 4 }
const DD_SHARE = 0.32
const RUG_H = 5
const TICK = { fill: '#7a818b', fontSize: 10, fontFamily: 'var(--font-jetbrains-mono), monospace' }

/**
 * Equity with buy & hold behind it, drawdown underneath, and a rug of the
 * missing-bar holes along the bottom so a jump in the curve can be checked
 * against the data it was computed from. Plain lines, no gradient fills, no
 * draw-in animation.
 */
export default function EquityChart() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
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
    const eqH = innerH * (1 - DD_SHARE) - 6
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
    const holes = gaps?.supported ? gaps.holes.filter((h) => h.i >= start && h.i <= end) : []
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, stitched, holes }
  }, [result, dataset, width, height, wf, gaps])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - MARGIN.left
    const idx = Math.round(geom.x.invert(Math.max(0, Math.min(geom.innerW, px))))
    const p = geom.pts.reduce((a, b) => (Math.abs(b.i - idx) < Math.abs(a.i - idx) ? b : a), geom.pts[0])
    setHover(p)
  }

  const empty = !result
    ? datasetLoading
      ? 'Loading data…'
      : running
        ? 'Running…'
        : 'The equity curve appears after a run.'
    : null

  return (
    <figure className="flex h-full min-h-0 flex-col" aria-label="Equity and drawdown">
      <figcaption className="flex shrink-0 flex-wrap items-baseline gap-x-4 gap-y-0.5 px-4 pt-2 text-[11.5px] text-dim">
        <span className="v9-h">Equity and drawdown</span>
        <span className="flex-1" />
        {result && (
          <>
            <Legend color="#e8b339" label="strategy" />
            <Legend color="#5aa3b8" label={`hold ${dataset?.symbol}`} dashed />
            {geom?.stitched && <Legend color="#9a8cf0" label="walk-forward OOS" />}
            {geom?.holes?.length > 0 && (
              <span>
                <span className="mr-1 inline-block h-2 w-[2px] align-[-1px] bg-amber" />
                hole in the data
              </span>
            )}
          </>
        )}
      </figcaption>
      <div ref={ref} className="relative min-h-0 flex-1">
        {empty ? (
          <p className="flex h-full items-center justify-center text-[12px] text-dim">{empty}</p>
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="cursor-crosshair" role="img" aria-label={`Strategy equity from ${fmtMoney(result.equity[result.windowStart])} to ${fmtMoney(result.metrics.finalEquity)}; max drawdown ${(result.metrics.maxDd * 100).toFixed(1)}%`}>
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#2c3138" strokeWidth={1} />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke="#5aa3b8" strokeOpacity={0.7} strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke="#9a8cf0" strokeWidth={1.25} />}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke="#e8b339" strokeWidth={1.5} />
                <AxisLeft scale={geom.y} left={geom.innerW} numTicks={3} hideAxisLine hideTicks tickLabelProps={() => ({ ...TICK, dx: 6, textAnchor: 'start', dy: '0.33em' })} tickFormat={(v) => `${(v / 1000).toFixed(0)}k`} />

                <g transform={`translate(0,${geom.eqH + 6})`}>
                  <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} yScale={geom.yDd} fill="#ff6b6b" fillOpacity={0.14} stroke="#ff6b6b" strokeWidth={0.75} strokeOpacity={0.7} />
                  <AxisLeft scale={geom.yDd} left={geom.innerW} numTicks={2} hideAxisLine hideTicks tickLabelProps={() => ({ ...TICK, dx: 6, textAnchor: 'start', dy: '0.33em' })} tickFormat={(v) => `${(v * 100).toFixed(0)}%`} />
                </g>

                {geom.holes.map((h) => (
                  <rect key={h.i} x={geom.x(h.i) - 0.5} y={geom.innerH + 1} width={1} height={RUG_H} fill="#e8b339" opacity={0.8}>
                    <title>{`${h.missing} missing bar${h.missing === 1 ? '' : 's'} before ${fmtTime(h.to)} ET`}</title>
                  </rect>
                ))}

                <AxisBottom
                  top={geom.innerH + RUG_H + 2}
                  scale={geom.x}
                  tickValues={geom.x.ticks(Math.max(2, Math.floor(geom.innerW / 110))).filter((v) => geom.x(v) > 22 && geom.x(v) < geom.innerW - 22)}
                  hideAxisLine
                  tickStroke="#2c3138"
                  tickLength={3}
                  tickLabelProps={() => ({ ...TICK, textAnchor: 'middle' })}
                  tickFormat={(v) => fmtDate(dataset.time[Math.round(v)])}
                />
                {hover && <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#5aa3b8" strokeWidth={1} strokeDasharray="2,3" />}
              </g>
            </svg>
            {hover && (
              <div className="pointer-events-none absolute top-1 left-4 border border-hair-bright bg-canvas px-2 py-1 text-[11px] leading-snug">
                <div className="v9-num text-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div className="v9-num text-amber">{fmtMoney(hover.e)}</div>
                <div className="v9-num text-dim">
                  hold {fmtMoney(hover.b)} · drawdown <span className="text-neg">{fmtPct(hover.dd)}</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </figure>
  )
}

function Legend({ color, label, dashed }) {
  return (
    <span className="flex items-center gap-1">
      <svg width="14" height="6" aria-hidden="true">
        <line x1="0" y1="3" x2="14" y2="3" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
      </svg>
      {label}
    </span>
  )
}
