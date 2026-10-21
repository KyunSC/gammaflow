'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import Shell from './Shell'

// Data flow copied unchanged from app/page.jsx: same tickers, cache, retries and polling.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
const CRYPTO_SET = new Set(CRYPTO_TICKERS)
const REFRESH_INTERVAL = 15000
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

const DISPLAY = {
  'ES=F': ['/ES', 'E-mini S&P 500 futures'],
  'NQ=F': ['/NQ', 'E-mini Nasdaq-100 futures'],
  SPY: ['SPY', 'S&P 500 ETF'],
  QQQ: ['QQQ', 'Nasdaq-100 ETF'],
  '^VIX': ['VIX', 'CBOE volatility index'],
  'XEQT.TO': ['XEQT', 'iShares all-equity ETF, TSX'],
  'BTC-USD': ['BTC', 'Bitcoin, USD'],
  'ETH-USD': ['ETH', 'Ether, USD'],
  'SOL-USD': ['SOL', 'Solana, USD'],
}
const GEX_ON_CHART = new Set(['ES=F', 'NQ=F', 'SPY', 'QQQ'])
const GROUPS = [
  { title: 'Futures, ETFs and VIX', note: 'GEX levels on the chart for /ES, /NQ, SPY and QQQ', symbols: EQUITIES_TICKERS },
  { title: 'Crypto', note: 'trades around the clock', symbols: CRYPTO_TICKERS },
]

export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [warmingUp, setWarmingUp] = useState(false)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [attempt, setAttempt] = useState(0)
  const [manual, setManual] = useState(false)
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
  }, [])

  const retryNow = async () => {
    setManual(true)
    await fetchData({ skipIfHidden: false })
    setManual(false)
  }

  const showSkeleton = loading || warmingUp
  const bySymbol = new Map((data?.tickers || []).map((t) => [t.symbol, t]))
  const meta = showSkeleton
    ? `Contacting the market API, attempt ${attempt} of ${RETRY_DELAYS.length + 1}…`
    : lastUpdated
      ? `Updated ${lastUpdated.toLocaleTimeString()} · refreshes every 15 s`
      : error ? 'No prices yet' : null

  return (
    <Shell current="markets" meta={meta}>
      <main className="l10-main">
        <h1 className="l10-h1">Markets</h1>
        <p className="l10-lede">
          Last price against the previous close. Open a symbol for its chart with GEX levels, volume profile and order flow, or test a
          strategy in the <Link href="/backtest">backtester</Link>.
        </p>

        {!showSkeleton && error && !data && (
          <div className="l10-status is-error" role="alert">
            <p><strong>No prices: the market API did not answer.</strong> Last error: {error.replace(' (API)', '')}.</p>
            <p>
              {error.includes('(API)')
                ? 'A server error usually means the backend is still starting. This page keeps polling every 15 seconds and fills in as soon as a request succeeds.'
                : 'This page keeps polling every 15 seconds and fills in as soon as a request succeeds.'}
            </p>
            <p>The backtester does not need this API: it falls back to the bundled QQQ and SPY 5-minute sample.</p>
            <div className="l10-actions">
              <button type="button" className="l10-btn" onClick={retryNow} disabled={manual}>{manual ? 'Retrying…' : 'Retry now'}</button>
              <Link href="/backtest" className="l10-btn">Open the backtester</Link>
            </div>
          </div>
        )}

        {warmingUp && (
          <div className="l10-status" role="status">
            <p>The market API returned a server error; retrying (attempt {attempt} of {RETRY_DELAYS.length + 1}). A cold backend can take up to a minute.</p>
          </div>
        )}

        {(showSkeleton || data) && GROUPS.map((g) => (
          <QuoteGroup key={g.title} group={g} bySymbol={bySymbol} skeleton={showSkeleton && !data} />
        ))}
      </main>
    </Shell>
  )
}

function QuoteGroup({ group, bySymbol, skeleton }) {
  const router = useRouter()
  const rows = skeleton ? group.symbols.map((s) => ({ symbol: s, skeleton: true })) : group.symbols.map((s) => bySymbol.get(s)).filter(Boolean)
  if (!skeleton && !rows.length) {
    return (
      <section className="l10-quotes">
        <h2 className="l10-qtitle">{group.title}</h2>
        <p className="l10-lede">No quotes returned for this group.</p>
      </section>
    )
  }
  return (
    <section className="l10-quotes" aria-busy={skeleton}>
      <h2 className="l10-qtitle">{group.title} <span>{group.note}</span></h2>
      <table className="l10-table">
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col">Last</th>
            <th scope="col" className="l10-col-chg">Change</th>
            <th scope="col">Change %</th>
            <th scope="col" className="l10-col-vol">Volume</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => <QuoteRow key={t.symbol} t={t} onOpen={() => router.push(`/ticker/${t.symbol}`)} />)}
        </tbody>
      </table>
    </section>
  )
}

function QuoteRow({ t, onOpen }) {
  const [name, desc] = DISPLAY[t.symbol] || [t.symbol.replace(/-USD$/, ''), '']
  const href = `/ticker/${t.symbol}`
  const sym = (
    <td className="l10-sym">
      <Link href={href} onClick={(e) => e.stopPropagation()}>{name}</Link>
      <small>{desc}{GEX_ON_CHART.has(t.symbol) ? ' · GEX' : ''}</small>
    </td>
  )
  if (t.skeleton) {
    return (
      <tr>
        {sym}
        <td><span className="l10-skel" style={{ width: 72 }} /></td>
        <td className="l10-col-chg"><span className="l10-skel" style={{ width: 48 }} /></td>
        <td><span className="l10-skel" style={{ width: 52 }} /></td>
        <td className="l10-col-vol"><span className="l10-skel" style={{ width: 84 }} /></td>
      </tr>
    )
  }
  const err = t.error || t.price_error
  const prefix = t.symbol === '^VIX' ? '' : '$'
  const change = t.price !== null && t.previousClose ? t.price - t.previousClose : null
  const pct = change !== null ? (change / t.previousClose) * 100 : null
  const tone = change === null ? 'l10-muted' : change > 0 ? 'l10-pos' : change < 0 ? 'l10-neg' : 'l10-muted'
  const sign = change !== null && change >= 0 ? '+' : ''
  return (
    <tr onClick={onOpen} className={err ? 'l10-rowerr' : ''}>
      {sym}
      <td>{t.price !== null ? `${prefix}${t.price.toFixed(2)}` : '—'}</td>
      {err && t.price === null ? (
        <td colSpan={3} className="l10-errtext">{err}</td>
      ) : (
        <>
          <td className={`l10-col-chg ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : '—'}</td>
          <td className={tone}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : '—'}</td>
          <td className="l10-col-vol l10-muted">{t.volume ? t.volume.toLocaleString() : '—'}</td>
        </>
      )}
    </tr>
  )
}
