'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../lib/backtest/store'
import { findGaps } from './gaps'

const UP = '#5cbf60'
const DOWN = '#ff6b6b'
const AMBER = '#e8b339'
const GREY = '#8a9098'
const GAP_FILL = 'rgba(232,179,57,0.12)'

const NY = 'America/New_York'
const fmtTick = {
  year: new Intl.DateTimeFormat('en-US', { timeZone: NY, year: 'numeric' }),
  month: new Intl.DateTimeFormat('en-US', { timeZone: NY, month: 'short' }),
  day: new Intl.DateTimeFormat('en-US', { timeZone: NY, month: 'short', day: 'numeric' }),
  time: new Intl.DateTimeFormat('en-US', { timeZone: NY, hour: '2-digit', minute: '2-digit', hour12: false }),
  full: new Intl.DateTimeFormat('en-US', { timeZone: NY, weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }),
}

/**
 * Price with the run's trades. Same engine as the original panel, with two
 * honesty changes: the time axis is New York time (the blotter's clock), and
 * missing bars inside a session are kept as empty slots and shaded, so a hole
 * in the data looks like a hole instead of being closed up.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const gapSeriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)

  const gaps = useMemo(() => findGaps(dataset), [dataset])

  const { candles, gapBars } = useMemo(() => {
    if (!dataset) return { candles: [], gapBars: [] }
    const out = []
    const holes = []
    const step = gaps?.supported ? gaps.step : 0
    for (let i = 0; i < dataset.n; i++) {
      if (step && i && gaps.cum[i] > gaps.cum[i - 1]) {
        // Whitespace items: the slot exists on the axis, nothing is drawn in it.
        for (let k = 1; k <= gaps.cum[i] - gaps.cum[i - 1]; k++) {
          const t = dataset.time[i - 1] + k * step
          out.push({ time: t })
          holes.push({ time: t, value: 1, color: GAP_FILL })
        }
      }
      out.push({ time: dataset.time[i], open: dataset.open[i], high: dataset.high[i], low: dataset.low[i], close: dataset.close[i] })
    }
    return { candles: out, gapBars: holes }
  }, [dataset, gaps])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#8a9098',
        fontFamily: 'var(--font-jetbrains-mono), ui-monospace, monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      localization: { timeFormatter: (t) => fmtTick.full.format(new Date(t * 1000)) },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(32,36,42,0.9)' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: {
        borderColor: '#20242a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        minBarSpacing: 0.05,
        tickMarkFormatter: (t, type) => {
          const d = new Date(t * 1000)
          if (type === 0) return fmtTick.year.format(d)
          if (type === 1) return fmtTick.month.format(d)
          if (type === 2) return fmtTick.day.format(d)
          return fmtTick.time.format(d)
        },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5aa3b8', width: 1, style: 3, labelBackgroundColor: '#1a1d23' },
        horzLine: { color: '#5aa3b8', width: 1, style: 3, labelBackgroundColor: '#1a1d23' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    const gapSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'gaps',
      lastValueVisible: false,
      priceLineVisible: false,
      base: 0,
    })
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
    gapSeriesRef.current = gapSeries
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      gapSeriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current) return
    seriesRef.current.setData(candles)
    gapSeriesRef.current?.setData(gapBars)
    if (candles.length) chartRef.current?.timeScale().fitContent()
  }, [candles, gapBars])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!result) {
      markersRef.current?.setMarkers([])
      return
    }
    // Past ~40 trades the labels smear into each other; keep only the shapes.
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
        color: t.pnl >= 0 ? AMBER : GREY,
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
      color: 'rgba(154,140,240,0.75)',
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

  // Selecting a trade pans here. Logical indices include the empty gap slots.
  useEffect(() => {
    if (!selectedTrade || !chartRef.current) return
    const li = (i) => i + (gaps?.supported ? gaps.cum[i] : 0)
    const from = li(selectedTrade.entryIdx)
    const to = li(selectedTrade.exitIdx)
    const pad = Math.max(20, (to - from) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: from - pad, to: to + pad })
  }, [selectedTrade, gaps])

  const status = datasetError ? 'No bars to draw.' : datasetLoading && !dataset ? 'Loading bars…' : null

  return (
    <figure className="flex h-full min-h-0 flex-col" aria-label={dataset ? `Price chart, ${dataset.symbol} ${dataset.interval}` : 'Price chart'}>
      <figcaption className="flex shrink-0 flex-wrap items-baseline gap-x-4 gap-y-0.5 px-4 pt-2 text-[11.5px] text-dim">
        <span className="v9-h">Price{dataset ? ` · ${dataset.symbol} ${dataset.interval}` : ''}</span>
        <span>New York time</span>
        <span className="flex-1" />
        {result && (
          <>
            <span><span className="text-pos">▲</span> long <span className="text-neg">▼</span> short entry</span>
            <span><span className="text-amber">●</span> winning <span className="text-[#8a9098]">●</span> losing exit</span>
          </>
        )}
        {gaps?.supported && gaps.missingBars > 0 && (
          <span title="Empty slots where the dataset has no bar. They are left empty, not filled.">
            <span className="mr-1 inline-block h-2.5 w-2 align-[-1px]" style={{ background: GAP_FILL }} />
            missing bars ({gaps.missingBars.toLocaleString()})
          </span>
        )}
        {dataset?.ml?.pred && (
          <span title="Random-forest prediction for the next bars, drawn on its own scale at the bottom. Only present on out-of-sample bars.">
            <span className="text-violet">―</span> model prediction
          </span>
        )}
      </figcaption>
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="h-full w-full" />
        {status && (
          <div className="absolute inset-0 flex items-center justify-center bg-canvas text-[12px] text-dim" role="status">
            {status}
          </div>
        )}
      </div>
    </figure>
  )
}
