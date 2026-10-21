'use client'

import './site.css'
import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { STRATEGIES, FAMILIES } from '../../lib/backtest/strategies'
import { fontVars } from './fonts'

// Same tickers, cache and polling as app/page.jsx. Only the presentation
// differs: a quote table instead of cards.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const REFRESH_INTERVAL = 15000
const RETRY_DELAYS = [5000, 10000, 20000]

// Display grouping only: the API call is the same single request.
const GROUPS = [
  { title: 'Index futures and ETFs', symbols: ['ES=F', 'NQ=F', 'SPY', 'QQQ', 'XEQT.TO'] },
  { title: 'Volatility', symbols: ['^VIX'] },
  { title: 'Crypto', symbols: CRYPTO_TICKERS },
]

const DISPLAY_NAMES = { 'ES=F': '/ES', 'NQ=F': '/NQ', '^VIX': 'VIX' }
const displayName = (s) => DISPLAY_NAMES[s] || s.replace(/-USD$/, '')
const NO_DOLLAR = new Set(['^VIX'])

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

export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [warmingUp, setWarmingUp] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
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
          setAttempt(a)
          try {
            response = await fetch(`/api/market?tickers=${tickerParam}`)
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (a < RETRY_DELAYS.length) {
            setWarmingUp(true)
            await new Promise(r => setTimeout(r, RETRY_DELAYS[a]))
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
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const pending = loading || warmingUp
  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))

  let status
  if (warmingUp) {
    status = (
      <p className="v05-status is-warn" role="status">
        The market API isn&apos;t answering yet. Its host sleeps when idle and can take up to a minute to wake.
        Attempt {attempt + 1} of {RETRY_DELAYS.length + 1}; waiting {RETRY_DELAYS[Math.min(attempt, RETRY_DELAYS.length - 1)] / 1000} s before the next one.
      </p>
    )
  } else if (loading) {
    status = <p className="v05-status" role="status">Loading prices…</p>
  } else if (error && !data) {
    status = (
      <p className="v05-status is-error" role="alert">
        Couldn&apos;t load prices ({error}).{' '}
        {error.includes('(API)') ? 'The server may still be starting. ' : ''}
        The page tries again every {REFRESH_INTERVAL / 1000} s.
      </p>
    )
  } else if (lastUpdated) {
    status = (
      <p className="v05-status" role="status">
        Updated {lastUpdated.toLocaleTimeString()} · refreshes every {REFRESH_INTERVAL / 1000} s
      </p>
    )
  }

  return (
    <div className={`v05-site ${fontVars}`}>
      <header className="v05-masthead">
        <span className="v05-wordmark">GammaFlow</span>
        <nav aria-label="Site" className="v05-nav">
          <Link href="/" aria-current="page">Markets</Link>
          <Link href="/backtest">Backtester</Link>
        </nav>
      </header>

      <main className="v05-home">
        <section className="v05-quotes" aria-labelledby="v05-markets-h">
          <h1 id="v05-markets-h">Markets</h1>
          <p className="v05-lede">Last price and change against the previous close. Select a row for its chart with GEX levels, indicators and order flow.</p>
          <div className="v05-status-line">{status}</div>

          {GROUPS.map((g) => (
            <table key={g.title} className="v05-qtable">
              <caption>{g.title}</caption>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th scope="col" className="num">Last</th>
                  <th scope="col" className="num">Change</th>
                  <th scope="col" className="num">%</th>
                  <th scope="col" className="num hide-sm">Volume</th>
                </tr>
              </thead>
              <tbody>
                {g.symbols.map((sym) => (
                  <QuoteRow key={sym} symbol={sym} ticker={bySymbol.get(sym)} pending={pending && !bySymbol.has(sym)} />
                ))}
              </tbody>
            </table>
          ))}
        </section>

        <aside className="v05-aside" aria-labelledby="v05-bt-h">
          <h2 id="v05-bt-h">
            <Link href="/backtest">Backtester →</Link>
          </h2>
          <p>
            Runs a strategy in the browser on 5-minute QQQ and SPY bars with historical GEX levels, or on live
            OHLCV. Slippage and commission are charged on every fill, and every result sits next to buy &amp;
            hold over the same window.
          </p>
          <p>Research tools: parameter sweep, walk-forward, block-bootstrap Monte Carlo, cost ladder, prop-firm accounts, A/B/C compare.</p>
          <dl className="v05-strats">
            {FAMILIES.map((f) => {
              const list = STRATEGIES.filter((s) => s.family === f.id)
              if (!list.length) return null
              return (
                <div key={f.id}>
                  <dt>{f.label}</dt>
                  <dd>{list.map((s) => s.label).join(', ')}</dd>
                </div>
              )
            })}
          </dl>
        </aside>
      </main>
    </div>
  )
}

function QuoteRow({ symbol, ticker, pending }) {
  const name = displayName(symbol)
  const href = `/ticker/${symbol}`
  if (!ticker) {
    return (
      <tr className={pending ? 'is-pending' : 'is-empty'}>
        <th scope="row"><Link href={href}>{name}</Link></th>
        <td className="num">{pending ? <span className="v05-bar" aria-hidden /> : '—'}</td>
        <td className="num">{pending ? <span className="v05-bar short" aria-hidden /> : '—'}</td>
        <td className="num">{pending ? <span className="v05-bar short" aria-hidden /> : '—'}</td>
        <td className="num hide-sm">{pending ? <span className="v05-bar" aria-hidden /> : '—'}</td>
      </tr>
    )
  }
  const err = ticker.error || ticker.price_error
  const prefix = NO_DOLLAR.has(symbol) ? '' : '$'
  const change = ticker.price !== null && ticker.previousClose ? ticker.price - ticker.previousClose : null
  const pct = change !== null ? (change / ticker.previousClose) * 100 : null
  const tone = change === null ? '' : change > 0 ? 'pos' : change < 0 ? 'neg' : ''
  const sign = change !== null && change >= 0 ? '+' : ''
  return (
    <tr className={err ? 'has-error' : ''}>
      <th scope="row">
        <Link href={href}>{name}</Link>
        {err && <span className="v05-row-err">{err}</span>}
      </th>
      <td className="num">{ticker.price !== null ? `${prefix}${ticker.price.toFixed(2)}` : '—'}</td>
      <td className={`num ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : '—'}</td>
      <td className={`num ${tone}`}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : '—'}</td>
      <td className="num hide-sm dim">{ticker.volume ? ticker.volume.toLocaleString() : '—'}</td>
    </tr>
  )
}
