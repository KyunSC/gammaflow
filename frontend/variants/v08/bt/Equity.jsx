'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisRight } from '@visx/axis'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtTime } from '../../../lib/backtest/format'
import useSize from '../../../components/backtest/useSize'
import { Region, NoRunYet } from './ui'

const MARGIN = { top: 8, right: 52, bottom: 22, left: 18 }
const DD_SHARE = 0.28
const AMBER = '#e8b339'
const CYAN = '#5aa5ba'
const VIOLET = '#9585e6'
const NEG = '#ff7070'
const AXIS = '#9aa1aa'
const tick = { fill: AXIS, fontSize: 10, fontFamily: 'var(--font-jetbrains-mono), ui-monospace, monospace' }
const shortDate = (s) =>
  Number.isFinite(s) ? new Date(s * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'America/New_York' }) : ''

/**
 * Equity against holding the same symbol, with the drawdown underneath on its
 * own scale, so the underwater stretches keep their shape instead of being
 * flattened onto the equity axis.
 */
export default function Equity() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
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
    // Roughly one point per pixel.
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
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, stitched }
  }, [result, dataset, width, height, wf])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - MARGIN.left
    const idx = Math.round(geom.x.invert(Math.max(0, Math.min(geom.innerW, px))))
    setHover(geom.pts.reduce((a, b) => (Math.abs(b.i - idx) < Math.abs(a.i - idx) ? b : a), geom.pts[0]))
  }

  const capital = result?.config?.costs?.initialCapital

  return (
    <Region
      className="v8-fill"
      title="Equity and drawdown"
      aside={
        result ? (
          <span className="v8-legend">
            <Key color={AMBER} label="strategy" />
            <Key color={CYAN} label={`hold ${dataset?.symbol ?? ''}`} dashed />
            {geom?.stitched && <Key color={VIOLET} label="walk-forward, out of sample" />}
          </span>
        ) : null
      }
    >
      <div ref={ref} className="v8-chartbox">
        {!result ? (
          <NoRunYet what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="Strategy equity against buy and hold, with drawdown below">
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                {Number.isFinite(capital) && (
                  <line x1={0} x2={geom.innerW} y1={geom.y(capital)} y2={geom.y(capital)} stroke="#343a44" strokeWidth={1} />
                )}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke={CYAN} strokeOpacity={0.8} strokeWidth={1} strokeDasharray="4,3" />
                {geom.stitched && <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke={VIOLET} strokeWidth={1.25} />}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke={AMBER} strokeWidth={1.5} />
                <AxisRight
                  scale={geom.y}
                  left={geom.innerW}
                  numTicks={3}
                  hideAxisLine
                  hideTicks
                  tickLabelProps={() => ({ ...tick, dx: 6, dy: 3 })}
                  tickFormat={(v) => `${(v / 1000).toFixed(0)}k`}
                />

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <line x1={0} x2={geom.innerW} y1={0} y2={0} stroke="#23272e" />
                  <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} yScale={geom.yDd} fill={NEG} fillOpacity={0.22} stroke={NEG} strokeWidth={0.75} strokeOpacity={0.7} />
                  <AxisRight
                    scale={geom.yDd}
                    left={geom.innerW}
                    tickValues={[geom.yDd.domain()[0]]}
                    hideAxisLine
                    hideTicks
                    tickLabelProps={() => ({ ...tick, fill: NEG, dx: 6, dy: 3 })}
                    tickFormat={(v) => `${(v * 100).toFixed(1)}%`}
                  />
                </g>

                <AxisBottom
                  top={geom.innerH}
                  scale={geom.x}
                  numTicks={Math.max(2, Math.floor(geom.innerW / 120))}
                  stroke="#23272e"
                  tickStroke="#23272e"
                  tickLabelProps={() => ({ ...tick, textAnchor: 'middle', dy: 2 })}
                  tickFormat={(v) => shortDate(dataset.time[Math.round(v)])}
                />
                {hover && <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke={CYAN} strokeWidth={1} strokeDasharray="2,3" />}
              </g>
            </svg>
            {hover && (
              <div className="v8-tip" style={{ left: Math.min(Math.max(4, geom.x(hover.i) + 12), Math.max(4, width - 210)) }}>
                <div className="text-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div><span className="text-amber">strategy</span> <span className="num">{fmtMoney(hover.e)}</span></div>
                <div><span className="text-cyan">hold</span> <span className="num">{fmtMoney(hover.b)}</span></div>
                <div><span className="text-neg">drawdown</span> <span className="num">{fmtPct(hover.dd)}</span></div>
              </div>
            )}
          </>
        )}
      </div>
    </Region>
  )
}

function Key({ color, label, dashed }) {
  return (
    <span className="v8-key">
      <svg width="14" height="4" aria-hidden>
        <line x1="0" y1="2" x2="14" y2="2" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
      </svg>
      {label}
    </span>
  )
}
