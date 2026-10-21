'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fontVars } from './fonts'
import './v07.css'

// Same tickers, polling and cache as app/page.jsx.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const REFRESH_INTERVAL = 15000
const RETRY_DELAYS = [5000, 10000, 20000]
const MARKET_CACHE_PREFIX = 'marketDataCache:'
const MARKET_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

const GROUPS = [
  { title: 'Futures, ETFs and volatility', tickers: EQUITIES_TICKERS },
  { title: 'Crypto', tickers: CRYPTO_TICKERS },
]

const DISPLAY = {
  'ES=F': { label: '/ES', name: 'E-mini S&P 500 futures' },
  'NQ=F': { label: '/NQ', name: 'E-mini Nasdaq-100 futures' },
  SPY: { label: 'SPY', name: 'SPDR S&P 500 ETF' },
  QQQ: { label: 'QQQ', name: 'Invesco QQQ (Nasdaq-100) ETF' },
  '^VIX': { label: 'VIX', name: 'Cboe Volatility Index', noDollar: true },
  'XEQT.TO': { label: 'XEQT.TO', name: 'iShares Core Equity ETF Portfolio, TSX' },
  'BTC-USD': { label: 'BTC', name: 'Bitcoin in USD' },
  'ETH-USD': { label: 'ETH', name: 'Ether in USD' },
  'SOL-USD': { label: 'SOL', name: 'Solana in USD' },
}
// Symbols with historical GEX levels on the chart page.
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

/**
 * Dashboard as a quote board: one row per instrument, prices in a column so
 * they can be compared, rows that are real links. Loading and error states say
 * what is happening (the API sleeps when idle and takes ~30–60 s to wake).
 */
export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [warmingUp, setWarmingUp] = useState(false)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [attempt, setAttempt] = useState(0)
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
      setError(null)
      setWarmingUp(false)
      writeMarketCache(tickerParam, result)
    } catch (err) {
      if (isInitial) setError(err.message)
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

  const pending = loading || warmingUp
  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))

  return (
    <div className={`v7 v7-page ${fontVars}`}>
      <header className="v7-site">
        <div className="v7-site-inner">
          <span className="v7-wordmark">GammaFlow</span>
          <nav aria-label="Site" className="v7-site-nav">
            <span aria-current="page">Markets</span>
            <Link href="/ticker/SPY">Charts</Link>
            <Link href="/backtest">Backtester</Link>
          </nav>
        </div>
      </header>

      <main className="v7-home">
        <div className="v7-home-head">
          <h1>Markets</h1>
          <Status pending={pending} warmingUp={warmingUp} attempt={attempt} error={error} hasData={Boolean(data)} lastUpdated={lastUpdated}
            onRetry={() => fetchData({ skipIfHidden: false })} />
        </div>

        {GROUPS.map((g) => (
          <section key={g.title} className="v7-board-sec" aria-labelledby={`v7-g-${g.title}`}>
            <h2 id={`v7-g-${g.title}`}>{g.title}</h2>
            <table className="v7-board">
              <thead>
                <tr>
                  <th scope="col" className="b-sym">Symbol</th>
                  <th scope="col" className="b-name">Instrument</th>
                  <th scope="col" className="b-num">Last</th>
                  <th scope="col" className="b-num">Change</th>
                  <th scope="col" className="b-num">%</th>
                  <th scope="col" className="b-num b-vol">Volume</th>
                  <th scope="col" className="b-go"><span className="v7-sr">Links</span></th>
                </tr>
              </thead>
              <tbody>
                {g.tickers.map((sym) => (
                  <Row key={sym} symbol={sym} ticker={bySymbol.get(sym)} pending={pending && !data} />
                ))}
              </tbody>
            </table>
          </section>
        ))}

        <section className="v7-home-foot" aria-label="About this data">
          <p>
            Prices from <code>/api/market</code>, refreshed every 15 s while this tab is visible. Change is against the previous close.
            Charts for /ES, /NQ, SPY and QQQ carry GEX levels.
          </p>
          <p>
            <Link href="/backtest">Open the backtester</Link> to test gamma-level, technical and model strategies on 5-minute history, after costs and
            against buy &amp; hold.
          </p>
        </section>
      </main>
    </div>
  )
}

function Status({ pending, warmingUp, attempt, error, hasData, lastUpdated, onRetry }) {
  if (warmingUp) {
    return (
      <p className="v7-status is-wait" role="status">
        Waiting for the market API to wake up (attempt {attempt} of {RETRY_DELAYS.length + 1}). After a quiet spell it takes 30–60 s.
      </p>
    )
  }
  if (pending) return <p className="v7-status" role="status">Loading prices…</p>
  if (error && !hasData) {
    return (
      <p className="v7-status is-error" role="alert">
        {error.includes('(API)') ? 'The market API is not answering' : `Couldn't load prices (${error})`}. Checking again every 15 s.{' '}
        <button type="button" className="v7-link v7-link-inline" onClick={onRetry}>Retry now</button>
      </p>
    )
  }
  return (
    <p className="v7-status" role="status">
      {lastUpdated ? <>Updated {lastUpdated.toLocaleTimeString()}</> : null}
    </p>
  )
}

function Row({ symbol, ticker, pending }) {
  const router = useRouter()
  const d = DISPLAY[symbol] || { label: symbol.replace(/-USD$/, ''), name: '' }
  const href = `/ticker/${encodeURIComponent(symbol)}`
  const price = ticker?.price
  const prev = ticker?.previousClose
  const change = price !== null && price !== undefined && prev ? price - prev : null
  const pct = change !== null ? (change / prev) * 100 : null
  const cls = change === null ? '' : change > 0 ? 'v7-pos' : change < 0 ? 'v7-neg' : 'v7-flat'
  const sign = (v) => (v > 0 ? '+' : v < 0 ? '−' : '')
  const err = ticker?.error || ticker?.price_error
  const dollar = d.noDollar ? '' : '$'
  const blank = pending ? <span className="v7-skel" aria-hidden="true" /> : '—'

  return (
    <tr className={`v7-board-row${err ? ' has-error' : ''}`} onClick={(e) => { if (!e.target.closest('a')) router.push(href) }}>
      <th scope="row" className="b-sym">
        <Link href={href}>{d.label}</Link>
        {HAS_GEX.has(symbol) && <span className="v7-gex" title="GEX levels on the chart">GEX</span>}
      </th>
      <td className="b-name">{d.name}{err ? <span className="v7-row-err"> · {err}</span> : null}</td>
      <td className="b-num">{price !== null && price !== undefined ? `${dollar}${price.toFixed(2)}` : blank}</td>
      <td className={`b-num ${cls}`}>{change !== null ? `${sign(change)}${Math.abs(change).toFixed(2)}` : pending ? '' : '—'}</td>
      <td className={`b-num ${cls}`}>{pct !== null ? `${sign(pct)}${Math.abs(pct).toFixed(2)}%` : pending ? '' : '—'}</td>
      <td className="b-num b-vol">{ticker?.volume ? ticker.volume.toLocaleString() : pending ? '' : '—'}</td>
      <td className="b-go"><Link href={href} tabIndex={-1} aria-hidden="true">Chart →</Link></td>
    </tr>
  )
}
