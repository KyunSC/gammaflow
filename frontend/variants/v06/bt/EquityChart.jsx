'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../../lib/backtest/format'
import { NoRunYet } from '../../../components/backtest/Panel'
import useSize from '../../../components/backtest/useSize'
import Section from './Section'
import { useGaps } from './ui'

// Bottom margin leaves room for the date labels (the original clipped them).
const MARGIN = { top: 8, right: 48, bottom: 24, left: 18 }
const DD_SHARE = 0.3
const AXIS = { fill: '#868d97', fontSize: 10, fontFamily: 'var(--v06-mono), monospace' }
const GAP = 'rgba(214, 220, 228, 0.5)'

/**
 * Equity with buy & hold behind it, drawdown underneath, and a tick on the
 * time axis wherever bars are missing: a step in the curve that sits on one of
 * those ticks was priced across a hole.
 */
export default function EquityChart() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const gaps = useGaps()
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)

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
    if (pts[pts.length - 1].i !== end) pts.push({ i: end, e: result.equity[end], b: result.buyHold[end], dd: result.metrics.ddCurve[end - start] ?? 0 })

    const x = scaleLinear({ domain: [start, end], range: [0, innerW] })
    const pad = (hi - lo) * 0.06 || 1
    const y = scaleLinear({ domain: [lo - pad, hi + pad], range: [eqH, 0] })
    const yDd = scaleLinear({ domain: [Math.min(-0.0001, -result.metrics.maxDd * 1.05), 0], range: [ddH, 0] })
    const stitched = wf?.stitched ? pts.map((p) => ({ i: p.i, v: wf.stitched[p.i] })).filter((p) => Number.isFinite(p.v)) : null
    const holes = gaps ? gaps.holes.filter((h) => h.idx > start && h.idx <= end) : []
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, stitched, holes }
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
      title="Equity and drawdown"
      right={
        result ? (
          <span className="v6-legend">
            <span><i className="v6-sw" style={{ background: '#E8B339' }} />strategy</span>
            <span><i className="v6-sw v6-sw-dash" />{dataset?.symbol} buy &amp; hold</span>
            {geom?.stitched && <span><i className="v6-sw" style={{ background: '#7C6BD6' }} />walk-forward OOS</span>}
            {geom?.holes.length > 0 && <span><i className="v6-sw v6-sw-bar" style={{ background: GAP }} />missing bars</span>}
          </span>
        ) : null
      }
      className="h-full"
      scroll={false}
    >
      <div ref={ref} className="relative h-full w-full">
        {!result ? (
          <NoRunYet what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="cursor-crosshair" role="img" aria-label="Strategy equity against buy and hold, with drawdown below">
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#343a43" strokeWidth={1} />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke="#8a919b" strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke="#7C6BD6" strokeWidth={1.25} />}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke="#E8B339" strokeWidth={1.5} />
                <AxisLeft scale={geom.y} left={geom.innerW} numTicks={3} hideAxisLine hideTicks tickLabelProps={() => ({ ...AXIS, dx: 6, textAnchor: 'start' })} tickFormat={(v) => `${(v / 1000).toFixed(0)}k`} />

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} yScale={geom.yDd} fill="rgba(255,107,107,0.16)" stroke="#ff6b6b" strokeWidth={0.75} strokeOpacity={0.7} />
                  <AxisLeft scale={geom.yDd} left={geom.innerW} numTicks={2} hideAxisLine hideTicks tickLabelProps={() => ({ ...AXIS, dx: 6, textAnchor: 'start' })} tickFormat={(v) => `${(v * 100).toFixed(0)}%`} />
                </g>

                {geom.holes.map((h) => (
                  <line key={h.idx} x1={geom.x(h.idx)} x2={geom.x(h.idx)} y1={geom.innerH - 6} y2={geom.innerH} stroke={GAP} strokeWidth={1} />
                ))}
                <AxisBottom
                  top={geom.innerH}
                  scale={geom.x}
                  numTicks={Math.max(2, Math.floor(geom.innerW / 110))}
                  stroke="#24282f"
                  tickStroke="#24282f"
                  tickLabelProps={() => ({ ...AXIS, textAnchor: 'middle' })}
                  tickFormat={(v) => fmtDate(dataset.time[Math.round(v)])}
                />
                {hover && <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#4A90A4" strokeWidth={1} strokeDasharray="2,3" />}
              </g>
            </svg>
            {hover && (
              <div className="v6-tip">
                <div className="v6-dim">{fmtTime(dataset.time[hover.i])}</div>
                <div className="text-amber">{fmtMoney(hover.e)}</div>
                <div className="v6-dim">buy &amp; hold {fmtMoney(hover.b)} · drawdown <span className="text-neg">{fmtPct(hover.dd)}</span></div>
              </div>
            )}
          </>
        )}
      </div>
    </Section>
  )
}
