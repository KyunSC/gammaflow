'use client'

import { useEffect, useMemo, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts'
import { useBacktest } from '../../lib/backtest/store'
import { fmtNum, fmtPct } from '../../lib/backtest/format'
import { EmptyState } from '../../components/backtest/Panel'
import Block from './Block'
import { holesFor } from './gaps'

const UP = '#4caf50'
const DOWN = '#ff6b6b'
const HOLE = '#e8b339'

/**
 * Variant 05 copy of components/backtest/PricePanel.jsx. Same chart engine and
 * the same pan-to-trade behaviour, plus:
 * - a rug of amber ticks along the bottom wherever bars are missing inside a
 *   session (lightweight-charts spaces bars by index, so the hole is otherwise
 *   invisible);
 * - exit markers coloured by win/loss, like every other P/L on the page;
 * - entry and exit price lines for the selected trade;
 * - a quieter model-prediction overlay.
 */
export default function PriceChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const markersRef = useRef(null)
  const overlayRef = useRef(null)
  const holeSeriesRef = useRef(null)
  const linesRef = useRef([])

  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectedTrade = useBacktest((s) => s.selectedTrade)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const holes = holesFor(dataset)

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
        vertLines: { visible: false },
        horzLines: { color: 'rgba(34,38,45,0.7)' },
      },
      rightPriceScale: { borderColor: '#22262D', scaleMargins: { top: 0.08, bottom: 0.1 } },
      timeScale: { borderColor: '#22262D', timeVisible: true, secondsVisible: false, rightOffset: 4 },
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

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      overlayRef.current = null
      holeSeriesRef.current = null
      linesRef.current = []
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return
    seriesRef.current.setData(candles)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  // Hole rug: one short amber bar on the first bar after each hole, on its own
  // hidden scale pinned to the bottom 4% of the pane.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (holeSeriesRef.current) {
      chart.removeSeries(holeSeriesRef.current)
      holeSeriesRef.current = null
    }
    if (!dataset || !holes.holes.length) return
    const rug = chart.addSeries(HistogramSeries, {
      color: HOLE,
      priceScaleId: 'holes',
      lastValueVisible: false,
      priceLineVisible: false,
      base: 0,
    })
    chart.priceScale('holes').applyOptions({ scaleMargins: { top: 0.96, bottom: 0 }, visible: false })
    rug.setData(holes.holes.map((h) => ({ time: dataset.time[h.idx], value: 1 })))
    holeSeriesRef.current = rug
  }, [dataset, holes])

  // Trade markers. Labels only while they still fit; past ~40 trades they
  // overlap into a smear over the candles they are meant to explain.
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
        color: t.pnl >= 0 ? UP : DOWN,
        shape: 'circle',
        size: 0.6,
        text: labelled ? `${t.pnl >= 0 ? '+' : ''}${(t.pnlPct * 100).toFixed(2)}%` : undefined,
      })
    }
    markers.sort((a, b) => a.time - b.time)
    if (!markersRef.current) markersRef.current = createSeriesMarkers(series, markers)
    else markersRef.current.setMarkers(markers)
  }, [result])

  // Model prediction overlay, research plane only: bottom band, kept faint.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (overlayRef.current) {
      chart.removeSeries(overlayRef.current)
      overlayRef.current = null
    }
    if (!dataset?.ml?.pred) return
    const line = chart.addSeries(LineSeries, {
      color: 'rgba(124,107,214,0.55)',
      lineWidth: 1,
      priceScaleId: 'ml',
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    })
    chart.priceScale('ml').applyOptions({ scaleMargins: { top: 0.84, bottom: 0.05 }, visible: false })
    const pts = []
    for (let i = 0; i < dataset.n; i++) {
      const v = dataset.ml.pred[i]
      if (Number.isFinite(v)) pts.push({ time: dataset.time[i], value: v })
    }
    line.setData(pts)
    overlayRef.current = line
  }, [dataset])

  // Selecting a trade pans here and pins its entry and exit prices.
  useEffect(() => {
    const series = seriesRef.current
    for (const l of linesRef.current) series?.removePriceLine(l)
    linesRef.current = []
    if (!selectedTrade || !chartRef.current || !series) return
    const pad = Math.max(20, (selectedTrade.exitIdx - selectedTrade.entryIdx) * 4)
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: selectedTrade.entryIdx - pad,
      to: selectedTrade.exitIdx + pad,
    })
    linesRef.current = [
      series.createPriceLine({ price: selectedTrade.entryPrice, color: '#8A9098', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'entry' }),
      series.createPriceLine({ price: selectedTrade.exitPrice, color: selectedTrade.pnl >= 0 ? UP : DOWN, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'exit' }),
    ]
  }, [selectedTrade])

  const resetView = () => chartRef.current?.timeScale().fitContent()

  return (
    <Block
      title="Price"
      meta={dataset ? `${dataset.symbol} ${dataset.interval} · axis in UTC` : null}
      right={
        <span className="flex flex-wrap items-center justify-end gap-x-3 font-mono text-[10.5px] text-dim">
          {selectedTrade && (
            <span className="text-muted">
              trade {selectedTrade.side} {fmtNum(selectedTrade.entryPrice)} → {fmtNum(selectedTrade.exitPrice)}{' '}
              <span className={selectedTrade.pnl >= 0 ? 'text-pos' : 'text-neg'}>{fmtPct(selectedTrade.pnlPct)}</span>
            </span>
          )}
          <span className="hidden md:inline">
            <span className="text-pos">▲</span> long <span className="text-neg">▼</span> short · exit ● <span className="text-pos">won</span>/<span className="text-neg">lost</span>
          </span>
          {holes.holes.length > 0 && (
            <span>
              <span className="text-amber">▮</span> missing bars ({holes.holes.length})
            </span>
          )}
          {dataset?.ml && <span className="hidden text-violet md:inline">model prediction</span>}
          <button onClick={resetView} className="text-muted hover:text-ink" title="Fit all bars">
            fit
          </button>
        </span>
      }
      className="h-full"
    >
      {/* The container is always mounted: the chart's one-shot init effect needs it. */}
      <div className="absolute inset-0">
        <div ref={containerRef} className="h-full w-full" />
        {datasetLoading && !dataset && (
          <div className="absolute inset-0 bg-canvas">
            <EmptyState>Loading bars…</EmptyState>
          </div>
        )}
      </div>
    </Block>
  )
}
