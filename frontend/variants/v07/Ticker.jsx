'use client'

import { useState, useEffect, use } from 'react'
import CandlestickChart from '../../components/CandlestickChart'
import SettingsPopup from '../../components/SettingsPopup'
import IndicatorSelector from '../../components/IndicatorSelector'
import DrawingSelector from '../../components/DrawingSelector'
import ChartTypeSelector from '../../components/ChartTypeSelector'
import TrendLogicTable from '../../components/TrendLogicTable'
import DrawingsInspector from '../../components/DrawingsInspector'
import { DEFAULT_CHART_COLORS, CHART_COLORS_STORAGE_KEY, DEFAULT_TIMEZONE, TIMEZONE_STORAGE_KEY } from '../../components/chartDefaults'
import { INDICATORS_STORAGE_KEY, INDICATOR_OVERRIDES_STORAGE_KEY } from '../../components/indicators'
import Link from 'next/link'
import { fontVars } from './fonts'
import './v07.css'

const HISTORICAL_CACHE_PREFIX = 'historicalDataCache:'
// Older than this and we treat the cache as too stale to seed — saves a flash
// of week-old bars if someone returns after a long gap.
const HISTORICAL_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

const readHistoricalCache = (key) => {
  try {
    const raw = localStorage.getItem(HISTORICAL_CACHE_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || !Array.isArray(parsed.data) || parsed.data.length === 0) return null
    if (Date.now() - (parsed.savedAt || 0) > HISTORICAL_CACHE_MAX_AGE_MS) return null
    return parsed
  } catch { return null }
}

const writeHistoricalCache = (key, data, lastFetched) => {
  try {
    localStorage.setItem(HISTORICAL_CACHE_PREFIX + key, JSON.stringify({
      data,
      lastFetched: lastFetched ?? null,
      savedAt: Date.now(),
    }))
  } catch { /* quota exceeded — ignore */ }
}

export default function TickerDetail({ params }) {
  const [reload, setReload] = useState(0)
  const { symbol: rawSymbol } = use(params)
  const symbol = decodeURIComponent(rawSymbol)

  const DISPLAY_NAMES = {
    'ES=F': '/ES',
    'NQ=F': '/NQ',
    '^VIX': 'VIX',
  }
  const displayName = DISPLAY_NAMES[symbol] || symbol
  const [ohlcData, setOhlcData] = useState([])
  const [period, setPeriod] = useState('5d')
  const [interval, setInterval] = useState('5m')
  const [tickBars, setTickBars] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [activeIndicators, setActiveIndicators] = useState([])
  const [indicatorOverrides, setIndicatorOverrides] = useState({})
  const [upColor, setUpColor] = useState(DEFAULT_CHART_COLORS.upColor)
  const [downColor, setDownColor] = useState(DEFAULT_CHART_COLORS.downColor)
  const [bgColor, setBgColor] = useState(DEFAULT_CHART_COLORS.bgColor)
  const [borderUpColor, setBorderUpColor] = useState(DEFAULT_CHART_COLORS.borderUpColor)
  const [borderDownColor, setBorderDownColor] = useState(DEFAULT_CHART_COLORS.borderDownColor)
  const [gexLevels, setGexLevels] = useState(null)
  const [chartType, setChartType] = useState('candlestick')
  const [drawingTool, setDrawingTool] = useState(null)
  const [drawings, setDrawings] = useState([])
  const [timezone, setTimezone] = useState(DEFAULT_TIMEZONE)
  const [livePrice, setLivePrice] = useState(null)
  const [warmingUp, setWarmingUp] = useState(false)

  // Hydrate from localStorage after mount to avoid SSR/client mismatch
  useEffect(() => {
    try {
      const savedIndicators = JSON.parse(localStorage.getItem(INDICATORS_STORAGE_KEY))
      if (savedIndicators) setActiveIndicators(savedIndicators)
    } catch { /* ignore */ }
    try {
      const savedOverrides = JSON.parse(localStorage.getItem(INDICATOR_OVERRIDES_STORAGE_KEY))
      if (savedOverrides && typeof savedOverrides === 'object') setIndicatorOverrides(savedOverrides)
    } catch { /* ignore */ }
    try {
      const savedTz = localStorage.getItem(TIMEZONE_STORAGE_KEY)
      if (savedTz) setTimezone(savedTz)
    } catch { /* ignore */ }
    try {
      const savedColors = JSON.parse(localStorage.getItem(CHART_COLORS_STORAGE_KEY))
      if (savedColors?.upColor) setUpColor(savedColors.upColor)
      if (savedColors?.downColor) setDownColor(savedColors.downColor)
      if (savedColors?.bgColor) setBgColor(savedColors.bgColor)
      if (savedColors?.borderUpColor !== undefined) setBorderUpColor(savedColors.borderUpColor)
      if (savedColors?.borderDownColor !== undefined) setBorderDownColor(savedColors.borderDownColor)
    } catch { /* ignore */ }
  }, [])

  // Futures charts render GEX at futures-converted strikes; ETF charts render
  // at the ETF strike directly.
  const GEX_SOURCES = {
    'NQ=F': { gexSymbol: 'QQQ', useEtfStrike: false },
    'ES=F': { gexSymbol: 'SPY', useEtfStrike: false },
    'QQQ':  { gexSymbol: 'QQQ', useEtfStrike: true },
    'SPY':  { gexSymbol: 'SPY', useEtfStrike: true },
  }
  const gexSource = GEX_SOURCES[symbol]
  useEffect(() => {
    if (!gexSource) {
      setGexLevels(null)
      return
    }

    const fetchGex = async ({ skipIfHidden = true } = {}) => {
      if (skipIfHidden && document.hidden) return
      try {
        const res = await fetch(`/api/gamma?symbol=${gexSource.gexSymbol}`)
        if (res.ok) {
          const data = await res.json()
          setGexLevels(data)
        }
      } catch (err) {
        console.error('GEX fetch error:', err)
      }
    }

    fetchGex({ skipIfHidden: false })
    const gexInterval = window.setInterval(fetchGex, 5 * 60 * 1000)
    return () => window.clearInterval(gexInterval)
  }, [symbol])

  // Aggregate N consecutive bars into one tick bar
  function aggregateToTickBars(data, n) {
    const result = []
    for (let i = 0; i < data.length; i += n) {
      const group = data.slice(i, i + n)
      if (!group.length) continue
      result.push({
        time: group[0].time,
        open: group[0].open,
        high: group.reduce((m, d) => Math.max(m, Number(d.high)), -Infinity),
        low: group.reduce((m, d) => Math.min(m, Number(d.low)), Infinity),
        close: group[group.length - 1].close,
        volume: group.reduce((s, d) => s + Number(d.volume), 0),
      })
    }
    return result
  }

  // When tick bars mode is toggled on, switch to 1m interval
  const handleTickBarsChange = (n) => {
    setTickBars(n)
    if (n !== null) {
      setInterval('1m')
      if (!['1d', '5d'].includes(period)) setPeriod('5d')
    }
  }

  // Live tick poller. Hits /api/market/live, which calls yfinance via the
  // Azure Function and never reads Supabase. Cached ~3s on the backend so
  // many viewers share a single upstream call per TTL. The returned price
  // is merged into the developing bar inside CandlestickChart via
  // mainSeries.update() — no setData, no indicator recompute.
  useEffect(() => {
    setLivePrice(null)
    let cancelled = false

    const fetchLive = async () => {
      if (document.hidden) return
      try {
        const res = await fetch(`/api/market/live?symbol=${encodeURIComponent(symbol)}`)
        if (!res.ok) return
        const body = await res.json()
        const price = body?.tickers?.[0]?.price
        if (!cancelled && typeof price === 'number' && Number.isFinite(price)) {
          setLivePrice(price)
        }
      } catch { /* network hiccup — next tick will retry */ }
    }

    fetchLive()
    const timer = window.setInterval(fetchLive, 3000)
    const onVisible = () => { if (!document.hidden) fetchLive() }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [symbol])

  const RETRY_DELAYS = [5000, 10000, 20000]

  useEffect(() => {
    let isInitial = true
    let cancelled = false
    let lastBars = []
    // Echoed back to the server on each /since poll so it can short-circuit
    // when ingestion hasn't written anything new — that turns a fast poll
    // loop into a sequence of empty cache-hit responses with zero Supabase
    // egress, while still showing fresh data the moment ingestion runs.
    let lastFetched = null

    // Intraday bars use epoch-seconds strings; daily/weekly use YYYY-MM-DD.
    // Incremental polling is only worthwhile for intraday — daily series are
    // tiny and the backend's long cache already absorbs repeated full fetches.
    const INCREMENTAL_INTERVALS = new Set(['1m', '5m', '15m', '30m', '1h', '4h'])
    const fetchInterval = tickBars ? '1m' : interval
    const canIncremental = INCREMENTAL_INTERVALS.has(fetchInterval)
    // tickBars is a client-side aggregation of the raw fetchInterval bars, so
    // it doesn't need its own cache key.
    const cacheKey = `${symbol}|${period}|${fetchInterval}`

    // Seed from localStorage so the chart renders instantly on a fresh visit
    // while the background fetch refreshes it. On a cold backend (Render free
    // tier ~30-60s) this is the difference between "blank skeleton for a
    // minute" and "see your last view immediately."
    const cached = readHistoricalCache(cacheKey)
    if (cached) {
      lastBars = cached.data
      lastFetched = cached.lastFetched ?? null
      setOhlcData(cached.data)
      setLoading(false)
      setError(null)
      isInitial = false
    }

    const parseError = async (response) => {
      const suffix = response.status >= 500 ? ' (API)' : ''
      let errorMessage = `HTTP ${response.status}${suffix}`
      try {
        const errorData = await response.json()
        errorMessage = errorData.error || errorMessage
      } catch { /* not JSON */ }
      return errorMessage
    }

    const fetchFull = async (isInitialLoad = false) => {
      const doFetch = () => fetch(
        `/api/historical?symbol=${encodeURIComponent(symbol)}&period=${period}&interval=${fetchInterval}`
      )

      let response
      let lastErr

      if (isInitialLoad) {
        for (let attempt = 0; attempt <= RETRY_DELAYS.length; attempt++) {
          try {
            response = await doFetch()
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (attempt < RETRY_DELAYS.length && !cancelled) {
            setWarmingUp(true)
            await new Promise(r => setTimeout(r, RETRY_DELAYS[attempt]))
          }
        }
        if (!response) throw lastErr || new Error('Network error')
      } else {
        response = await doFetch()
      }

      if (!response.ok) throw new Error(await parseError(response))
      const result = await response.json()
      lastBars = result.data
      lastFetched = result.lastFetched ?? lastFetched
      setOhlcData(result.data)
      writeHistoricalCache(cacheKey, lastBars, lastFetched)
      if (isInitialLoad) setWarmingUp(false)
    }

    const fetchIncremental = async () => {
      if (!lastBars.length) return fetchFull()
      const lastTime = Number(lastBars[lastBars.length - 1].time)
      if (!Number.isFinite(lastTime)) return fetchFull()

      const url = new URL('/api/historical/since', window.location.origin)
      url.searchParams.set('symbol', symbol)
      url.searchParams.set('interval', fetchInterval)
      url.searchParams.set('since', String(lastTime))
      if (lastFetched != null) url.searchParams.set('lastFetched', String(lastFetched))

      const response = await fetch(url.toString())
      if (!response.ok) throw new Error(await parseError(response))
      const result = await response.json()
      // Track the server's view of the latest ingestion timestamp regardless
      // of whether new bars came back — empty responses still advance it as
      // ingestion's MAX(fetched_at) cache refreshes.
      if (result.lastFetched != null) lastFetched = result.lastFetched
      const newBars = result.data || []
      if (!newBars.length) return

      // Replace any existing bars at-or-after the first returned bar (the
      // last known bucket may still be developing), then append the rest.
      const firstNew = Number(newBars[0].time)
      const merged = lastBars.filter(b => Number(b.time) < firstNew).concat(newBars)
      lastBars = merged
      setOhlcData(merged)
      writeHistoricalCache(cacheKey, merged, lastFetched)
    }

    const fetchOHLCData = async () => {
      // Skip polls while the tab is hidden — the user can't see them anyway,
      // and each skipped poll avoids a Supabase read.
      if (!isInitial && typeof document !== 'undefined' && document.hidden) return

      if (isInitial) {
        setLoading(true)
        setError(null)
      }
      try {
        if (isInitial || !canIncremental) {
          await fetchFull(isInitial)
        } else {
          await fetchIncremental()
        }
        if (!isInitial) setError(null)
      } catch (err) {
        if (isInitial) {
          setError(err.message)
          setOhlcData([])
          lastBars = []
        }
      } finally {
        if (isInitial) setLoading(false)
        isInitial = false
      }
    }

    // 1m-only side channel: pulls recent bars straight from Yahoo (via
    // /api/historical/recent → LiveHistoricalService), bypassing Supabase
    // and the 5-minute Azure Function timer. Lets the developing candle
    // roll over at every minute boundary without increasing DB egress or
    // function invocations. Merges with the same replace-from-firstNew
    // policy as /since; when ingestion eventually catches up, /since's
    // authoritative bars overwrite anything we filled in here.
    const fetchRecent = async () => {
      if (typeof document !== 'undefined' && document.hidden) return
      if (!lastBars.length) return
      try {
        const url = new URL('/api/historical/recent', window.location.origin)
        url.searchParams.set('symbol', symbol)
        const response = await fetch(url.toString())
        if (!response.ok) return
        const result = await response.json()
        const newBars = result.data || []
        if (!newBars.length) return

        const firstNew = Number(newBars[0].time)
        if (!Number.isFinite(firstNew)) return
        const merged = lastBars.filter(b => Number(b.time) < firstNew).concat(newBars)
        lastBars = merged
        setOhlcData(merged)
        writeHistoricalCache(cacheKey, merged, lastFetched)
      } catch { /* network hiccup — next tick will retry */ }
    }

    // The /since endpoint echoes back the server's latest ingestion timestamp
    // as `lastFetched`; subsequent polls send it back, and the server returns
    // an empty body without touching Supabase whenever ingestion hasn't moved
    // on. That makes a tight poll loop essentially free, so we can keep the
    // candle visually responsive without burning egress.
    const POLL_MS = {
      '1m': 5_000,
      '5m': 10_000,
      '15m': 15_000,
      '30m': 15_000,
      '1h': 30_000,
      '4h': 30_000,
    }
    const pollInterval = POLL_MS[fetchInterval] || 60_000

    fetchOHLCData()
    const timer = window.setInterval(fetchOHLCData, pollInterval)

    // Spin up the 1m-bar side poller only when the chart is on 1m. The
    // 30s cadence matches the backend cache TTL, so each poll is at most
    // one Yahoo call shared across all viewers of this symbol. The
    // initial kick is delayed so the main /historical fetch can populate
    // lastBars first — fetchRecent is a no-op while lastBars is empty.
    let recentTimer = null
    let recentInitialKick = null
    if (fetchInterval === '1m') {
      recentInitialKick = window.setTimeout(fetchRecent, 3_000)
      recentTimer = window.setInterval(fetchRecent, 30_000)
    }

    // Refresh immediately on tab re-focus so users see fresh data without waiting a full poll cycle.
    const onVisible = () => {
      if (document.hidden) return
      fetchOHLCData()
      if (fetchInterval === '1m') fetchRecent()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      setWarmingUp(false)
      window.clearInterval(timer)
      if (recentTimer) window.clearInterval(recentTimer)
      if (recentInitialKick) window.clearTimeout(recentInitialKick)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [symbol, period, interval, tickBars, reload])

  useEffect(() => {
    localStorage.setItem(CHART_COLORS_STORAGE_KEY, JSON.stringify({ upColor, downColor, bgColor, borderUpColor, borderDownColor }))
  }, [upColor, downColor, bgColor, borderUpColor, borderDownColor])

  const handleTimezoneChange = (tz) => {
    setTimezone(tz)
    localStorage.setItem(TIMEZONE_STORAGE_KEY, tz)
  }

  const handleResetColors = () => {
    setUpColor(DEFAULT_CHART_COLORS.upColor)
    setDownColor(DEFAULT_CHART_COLORS.downColor)
    setBgColor(DEFAULT_CHART_COLORS.bgColor)
    setBorderUpColor(DEFAULT_CHART_COLORS.borderUpColor)
    setBorderDownColor(DEFAULT_CHART_COLORS.borderDownColor)
  }

  const handleToggleIndicator = (id) => {
    setActiveIndicators(prev => {
      const next = prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
      localStorage.setItem(INDICATORS_STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }

  const handleUpdateIndicator = (id, patch) => {
    setIndicatorOverrides(prev => {
      const next = { ...prev, [id]: { ...(prev[id] || {}), ...patch } }
      try { localStorage.setItem(INDICATOR_OVERRIDES_STORAGE_KEY, JSON.stringify(next)) } catch { /* ignore */ }
      return next
    })
  }

  const fullName = NAMES[symbol]
  const showChart = !loading && !warmingUp && !error && ohlcData.length > 0
  const gexLine = !gexSource
    ? 'No GEX levels for this symbol'
    : !gexLevels
      ? `GEX levels (from ${gexSource.gexSymbol}) not loaded`
      : gexLevels.marketOpen
        ? `GEX levels from the latest ${gexSource.gexSymbol} snapshot`
        : `GEX levels from the last ${gexSource.gexSymbol} close`

  return (
    <div className={`v7 v7-page v7-tk ${fontVars}`}>
      <header className="v7-site">
        <div className="v7-site-inner v7-site-wide">
          <Link href="/" className="v7-wordmark">GammaFlow</Link>
          <nav aria-label="Site" className="v7-site-nav">
            <Link href="/">Markets</Link>
            <span aria-current="page">Charts</span>
            <Link href="/backtest">Backtester</Link>
          </nav>
        </div>
      </header>

      <main className="v7-tk-main">
        <div className="v7-tk-head">
          <h1>{displayName}</h1>
          {fullName && <span className="v7-tk-name">{fullName}</span>}
          {livePrice !== null && <span className="v7-tk-live v7-num" title="Live price, polled every 3 s">{livePrice.toFixed(2)}</span>}
          <span className={`v7-tk-gex${gexLevels && !gexLevels.marketOpen ? ' is-stale' : ''}`}>{gexLine}</span>
        </div>

        <div className="v7-tk-toolbar" role="toolbar" aria-label="Chart controls">
          <TimeControls
            period={period}
            interval={interval}
            onPeriodChange={setPeriod}
            onIntervalChange={setInterval}
            tickBars={tickBars}
            onTickBarsChange={handleTickBarsChange}
          />
          <span className="v7-tk-sep" aria-hidden="true" />
          <div className="v7-tk-tools">
            <IndicatorSelector activeIndicators={activeIndicators} onToggle={handleToggleIndicator} />
            <DrawingSelector
              activeTool={drawingTool}
              onSelectTool={setDrawingTool}
              onClearAll={() => setDrawings([])}
              drawingCount={drawings.length}
            />
            <DrawingsInspector
              drawings={drawings}
              onDelete={(idx) => setDrawings(prev => prev.filter((_, i) => i !== idx))}
              onClearAll={() => setDrawings([])}
              activeIndicators={activeIndicators}
              onToggleIndicator={handleToggleIndicator}
              indicatorOverrides={indicatorOverrides}
              onUpdateIndicator={handleUpdateIndicator}
            />
            <ChartTypeSelector chartType={chartType} onSelect={setChartType} />
            <button type="button" className="settings-button" onClick={() => setSettingsOpen(prev => !prev)} aria-expanded={settingsOpen}>
              Colours &amp; timezone
            </button>
          </div>
        </div>

        {settingsOpen && (
          <SettingsPopup
            upColor={upColor}
            downColor={downColor}
            bgColor={bgColor}
            borderUpColor={borderUpColor}
            borderDownColor={borderDownColor}
            onUpColorChange={setUpColor}
            onDownColorChange={setDownColor}
            onBgColorChange={setBgColor}
            onBorderUpColorChange={setBorderUpColor}
            onBorderDownColorChange={setBorderDownColor}
            onClose={() => setSettingsOpen(false)}
            onReset={handleResetColors}
            timezone={timezone}
            onTimezoneChange={handleTimezoneChange}
          />
        )}

        {(loading || warmingUp) && (
          <div className="v7-tk-state" role="status">
            <div className="v7-tk-ghost" aria-hidden="true" />
            <div className="v7-tk-msg">
              <p className="v7-tk-msg-h">{warmingUp ? 'Waiting for the market API to wake up' : `Loading ${displayName} ${tickBars ? `${tickBars}-tick` : interval} bars for ${period}…`}</p>
              {warmingUp && <p>After a quiet spell the server takes 30–60 s to start. Retrying automatically at 5, 10 and 20 s.</p>}
            </div>
          </div>
        )}
        {!loading && !warmingUp && error && (
          <div className="v7-tk-state is-error" role="alert">
            <div className="v7-tk-ghost" aria-hidden="true" />
            <div className="v7-tk-msg">
              <p className="v7-tk-msg-h">
                {error.includes('(API)') ? 'The market API is not answering' : `Couldn't load ${displayName} bars`}
              </p>
              <p>{error.includes('(API)') ? `${error}. It may still be starting up; the chart polls again on its own.` : error}</p>
              <p><button type="button" className="btn" onClick={() => setReload((n) => n + 1)}>Retry now</button></p>
            </div>
          </div>
        )}
        {showChart && (
          <div className="chart-with-trend">
            <CandlestickChart data={tickBars ? aggregateToTickBars(ohlcData, tickBars) : ohlcData} symbol={symbol} upColor={upColor} downColor={downColor} bgColor={bgColor} borderUpColor={borderUpColor} borderDownColor={borderDownColor} activeIndicators={activeIndicators} indicatorOverrides={indicatorOverrides} gexLevels={gexLevels} gexUseEtfStrike={!!gexSource?.useEtfStrike} chartType={chartType} drawingTool={drawingTool} drawings={drawings} onDrawingComplete={(d) => { setDrawings(prev => [...prev, d]); setDrawingTool(null) }} onDrawingUpdate={(idx, updated) => { setDrawings(prev => updated === null ? prev.filter((_, i) => i !== idx) : prev.map((d, i) => i === idx ? updated : d)) }} timezone={timezone} livePrice={livePrice} />
            {activeIndicators.includes('trend-logic') && <TrendLogicTable symbol={symbol} />}
          </div>
        )}
        {!loading && !warmingUp && !error && ohlcData.length === 0 && (
          <div className="v7-tk-state" role="status">
            <div className="v7-tk-ghost" aria-hidden="true" />
            <div className="v7-tk-msg">
              <p className="v7-tk-msg-h">No {tickBars ? '1m' : interval} bars stored for {displayName} over {period}</p>
              <p>Try a longer period or a different interval.</p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

const NAMES = {
  'ES=F': 'E-mini S&P 500 futures',
  'NQ=F': 'E-mini Nasdaq-100 futures',
  SPY: 'SPDR S&P 500 ETF',
  QQQ: 'Invesco QQQ (Nasdaq-100) ETF',
  '^VIX': 'Cboe Volatility Index',
  'XEQT.TO': 'iShares Core Equity ETF Portfolio, TSX',
  'BTC-USD': 'Bitcoin in USD',
  'ETH-USD': 'Ether in USD',
  'SOL-USD': 'Solana in USD',
}

const PERIODS = ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y', 'max']
const INTERVALS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk']
const TICK_BAR_SIZES = [10, 25, 50, 100, 250, 500]
// Same availability table as components/TimeframeSelector.jsx.
const VALID_PERIODS = {
  '1m': ['1d', '5d'],
  '5m': ['1d', '5d', '10d', '14d', '1mo', '3mo'],
  '15m': ['1d', '5d', '10d', '14d', '1mo', '3mo'],
  '30m': ['1d', '5d', '10d', '14d', '1mo', '3mo'],
  '1h': ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y'],
  '4h': ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y'],
  '1d': ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y', 'max'],
  '1wk': ['1mo', '3mo', '6mo', '1y', '2y', 'max'],
}

/** Interval as a segmented row (the choice you make most), period and tick
 *  bars as selects. Same rules as TimeframeSelector: unavailable combinations
 *  are disabled, and tick bars force 1m data. */
function TimeControls({ period, interval, onPeriodChange, onIntervalChange, tickBars, onTickBarsChange }) {
  const periodOk = (p) => (tickBars ? VALID_PERIODS['1m'] : VALID_PERIODS[interval])?.includes(p)
  const intervalOk = (i) => !tickBars && VALID_PERIODS[i]?.includes(period)
  return (
    <div className="v7-tk-time">
      <div className="v7-seg" role="radiogroup" aria-label="Interval">
        {INTERVALS.map((i) => (
          <button key={i} type="button" role="radio" aria-checked={!tickBars && interval === i} disabled={!intervalOk(i)} onClick={() => onIntervalChange(i)}
            title={intervalOk(i) ? `${i} bars` : tickBars ? 'Tick bars use 1m data' : `No ${i} data for ${period}`}>
            {i}
          </button>
        ))}
      </div>
      <label className="v7-tk-sel">
        <span>Period</span>
        <span className="v7-select">
          <select className="field" value={period} onChange={(e) => onPeriodChange(e.target.value)}>
            {PERIODS.map((p) => <option key={p} value={p} disabled={!periodOk(p)}>{p}{periodOk(p) ? '' : ' (n/a)'}</option>)}
          </select>
        </span>
      </label>
      <label className="v7-tk-sel">
        <span>Tick bars</span>
        <span className="v7-select">
          <select className="field" value={tickBars ?? ''} onChange={(e) => onTickBarsChange(e.target.value === '' ? null : Number(e.target.value))}>
            <option value="">Off</option>
            {TICK_BAR_SIZES.map((n) => <option key={n} value={n}>{n} bars of 1m</option>)}
          </select>
        </span>
      </label>
    </div>
  )
}
