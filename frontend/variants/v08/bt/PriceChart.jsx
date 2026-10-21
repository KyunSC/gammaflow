'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtPct, fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import { findGaps, missingInSpan } from './gaps'
import { Region, Note } from './ui'
import { FOCUS_EVENT } from './GapsList'

const UP = '#5cbf60'
const DOWN = '#ff7070'
const WIN = '#e8b339'
const LOSS = '#9aa1aa'
// Below this many visible bars each hole also gets a full-height line; above
// it the lines would merge into a grey wash, so only the rail ticks remain.
const LINE_BARS = 600

// Axis and crosshair in New York time, matching the trade list. The engine,
// the session rules and the blotter all work in ET; a UTC axis made 09:30
// read as 13:30.
const ET = 'America/New_York'
const fmtEt = (opts) => new Intl.DateTimeFormat('en-US', { timeZone: ET, ...opts })
const etYear = fmtEt({ year: 'numeric' })
const etMonth = fmtEt({ month: 'short' })
const etDay = fmtEt({ month: 'short', day: 'numeric' })
const etTime = fmtEt({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const etFull = fmtEt({ weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const tickMark = (time, type) => {
  const d = new Date(time * 1000)
  if (type === 0) return etYear.format(d)
  if (type === 1) return etMonth.format(d)
  if (type === 2) return etDay.format(d)
  return etTime.format(d)
}

/**
 * Price with entries and exits, on the same charting engine as the ticker page.
 *
 * The chart is index-based, so a hole in the bars is invisible: the candles
 * either side of it sit next to each other. The rail under the candles marks
 * every hole, and when zoomed in each one also gets a dashed line, so a trade
 * that straddles missing data can be seen doing so.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const [gapXs, setGapXs] = useState({ xs: [], lines: false, axis: 26 })

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const gaps = findGaps(dataset)

  const candles = useMemo(() => {
    if (!dataset) return []
    const out = new Array(dataset.n)
    for (let i = 0; i < dataset.n; i++) {
      out[i] = { time: dataset.time[i], open: dataset.open[i], high: dataset.high[i], low: dataset.low[i], close: dataset.close[i] }
    }
    return out
  }, [dataset])

  const placeGaps = useCallback(() => {
    const chart = chartRef.current
    if (!chart || !gaps || !gaps.holes.length) {
      setGapXs((g) => (g.xs.length ? { xs: [], lines: false, axis: g.axis } : g))
      return
    }
    const ts = chart.timeScale()
    const range = ts.getVisibleLogicalRange()
    const width = containerRef.current?.clientWidth || 0
    if (!range) return
    const xs = []
    for (const h of gaps.holes) {
      if (h.idx < range.from - 1 || h.idx > range.to + 1) continue
      // logicalToCoordinate only takes whole bar indexes; the hole sits
      // halfway between the bar before it and the bar after it.
      const a = ts.logicalToCoordinate(h.idx - 1)
      const b = ts.logicalToCoordinate(h.idx)
      if (a === null || b === null) continue
      const x = (a + b) / 2
      if (x < 0 || x > width) continue
      xs.push({ x, missing: h.missing, from: h.from, to: h.to })
    }
    setGapXs({ xs, lines: range.to - range.from < LINE_BARS, axis: ts.height() || 26 })
  }, [gaps])

  // Chart lifecycle
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#9aa1aa',
        fontFamily: 'var(--font-jetbrains-mono), ui-monospace, monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      localization: { locale: 'en-US', timeFormatter: (t) => `${etFull.format(new Date(t * 1000))} ET` },
      grid: {
        vertLines: { color: 'rgba(35,39,46,0.55)' },
        horzLines: { color: 'rgba(35,39,46,0.55)' },
      },
      rightPriceScale: { borderColor: '#23272e', scaleMargins: { top: 0.1, bottom: 0.14 } },
      timeScale: { borderColor: '#23272e', timeVisible: true, secondsVisible: false, rightOffset: 4, tickMarkFormatter: tickMark },
      crosshair: {
        mode: 0,
        vertLine: { color: '#5aa5ba', width: 1, style: 3, labelBackgroundColor: '#1a1d22' },
        horzLine: { color: '#5aa5ba', width: 1, style: 3, labelBackgroundColor: '#1a1d22' },
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
    }
  }, [])

  // Re-place the hole markers whenever the view pans, zooms or resizes.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const ts = chart.timeScale()
    // The chart lays itself out a frame later than the callbacks fire, so
    // coordinates are read on the next frame.
    let raf = 0
    const later = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(placeGaps)
    }
    ts.subscribeVisibleLogicalRangeChange(later)
    ts.subscribeSizeChange(later)
    later()
    return () => {
      cancelAnimationFrame(raf)
      ts.unsubscribeVisibleLogicalRangeChange(later)
      ts.unsubscribeSizeChange(later)
    }
  }, [placeGaps])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
    requestAnimationFrame(placeGaps)
  }, [candles, placeGaps])

  // Trade markers. Labels only while they still fit; the selected trade is
  // always labelled and drawn larger.
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
      const sel = selectedTrade && selectedTrade.entryIdx === t.entryIdx
      markers.push({
        time: t.entryTime,
        position: long ? 'belowBar' : 'aboveBar',
        color: long ? UP : DOWN,
        shape: long ? 'arrowUp' : 'arrowDown',
        text: labelled || sel ? (long ? 'L' : 'S') : undefined,
        size: sel ? 2 : 1,
      })
      markers.push({
        time: t.exitTime,
        position: long ? 'aboveBar' : 'belowBar',
        color: t.pnl >= 0 ? WIN : LOSS,
        shape: 'circle',
        text: labelled || sel ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%` : undefined,
        size: sel ? 2 : 0.6,
      })
    }
    markers.sort((a, b) => a.time - b.time)
    if (!markersRef.current) markersRef.current = createSeriesMarkers(series, markers)
    else markersRef.current.setMarkers(markers)
  }, [result, selectedTrade])

  // Model prediction overlay (research plane only), on its own hidden scale.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (overlayRef.current) {
      chart.removeSeries(overlayRef.current)
      overlayRef.current = null
    }
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(149,133,230,0.7)',
      lineWidth: 1,
      priceScaleId: 'ml',
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.86, bottom: 0.02 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  // The data-gaps list asks for a session by event, so it needs no chart ref.
  useEffect(() => {
    const onFocus = (e) => chartRef.current?.timeScale().setVisibleLogicalRange(e.detail)
    window.addEventListener(FOCUS_EVENT, onFocus)
    return () => window.removeEventListener(FOCUS_EVENT, onFocus)
  }, [])

  // Selecting a trade in the list pans here.
  useEffect(() => {
    if (!selectedTrade || !chartRef.current) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selectedTrade.entryIdx - pad, to: selectedTrade.exitIdx + pad })
  }, [selectedTrade])

  const sel = result && selectedTrade ? selectedTrade : null
  const selNo = sel ? result.trades.findIndex((t) => t.entryIdx === sel.entryIdx) + 1 : 0
  const selMissing = sel ? missingInSpan(gaps, sel.entryIdx, sel.exitIdx) : 0

  return (
    <Region
      className="v8-fill"
      title={dataset ? `Price · ${dataset.symbol} ${dataset.interval}` : 'Price'}
      aside={
        <span className="v8-legend">
          <span><i className="v8-key-up" aria-hidden>▲</i> long</span>
          <span><i className="v8-key-dn" aria-hidden>▼</i> short</span>
          <span><i className="v8-key-win" aria-hidden>●</i> exit, win</span>
          <span><i className="v8-key-loss" aria-hidden>●</i> exit, loss</span>
          {gaps && gaps.holes.length > 0 && (
            <span><i className="v8-key-gap" aria-hidden>┆</i> missing bars</span>
          )}
          {dataset?.ml && <span className="text-violet" title="Random-forest prediction, on its own scale along the bottom">— model prediction</span>}
          <button type="button" className="v8-textbtn" onClick={() => chartRef.current?.timeScale().fitContent()} title="Show the whole sample">
            Fit
          </button>
        </span>
      }
    >
      {sel && (
        <p className="v8-selline">
          Trade {selNo}: {sel.side} {fmtTime(sel.entryTime)} → {fmtTime(sel.exitTime)},{' '}
          <span className={signClass(sel.pnl)}>{fmtPct(sel.pnlPct)} ({fmtMoneySigned(sel.pnl)})</span>
          {selMissing > 0 && <span className="v8-gapnote"> · held across {selMissing} missing bar{selMissing === 1 ? '' : 's'}</span>}
        </p>
      )}
      {/* Always mounted: the chart's one-shot init effect needs the node. */}
      <div className="v8-chartbox">
        <div ref={containerRef} className="v8-chart" role="img" aria-label={dataset ? `${dataset.symbol} ${dataset.interval} candles with trade markers` : 'Price chart'} />
        {gapXs.xs.length > 0 && (
          <div className="v8-gaplayer" style={{ bottom: gapXs.axis }} aria-hidden>
            {gapXs.xs.map((g) => (
              <span
                key={g.from}
                className={gapXs.lines ? 'v8-gapline' : 'v8-gaptick'}
                style={{ left: g.x }}
                title={`${g.missing} bar${g.missing === 1 ? '' : 's'} missing: ${fmtTime(g.from)} → ${fmtTime(g.to)}`}
              />
            ))}
          </div>
        )}
        {datasetLoading && !dataset && (
          <div className="v8-chartcover">
            <Note>Loading bars…</Note>
          </div>
        )}
      </div>
    </Region>
  )
}
