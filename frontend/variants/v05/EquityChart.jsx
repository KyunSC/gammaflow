'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../lib/backtest/format'
import { NoRunYet } from '../../components/backtest/Panel'
import useSize from '../../components/backtest/useSize'
import Block from './Block'
import { holesFor } from './gaps'

const MARGIN = { top: 6, right: 50, bottom: 18, left: 4 }
const DD_SHARE = 0.3
const MONO = 'var(--font-jetbrains-mono), monospace'

/**
 * Variant 05 copy of components/backtest/EquityPanel.jsx. Same curves and
 * downsampling. Gradient fills and the path-draw animation are gone (the
 * animation replayed on every auto-run); added: a rug of missing-bar ticks
 * under the x-axis and a band over the selected trade.
 */
export default function EquityChart() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)
  const holes = holesFor(dataset)

  const geom = useMemo(() => {
    if (!result || !dataset || width < 60 || height < 60) return null
    const start = result.windowStart
    const end = result.windowEnd
    const n = end - start + 1
    if (n < 2) return null

    const innerW = Math.max(10, width - MARGIN.left - MARGIN.right)
    const innerH = Math.max(10, height - MARGIN.top - MARGIN.bottom)
    const eqH = innerH * (1 - DD_SHARE) - 8
    const ddH = innerH * DD_SHARE - 4

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
    const span = hi - lo

    const stitched = wf?.stitched
      ? pts.map((p) => ({ i: p.i, v: wf.stitched[p.i] })).filter((p) => Number.isFinite(p.v))
      : null

    const rug = holes.holes.filter((h) => h.idx >= start && h.idx <= end)
    return { pts, x, y, yDd, innerW, innerH, eqH, ddH, start, end, stitched, span, rug }
  }, [result, dataset, width, height, wf, holes])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left - MARGIN.left
    const idx = Math.round(geom.x.invert(Math.max(0, Math.min(geom.innerW, px))))
    const p = geom.pts.reduce((a, b) => (Math.abs(b.i - idx) < Math.abs(a.i - idx) ? b : a), geom.pts[0])
    setHover(p)
  }

  const tick = { fill: '#5A616B', fontSize: 9.5, fontFamily: MONO }
  const kFmt = (v) => (geom && geom.span < 4000 ? `${(v / 1000).toFixed(1)}k` : `${(v / 1000).toFixed(0)}k`)
  const sel = geom && selectedTrade && selectedTrade.exitIdx >= geom.start && selectedTrade.entryIdx <= geom.end ? selectedTrade : null

  return (
    <Block
      title="Equity and drawdown"
      meta={result ? <span className="hidden sm:inline">start {fmtMoney(result.config.costs.initialCapital)}</span> : null}
      right={
        result ? (
          <span className="flex items-center gap-3 font-mono text-[10.5px] text-dim">
            <Legend color="#E8B339" label="strategy" />
            <Legend color="#8A9098" label={`${dataset?.symbol} hold`} dashed />
            {geom?.stitched && <Legend color="#7C6BD6" label="walk-forward OOS" />}
            {geom?.rug.length > 0 && (
              <span className="hidden sm:inline">
                <span className="text-amber">▮</span> missing bars
              </span>
            )}
          </span>
        ) : null
      }
      className="h-full"
    >
      <div ref={ref} className="absolute inset-0">
        {!result ? (
          <NoRunYet what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg
              width={width}
              height={height}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
              className="cursor-crosshair"
              role="img"
              aria-label={`Equity curve against ${dataset.symbol} buy and hold, with drawdown below`}
            >
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                {sel && (
                  <rect
                    x={geom.x(Math.max(geom.start, sel.entryIdx))}
                    width={Math.max(2, geom.x(Math.min(geom.end, sel.exitIdx)) - geom.x(Math.max(geom.start, sel.entryIdx)))}
                    y={0}
                    height={geom.innerH}
                    fill="#E8B339"
                    opacity={0.12}
                  />
                )}
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#2E343D" strokeWidth={1} />
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.b)} stroke="#8A9098" strokeOpacity={0.7} strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && (
                  <LinePath data={geom.stitched} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.v)} stroke="#7C6BD6" strokeWidth={1.25} strokeOpacity={0.9} />
                )}
                <LinePath data={geom.pts} x={(d) => geom.x(d.i)} y={(d) => geom.y(d.e)} stroke="#E8B339" strokeWidth={1.5} />
                <AxisLeft
                  scale={geom.y}
                  left={geom.innerW}
                  numTicks={3}
                  hideAxisLine
                  hideTicks
                  tickLabelProps={() => ({ ...tick, dx: 6, textAnchor: 'start' })}
                  tickFormat={kFmt}
                />

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <text x={0} y={9} {...tick}>drawdown</text>
                  <AreaClosed
                    data={geom.pts}
                    x={(d) => geom.x(d.i)}
                    y={(d) => geom.yDd(d.dd)}
                    yScale={geom.yDd}
                    fill="#ff6b6b"
                    fillOpacity={0.16}
                    stroke="#ff6b6b"
                    strokeWidth={0.75}
                    strokeOpacity={0.6}
                  />
                  <AxisLeft
                    scale={geom.yDd}
                    left={geom.innerW}
                    numTicks={2}
                    hideAxisLine
                    hideTicks
                    tickLabelProps={() => ({ ...tick, dx: 6, textAnchor: 'start' })}
                    tickFormat={(v) => `${(v * 100).toFixed(0)}%`}
                  />
                </g>

                {geom.rug.map((h) => (
                  <line key={h.idx} x1={geom.x(h.idx)} x2={geom.x(h.idx)} y1={geom.innerH - 5} y2={geom.innerH} stroke="#E8B339" strokeWidth={1} />
                ))}

                <AxisBottom
                  top={geom.innerH}
                  scale={geom.x}
                  numTicks={Math.max(2, Math.floor(geom.innerW / 110))}
                  stroke="#22262D"
                  tickStroke="#22262D"
                  tickLabelProps={() => ({ ...tick, textAnchor: 'middle' })}
                  tickFormat={(v) => fmtDate(dataset.time[Math.round(v)])}
                />

                {hover && (
                  <line x1={geom.x(hover.i)} x2={geom.x(hover.i)} y1={0} y2={geom.innerH} stroke="#4A90A4" strokeWidth={1} strokeDasharray="2,3" />
                )}
              </g>
            </svg>

            {hover && (
              <div className="pointer-events-none absolute top-1 left-2 bg-canvas/95 px-2 py-1 font-mono text-[10.5px] leading-snug">
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
    </Block>
  )
}

function Legend({ color, label, dashed }) {
  return (
    <span className="flex items-center gap-1">
      <svg width="14" height="4" aria-hidden>
        <line x1="0" y1="2" x2="14" y2="2" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
      </svg>
      {label}
    </span>
  )
}
