'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import { scanGaps } from '../gaps'
import { Empty } from './ui'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const AMBER = '#e8b339'
const LOSER = '#8f959c'
const HOLE = 'rgba(233,231,226,0.55)'

/**
 * Price with the trades on it. Same engine as the ticker page, so a trade sits
 * on the candles the engine filled against. Two additions over the original:
 * a strip along the bottom marks every bar that follows missing bars (the
 * chart otherwise closes the hole), and the selected trade gets its entry and
 * exit drawn as price lines.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const holesRef = useRef(null)
  const linesRef = useRef([])

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const gaps = useMemo(() => scanGaps(dataset), [dataset])

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
        textColor: '#9da2a8',
        fontFamily: 'var(--v7-font-mono), var(--font-jetbrains-mono), monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: 'rgba(35,38,44,0.55)' }, horzLines: { color: 'rgba(35,38,44,0.55)' } },
      rightPriceScale: { borderColor: '#23262c', scaleMargins: { top: 0.08, bottom: 0.14 } },
      timeScale: { borderColor: '#23262c', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#4a90a4', width: 1, style: 3, labelBackgroundColor: '#1a1d21' },
        horzLine: { color: '#4a90a4', width: 1, style: 3, labelBackgroundColor: '#1a1d21' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
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
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
      holesRef.current = null
      linesRef.current = []
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  // Hole strip: one thin bar on every candle that follows missing bars.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (holesRef.current) {
      chart.removeSeries(holesRef.current)
      holesRef.current = null
    }
    if (!dataset || !gaps || !gaps.holes) return
    const strip = chart.addSeries(HistogramSeries, {
      color: HOLE,
      priceScaleId: 'holes',
      lastValueVisible: false,
      priceLineVisible: false,
      base: 0,
    })
    chart.priceScale('holes').applyOptions({ scaleMargins: { top: 0.955, bottom: 0 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) if (gaps.after[i]) pts.push({ time: dataset.time[i], value: 1 })
    strip.setData(pts)
    holesRef.current = strip
  }, [dataset, gaps])

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
        color: t.pnl >= 0 ? AMBER : LOSER,
        shape: 'circle',
        text: labelled ? `${t.pnl >= 0 ? '+' : '−'}${Math.abs(t.pnlPct * 100).toFixed(2)}%` : undefined,
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
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(143,128,224,0.7)',
      lineWidth: 1,
      priceScaleId: 'ml',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.84, bottom: 0.06 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  // Selected trade: pan to it and draw its entry and exit prices.
  useEffect(() => {
    const series = seriesRef.current
    for (const l of linesRef.current) {
      try { series?.removePriceLine(l) } catch { /* series gone */ }
    }
    linesRef.current = []
    if (!selectedTrade || !chartRef.current || !series) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
    const scale = result?.config?.costs?.instrument?.priceScale > 0 ? result.config.costs.instrument.priceScale : 1
    linesRef.current = [
      series.createPriceLine({ price: selectedTrade.entryPrice / scale, color: '#4a90a4', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `#${selectedTrade.n ?? ''} in` }),
      series.createPriceLine({ price: selectedTrade.exitPrice / scale, color: selectedTrade.pnl >= 0 ? AMBER : LOSER, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'out' }),
    ]
  }, [selectedTrade, result])

  return (
    <section className="v7-block v7-price" aria-label="Price chart with trades">
      <header className="v7-block-head">
        <h3>Price{dataset ? ` · ${dataset.symbol} ${dataset.interval}` : ''}</h3>
        <ul className="v7-legend" aria-label="Legend">
          <li><span className="v7-key v7-key-up" aria-hidden="true">▲</span>long</li>
          <li><span className="v7-key v7-key-down" aria-hidden="true">▼</span>short</li>
          <li><span className="v7-key v7-key-dot v7-key-win" aria-hidden="true" />exit, won</li>
          <li><span className="v7-key v7-key-dot v7-key-loss" aria-hidden="true" />exit, lost</li>
          {gaps?.holes > 0 && <li title="Each tick along the bottom marks a bar that follows missing bars"><span className="v7-key v7-key-hole" aria-hidden="true" />bar after a hole</li>}
          {dataset?.ml && <li title="Random-forest prediction, on its own scale near the bottom of the chart"><span className="v7-key v7-key-ml" aria-hidden="true" />RF prediction</li>}
        </ul>
      </header>
      <div className="v7-block-body v7-chart-wrap">
        <div ref={containerRef} className="v7-chart" />
        {datasetLoading && !dataset && (
          <div className="v7-chart-cover">
            <Empty>Loading bars…</Empty>
          </div>
        )}
      </div>
    </section>
  )
}
