'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import Shell from './Shell'

// Same tickers, polling and cache as app/page.jsx; only the presentation differs.
const GROUPS = [
  {
    title: 'Index futures',
    rows: [
      { symbol: 'ES=F', label: '/ES', name: 'E-mini S&P 500', unit: 'index pts', gex: true },
      { symbol: 'NQ=F', label: '/NQ', name: 'E-mini Nasdaq-100', unit: 'index pts', gex: true },
    ],
  },
  {
    title: 'ETFs',
    rows: [
      { symbol: 'SPY', label: 'SPY', name: 'SPDR S&P 500 ETF', unit: 'USD', gex: true },
      { symbol: 'QQQ', label: 'QQQ', name: 'Invesco QQQ Trust', unit: 'USD', gex: true },
      { symbol: 'XEQT.TO', label: 'XEQT', name: 'iShares Core Equity ETF Portfolio, TSX', unit: 'CAD' },
    ],
  },
  {
    title: 'Volatility',
    rows: [{ symbol: '^VIX', label: 'VIX', name: 'Cboe Volatility Index', unit: 'index' }],
  },
  {
    title: 'Crypto',
    rows: [
      { symbol: 'BTC-USD', label: 'BTC', name: 'Bitcoin', unit: 'USD' },
      { symbol: 'ETH-USD', label: 'ETH', name: 'Ether', unit: 'USD' },
      { symbol: 'SOL-USD', label: 'SOL', name: 'Solana', unit: 'USD' },
    ],
  },
]
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const REFRESH_INTERVAL = 15000
// Retry delays on 5xx (covers Render free-tier cold boots ~30-60s)
const RETRY_DELAYS = [5000, 10000, 20000]

const MARKET_CACHE_PREFIX = 'marketDataCache:'
const MARKET_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

const readMarketCache = (key) => {
  try {
    const raw = localStorage.getItem(MARKET_CACHE_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || !parsed.payload) return null
    if (Date.now() - (parsed.savedAt || 0) > MARKET_CACHE_MAX_AGE_MS) return null
    return parsed
  } catch { return null }
}

const writeMarketCache = (key, payload) => {
  try {
    localStorage.setItem(MARKET_CACHE_PREFIX + key, JSON.stringify({ payload, savedAt: Date.now() }))
  } catch { /* quota exceeded — ignore */ }
}

const compact = (v) => {
  if (!Number.isFinite(v) || v <= 0) return '—'
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return String(Math.round(v))
}

export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [warmingUp, setWarmingUp] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [fromCache, setFromCache] = useState(false)
  const isInitialRef = useRef(true)
  const inflightRef = useRef(false)

  const fetchData = async ({ skipIfHidden = true } = {}) => {
    if (skipIfHidden && typeof document !== 'undefined' && document.hidden) return
    if (inflightRef.current) return
    inflightRef.current = true
    const isInitial = isInitialRef.current
    try {
      const tickerParam = DEFAULT_TICKERS.join(',')
      let response
      let lastErr
      if (isInitial) {
        for (let a = 0; a <= RETRY_DELAYS.length; a++) {
          setAttempt(a + 1)
          try {
            response = await fetch(`/api/market?tickers=${tickerParam}`)
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (a < RETRY_DELAYS.length) {
            setWarmingUp(true)
            await new Promise((r) => setTimeout(r, RETRY_DELAYS[a]))
          }
        }
        if (!response) throw lastErr || new Error('Network error')
      } else {
        response = await fetch(`/api/market?tickers=${tickerParam}`)
      }
      if (!response.ok) {
        const suffix = response.status >= 500 ? ' (API)' : ''
        throw new Error(`HTTP ${response.status}${suffix}`)
      }
      const result = await response.json()
      setData(result)
      setLastUpdated(new Date())
      setFromCache(false)
      setError(null)
      setWarmingUp(false)
      writeMarketCache(tickerParam, result)
    } catch (err) {
      if (isInitial) setError(err.message)
      // later poll failures are silent: the last known prices stay up
    } finally {
      if (isInitial) {
        setLoading(false)
        setWarmingUp(false)
        isInitialRef.current = false
      }
      inflightRef.current = false
    }
  }

  useEffect(() => {
    const tickerParam = DEFAULT_TICKERS.join(',')
    const cached = readMarketCache(tickerParam)
    if (cached) {
      setData(cached.payload)
      setLastUpdated(new Date(cached.savedAt))
      setFromCache(true)
      setLoading(false)
      isInitialRef.current = false
    }
    fetchData({ skipIfHidden: false })
    const interval = setInterval(fetchData, REFRESH_INTERVAL)
    const onVisible = () => { if (!document.hidden) fetchData({ skipIfHidden: false }) }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  const pending = loading || warmingUp
  const failed = !pending && error && !data
  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))

  const status = pending ? (
    warmingUp ? (
      <span className="text-amber">
        Waiting for the market API, attempt {attempt} of {RETRY_DELAYS.length + 1}. A cold server can take up to a minute.
      </span>
    ) : (
      <span>Loading prices…</span>
    )
  ) : failed ? (
    <span className="text-neg">No prices</span>
  ) : lastUpdated ? (
    <span>
      {fromCache ? 'Cached from ' : 'Updated '}
      <span className="num">{lastUpdated.toLocaleTimeString()}</span> · refreshes every 15 s
    </span>
  ) : null

  return (
    <Shell current="markets" status={status}>
      <div className="v8-home">
        <div className="v8-home-head">
          <h1>Markets</h1>
          <p className="v8-hint">Last price and change from the previous close. Choose a symbol to open its chart.</p>
        </div>

        {failed && (
          <div className="v8-errblock" role="alert">
            <p>
              Couldn&apos;t load prices from the market API ({error.includes('(API)') ? error.replace(' (API)', ', server error') : error}). The page
              keeps asking every 15 seconds.
            </p>
            <p>
              <button type="button" className="btn" onClick={() => fetchData({ skipIfHidden: false })}>
                Try again now
              </button>{' '}
              <span className="text-dim">The backtester does not need this API: it can run on the bundled QQQ and SPY sample.</span>{' '}
              <Link href="/backtest" className="v8-textbtn">Open the backtester</Link>
            </p>
          </div>
        )}

        <table className="v8-watch" aria-busy={pending}>
          <caption className="v8-sr">Watchlist</caption>
          <thead>
            <tr>
              <th scope="col">Symbol</th>
              <th scope="col" className="v8-watch-name">Name</th>
              <th scope="col" className="r">Last</th>
              <th scope="col" className="r">Change</th>
              <th scope="col" className="r">%</th>
              <th scope="col" className="r v8-watch-vol">Volume</th>
              <th scope="col" className="v8-watch-unit">Unit</th>
            </tr>
          </thead>
          {GROUPS.map((g) => (
            <tbody key={g.title}>
              <tr className="v8-watch-group">
                <th scope="rowgroup" colSpan={7}>{g.title}</th>
              </tr>
              {g.rows.map((row) => (
                <Row key={row.symbol} row={row} ticker={bySymbol.get(row.symbol)} pending={pending} failed={failed} />
              ))}
            </tbody>
          ))}
        </table>
        <p className="v8-hint v8-home-foot">
          GEX marks the charts that draw gamma-exposure levels: SPY and QQQ at their own strikes, /ES and /NQ at strikes converted from SPY and QQQ.
        </p>
      </div>
    </Shell>
  )
}

function Row({ row, ticker, pending, failed }) {
  const router = useRouter()
  const href = `/ticker/${row.symbol}`
  const err = ticker?.error || ticker?.price_error
  const price = ticker?.price ?? null
  const change = price !== null && ticker?.previousClose ? price - ticker.previousClose : null
  const pct = change !== null ? (change / ticker.previousClose) * 100 : null
  const tone = change === null ? '' : change > 0 ? 'text-pos' : change < 0 ? 'text-neg' : 'text-dim'
  const sign = change !== null && change > 0 ? '+' : ''
  const none = ticker || failed || !pending
  const blank = none ? <span className="text-dim">—</span> : <span className="v8-wait" aria-hidden>···</span>

  return (
    <tr className="v8-watch-row" onClick={() => router.push(href)}>
      <th scope="row">
        <Link href={href} onClick={(e) => e.stopPropagation()}>{row.label}</Link>
        {row.gex && <span className="v8-gextag" title="Chart includes GEX levels">GEX</span>}
      </th>
      <td className="v8-watch-name">
        {row.name}
        {err && <span className="v8-rowerr">{err}</span>}
      </td>
      <td className="r num v8-watch-last">{price !== null ? price.toFixed(2) : blank}</td>
      <td className={`r num ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : blank}</td>
      <td className={`r num ${tone}`}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : blank}</td>
      <td className="r num v8-watch-vol text-dim">{ticker ? compact(ticker.volume) : blank}</td>
      <td className="v8-watch-unit text-dim">{row.unit}</td>
    </tr>
  )
}
