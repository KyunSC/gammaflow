'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import { Region, Empty } from './ui'
import useGaps from './useGaps'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const GAP = 'rgba(230,232,235,0.13)'
const SEL = 'rgba(232,179,57,0.12)'

/**
 * Price with entry/exit markers (same engine as the ticker page).
 *
 * Difference from components/backtest/PricePanel: missing bars inside a
 * session are inserted as empty slots, so a hole in the data is a visible
 * hole on the chart (with a pale column through it) instead of two candles
 * drawn side by side. The selected trade gets a faint amber span.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const gapSeriesRef = useRef(null)
  const selSeriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)
  const gaps = useGaps()

  // Candles plus whitespace for every missing bar; `logical[i]` is where bar i
  // lands on the chart's logical axis once those slots are in.
  const built = useMemo(() => {
    if (!dataset) return null
    const candles = []
    const bands = []
    const logical = new Int32Array(dataset.n)
    const step = gaps?.step
    let hk = 0
    for (let i = 0; i < dataset.n; i++) {
      if (gaps?.holes && hk < gaps.holes.length && gaps.holes[hk].idx === i) {
        const h = gaps.holes[hk++]
        for (let t = h.from + step; t < h.to; t += step) {
          candles.push({ time: t })
          bands.push({ time: t, value: 1, color: GAP })
        }
      }
      logical[i] = candles.length
      candles.push({
        time: dataset.time[i],
        open: dataset.open[i],
        high: dataset.high[i],
        low: dataset.low[i],
        close: dataset.close[i],
      })
    }
    return { candles, bands, logical }
  }, [dataset, gaps])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#80878f',
        fontFamily: 'var(--v3-font-mono), var(--font-jetbrains-mono), monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(36,40,47,0.55)' },
        horzLines: { color: 'rgba(36,40,47,0.55)' },
      },
      rightPriceScale: { borderColor: '#24282f', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: '#24282f', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5aa3b8', width: 1, style: 3, labelBackgroundColor: '#1c2026' },
        horzLine: { color: '#5aa3b8', width: 1, style: 3, labelBackgroundColor: '#1c2026' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    // Column series sit behind the candles on their own hidden 0..1 scale.
    const sel = chart.addSeries(HistogramSeries, { priceScaleId: 'sel', lastValueVisible: false, priceLineVisible: false, base: 0 })
    const gap = chart.addSeries(HistogramSeries, { priceScaleId: 'gaps', lastValueVisible: false, priceLineVisible: false, base: 0 })
    chart.priceScale('sel').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
    chart.priceScale('gaps').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
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
    gapSeriesRef.current = gap
    selSeriesRef.current = sel
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      gapSeriesRef.current = null
      selSeriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !built?.candles.length) return
    seriesRef.current.setData(built.candles)
    gapSeriesRef.current?.setData(built.bands)
    chartRef.current?.timeScale().fitContent()
  }, [built])

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
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(154,140,230,0.7)',
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
  }, [dataset])

  // Selecting a trade pans to it and shades its span.
  useEffect(() => {
    const sel = selSeriesRef.current
    if (!sel) return
    if (!selectedTrade || !dataset || !built) {
      sel.setData([])
      return
    }
    const pts = []
    for (let i = selectedTrade.entryIdx; i <= selectedTrade.exitIdx && i < dataset.n; i++) {
      pts.push({ time: dataset.time[i], value: 1, color: SEL })
    }
    sel.setData(pts)
    const a = built.logical[selectedTrade.entryIdx]
    const b = built.logical[Math.min(selectedTrade.exitIdx, dataset.n - 1)]
    const pad = Math.max(20, (b - a) * 4)
    chartRef.current?.timeScale().setVisibleLogicalRange({ from: a - pad, to: b + pad })
  }, [selectedTrade, dataset, built])

  const holes = gaps?.holes?.length || 0

  return (
    <Region
      title={dataset ? `Price · ${dataset.symbol} ${dataset.interval}` : 'Price'}
      className="v3-fill"
      aside={
        <span className="v3-legend">
          {result && <span>{result.trades.length.toLocaleString()} trades</span>}
          <span><i className="v3-key v3-key-long" aria-hidden="true">▲</i>long</span>
          <span><i className="v3-key v3-key-short" aria-hidden="true">▼</i>short</span>
          <span title="Exit marker: amber when the trade made money, grey when it lost"><i className="v3-key v3-key-exit" aria-hidden="true">●</i>exit</span>
          {holes > 0 && <span><i className="v3-gap-swatch" aria-hidden="true" />missing bars</span>}
          {dataset?.ml && <span className="v3-violet" title="Random-forest prediction, drawn in the bottom band on its own scale">model pred.</span>}
        </span>
      }
    >
      <div className="v3-chart-wrap">
        <div ref={containerRef} className="v3-chart" role="img" aria-label={dataset ? `Candlestick chart of ${dataset.symbol} with trade markers` : 'Price chart'} />
        {!dataset && (
          <div className="v3-chart-cover">
            {datasetError ? <Empty>No bars to draw.</Empty> : datasetLoading ? <Empty>Loading bars…</Empty> : null}
          </div>
        )}
      </div>
    </Region>
  )
}
