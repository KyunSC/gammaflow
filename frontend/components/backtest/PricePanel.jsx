'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../lib/backtest/store'
import { priceOverlays, inputLabel } from '../../lib/backtest/tradeInsight'
import { fmtTime } from '../../lib/backtest/format'
import Panel, { EmptyState } from './Panel'
import TradeInspector from './TradeInspector'
import useStrategyState from './useStrategyState'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const WIN = '#E8B339'
const LOSS = '#8A9098'
const OVERLAY_COLORS = ['#4A90A4', '#C792EA', '#E8B339', '#8A9098', '#5FB3A1', '#D98C5F']
const MAX_OVERLAYS = 6

const ET_TIME = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const ET_DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' })
const ET_MONTH = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', year: 'numeric' })

/** Tick labels in New York time. `type`: 0 year, 1 month, 2 day, 3 time, 4 time with seconds. */
function etTick(time, type) {
  const d = new Date(time * 1000)
  if (type >= 3) return ET_TIME.format(d)
  if (type === 2) return ET_DAY.format(d)
  return ET_MONTH.format(d)
}

/**
 * Price with entry/exit markers, reusing the same charting engine as the
 * ticker page so a trade drawn here sits on exactly the candles the engine
 * filled against.
 */
export default function PricePanel() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const strategyLinesRef = useRef([])
  const tradeLinesRef = useRef([])
  const tradePathRef = useRef(null)
  const tradesRef = useRef(null)

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const showLines = useBacktest((s) => s.strategyLines)
  const toggleLines = useBacktest((s) => s.toggleStrategyLines)

  tradesRef.current = result?.trades ?? null

  const state = useStrategyState(result, dataset)
  const overlays = useMemo(
    () => (state && dataset ? priceOverlays(state, dataset.close).slice(0, MAX_OVERLAYS) : []),
    [state, dataset],
  )
  // Futures runs on ETF bars (QQQ → NQ) record fills in futures points; the
  // chart draws the ETF, so trade prices come back down by the same factor.
  const priceScale = result?.config.costs?.instrument?.priceScale > 0 ? result.config.costs.instrument.priceScale : 1

  const candles = useMemo(() => {
    if (!dataset) return []
    const out = new Array(dataset.n)
    for (let i = 0; i < dataset.n; i++) {
      out[i] = {
        time: dataset.time[i],
        open: dataset.open[i],
        high: dataset.high[i],
        low: dataset.low[i],
        close: dataset.close[i],
      }
    }
    return out
  }, [dataset])

  // Chart lifecycle
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
      grid: {
        vertLines: { color: 'rgba(34,38,45,0.6)' },
        horzLines: { color: 'rgba(34,38,45,0.6)' },
      },
      rightPriceScale: { borderColor: '#22262D', scaleMargins: { top: 0.12, bottom: 0.12 } },
      // Bars are epoch seconds; label them in New York time so the axis
      // agrees with the blotter and the inspector.
      timeScale: { borderColor: '#22262D', timeVisible: true, secondsVisible: false, rightOffset: 4, tickMarkFormatter: etTick },
      localization: { timeFormatter: (t) => fmtTime(t) },
      crosshair: {
        mode: 0,
        vertLine: { color: '#4A90A4', width: 1, style: 3, labelBackgroundColor: '#1c2027' },
        horzLine: { color: '#4A90A4', width: 1, style: 3, labelBackgroundColor: '#1c2027' },
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

    // Clicking the chart inspects the trade open on that bar, or the nearest
    // entry or exit within a few bars of it.
    chart.subscribeClick((param) => {
      const trades = tradesRef.current
      if (!trades?.length || param.logical === undefined || param.logical === null) return
      const i = Math.round(param.logical)
      let hit = trades.find((t) => t.entryIdx <= i && i <= t.exitIdx)
      if (!hit) {
        let best = 4
        for (const t of trades) {
          const d = Math.min(Math.abs(t.entryIdx - i), Math.abs(t.exitIdx - i))
          if (d < best) {
            best = d
            hit = t
          }
        }
      }
      if (hit) useBacktest.getState().selectTrade(hit)
    })

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
      strategyLinesRef.current = []
      tradeLinesRef.current = []
      tradePathRef.current = null
    }
  }, [])

  // Bars
  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  // Trade markers — v5 moved markers to the series-markers plugin.
  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!result) {
      markersRef.current?.setMarkers([])
      return
    }

    // Past ~40 trades the labels overlap into a smear and hide the candles they
    // are supposed to explain, so only the shapes survive at high trade counts.
    // The selected trade always keeps its labels and is drawn larger.
    const labelled = result.trades.length <= 40
    const markers = []
    for (const t of result.trades) {
      const long = t.side === 'long'
      const sel = selectedTrade && selectedTrade.entryIdx === t.entryIdx
      const text = labelled || sel
      markers.push({
        time: t.entryTime,
        position: long ? 'belowBar' : 'aboveBar',
        color: long ? UP : DOWN,
        shape: long ? 'arrowUp' : 'arrowDown',
        text: text ? (long ? 'L' : 'S') : undefined,
        size: sel ? 2 : 1,
      })
      markers.push({
        time: t.exitTime,
        position: long ? 'aboveBar' : 'belowBar',
        color: t.pnl >= 0 ? WIN : LOSS,
        shape: 'circle',
        text: text ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%${sel ? ` ${t.reason}` : ''}` : undefined,
        size: sel ? 2 : 1,
      })
    }
    markers.sort((a, b) => a.time - b.time)

    if (!markersRef.current) markersRef.current = createSeriesMarkers(series, markers)
    else markersRef.current.setMarkers(markers)
  }, [result, selectedTrade])

  // Selected trade: entry, exit, stop and target as price lines, and a straight
  // path from fill to fill so the trade reads as one move rather than two dots.
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series) return
    for (const line of tradeLinesRef.current) series.removePriceLine(line)
    tradeLinesRef.current = []
    if (tradePathRef.current) {
      chart.removeSeries(tradePathRef.current)
      tradePathRef.current = null
    }
    const t = selectedTrade
    if (!t || !result || !result.trades.some((x) => x.entryIdx === t.entryIdx)) return

    const px = (v) => v / priceScale
    const long = t.side === 'long'
    const add = (price, color, title, lineStyle) => {
      if (!Number.isFinite(price) || !(price > 0)) return
      tradeLinesRef.current.push(
        series.createPriceLine({ price: px(price), color, lineWidth: 1, lineStyle, axisLabelVisible: true, title }),
      )
    }
    add(t.entryPrice, long ? UP : DOWN, long ? 'long in' : 'short in', 2)
    add(t.exitPrice, t.pnl >= 0 ? WIN : LOSS, `out · ${t.reason}`, 2)
    if (t.stopPrice) add(t.stopPrice, DOWN, 'stop', 1)
    if (t.targetPrice) add(t.targetPrice, UP, 'target', 1)

    if (t.exitTime > t.entryTime) {
      const path = chart.addSeries(LineSeries, {
        color: t.pnl >= 0 ? WIN : LOSS,
        lineWidth: 2,
        lineStyle: 0,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      })
      path.setData([
        { time: t.entryTime, value: px(t.entryPrice) },
        { time: t.exitTime, value: px(t.exitPrice) },
      ])
      tradePathRef.current = path
    }
  }, [selectedTrade, result, priceScale])

  // The strategy's own lines (moving averages, VWAP, bands, levels), read from
  // its prepared state, so you can see the condition each marker answered.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    for (const line of strategyLinesRef.current) chart.removeSeries(line)
    strategyLinesRef.current = []
    if (!showLines || !dataset || !overlays.length) return
    overlays.forEach((o, j) => {
      const line = chart.addSeries(LineSeries, {
        color: OVERLAY_COLORS[j % OVERLAY_COLORS.length],
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        title: inputLabel(o.key),
      })
      const pts = new Array(dataset.n)
      for (let i = 0; i < dataset.n; i++) {
        const v = o.values[i]
        // Whitespace keeps a warm-up NaN from drawing a line down to zero.
        pts[i] = Number.isFinite(v) ? { time: dataset.time[i], value: v } : { time: dataset.time[i] }
      }
      line.setData(pts)
      strategyLinesRef.current.push(line)
    })
  }, [overlays, showLines, dataset])

  // Model prediction overlay (research plane only) — shows where the forest had
  // an opinion and where it was still training.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (overlayRef.current) {
      chart.removeSeries(overlayRef.current)
      overlayRef.current = null
    }
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(124,107,214,0.75)',
      lineWidth: 1,
      priceScaleId: 'ml',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  // Clicking a blotter row (or stepping with J/K) pans here. Keyed on the
  // entry bar, so a re-run that keeps the same trade leaves the view alone.
  const selEntry = selectedTrade?.entryIdx
  const selExit = selectedTrade?.exitIdx
  useEffect(() => {
    if (selEntry === undefined || !chartRef.current) return
    const pad = Math.max(20, (selExit - selEntry) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({ from: selEntry - pad, to: selExit + pad })
  }, [selEntry, selExit])

  return (
    <Panel
      label={dataset ? `price · ${dataset.symbol} ${dataset.interval}` : 'price'}
      right={
        result ? (
          <span className="flex items-center gap-2 text-dim">
            {overlays.length > 0 && (
              <button
                onClick={toggleLines}
                className={`btn !px-1.5 !py-0 ${showLines ? 'btn-active' : ''}`}
                title={`Strategy lines: ${overlays.map((o) => inputLabel(o.key)).join(', ')}`}
              >
                lines
              </button>
            )}
            <span>
              {result.trades.length} trades
              {dataset?.ml && <span className="ml-2 text-violet">· rf pred</span>}
            </span>
            {!selectedTrade && result.trades.length > 0 && <span className="hidden xl:inline">· click a trade or press K to inspect</span>}
          </span>
        ) : null
      }
      className="h-full"
      scroll={false}
      delay={0.04}
    >
      {/* The container is always mounted: swapping it out for a loading state
          would leave the chart's one-shot init effect with a null ref. */}
      <div className="relative h-full w-full">
        <div ref={containerRef} className="h-full w-full" />
        <TradeInspector state={state} />
        {datasetLoading && !dataset && (
          <div className="absolute inset-0 bg-panel">
            <EmptyState>Loading bars…</EmptyState>
          </div>
        )}
      </div>
    </Panel>
  )
}
