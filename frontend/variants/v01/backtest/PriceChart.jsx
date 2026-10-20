'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import { findGaps } from './gaps'
import { Empty } from './Empty'
import b from './bt.module.css'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const GAP = '#b3a6ff'

/**
 * Copy of components/backtest/PricePanel.jsx. Same chart, markers, model
 * overlay and pan-to-trade. Added: a strip along the top marking every bar
 * that follows a hole in the data (lightweight-charts closes those holes up,
 * so without it they are invisible), and entry/exit price lines on the
 * selected trade.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const gapSeriesRef = useRef(null)
  const priceLinesRef = useRef([])

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)

  const gaps = useMemo(() => findGaps(dataset), [dataset])

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
        textColor: '#a0a7af',
        fontFamily: 'var(--v01-mono), var(--font-jetbrains-mono), monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: 'rgba(34,38,45,0.5)' }, horzLines: { color: 'rgba(34,38,45,0.5)' } },
      rightPriceScale: { borderColor: '#22262D', scaleMargins: { top: 0.12, bottom: 0.12 } },
      timeScale: { borderColor: '#22262D', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5aa3b8', width: 1, style: 3, labelBackgroundColor: '#1c2027' },
        horzLine: { color: '#5aa3b8', width: 1, style: 3, labelBackgroundColor: '#1c2027' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
      priceLineVisible: false, lastValueVisible: false,
    })
    const gapSeries = chart.addSeries(HistogramSeries, {
      color: GAP, priceScaleId: 'gaps', lastValueVisible: false, priceLineVisible: false, base: 0,
    })
    chart.priceScale('gaps').applyOptions({ scaleMargins: { top: 0, bottom: 0.95 }, visible: false })
    chartRef.current = chart
    seriesRef.current = series
    gapSeriesRef.current = gapSeries
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
      gapSeriesRef.current = null
      priceLinesRef.current = []
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current) return
    seriesRef.current.setData(candles)
    if (candles.length) chartRef.current?.timeScale().fitContent()
  }, [candles])

  useEffect(() => {
    if (!gapSeriesRef.current) return
    gapSeriesRef.current.setData(gaps && dataset ? gaps.holes.map((h) => ({ time: dataset.time[h.idx], value: 1 })) : [])
  }, [gaps, dataset])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!result) {
      markersRef.current?.setMarkers([])
      return
    }
    const labelled = result.trades.length <= 40
    const markers = []
    for (const t of result.trades) {
      const long = t.side === 'long'
      markers.push({ time: t.entryTime, position: long ? 'belowBar' : 'aboveBar', color: long ? UP : DOWN, shape: long ? 'arrowUp' : 'arrowDown', text: labelled ? (long ? 'L' : 'S') : undefined })
      markers.push({ time: t.exitTime, position: long ? 'aboveBar' : 'belowBar', color: t.pnl >= 0 ? '#E8B339' : '#8A9098', shape: 'circle', text: labelled ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%` : undefined })
    }
    markers.sort((a, c) => a.time - c.time)
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
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, { color: 'rgba(124,107,214,0.75)', lineWidth: 1, priceScaleId: 'ml', lastValueVisible: false, priceLineVisible: false })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    for (const l of priceLinesRef.current) series.removePriceLine(l)
    priceLinesRef.current = []
    if (!selectedTrade || !chartRef.current) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
    priceLinesRef.current = [
      series.createPriceLine({ price: selectedTrade.entryPrice, color: '#a0a7af', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'in' }),
      series.createPriceLine({ price: selectedTrade.exitPrice, color: selectedTrade.pnl >= 0 ? '#E8B339' : '#8A9098', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'out' }),
    ]
  }, [selectedTrade])

  return (
    <section className={b.region} aria-label="Price chart with trades">
      <header className={b.regionHead}>
        <h2 className={b.regionTitle}>Price{dataset ? ` · ${dataset.symbol} ${dataset.interval}` : ''}</h2>
        {result && <span className={b.regionMeta}>{result.trades.length} trades</span>}
        <span className={b.regionRight}>
          <span className={`${b.legend} ${b.hideNarrow}`}><span className="text-pos">▲</span><span className="text-neg">▼</span> entry</span>
          <span className={`${b.legend} ${b.hideNarrow}`}><span className="text-amber">●</span> exit, win <span className="text-muted">●</span> loss</span>
          {dataset?.ml && <span className={`${b.legend} ${b.hideNarrow}`}><span style={{ color: '#9d90e8' }}>—</span> model prediction</span>}
          {gaps?.holes.length > 0 && (
            <span className={b.legend} title="One tick per hole inside a session; the chart closes the hole up, so the candles either side look adjacent">
              <span style={{ color: GAP }}>▮</span> {gaps.holes.length} data holes
            </span>
          )}
        </span>
      </header>
      <div className={b.regionBody}>
        <div ref={containerRef} className="h-full w-full" />
        {datasetLoading && !dataset && (
          <div className="absolute inset-0 bg-canvas">
            <Empty>Loading bars…</Empty>
          </div>
        )}
      </div>
    </section>
  )
}
