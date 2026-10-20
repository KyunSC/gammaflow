'use client'

import { useMemo, useState } from 'react'
import { scaleLinear } from '@visx/scale'
import { LinePath, AreaClosed } from '@visx/shape'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoney, fmtPct, fmtDate, fmtTime } from '../../../lib/backtest/format'
import useSize from '../../../components/backtest/useSize'
import { Region, NoResult } from './ui'
import useGaps from './useGaps'

const MARGIN = { top: 8, right: 50, bottom: 24, left: 6 }
const DD_SHARE = 0.3
const TICK = { fill: '#80878f', fontSize: 10, fontFamily: 'var(--v3-font-mono), var(--font-jetbrains-mono), monospace' }

/**
 * Equity with the same-symbol hold line behind it and the drawdown well
 * underneath. Unlike components/backtest/EquityPanel, the x axis leaves room
 * for missing bars: each hole is a hatched column and the lines break across
 * it rather than drawing a straight segment over data that is not there.
 * No fill gradients and no draw-in animation.
 */
export default function EquityChart() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const wf = useBacktest((s) => s.wf.data)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const gaps = useGaps()
  const [ref, { width, height }] = useSize()
  const [hover, setHover] = useState(null)

  const geom = useMemo(() => {
    if (!result || !dataset || width < 60 || height < 60) return null
    const start = result.windowStart
    const end = result.windowEnd
    const n = end - start + 1
    if (n < 2) return null

    // Position on the x axis: bar index plus every missing bar before it.
    const pos = new Float64Array(dataset.n)
    const holeAt = new Uint8Array(dataset.n)
    let extra = 0
    let hk = 0
    const holes = gaps?.holes || []
    for (let i = 0; i < dataset.n; i++) {
      while (hk < holes.length && holes[hk].idx === i) {
        extra += holes[hk].missing
        holeAt[i] = 1
        hk++
      }
      pos[i] = i + extra
    }

    const innerW = Math.max(10, width - MARGIN.left - MARGIN.right)
    const innerH = Math.max(10, height - MARGIN.top - MARGIN.bottom)
    const eqH = innerH * (1 - DD_SHARE) - 8
    const ddH = innerH * DD_SHARE

    const stride = Math.max(1, Math.floor(n / Math.max(80, innerW)))
    const idx = new Set()
    for (let i = start; i <= end; i += stride) idx.add(i)
    idx.add(end)
    for (const h of holes) {
      if (h.idx > start && h.idx <= end) {
        idx.add(h.idx - 1)
        idx.add(h.idx)
      }
    }
    const order = [...idx].sort((a, b) => a - b)
    const pts = []
    let lo = Infinity
    let hi = -Infinity
    for (const i of order) {
      if (holeAt[i] && i > start && pts.length) pts.push({ br: true, i })
      const e = result.equity[i]
      const b = result.buyHold[i]
      lo = Math.min(lo, e, b)
      hi = Math.max(hi, e, b)
      pts.push({ i, e, b, dd: result.metrics.ddCurve[i - start] ?? 0 })
    }
    const solid = pts.filter((p) => !p.br)

    const x = scaleLinear({ domain: [pos[start], pos[end]], range: [0, innerW] })
    const xi = (i) => x(pos[i])
    const pad = (hi - lo) * 0.06 || 1
    const y = scaleLinear({ domain: [lo - pad, hi + pad], range: [eqH, 0] })
    const yDd = scaleLinear({ domain: [Math.min(-0.0001, -result.metrics.maxDd * 1.05), 0], range: [ddH, 0] })

    const bands = holes
      .filter((h) => h.idx > start && h.idx <= end)
      .map((h) => ({ x0: xi(h.idx - 1), x1: xi(h.idx) }))

    const stitched = wf?.stitched
      ? solid.map((p) => ({ i: p.i, v: wf.stitched[p.i] })).filter((p) => Number.isFinite(p.v))
      : null

    // Tick at bar positions so labels map back to real timestamps.
    const nTicks = Math.max(2, Math.floor(innerW / 120))
    const ticks = []
    for (let k = 0; k <= nTicks; k++) ticks.push(Math.round(start + ((end - start) * k) / nTicks))

    return { pts, solid, x, xi, y, yDd, innerW, innerH, eqH, ddH, start, end, stitched, bands, ticks, pos }
  }, [result, dataset, width, height, wf, gaps])

  const onMove = (e) => {
    if (!geom) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = Math.max(0, Math.min(geom.innerW, e.clientX - rect.left - MARGIN.left))
    const p = geom.solid.reduce((a, b) => (Math.abs(geom.xi(b.i) - px) < Math.abs(geom.xi(a.i) - px) ? b : a), geom.solid[0])
    setHover(p)
  }

  const defined = (d) => !d.br

  return (
    <Region
      title="Equity and drawdown"
      className="v3-fill"
      aside={
        result ? (
          <span className="v3-legend">
            <Legend color="#E8B339" label="strategy" />
            <Legend color="#a5abb3" label={`hold ${dataset?.symbol ?? ''}`} dashed />
            {geom?.stitched && <Legend color="#9a8ce6" label="walk-fwd OOS" />}
            {geom?.bands.length > 0 && <span><i className="v3-gap-swatch" aria-hidden="true" />missing bars</span>}
          </span>
        ) : null
      }
    >
      <div ref={ref} className="v3-chart-wrap">
        {!result ? (
          <NoResult what="Equity curves" />
        ) : !geom ? null : (
          <>
            <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)} className="v3-crosshair" role="img" aria-label="Strategy equity against holding the symbol, with drawdown below">
              <defs>
                <pattern id="v3-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <rect width="4" height="4" fill="rgba(230,232,235,0.05)" />
                  <line x1="0" y1="0" x2="0" y2="4" stroke="rgba(230,232,235,0.28)" strokeWidth="1.2" />
                </pattern>
              </defs>
              <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                {geom.bands.map((b, k) => (
                  <rect key={k} x={b.x0} width={Math.max(1.5, b.x1 - b.x0)} y={0} height={geom.innerH} fill="url(#v3-hatch)" />
                ))}
                {selectedTrade && selectedTrade.entryIdx >= geom.start && (
                  <rect
                    x={geom.xi(selectedTrade.entryIdx)}
                    width={Math.max(2, geom.xi(Math.min(selectedTrade.exitIdx, geom.end)) - geom.xi(selectedTrade.entryIdx))}
                    y={0}
                    height={geom.innerH}
                    fill="rgba(232,179,57,0.14)"
                  />
                )}
                <line x1={0} x2={geom.innerW} y1={geom.y(result.config.costs.initialCapital)} y2={geom.y(result.config.costs.initialCapital)} stroke="#323841" strokeWidth={1} />
                <LinePath data={geom.pts} defined={defined} x={(d) => geom.xi(d.i)} y={(d) => geom.y(d.b)} stroke="#a5abb3" strokeOpacity={0.55} strokeWidth={1} strokeDasharray="3,3" />
                {geom.stitched && (
                  <LinePath data={geom.stitched} x={(d) => geom.xi(d.i)} y={(d) => geom.y(d.v)} stroke="#9a8ce6" strokeWidth={1.25} />
                )}
                <LinePath data={geom.pts} defined={defined} x={(d) => geom.xi(d.i)} y={(d) => geom.y(d.e)} stroke="#E8B339" strokeWidth={1.5} />
                <AxisLeft
                  scale={geom.y}
                  left={geom.innerW}
                  numTicks={3}
                  hideAxisLine
                  hideTicks
                  tickLabelProps={() => ({ ...TICK, dx: 6, textAnchor: 'start' })}
                  tickFormat={(v) => `${(v / 1000).toFixed(0)}k`}
                />

                <g transform={`translate(0,${geom.eqH + 8})`}>
                  <line x1={0} x2={geom.innerW} y1={0} y2={0} stroke="#24282f" />
                  <AreaClosed
                    data={geom.pts}
                    defined={defined}
                    x={(d) => geom.xi(d.i)}
                    y={(d) => geom.yDd(d.dd)}
                    yScale={geom.yDd}
                    fill="rgba(255,107,107,0.16)"
                    stroke="#ff6b6b"
                    strokeWidth={1}
                    strokeOpacity={0.7}
                  />
                  <AxisLeft
                    scale={geom.yDd}
                    left={geom.innerW}
                    numTicks={2}
                    hideAxisLine
                    hideTicks
                    tickLabelProps={() => ({ ...TICK, dx: 6, textAnchor: 'start' })}
                    tickFormat={(v) => `${(v * 100).toFixed(0)}%`}
                  />
                </g>

                <AxisBottom
                  top={geom.innerH}
                  scale={geom.x}
                  tickValues={geom.ticks.map((i) => geom.pos[i])}
                  stroke="#24282f"
                  tickStroke="#24282f"
                  tickLength={4}
                  tickLabelProps={(v, k) => ({ ...TICK, textAnchor: k === 0 ? 'start' : k === geom.ticks.length - 1 ? 'end' : 'middle' })}
                  tickFormat={(v, k) => fmtDate(dataset.time[geom.ticks[k]])}
                />

                {hover && (
                  <line x1={geom.xi(hover.i)} x2={geom.xi(hover.i)} y1={0} y2={geom.innerH} stroke="#5aa3b8" strokeWidth={1} strokeDasharray="2,3" />
                )}
              </g>
            </svg>

            {hover && (
              <div className="v3-tip">
                <div className="v3-dim">{fmtTime(dataset.time[hover.i])} ET</div>
                <div className="v3-amber">{fmtMoney(hover.e)}</div>
                <div className="v3-dim">
                  hold {fmtMoney(hover.b)} · drawdown <span className="v3-neg">{fmtPct(hover.dd)}</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Region>
  )
}

function Legend({ color, label, dashed }) {
  return (
    <span>
      <svg width="14" height="6" aria-hidden="true" className="v3-legend-line">
        <line x1="0" y1="3" x2="14" y2="3" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
      </svg>
      {label}
    </span>
  )
}
