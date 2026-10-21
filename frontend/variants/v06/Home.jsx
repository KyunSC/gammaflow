'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { fontVars } from './fonts'
import './v06.css'

// Same symbols, polling, retries and cache as app/page.jsx.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const REFRESH_INTERVAL = 15000
const RETRY_DELAYS = [5000, 10000, 20000]
const MARKET_CACHE_PREFIX = 'marketDataCache:'
const MARKET_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

// Grouped by what moves together. Names are plain descriptions of the
// instrument, so a row says what it is without a logo.
const GROUPS = [
  { title: 'Index futures and ETFs', symbols: ['ES=F', 'NQ=F', 'SPY', 'QQQ', 'XEQT.TO'] },
  { title: 'Volatility', symbols: ['^VIX'] },
  { title: 'Crypto', symbols: CRYPTO_TICKERS },
]
const META = {
  'ES=F': { label: '/ES', name: 'E-mini S&P 500 futures', gex: 'SPY' },
  'NQ=F': { label: '/NQ', name: 'E-mini Nasdaq-100 futures', gex: 'QQQ' },
  SPY: { label: 'SPY', name: 'SPDR S&P 500 ETF', gex: 'SPY' },
  QQQ: { label: 'QQQ', name: 'Invesco QQQ (Nasdaq-100)', gex: 'QQQ' },
  'XEQT.TO': { label: 'XEQT', name: 'iShares Core Equity ETF Portfolio, TSX' },
  '^VIX': { label: 'VIX', name: 'CBOE Volatility Index', noDollar: true },
  'BTC-USD': { label: 'BTC', name: 'Bitcoin, USD' },
  'ETH-USD': { label: 'ETH', name: 'Ether, USD' },
  'SOL-USD': { label: 'SOL', name: 'Solana, USD' },
}

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

const fmtClock = (d) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [warmingUp, setWarmingUp] = useState(false)
  const [attempt, setAttempt] = useState(null) // { n, of, waitMs } while retrying a cold API
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
        for (let i = 0; i <= RETRY_DELAYS.length; i++) {
          try {
            response = await fetch(`/api/market?tickers=${tickerParam}`)
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (i < RETRY_DELAYS.length) {
            setWarmingUp(true)
            setAttempt({ n: i + 2, of: RETRY_DELAYS.length + 1, waitMs: RETRY_DELAYS[i], status: response?.status })
            await new Promise((r) => setTimeout(r, RETRY_DELAYS[i]))
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
      // Later poll failures stay quiet and keep the last known prices.
    } finally {
      if (isInitial) {
        setLoading(false)
        setWarmingUp(false)
        setAttempt(null)
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
  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))

  let status
  if (warmingUp && attempt) {
    status = (
      <>The market API did not answer{attempt.status ? ` (HTTP ${attempt.status})` : ''}; it may be starting up. Attempt {attempt.n} of {attempt.of} after a {attempt.waitMs / 1000} s wait.</>
    )
  } else if (pending) {
    status = <>Loading prices…</>
  } else if (error && !data) {
    status = (
      <>
        <span className="v6h-bad">Prices unavailable: {error.replace(' (API)', ' from the API')}.</span> The page keeps asking every {REFRESH_INTERVAL / 1000} s.{' '}
        <button type="button" className="v6h-link" onClick={() => fetchData({ skipIfHidden: false })}>Try now</button>
      </>
    )
  } else if (lastUpdated) {
    status = (
      <>
        {fromCache ? 'Last saved prices from' : 'Updated'} <span className="v6h-num">{fmtClock(lastUpdated)}</span>
        {fromCache ? ', refreshing…' : ` · refreshes every ${REFRESH_INTERVAL / 1000} s`}
      </>
    )
  }

  return (
    <div className="v6h" style={fontVars}>
      <header className="v6h-top">
        <span className="v6h-brand">GammaFlow</span>
        <nav aria-label="Sections" className="v6h-nav">
          <span aria-current="page">Prices</span>
          <Link href="/backtest">Backtester</Link>
        </nav>
      </header>

      <main className="v6h-main">
        <div className="v6h-intro">
          <h1>Prices</h1>
          <p className="v6h-status" role="status" aria-live="polite">{status}</p>
        </div>

        <table className="v6h-table">
          <caption className="v6h-sr">Latest prices, change from previous close, and volume</caption>
          <thead>
            <tr>
              <th scope="col">Symbol</th>
              <th scope="col" className="v6h-col-name">Instrument</th>
              <th scope="col" className="r">Last</th>
              <th scope="col" className="r">Change</th>
              <th scope="col" className="r">%</th>
              <th scope="col" className="r v6h-col-vol">Volume</th>
            </tr>
          </thead>
          {GROUPS.map((g) => (
            <tbody key={g.title}>
              <tr className="v6h-group"><th scope="rowgroup" colSpan={6}>{g.title}</th></tr>
              {g.symbols.map((sym) => (
                <QuoteRow key={sym} symbol={sym} ticker={bySymbol.get(sym)} pending={pending && !data} missing={!pending && !!data && !bySymbol.has(sym)} />
              ))}
            </tbody>
          ))}
        </table>

        <section className="v6h-tools" aria-labelledby="v6h-tools-h">
          <h2 id="v6h-tools-h">Research</h2>
          <dl>
            <div>
              <dt><Link href="/backtest">Backtester</Link></dt>
              <dd>
                Runs MA cross, Bollinger and VWAP reversion, S/R levels, GEX wall fade, GEX regime, a random-forest signal or
                your own rules over 5-minute bars, with slippage and commission, buy &amp; hold alongside, and a count of every
                run you make. Sweeps, walk-forward and Monte Carlo in the advanced view.
              </dd>
            </div>
            <div>
              <dt>Charts</dt>
              <dd>
                Select a row for its chart: indicators, drawings and volume profile on every symbol; gamma levels (call wall,
                put wall, gamma flip) on SPY, QQQ, /ES and /NQ.
              </dd>
            </div>
          </dl>
        </section>
      </main>
    </div>
  )
}

function QuoteRow({ symbol, ticker, pending, missing }) {
  const meta = META[symbol]
  const href = `/ticker/${encodeURIComponent(symbol)}`
  const hasPrice = ticker && ticker.price !== null && ticker.price !== undefined
  const change = hasPrice && ticker.previousClose ? ticker.price - ticker.previousClose : null
  const pct = change !== null ? (change / ticker.previousClose) * 100 : null
  const tone = change === null ? '' : change >= 0 ? 'v6h-pos' : 'v6h-neg'
  const sign = change !== null && change >= 0 ? '+' : ''
  const err = ticker?.error || ticker?.price_error
  const blank = pending ? <span className="v6h-wait" aria-hidden="true" /> : '—'

  return (
    <tr className="v6h-row">
      <th scope="row">
        <Link href={href} className="v6h-sym" aria-label={`${meta.label}, ${meta.name}: open chart`}>{meta.label}</Link>
        {meta.gex && <span className="v6h-tag" title={`Chart shows gamma levels from ${meta.gex} options`}>GEX</span>}
      </th>
      <td className="v6h-col-name">{meta.name}</td>
      <td className="r v6h-num">{hasPrice ? `${meta.noDollar ? '' : '$'}${ticker.price.toFixed(2)}` : blank}</td>
      {err || missing ? (
        <td colSpan={3} className="r v6h-err">{err || 'Not in the last response'}</td>
      ) : (
        <>
          <td className={`r v6h-num ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : blank}</td>
          <td className={`r v6h-num ${tone}`}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : blank}</td>
          <td className="r v6h-num v6h-col-vol v6h-dim">{ticker?.volume > 0 ? ticker.volume.toLocaleString() : pending ? blank : '—'}</td>
        </>
      )}
    </tr>
  )
}
