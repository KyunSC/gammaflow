'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import s from './site.module.css'
import { fontVars } from './fonts'

// Same symbols, refresh cadence, retry schedule and cache as app/page.jsx.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const REFRESH_INTERVAL = 15000
const RETRY_DELAYS = [5000, 10000, 20000]
const MARKET_CACHE_PREFIX = 'marketDataCache:'
const MARKET_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

/** Grouped by what the instrument is, not by "stocks vs crypto". */
const GROUPS = [
  { title: 'Index futures', rows: [['ES=F', '/ES', 'E-mini S&P 500'], ['NQ=F', '/NQ', 'E-mini Nasdaq-100']] },
  { title: 'ETFs', rows: [['SPY', 'SPY', 'SPDR S&P 500 ETF'], ['QQQ', 'QQQ', 'Invesco QQQ (Nasdaq-100)'], ['XEQT.TO', 'XEQT', 'iShares Core Equity ETF Portfolio, TSX']] },
  { title: 'Volatility', rows: [['^VIX', 'VIX', 'Cboe Volatility Index']] },
  { title: 'Crypto', rows: [['BTC-USD', 'BTC', 'Bitcoin, USD'], ['ETH-USD', 'ETH', 'Ether, USD'], ['SOL-USD', 'SOL', 'Solana, USD']] },
]
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
  }, [])

  const pending = loading || warmingUp
  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))
  const failed = !pending && error && !data

  let status
  if (pending) {
    status = attempt > 1
      ? `Market API not answering yet. Attempt ${attempt} of ${RETRY_DELAYS.length + 1}; a cold server can take about a minute.`
      : 'Loading quotes…'
  } else if (failed) {
    status = null
  } else if (lastUpdated) {
    status = `Updated ${lastUpdated.toLocaleTimeString()} · refreshes every ${REFRESH_INTERVAL / 1000} s`
  }

  return (
    <div className={`${s.page} ${fontVars}`}>
      <header className={s.bar}>
        <span className={s.brand}>GammaFlow</span>
        <nav aria-label="Pages" className={s.nav}>
          <span aria-current="page" className={s.navOn}>Board</span>
          <Link href="/ticker/SPY" className={s.navLink}>Charts</Link>
          <Link href="/backtest" className={s.navLink}>Backtester</Link>
        </nav>
      </header>

      <main className={s.board}>
        <div className={s.boardHead}>
          <h1 className={s.h1}>Market board</h1>
          {status && <p className={s.status} aria-live="polite">{status}</p>}
        </div>

        {failed && (
          <div role="alert" className={s.alert}>
            <p>
              <strong>No quotes.</strong>{' '}
              {error.includes('(API)')
                ? `The market API returned an error (${error.replace(' (API)', '')}). The board keeps retrying every ${REFRESH_INTERVAL / 1000} s.`
                : `The request failed: ${error}. The board keeps retrying every ${REFRESH_INTERVAL / 1000} s.`}
            </p>
            <p className={s.alertMore}>
              Chart pages need the same API. The <Link href="/backtest">backtester</Link> runs on its bundled QQQ/SPY sample without it.
            </p>
          </div>
        )}

        <table className={s.quotes}>
          <caption className={s.srOnly}>Last price, change on the previous close and volume</caption>
          <thead>
            <tr>
              <th scope="col" className={s.colSym}>Symbol</th>
              <th scope="col" className={s.num}>Last</th>
              <th scope="col" className={`${s.num} ${s.hideSm}`}>Change</th>
              <th scope="col" className={s.num}>%</th>
              <th scope="col" className={`${s.num} ${s.hideSm}`}>Volume</th>
            </tr>
          </thead>
          {GROUPS.map((g) => (
            <tbody key={g.title}>
              <tr className={s.groupRow}>
                <th scope="rowgroup" colSpan={5}>{g.title}</th>
              </tr>
              {g.rows.map(([sym, label, name]) => (
                <QuoteRow key={sym} sym={sym} label={label} name={name} t={bySymbol.get(sym)} pending={pending} />
              ))}
            </tbody>
          ))}
        </table>
        <p className={s.foot}>
          Change is against the previous close reported by the market API. Select a row to open its chart.
        </p>
      </main>
    </div>
  )
}

function QuoteRow({ sym, label, name, t, pending }) {
  const href = `/ticker/${encodeURIComponent(sym)}`
  const price = t?.price ?? null
  const change = price !== null && t?.previousClose ? price - t.previousClose : null
  const pct = change !== null ? (change / t.previousClose) * 100 : null
  const tone = change === null ? '' : change >= 0 ? s.up : s.down
  const sign = change !== null && change >= 0 ? '+' : ''
  const err = t?.error || t?.price_error
  const dollar = NO_DOLLAR.has(sym) ? '' : '$'
  const blank = pending ? <span className={s.skel} aria-hidden="true" /> : <span className={s.na}>—</span>

  return (
    <tr className={s.row}>
      <th scope="row" className={s.colSym}>
        <Link href={href} className={s.rowLink}>
          <span className={s.sym}>{label}</span>
          <span className={s.name}>{name}</span>
        </Link>
        {err && <span className={s.rowErr}>{err}</span>}
      </th>
      <td className={s.num}>{price !== null ? `${dollar}${price.toFixed(2)}` : blank}</td>
      <td className={`${s.num} ${s.hideSm} ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : blank}</td>
      <td className={`${s.num} ${tone}`}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : blank}</td>
      <td className={`${s.num} ${s.hideSm} ${s.vol}`}>{t?.volume ? t.volume.toLocaleString() : pending ? blank : <span className={s.na}>—</span>}</td>
    </tr>
  )
}
