'use client'

import './site.css'
import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { fontVars } from './fonts'

// Same instruments, cache and retry policy as app/page.jsx.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const CRYPTO_SET = new Set(CRYPTO_TICKERS)
const REFRESH_INTERVAL = 15000
const RETRY_DELAYS = [5000, 10000, 20000]
const MARKET_CACHE_PREFIX = 'marketDataCache:'
const MARKET_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

// What each row is, so the table reads without knowing the tickers by heart.
const ROWS = {
  'ES=F': { name: '/ES', desc: 'E-mini S&P 500 future' },
  'NQ=F': { name: '/NQ', desc: 'E-mini Nasdaq-100 future' },
  SPY: { name: 'SPY', desc: 'S&P 500 ETF' },
  QQQ: { name: 'QQQ', desc: 'Nasdaq-100 ETF' },
  '^VIX': { name: 'VIX', desc: 'Cboe volatility index', noDollar: true },
  'XEQT.TO': { name: 'XEQT', desc: 'iShares all-equity ETF (TSX)' },
  'BTC-USD': { name: 'BTC', desc: 'Bitcoin, USD' },
  'ETH-USD': { name: 'ETH', desc: 'Ether, USD' },
  'SOL-USD': { name: 'SOL', desc: 'Solana, USD' },
}
// Symbols with GEX levels on their chart (see the ticker page's GEX_SOURCES).
const HAS_GEX = new Set(['ES=F', 'NQ=F', 'SPY', 'QQQ'])

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

export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
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
          try {
            response = await fetch(`/api/market?tickers=${tickerParam}`)
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (a < RETRY_DELAYS.length) {
            setAttempt(a + 1)
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
      writeMarketCache(tickerParam, result)
    } catch (err) {
      if (isInitial) setError(err.message)
    } finally {
      if (isInitial) {
        setLoading(false)
        setAttempt(0)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))
  const pending = loading && !data

  let status
  if (pending && attempt === 0) status = { tone: 'wait', text: 'Fetching quotes…' }
  else if (pending) status = { tone: 'wait', text: `The market data API is not answering yet (it can take up to a minute to wake). Retry ${attempt} of ${RETRY_DELAYS.length}…` }
  else if (error && !data) status = {
    tone: 'error',
    text: error.includes('(API)')
      ? `The market data API returned an error (${error.replace(' (API)', '')}) after ${RETRY_DELAYS.length + 1} tries. The page keeps asking every ${REFRESH_INTERVAL / 1000} s.`
      : `Could not reach the market data API: ${error}. The page keeps asking every ${REFRESH_INTERVAL / 1000} s.`,
  }
  else if (lastUpdated) status = { tone: fromCache ? 'wait' : 'ok', text: `${fromCache ? 'Showing saved quotes from' : 'Updated'} ${lastUpdated.toLocaleTimeString()}${fromCache ? ', refreshing…' : `, refreshes every ${REFRESH_INTERVAL / 1000} s`}` }

  return (
    <div className={`v3-site ${fontVars}`}>
      <header className="v3s-head">
        <div className="v3s-brand-row">
          <span className="v3s-brand">GammaFlow</span>
          <nav aria-label="Site" className="v3s-nav">
            <span aria-current="page">Quotes</span>
            <Link href="/backtest">Backtester</Link>
          </nav>
        </div>
        <h1 className="v3s-title">Quotes</h1>
        <p className="v3s-lede">
          Last price and day change for the futures, ETFs, VIX and crypto the lab tracks. Open a symbol for its chart;
          /ES, /NQ, SPY and QQQ charts carry GEX levels.
        </p>
        {status && (
          <p className={`v3s-status is-${status.tone}`} role={status.tone === 'error' ? 'alert' : 'status'} aria-live="polite">
            {status.text}
          </p>
        )}
      </header>

      <main>
        <QuoteTable title="Futures, ETFs and volatility" symbols={EQUITIES_TICKERS} bySymbol={bySymbol} pending={pending} failed={Boolean(error && !data)} />
        <QuoteTable title="Crypto" symbols={CRYPTO_TICKERS} bySymbol={bySymbol} pending={pending} failed={Boolean(error && !data)} />
        {error && !data && (
          <p className="v3s-aside">
            The <Link href="/backtest">backtester</Link> does not need this API: it falls back to the bundled QQQ and SPY
            5-minute sample, and says so on the page.
          </p>
        )}
      </main>
    </div>
  )
}

function QuoteTable({ title, symbols, bySymbol, pending, failed }) {
  return (
    <section className="v3s-section" aria-labelledby={`v3s-${title}`}>
      <h2 className="v3s-h2" id={`v3s-${title}`}>{title}</h2>
      <table className="v3s-table">
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col" className="v3s-hide-sm">Instrument</th>
            <th scope="col" className="r">Last</th>
            <th scope="col" className="r">Change</th>
            <th scope="col" className="r">%</th>
            <th scope="col" className="r v3s-hide-sm">Volume</th>
          </tr>
        </thead>
        <tbody>
          {symbols.map((sym) => (
            <QuoteRow key={sym} symbol={sym} ticker={bySymbol.get(sym)} pending={pending} failed={failed} />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function QuoteRow({ symbol, ticker, pending, failed }) {
  const meta = ROWS[symbol] || { name: symbol, desc: '' }
  const href = `/ticker/${encodeURIComponent(symbol)}`
  const price = ticker?.price
  const prev = ticker?.previousClose
  const change = Number.isFinite(price) && prev ? price - prev : null
  const pct = change !== null ? (change / prev) * 100 : null
  const dir = change === null ? '' : change > 0 ? 'is-up' : change < 0 ? 'is-down' : ''
  const sign = change !== null && change > 0 ? '+' : change !== null && change < 0 ? '−' : ''
  const rowError = ticker?.error || ticker?.price_error
  const placeholder = pending ? <span className="v3s-wait" aria-hidden="true">····</span> : '—'

  return (
    <tr className={dir}>
      <th scope="row">
        <Link href={href} className="v3s-sym">{meta.name}</Link>
        {HAS_GEX.has(symbol) && <span className="v3s-gex" title="Chart shows GEX levels">GEX</span>}
        <span className="v3s-desc-sm">{meta.desc}</span>
      </th>
      <td className="v3s-hide-sm v3s-desc">
        {meta.desc}
        {rowError && <span className="v3s-row-error"> · {rowError}</span>}
      </td>
      <td className="r v3s-num">{Number.isFinite(price) ? `${meta.noDollar ? '' : '$'}${price.toFixed(2)}` : placeholder}</td>
      <td className="r v3s-num v3s-chg">{change !== null ? `${sign}${Math.abs(change).toFixed(2)}` : pending ? placeholder : failed ? '—' : '—'}</td>
      <td className="r v3s-num v3s-chg">{pct !== null ? `${sign}${Math.abs(pct).toFixed(2)}%` : pending ? placeholder : '—'}</td>
      <td className="r v3s-num v3s-hide-sm v3s-vol">{ticker?.volume > 0 ? ticker.volume.toLocaleString() : pending ? placeholder : '—'}</td>
    </tr>
  )
}
