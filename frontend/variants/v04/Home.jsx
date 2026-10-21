'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { fontVars } from './fonts'
import { NAMES, GEX, displayName } from './symbols'
import Masthead from './Masthead'
import './v04.css'

const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const CRYPTO_SET = new Set(CRYPTO_TICKERS)
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

const clock = (d) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/**
 * The dashboard as a quote board: one row per instrument so prices can be
 * read down a column. Data flow is the original page's, unchanged — seed from
 * the local cache, retry the first load through a cold backend, then poll
 * every 15 s while the tab is visible.
 */
export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [warmingUp, setWarmingUp] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [lastTried, setLastTried] = useState(null)
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
      // later poll failures stay quiet and keep the last known prices
    } finally {
      setLastTried(new Date())
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
  // Symbols the API returned that the board does not list still get a row.
  const extras = (data?.tickers || []).filter((t) => !DEFAULT_TICKERS.includes(t.symbol))

  let status
  if (warmingUp) {
    status = <span className="v4-status-warn">Waiting for the market API to start: attempt {attempt} of {RETRY_DELAYS.length + 1}. A cold start can take up to a minute.</span>
  } else if (loading) {
    status = <span>Loading quotes…</span>
  } else if (error && !data) {
    status = (
      <span className="v4-status-err">
        Couldn&apos;t load quotes ({error.replace(' (API)', ' from the API')}). Still retrying every 15 s
        {lastTried && <>; last try {clock(lastTried)}</>}.{' '}
        <button className="v4-textbtn" onClick={() => fetchData({ skipIfHidden: false })}>Retry now</button>
      </span>
    )
  } else if (lastUpdated) {
    status = <span>Updated {clock(lastUpdated)} · refreshes every 15 s while this tab is open</span>
  }

  return (
    <div className={`v4 v4-page ${fontVars}`}>
      <Masthead current="markets" />
      <main className="v4-wrap">
        <div className="v4-board-head">
          <h1 className="v4-title">Markets</h1>
          <p className="v4-status" role="status" aria-live="polite">{status}</p>
        </div>

        <QuoteGroup
          title="Futures, ETFs and volatility"
          symbols={EQUITIES_TICKERS}
          extra={extras.filter((t) => !CRYPTO_SET.has(t.symbol))}
          bySymbol={bySymbol}
          pending={pending}
          failed={!pending && !data}
        />
        <QuoteGroup title="Crypto" symbols={CRYPTO_TICKERS} extra={[]} bySymbol={bySymbol} pending={pending} failed={!pending && !data} />

        <section className="v4-next">
          <div>
            <h2>Backtester</h2>
            <p>
              Test technical, gamma-level, model and custom-rule strategies on 5-minute QQQ and SPY bars with
              historical GEX, or on live prices. Costs are on by default; sweeps, walk-forward and Monte Carlo
              show how much of a result is fit to this sample.
            </p>
          </div>
          <Link href="/backtest" className="v4-cta">Open backtester</Link>
        </section>
      </main>
    </div>
  )
}

function QuoteGroup({ title, symbols, extra, bySymbol, pending, failed }) {
  const router = useRouter()
  const rows = [...symbols.map((s) => bySymbol.get(s) || { symbol: s, missing: true }), ...extra]
  return (
    <section className="v4-group" aria-busy={pending || undefined}>
      <h2>{title}</h2>
      <table className="v4-quotes">
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col">Last</th>
            <th scope="col" className="v4-q-wide">Change</th>
            <th scope="col">Change %</th>
            <th scope="col" className="v4-q-wide">Volume</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <QuoteRow key={t.symbol} t={t} pending={pending} failed={failed} onOpen={() => router.push(`/ticker/${t.symbol}`)} />
          ))}
        </tbody>
      </table>
    </section>
  )
}

function QuoteRow({ t, pending, failed, onOpen }) {
  const err = t.error || t.price_error
  const hasPrice = typeof t.price === 'number' && Number.isFinite(t.price)
  const change = hasPrice && t.previousClose ? t.price - t.previousClose : null
  const pct = change !== null ? (change / t.previousClose) * 100 : null
  const tone = change === null ? 'v4-flat' : change > 0 ? 'v4-pos' : change < 0 ? 'v4-neg' : 'v4-flat'
  const sign = change !== null && change > 0 ? '+' : ''
  const prefix = t.symbol === '^VIX' ? '' : '$'
  const blank = pending ? <span className="v4-q-wait" aria-hidden="true">———</span> : <span className="v4-dim">—</span>

  return (
    <tr onClick={onOpen}>
      <td>
        <Link href={`/ticker/${t.symbol}`} className="v4-q-sym" onClick={(e) => e.stopPropagation()}>
          {displayName(t.symbol)}
        </Link>
        <span className="v4-q-name">{NAMES[t.symbol] || t.name || ''}</span>
        {GEX[t.symbol] && <span className="v4-q-gex" title={`The chart draws ${GEX[t.symbol]} gamma-exposure levels`}>GEX levels</span>}
        {err && <span className="v4-q-err">{err}</span>}
        {!pending && !failed && t.missing && <span className="v4-q-err">Not in the last response</span>}
      </td>
      <td className="v4-q-num v4-q-last">{hasPrice ? `${prefix}${t.price.toFixed(2)}` : blank}</td>
      <td className={`v4-q-num v4-q-wide ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : blank}</td>
      <td className={`v4-q-num ${tone}`}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : blank}</td>
      <td className="v4-q-num v4-q-wide v4-muted">{t.volume > 0 ? t.volume.toLocaleString() : blank}</td>
    </tr>
  )
}
