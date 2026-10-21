'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import Section, { Empty, Legend } from './Section'
import { gapsFor } from './gaps'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const AMBER = '#E8B339'

/**
 * Price with entry/exit markers (same chart engine as the ticker page), plus
 * an amber tick wherever bars are missing inside a session. The chart's time
 * axis is bar-indexed, so without the ticks a hole looks like any other pair
 * of adjacent candles.
 */
export default function PriceChart({ id }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const [gapXs, setGapXs] = useState({ xs: [], h: 0, w: 0, spacing: 0 })

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)
  const gaps = gapsFor(dataset)

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
        textColor: '#8A929C',
        fontFamily: 'var(--font-jetbrains-mono), monospace',
        fontSize: 10,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(34,38,45,0.7)' } },
      rightPriceScale: { borderColor: '#22262D', scaleMargins: { top: 0.08, bottom: 0.2 } },
      // Default minBarSpacing (0.5px) cannot fit ~3k bars in a laptop-width pane,
      // so "fit" silently dropped the first weeks. Allow thinner bars.
      timeScale: { borderColor: '#22262D', timeVisible: true, secondsVisible: false, rightOffset: 4, minBarSpacing: 0.05 },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5AA3B8', width: 1, style: 3, labelBackgroundColor: '#171a20' },
        horzLine: { color: '#5AA3B8', width: 1, style: 3, labelBackgroundColor: '#171a20' },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
      priceLineVisible: false, lastValueVisible: false,
    })
    chartRef.current = chart
    seriesRef.current = series
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
    // autoSize settles the pane width a frame later (e.g. after switching
    // layouts); fit again once it has, or the first weeks sit off-screen.
    const t = setTimeout(() => chartRef.current?.timeScale().fitContent(), 120)
    return () => clearTimeout(t)
  }, [candles])

  // Missing-bar ticks follow pan and zoom.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const ts = chart.timeScale()
    // Measure after the chart has laid out: scale sizes read 0 synchronously.
    let raf = 0
    const update = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(measure)
    }
    const measure = () => {
      if (!gaps.idx.length || !containerRef.current) {
        setGapXs((g) => (g.xs.length ? { xs: [], h: 0, w: 0, spacing: 0 } : g))
        return
      }
      let w = 0
      let h = 0
      try {
        w = containerRef.current.clientWidth - chart.priceScale('right').width()
        h = containerRef.current.clientHeight - ts.height()
      } catch { return }
      // Map bar index to pixels from the visible logical range directly.
      const r = ts.getVisibleLogicalRange()
      if (!r || !(r.to > r.from) || !(w > 0)) return
      const spacing = w / (r.to - r.from)
      const xs = []
      for (const g of gaps.idx) {
        const x = (g - 0.5 - r.from) * spacing
        if (x >= 0 && x <= w) xs.push(Math.round(x))
      }
      setGapXs({ xs, h, w, spacing })
    }
    update()
    const late = setTimeout(update, 250)
    ts.subscribeVisibleLogicalRangeChange(update)
    ts.subscribeSizeChange(update)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(late)
      try {
        ts.unsubscribeVisibleLogicalRangeChange(update)
        ts.unsubscribeSizeChange(update)
      } catch { /* chart already removed */ }
    }
  }, [gaps, candles])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!result) {
      markersRef.current?.setMarkers([])
      return
    }
    // Past ~40 trades labels smear into each other and hide the candles.
    const labelled = result.trades.length <= 40
    const markers = []
    for (const t of result.trades) {
      const long = t.side === 'long'
      markers.push({ time: t.entryTime, position: long ? 'belowBar' : 'aboveBar', color: long ? UP : DOWN, shape: long ? 'arrowUp' : 'arrowDown', text: labelled ? (long ? 'L' : 'S') : undefined })
      markers.push({
        time: t.exitTime,
        position: long ? 'aboveBar' : 'belowBar',
        color: t.pnl >= 0 ? AMBER : '#8A929C',
        shape: 'circle',
        text: labelled ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%` : undefined,
      })
    }
    markers.sort((a, b) => a.time - b.time)
    if (!markersRef.current) markersRef.current = createSeriesMarkers(series, markers)
    else markersRef.current.setMarkers(markers)
  }, [result])

  // Model prediction, in its own band at the bottom of the pane.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (overlayRef.current) {
      chart.removeSeries(overlayRef.current)
      overlayRef.current = null
    }
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(147,133,224,0.8)', lineWidth: 1, priceScaleId: 'ml', lastValueVisible: false, priceLineVisible: false,
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

  useEffect(() => {
    if (!selectedTrade || !chartRef.current) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
  }, [selectedTrade])

  const showLines = gapXs.spacing >= 4

  return (
    <Section
      id={id}
      title="Price"
      meta={dataset ? `${dataset.symbol} ${dataset.interval} · axis in UTC` : null}
      right={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {result && <span className="l10-legend">{result.trades.length} trades · arrow entry, dot exit (amber = winner)</span>}
          {gaps.idx.length > 0 && <Legend color={AMBER} label="missing bars" tick />}
          {dataset?.ml && <Legend color="#9385E0" label="model prediction (bottom band)" />}
          <button type="button" className="l10-link text-[11px]" onClick={() => chartRef.current?.timeScale().fitContent()}>
            Fit all
          </button>
        </span>
      }
      scroll={false}
    >
      <div className="relative h-full w-full">
        <div ref={containerRef} className="h-full w-full" />
        {gapXs.xs.length > 0 && (
          <div className="l10-gap-layer" style={{ width: gapXs.w, height: gapXs.h }} aria-hidden="true">
            {gapXs.xs.map((x, k) => (
              <span key={k}>
                {showLines && <span className="l10-gap-line" style={{ left: x, height: gapXs.h }} />}
                <span className="l10-gap-tick" style={{ left: x - 1, top: gapXs.h - 7 }} />
              </span>
            ))}
          </div>
        )}
        {!dataset && (
          <div className="absolute inset-0 bg-canvas">
            <Empty>{datasetLoading ? 'Loading bars…' : datasetError ? 'No bars loaded.' : 'No data.'}</Empty>
          </div>
        )}
      </div>
    </Section>
  )
}
