'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import Nav from './Nav'
import { fontVars } from './fonts'
import s from './Home.module.css'

// Same tickers, polling, retries and cache as app/page.jsx.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const REFRESH_INTERVAL = 15000
const RETRY_DELAYS = [5000, 10000, 20000]
const MARKET_CACHE_PREFIX = 'marketDataCache:'
const MARKET_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

const DISPLAY_NAMES = { 'ES=F': '/ES', 'NQ=F': '/NQ', '^VIX': 'VIX' }
const DESCRIPTIONS = {
  'ES=F': 'E-mini S&P 500 futures',
  'NQ=F': 'E-mini Nasdaq-100 futures',
  SPY: 'SPDR S&P 500 ETF',
  QQQ: 'Invesco QQQ, Nasdaq-100 ETF',
  '^VIX': 'Cboe Volatility Index',
  'XEQT.TO': 'iShares all-equity ETF, TSX',
  'BTC-USD': 'Bitcoin',
  'ETH-USD': 'Ether',
  'SOL-USD': 'Solana',
}
// The ticker page draws GEX levels for these (see GEX_SOURCES there).
const HAS_GEX = new Set(['ES=F', 'NQ=F', 'SPY', 'QQQ'])
const NO_DOLLAR = new Set(['^VIX'])

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
        for (let i = 0; i <= RETRY_DELAYS.length; i++) {
          try {
            response = await fetch(`/api/market?tickers=${tickerParam}`)
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (i < RETRY_DELAYS.length) {
            setAttempt(i + 1)
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
      setAttempt(0)
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
  const pending = loading || attempt > 0

  let status
  if (attempt > 0) {
    status = (
      <p className={s.statusWarn} role="status">
        The API isn&apos;t answering yet. It sleeps when idle and can take up to a minute to start. Retry {attempt} of {RETRY_DELAYS.length}…
      </p>
    )
  } else if (loading) {
    status = <p className={s.status} role="status">Fetching quotes…</p>
  } else if (error && !data) {
    status = (
      <p className={s.statusErr} role="alert">
        Couldn&apos;t load quotes ({error.replace(' (API)', ', API error')}). The page asks again every 15 s. The backtester works without the API.
      </p>
    )
  } else if (lastUpdated) {
    status = (
      <p className={s.status}>
        Updated {lastUpdated.toLocaleTimeString()}{fromCache ? ' (saved copy, refreshing)' : ''} · refreshes every 15 s
      </p>
    )
  }

  return (
    <div className={`${fontVars} ${s.page}`}>
      <Nav current="markets" />
      <div className={s.wrap}>
        <main className={s.main}>
          <header className={s.head}>
            <h1 className={s.title}>Markets</h1>
            {status}
          </header>
          <Board title="Equities, futures & volatility" symbols={EQUITIES_TICKERS} bySymbol={bySymbol} pending={pending} />
          <Board title="Crypto" symbols={CRYPTO_TICKERS} bySymbol={bySymbol} pending={pending} />
        </main>
        <aside className={s.aside} aria-label="Other pages">
          <h2 className={s.asideTitle}>
            <Link href="/backtest" className={s.asideLink}>Backtester</Link>
          </h2>
          <p className={s.asideText}>
            Test a strategy on QQQ/SPY 5-minute history with gamma levels, or on live prices, after slippage and commission and against buy &amp; hold. Sweeps,
            walk-forward, Monte Carlo and prop-account rules. Runs in the browser and falls back to bundled sample data when the API is
            down.
          </p>
          <h2 className={s.asideTitle}>Charts</h2>
          <p className={s.asideText}>
            Pick any row for its chart: indicators, drawings, volume profile, tick bars. GEX levels are drawn for /ES, /NQ, SPY and QQQ.
          </p>
        </aside>
      </div>
    </div>
  )
}

function Board({ title, symbols, bySymbol, pending }) {
  return (
    <section className={s.board} aria-label={title}>
      <h2 className={s.boardTitle}>{title}</h2>
      <div className={s.cols} aria-hidden="true">
        <span>Instrument</span>
        <span className={s.r}>Last</span>
        <span className={s.r}>Change</span>
        <span className={`${s.r} ${s.vol}`}>Volume</span>
      </div>
      <ul className={s.list}>
        {symbols.map((sym) => (
          <Row key={sym} sym={sym} t={bySymbol.get(sym)} pending={pending} />
        ))}
      </ul>
    </section>
  )
}

function Row({ sym, t, pending }) {
  const name = DISPLAY_NAMES[sym] || sym.replace(/-USD$/, '')
  const prefix = NO_DOLLAR.has(sym) ? '' : '$'
  const price = t?.price ?? null
  const change = price !== null && t?.previousClose ? price - t.previousClose : null
  const pct = change !== null ? (change / t.previousClose) * 100 : null
  const tone = change === null ? '' : change >= 0 ? s.pos : s.neg
  const sign = change !== null && change >= 0 ? '+' : ''
  const err = t?.error || t?.price_error

  return (
    <li>
      <Link href={`/ticker/${sym}`} className={s.row}>
        <span className={s.inst}>
          <span className={s.sym}>{name}</span>
          <span className={s.desc}>
            {DESCRIPTIONS[sym]}
            {HAS_GEX.has(sym) && <span className={s.gex}> · GEX</span>}
          </span>
        </span>
        <span className={`${s.num} ${s.r} ${s.last}`}>
          {price !== null ? `${prefix}${price.toFixed(2)}` : pending ? <span className={s.wait}>···</span> : '—'}
        </span>
        <span className={`${s.num} ${s.r} ${tone}`}>
          {change !== null ? (
            <>
              {sign}{change.toFixed(2)} <span className={s.pct}>{sign}{pct.toFixed(2)}%</span>
            </>
          ) : (
            <span className={s.dim}>—</span>
          )}
        </span>
        <span className={`${s.num} ${s.r} ${s.vol} ${s.dim}`}>{t?.volume ? t.volume.toLocaleString() : '—'}</span>
        {err && <span className={s.err}>{err}</span>}
      </Link>
    </li>
  )
}
