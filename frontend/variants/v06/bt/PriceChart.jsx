'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtNum, fmtPct, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import { EmptyState } from '../../../components/backtest/Panel'
import Section from './Section'
import { useGaps } from './ui'
import { tradeMissing } from '../gaps'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const GAP = 'rgba(214, 220, 228, 0.24)'
const SPAN = 'rgba(232, 179, 57, 0.13)'

/**
 * Price with the run's entries and exits — the same engine as the original
 * panel — plus two things it could not show: a grey line wherever bars are
 * missing (the index-based time axis otherwise hides the hole), and a band
 * over the bars of the selected trade.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const gapRef = useRef(null)
  const spanRef = useRef(null)

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const gaps = useGaps()

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
        textColor: '#959ca6',
        fontFamily: getComputedStyle(containerRef.current).getPropertyValue('--v06-mono') || 'monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(36,40,47,0.7)' } },
      rightPriceScale: { borderColor: '#24282f', scaleMargins: { top: 0.1, bottom: 0.12 } },
      timeScale: { borderColor: '#24282f', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#4A90A4', width: 1, style: 3, labelBackgroundColor: '#1b1e23' },
        horzLine: { color: '#4A90A4', width: 1, style: 3, labelBackgroundColor: '#1b1e23' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    // Underlays first so the candles draw on top of them.
    const span = chart.addSeries(HistogramSeries, { color: SPAN, priceScaleId: 'v6span', lastValueVisible: false, priceLineVisible: false, base: 0 })
    const gapS = chart.addSeries(HistogramSeries, { color: GAP, priceScaleId: 'v6gap', lastValueVisible: false, priceLineVisible: false, base: 0 })
    chart.priceScale('v6span').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
    chart.priceScale('v6gap').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
      priceLineVisible: false, lastValueVisible: false,
    })
    chartRef.current = chart
    seriesRef.current = series
    gapRef.current = gapS
    spanRef.current = span
    return () => {
      chart.remove()
      chartRef.current = seriesRef.current = markersRef.current = overlayRef.current = gapRef.current = spanRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  // Missing-bar lines: one at the first bar after each hole.
  useEffect(() => {
    if (!gapRef.current) return
    if (!dataset || !gaps?.holes.length) return gapRef.current.setData([])
    gapRef.current.setData(gaps.holes.map((h) => ({ time: dataset.time[h.idx], value: 1 })))
  }, [dataset, gaps])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!result) {
      markersRef.current?.setMarkers([])
      return
    }
    // Labels smear into each other past ~40 trades; shapes alone stay legible.
    const labelled = result.trades.length <= 40
    const markers = []
    for (const t of result.trades) {
      const long = t.side === 'long'
      markers.push({ time: t.entryTime, position: long ? 'belowBar' : 'aboveBar', color: long ? UP : DOWN, shape: long ? 'arrowUp' : 'arrowDown', text: labelled ? (long ? 'L' : 'S') : undefined })
      markers.push({ time: t.exitTime, position: long ? 'aboveBar' : 'belowBar', color: t.pnl >= 0 ? '#E8B339' : '#8A9098', shape: 'circle', text: labelled ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%` : undefined })
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
    const line = chart.addSeries(LineSeries, { color: 'rgba(124,107,214,0.8)', lineWidth: 1, priceScaleId: 'ml', lastValueVisible: false, priceLineVisible: false })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  // Selecting a trade pans to it and shades its bars.
  useEffect(() => {
    const span = spanRef.current
    if (span) {
      if (!selectedTrade || !dataset) span.setData([])
      else {
        const pts = []
        for (let i = selectedTrade.entryIdx; i <= selectedTrade.exitIdx && i < dataset.n; i++) pts.push({ time: dataset.time[i], value: 1 })
        span.setData(pts)
      }
    }
    if (!selectedTrade || !chartRef.current) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
  }, [selectedTrade, dataset])

  const t = selectedTrade
  const tMissing = t ? tradeMissing(gaps, t) : 0

  return (
    <Section
      title="Price"
      meta={dataset ? `${dataset.symbol} ${dataset.interval}` : null}
      right={
        <span className="v6-legend" aria-label="Chart legend">
          {result && <span><i className="v6-sw" style={{ background: UP }} />entry</span>}
          {result && <span><i className="v6-sw v6-sw-dot" style={{ background: '#E8B339' }} />winning exit</span>}
          {result && <span><i className="v6-sw v6-sw-dot" style={{ background: '#8A9098' }} />losing exit</span>}
          {gaps?.holes.length > 0 && <span><i className="v6-sw v6-sw-bar" style={{ background: GAP }} />missing bars</span>}
          {dataset?.ml && <span><i className="v6-sw" style={{ background: '#7c6bd6' }} />model prediction (bottom)</span>}
        </span>
      }
      className="h-full"
      bodyClassName="flex flex-col"
      scroll={false}
    >
      <div className="relative min-h-0 w-full flex-1">
        <div ref={containerRef} className="h-full w-full" role="img" aria-label={dataset ? `${dataset.symbol} ${dataset.interval} candles with trade markers` : 'Price chart'} />
        {datasetLoading && !dataset && (
          <div className="absolute inset-0 bg-canvas">
            <EmptyState>Loading bars…</EmptyState>
          </div>
        )}
      </div>
      {t && (
        <div className="v6-trade-line" aria-live="polite">
          <span className="v6-ink">Trade {t.n ?? ''}</span>
          <span className={t.side === 'long' ? 'text-pos' : 'text-neg'}>{t.side}</span>
          <span className="num">{fmtTime(t.entryTime)} → {fmtTime(t.exitTime)}</span>
          <span className="num">{fmtNum(t.entryPrice, 2)} → {fmtNum(t.exitPrice, 2)}</span>
          <span className={`num ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
          <span className={`num ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
          <span>exit: {t.reason}</span>
          {tMissing > 0 && <span className="v6-warn">held across {tMissing} missing bar{tMissing === 1 ? '' : 's'}</span>}
          <button type="button" className="v6-link ml-auto" onClick={() => selectTrade(null)}>Clear</button>
        </div>
      )}
    </Section>
  )
}
