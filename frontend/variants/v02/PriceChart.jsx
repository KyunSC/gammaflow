'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../lib/backtest/store'
import { holesFor } from './gaps'
import s from './bt.module.css'

const UP = '#5cb860'
const DOWN = '#ff6b6b'
const HOLE = "rgba(232, 179, 57, 0.13)"

/**
 * Price with fills, as in the original PricePanel, plus the one thing the
 * original could not show: lightweight-charts spaces bars by index, so a
 * missing half hour is drawn as continuous price. Each intraday hole gets a
 * full-height stripe on its own hidden scale so it can't be mistaken for data.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const holesRef = useRef(null)

  const dataset = useBacktest((st) => st.dataset)
  const result = useBacktest((st) => st.result)
  const selectedTrade = useBacktest((st) => st.selectedTrade)
  const datasetLoading = useBacktest((st) => st.datasetLoading)
  const datasetError = useBacktest((st) => st.datasetError)
  const gaps = holesFor(dataset)

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
        textColor: '#8a9098',
        fontFamily: 'var(--font-jetbrains-mono), monospace',
        fontSize: 10,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(31,35,40,0.9)' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.1 } },
      timeScale: { borderColor: '#1f2328', timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5a9fb3', width: 1, style: 3, labelBackgroundColor: '#191c21' },
        horzLine: { color: '#5a9fb3', width: 1, style: 3, labelBackgroundColor: '#191c21' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    // Holes first, so candles draw on top of the stripes.
    const holes = chart.addSeries(HistogramSeries, {
      priceScaleId: 'holes',
      color: HOLE,
      base: 0,
      lastValueVisible: false,
      priceLineVisible: false,
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
    holesRef.current = holes
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

  useEffect(() => {
    if (!holesRef.current) return
    if (!dataset || !gaps?.holes.length) {
      holesRef.current.setData([])
      return
    }
    holesRef.current.setData(gaps.holes.map((h) => ({ time: dataset.time[h.idx], value: 1 })))
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
        color: t.pnl >= 0 ? '#e8b339' : '#8a9098',
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
      color: 'rgba(139,124,224,0.7)',
      lineWidth: 1,
      priceScaleId: 'ml',
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.86, bottom: 0 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  useEffect(() => {
    if (!selectedTrade || !chartRef.current) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
  }, [selectedTrade])

  return (
    <div className={s.pane}>
      <div className={s.paneHead}>
        <span className={s.paneTitle}>Price{dataset ? ` · ${dataset.symbol} ${dataset.interval}` : ''}</span>
        {result && (
          <>
            <span className={s.legend}><span style={{ color: UP }}>▲</span> long <span style={{ color: DOWN }}>▼</span> short entry</span>
            <span className={s.legend}><span className="text-amber">●</span> winning <span className="text-muted">●</span> losing exit</span>
          </>
        )}
        {gaps?.holes.length > 0 && (
          <span className={s.legend} title="Bars missing inside a session. The chart joins the bars either side, so price looks continuous across the stripe.">
            <span style={{ display: 'inline-block', width: 8, height: 10, background: HOLE }} /> missing bars ({gaps.holes.length} holes)
          </span>
        )}
        {dataset?.ml && (
          <span className={s.legend} title="Random-forest return prediction, drawn on its own unlabelled scale along the bottom; present only on out-of-sample bars">
            <svg width="14" height="4" aria-hidden="true"><line x1="0" y1="2" x2="14" y2="2" stroke="#8b7ce0" strokeWidth="1.5" /></svg>
            model prediction (own scale)
          </span>
        )}
        {selectedTrade && <span className="ml-auto text-amber">showing trade #{selectedTrade.n ?? ''}</span>}
      </div>
      <div className={s.paneBody}>
        {/* Always mounted: the chart's one-shot init needs the ref. */}
        <div ref={containerRef} className="h-full w-full" />
        {!dataset && (
          <div className="absolute inset-0 flex items-center justify-center bg-canvas px-6 text-center text-[12px] text-dim">
            {datasetLoading ? 'Loading bars…' : datasetError ? 'No bars loaded. See the message above.' : 'No dataset.'}
          </div>
        )}
      </div>
    </div>
  )
}
