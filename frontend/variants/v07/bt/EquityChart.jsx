'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, Area } from '@visx/shape'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../../lib/backtest/format'
import { scanGaps } from '../gaps'
import useSize from '../../../components/backtest/useSize'
import { NoRunYet, minus } from './ui'

const MARGIN = { top: 8, right: 56, bottom: 20, left: 8 }
const DD_SHARE = 0.3
const MONO = 'var(--v7-font-mono), var(--font-jetbrains-mono), monospace'
const AXIS = '#8f959c'

/**
 * Equity against buy & hold, drawdown underneath, and a tick along the time
 * axis wherever the data has a hole. The x axis is bar-indexed, so without
 * those ticks a 40-minute hole looks like one 5-minute step.
 *
 * No area gradients and no line-drawing animation: the line is the data.
 */
export default function EquityChart() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)
  const gaps = useMemo(() => scanGaps(dataset), [dataset])

  const geom = useMemo(() => {
    if (!result || !dataset || width < 80 || height < 80) return null
    const start = result.windowStart
    const end = result.windowEnd
    const n = end - start + 1
    if (n < 2) return null
    const innerW = Math.max(10, width - MARGIN.left - MARGIN.right)
    const innerH = Math.max(10, height - MARGIN.top - MARGIN.bottom)
    const eqH = innerH * (1 - DD_SHARE) - 10
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
    const yDd = scaleLinear({ domain: [Math.min(-0.0001, -result.metrics.maxDd * 1.08), 0], range: [ddH, 0] })

    const stitched = wf?.stitched
      ? pts.map((p) => ({ i: p.i, v: wf.stitched[p.i] })).filter((p) => Number.isFinite(p.v))
      : null

    const holes = []
    if (gaps) for (let i = start + 1; i <= end; i++) if (gaps.after[i]) holes.push(i)

    // Time ticks inset from both ends so the first label is never clipped.
    const nT = Math.max(2, Math.floor(innerW / 120))
    const xTicks = Array.from({ length: nT }, (_, k) => Math.round(start + ((k + 0.5) / nT) * (end - start)))
    const yTicks = y.ticks(3)
    const ddTicks = [yDd.domain()[0] * 0.95, 0].map((v) => Math.round(v * 1000) / 1000)

    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, start, end, stitched, holes, xTicks, yTicks, ddTicks }
  }, [result, dataset, width, height, wf, gaps])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - MARGIN.left
    const idx = Math.round(geom.x.invert(Math.max(0, Math.min(geom.innerW, px))))
    const p = geom.pts.reduce((a, b) => (Math.abs(b.i - idx) < Math.abs(a.i - idx) ? b : a), geom.pts[0])
    setHover(p)
  }

  return (
    <section className="v7-block v7-equity" aria-label="Equity and drawdown">
      <header className="v7-block-head">
        <h3>Equity and drawdown</h3>
        {result && (
          <ul className="v7-legend" aria-label="Legend">
            <li><Swatch color="#e8b339" />strategy</li>
            <li><Swatch color="#4a90a4" dashed />{dataset?.symbol} buy &amp; hold</li>
            {geom?.stitched && <li><Swatch color="#8f80e0" />walk-forward out-of-sample</li>}
            {geom?.holes.length > 0 && <li><span className="v7-key v7-key-hole" aria-hidden="true" />hole in data</li>}
          </ul>
        )}
      </header>
      <div ref={ref} className="v7-block-body v7-equity-body">
        {!result ? (
          <NoRunYet what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img"
              aria-label={`Strategy equity from ${fmtMoney(result.equity[geom.start])} to ${fmtMoney(result.equity[geom.end])}; buy and hold to ${fmtMoney(result.buyHold[geom.end])}`}>
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                {geom.yTicks.map((v) => (
                  <g key={v}>
                    <line x1={0} x2={geom.innerW} y1={geom.y(v)} y2={geom.y(v)} stroke="#1c1f24" />
                    <text x={geom.innerW + 6} y={geom.y(v)} fill={AXIS} fontSize={10} fontFamily={MONO} dominantBaseline="middle">
                      ${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k
                    </text>
                  </g>
                ))}
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#3a3e46" />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke="#4a90a4" strokeWidth={1.1} strokeDasharray="4,3" />
                {geom.stitched && (
                  <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke="#8f80e0" strokeWidth={1.25} />
                )}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke="#e8b339" strokeWidth={1.5} />

                <g transform={`translate(0,${geom.eqH + 10})`}>
                  <text x={0} y={-2} fill={AXIS} fontSize={10} fontFamily={MONO}>drawdown</text>
                  <line x1={0} x2={geom.innerW} y1={geom.yDd(0)} y2={geom.yDd(0)} stroke="#3a3e46" />
                  <Area
                    data={geom.pts}
                    x={(d) => geom.x(d.i)}
                    y0={() => geom.yDd(0)}
                    y1={(d) => geom.yDd(d.dd)}
                    fill="rgba(255,107,107,0.14)"
                  />
                  <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} stroke="#ff6b6b" strokeWidth={1} />
                  {geom.ddTicks.map((v) => (
                    <text key={v} x={geom.innerW + 6} y={geom.yDd(v)} fill={AXIS} fontSize={10} fontFamily={MONO} dominantBaseline="middle">
                      {v === 0 ? '0%' : `−${Math.abs(v * 100).toFixed(1)}%`}
                    </text>
                  ))}
                </g>

                <line x1={0} x2={geom.innerW} y1={geom.innerH} y2={geom.innerH} stroke="#23262c" />
                {geom.holes.map((i) => (
                  <line key={i} x1={geom.x(i)} x2={geom.x(i)} y1={geom.innerH - 5} y2={geom.innerH} stroke="rgba(233,231,226,0.55)" strokeWidth={1} />
                ))}
                {geom.xTicks.map((v) => (
                  <text key={v} x={geom.x(v)} y={geom.innerH + 14} fill={AXIS} fontSize={10} fontFamily={MONO} textAnchor="middle">
                    {fmtDate(dataset.time[v])}
                  </text>
                ))}

                {hover && (
                  <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#4a90a4" strokeWidth={1} strokeDasharray="2,3" />
                )}
              </g>
            </svg>
            {hover && (
              <div className="v7-tip" style={{ left: Math.min(Math.max(8, geom.x(hover.i) + MARGIN.left + 12), Math.max(8, width - 200)) }}>
                <div className="v7-tip-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div className="v7-amber">{fmtMoney(hover.e)}</div>
                <div className="v7-tip-dim">hold {fmtMoney(hover.b)} · drawdown <span className="v7-neg">{minus(fmtPct(hover.dd))}</span></div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

function Swatch({ color, dashed }) {
  return (
    <svg width="14" height="6" aria-hidden="true" className="v7-swatch">
      <line x1="0" y1="3" x2="14" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dashed ? '4,2' : undefined} />
    </svg>
  )
}
