'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../lib/backtest/format'
import useSize from '../../components/backtest/useSize'
import { holesFor } from './gaps'
import s from './bt.module.css'

const MARGIN = { top: 6, right: 48, bottom: 22, left: 22 }
const DD_SHARE = 0.3
const TICK = { fill: '#767d87', fontSize: 9.5, fontFamily: 'var(--font-jetbrains-mono), monospace' }

/**
 * Equity against buy & hold, drawdown underneath. Same geometry as the
 * original EquityPanel, minus the gradient fills and the draw-on animation,
 * with the x-axis labels inside the frame and holes ticked along the axis.
 */
export default function Equity() {
  const result = useBacktest((st) => st.result)
  const dataset = useBacktest((st) => st.dataset)
  const wf = useBacktest((st) => st.wf.data)
  const running = useBacktest((st) => st.running)
  const loading = useBacktest((st) => st.datasetLoading)
  const autoRun = useBacktest((st) => st.autoRun)
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)
  const gaps = holesFor(dataset)

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
    const holeXs = gaps?.holes.filter((h) => h.idx >= start && h.idx <= end).map((h) => x(h.idx)) || []
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, stitched, holeXs }
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
    <div className={s.pane}>
      <div className={s.paneHead}>
        <span className={s.paneTitle}>Equity and drawdown</span>
        {result && (
          <>
            <Legend color="#e8b339" label="strategy, net of costs" />
            <Legend color="#767d87" label={`${dataset?.symbol} buy & hold`} dashed />
            {geom?.stitched && <Legend color="#8b7ce0" label="walk-forward out-of-sample" />}
            {geom?.holeXs.length > 0 && (
              <span className={s.legend}>
                <svg width="2" height="8" aria-hidden="true"><line x1="1" y1="0" x2="1" y2="8" stroke="#e8b339" strokeOpacity="0.6" /></svg>
                data hole
              </span>
            )}
          </>
        )}
      </div>
      <div ref={ref} className={s.paneBody}>
        {!result ? (
          <p className="flex h-full items-center justify-center px-6 text-center text-[12px] text-dim">
            {loading ? 'Loading bars…' : running ? 'Running…' : autoRun ? 'The equity curve appears after the first run.' : 'Press Run (R) to draw the equity curve.'}
          </p>
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="cursor-crosshair" role="img" aria-label="Equity curve against buy and hold, with drawdown below">
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#2d323a" strokeWidth={1} />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke="#767d87" strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke="#8b7ce0" strokeWidth={1.25} />}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke="#e8b339" strokeWidth={1.5} />
                <AxisLeft
                  scale={geom.y}
                  left={geom.innerW}
                  numTicks={3}
                  hideAxisLine
                  hideTicks
                  tickLabelProps={() => ({ ...TICK, dx: 6, dy: 3, textAnchor: 'start' })}
                  tickFormat={(v) => `${(v / 1000).toFixed(0)}k`}
                />

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <text x={0} y={9} fill="#767d87" fontSize={9.5} fontFamily="var(--font-sans)">drawdown</text>
                  <line x1={0} x2={geom.innerW} y1={0} y2={0} stroke="#1f2328" />
                  <AreaClosed data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.yDd(d.dd)} yScale={geom.yDd} fill="rgba(255,107,107,0.16)" stroke="#ff6b6b" strokeWidth={0.75} strokeOpacity={0.6} />
                  <AxisLeft
                    scale={geom.yDd}
                    left={geom.innerW}
                    numTicks={2}
                    hideAxisLine
                    hideTicks
                    tickLabelProps={() => ({ ...TICK, dx: 6, dy: 3, textAnchor: 'start' })}
                    tickFormat={(v) => `${(v * 100).toFixed(0)}%`}
                  />
                </g>

                {geom.holeXs.map((hx, k) => (
                  <line key={k} x1={hx} x2={hx} y1={geom.innerH - 5} y2={geom.innerH} stroke="#e8b339" strokeOpacity={0.6} strokeWidth={1} />
                ))}

                <AxisBottom
                  top={geom.innerH}
                  scale={geom.x}
                  numTicks={Math.max(2, Math.floor(geom.innerW / 110))}
                  stroke="#1f2328"
                  hideTicks
                  tickLabelProps={() => ({ ...TICK, dy: 2, textAnchor: 'middle' })}
                  tickFormat={(v) => fmtDate(dataset.time[Math.round(v)])}
                />

                {hover && <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#5a9fb3" strokeWidth={1} strokeDasharray="2,3" />}
              </g>
            </svg>

            {hover && (
              <div className="pointer-events-none absolute top-1 left-4 border border-hair-bright bg-panel-2 px-2 py-1 font-mono text-[10.5px] leading-snug">
                <div className="text-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div className="text-amber">{fmtMoney(hover.e)}</div>
                <div className="text-dim">
                  hold {fmtMoney(hover.b)} · dd <span className="text-neg">{fmtPct(hover.dd)}</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Legend({ color, label, dashed }) {
  return (
    <span className={s.legend}>
      <svg width="14" height="4" aria-hidden="true">
        <line x1="0" y1="2" x2="14" y2="2" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
      </svg>
      {label}
    </span>
  )
}
