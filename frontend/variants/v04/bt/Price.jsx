'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import { findHoles } from '../gaps'
import { Empty } from './Empty'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const HOLE = 'rgba(160, 167, 175, 0.2)'

/**
 * Price with entry/exit markers, same chart engine as the ticker page.
 *
 * Added here: intraday data holes are drawn as full-height stripes on a hidden
 * scale. The time axis closes up missing bars, so without them a session with
 * twenty missing 5m bars draws exactly like a complete one. The model
 * prediction overlay is a toggle, on by default only for the model strategy.
 */
export default function Price() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const holesRef = useRef(null)

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const strategyId = useBacktest((s) => s.strategyId)
  const [mlPick, setMl] = useState(null)
  const showMl = Boolean(dataset?.ml?.pred) && (mlPick ?? strategyId === 'mlSignal')
  const holes = findHoles(dataset)

  const candles = useMemo(() => {
    if (!dataset) return []
    const out = new Array(dataset.n)
    for (let i = 0; i < dataset.n; i++) {
      out[i] = { time: dataset.time[i], open: dataset.open[i], high: dataset.high[i], low: dataset.low[i], close: dataset.close[i] }
    }
    return out
  }, [dataset])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#8A9098',
        fontFamily: 'var(--font-jetbrains-mono), monospace',
        fontSize: 10,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(34,38,45,0.7)' } },
      rightPriceScale: { borderColor: '#22262D', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: '#22262D', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5aa5ba', width: 1, style: 3, labelBackgroundColor: '#1c2027' },
        horzLine: { color: '#5aa5ba', width: 1, style: 3, labelBackgroundColor: '#1c2027' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    // Hole stripes first, so candles draw over them.
    const holeSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'holes',
      color: HOLE,
      lastValueVisible: false,
      priceLineVisible: false,
      base: 0,
    })
    chart.priceScale('holes').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    chartRef.current = chart
    seriesRef.current = series
    holesRef.current = holeSeries
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
      holesRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  // The first bar after each hole carries a stripe.
  useEffect(() => {
    const hs = holesRef.current
    if (!hs) return
    if (!dataset || !holes?.holes.length) {
      hs.setData([])
      return
    }
    const isHole = new Set(holes.holes.map((h) => h.i))
    const pts = []
    for (let i = 0; i < dataset.n; i++) pts.push(isHole.has(i) ? { time: dataset.time[i], value: 1 } : { time: dataset.time[i] })
    hs.setData(pts)
  }, [dataset, holes])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!result) {
      markersRef.current?.setMarkers([])
      return
    }
    // Past ~40 trades the labels smear over the candles, so only shapes stay.
    const labelled = result.trades.length <= 40
    const markers = []
    for (const t of result.trades) {
      const long = t.side === 'long'
      markers.push({
        time: t.entryTime,
        position: long ? 'belowBar' : 'aboveBar',
        color: long ? UP : DOWN,
        shape: long ? 'arrowUp' : 'arrowDown',
        text: labelled ? (long ? 'L' : 'S') : undefined,
      })
      markers.push({
        time: t.exitTime,
        position: long ? 'aboveBar' : 'belowBar',
        color: t.pnl >= 0 ? '#E8B339' : '#8A9098',
        shape: 'circle',
        text: labelled ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%` : undefined,
      })
    }
    markers.sort((a, b) => a.time - b.time)
    if (!markersRef.current) markersRef.current = createSeriesMarkers(series, markers)
    else markersRef.current.setMarkers(markers)
  }, [result])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (overlayRef.current) {
      chart.removeSeries(overlayRef.current)
      overlayRef.current = null
    }
    if (!showMl || !dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(141,126,224,0.8)',
      lineWidth: 1,
      priceScaleId: 'ml',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset, showMl])

  useEffect(() => {
    if (!selectedTrade || !chartRef.current) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
  }, [selectedTrade])

  return (
    <section className="v4-region" aria-label="Price chart">
      <div className="v4-rh">
        <h2>Price</h2>
        <span className="v4-rh-meta">
          {dataset ? `${dataset.symbol} ${dataset.interval}` : ''}
          {result ? ` · ${result.trades.length.toLocaleString()} trades: arrows are entries, dots exits (amber won, grey lost)` : ''}
        </span>
        <span className="v4-rh-right">
          {holes?.holes.length > 0 && (
            <span className="v4-legend" title="Bars missing inside a session. The axis closes up the gap; the stripe marks where it was.">
              <svg width="6" height="10" aria-hidden="true"><rect width="6" height="10" fill={HOLE} /></svg>
              {holes.holes.length} data gaps
            </span>
          )}
          {dataset?.ml?.pred && (
            <button
              role="switch"
              aria-checked={showMl}
              onClick={() => setMl(!showMl)}
              className="v4-legend hover:text-ink"
              title="Random-forest prediction, out-of-sample bars only, on its own scale"
              style={{ color: showMl ? 'var(--v4-violet)' : undefined }}
            >
              <svg width="12" height="4" aria-hidden="true"><line x1="0" y1="2" x2="12" y2="2" stroke="currentColor" strokeWidth="1.5" /></svg>
              Model prediction {showMl ? 'on' : 'off'}
            </button>
          )}
        </span>
      </div>
      <div className="v4-region-body">
        <div ref={containerRef} className="absolute inset-0" />
        {datasetLoading && !dataset && (
          <div className="absolute inset-0 bg-canvas">
            <Empty>Loading bars…</Empty>
          </div>
        )}
      </div>
    </section>
  )
}
