'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import SiteBar from './SiteBar'
import { INSTRUMENTS } from './instruments'
import { fontVars } from './fonts'
import s from './site.module.css'

// Same tickers, endpoint, polling, retry and cache policy as app/page.jsx —
// only the presentation changes.
const EQUITIES_TICKERS = ['ES=F', 'NQ=F', 'SPY', 'QQQ', '^VIX', 'XEQT.TO']
const CRYPTO_TICKERS = ['BTC-USD', 'ETH-USD', 'SOL-USD']
const DEFAULT_TICKERS = [...EQUITIES_TICKERS, ...CRYPTO_TICKERS]
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

const GROUPS = [
  { title: 'Futures, ETFs and volatility', tickers: EQUITIES_TICKERS },
  { title: 'Crypto', tickers: CRYPTO_TICKERS },
]

const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

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
        for (let i = 0; i <= RETRY_DELAYS.length; i++) {
          setAttempt(i)
          try {
            response = await fetch(`/api/market?tickers=${tickerParam}`)
            if (response.ok || response.status < 500) break
          } catch (e) {
            lastErr = e
            response = undefined
          }
          if (i < RETRY_DELAYS.length) {
            setWarmingUp(true)
            await new Promise(r => setTimeout(r, RETRY_DELAYS[i]))
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pending = loading || warmingUp
  const bySymbol = new Map((data?.tickers || []).map(t => [t.symbol, t]))

  const updated = lastUpdated
    ? `${fromCache ? 'Cached prices from' : 'Updated'} ${lastUpdated.toLocaleTimeString()}`
    : pending ? 'Loading prices…' : 'No prices yet'

  return (
    <div className={`${s.root} ${fontVars}`}>
      <SiteBar current="home" right={<span aria-live="polite">{updated}</span>} />

      <main className={s.home}>
        <div className={s.pageHead}>
          <h1 className={s.h1}>Watchlist</h1>
          <span className={s.meta}>
            {DEFAULT_TICKERS.length} instruments · refreshes every {REFRESH_INTERVAL / 1000} s while this tab is visible · select a row for its chart
          </span>
        </div>

        <div>
          <Status pending={pending} warmingUp={warmingUp} attempt={attempt} error={error} hasData={Boolean(data)} onRetry={() => fetchData({ skipIfHidden: false })} />

          {GROUPS.map(group => (
            <section key={group.title} className={s.group} aria-labelledby={`grp-${group.tickers[0]}`}>
              <h2 id={`grp-${group.tickers[0]}`} className={s.h2}>{group.title}</h2>
              <table className={s.quotes}>
                <colgroup>
                  <col className={s.cSym} />
                  <col className={s.hideNarrow} />
                  <col className={s.cLast} />
                  <col className={s.cChg} />
                  <col className={s.cPct} />
                  <col className={`${s.cVol} ${s.hideNarrow}`} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Symbol</th>
                    <th scope="col" className={s.hideNarrow}>Instrument</th>
                    <th scope="col">Last</th>
                    <th scope="col">Change</th>
                    <th scope="col">%</th>
                    <th scope="col" className={s.hideNarrow}>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {group.tickers.map(sym => (
                    <QuoteRow key={sym} symbol={sym} ticker={bySymbol.get(sym)} pending={pending && !data} />
                  ))}
                </tbody>
              </table>
            </section>
          ))}
        </div>

        <aside className={s.aside} aria-labelledby="bt-aside">
          <h2 id="bt-aside">Backtester</h2>
          <p>
            Test technical, gamma-level (GEX) and model strategies on 5-minute QQQ and SPY research bars, or on
            live bars for six symbols.
          </p>
          <ul>
            <li>Costs, stops and prop-firm account rules</li>
            <li>Parameter sweep, walk-forward and Monte Carlo</li>
            <li>A run counter for how much you have searched</li>
          </ul>
          <Link href="/backtest" className={s.cta}>Open the backtester</Link>
          <p className={s.footnote}>
            It does not need the price API: when the server is down it runs on bundled QQQ/SPY sample bars and
            labels them as such.
          </p>
        </aside>
      </main>
    </div>
  )
}

function Status({ pending, warmingUp, attempt, error, hasData, onRetry }) {
  if (warmingUp) {
    const next = RETRY_DELAYS[Math.min(attempt, RETRY_DELAYS.length - 1)] / 1000
    return (
      <p className={s.status} role="status">
        <span className={s.statusTitle}>The price server is starting up.</span>
        <span>
          Attempt {attempt + 1} of {RETRY_DELAYS.length + 1} failed; trying again in {next} s. A cold start can take 30–60 s.
        </span>
      </p>
    )
  }
  if (pending) return null
  if (error && !hasData) {
    return (
      <div className={`${s.status} ${s.statusError}`} role="alert">
        <span className={s.statusTitle}>Prices unavailable.</span>
        <span>
          {error.startsWith('HTTP') ? `/api/market answered ${error.replace(' (API)', '')}.` : `/api/market could not be reached (${error}).`} The page asks again every {REFRESH_INTERVAL / 1000} s.
        </span>
        <button type="button" className={s.button} onClick={onRetry}>Retry now</button>
      </div>
    )
  }
  return null
}

function QuoteRow({ symbol, ticker, pending }) {
  const meta = INSTRUMENTS[symbol] || { label: symbol, name: '' }
  const err = ticker?.error || ticker?.price_error
  const price = ticker?.price ?? null
  const change = price !== null && ticker?.previousClose ? price - ticker.previousClose : null
  const pct = change !== null ? (change / ticker.previousClose) * 100 : null
  const tone = change === null ? s.flat : change > 0 ? s.pos : change < 0 ? s.neg : s.flat
  const sign = change !== null && change > 0 ? '+' : ''
  const empty = pending ? <span className={s.loadingCell}>…</span> : <span className={s.cellDim}>—</span>

  return (
    <tr>
      <td className={s.symCell}>
        <Link href={`/ticker/${symbol}`} className={s.symLink} aria-label={`${meta.label}, ${meta.name}: open chart`}>
          {meta.label}
        </Link>
        <span className={s.showNarrow}>{meta.name}</span>
      </td>
      <td className={`${s.nameCell} ${s.hideNarrow}`}>
        {meta.name}
        {err && <span className={s.nameNote}>{err}</span>}
      </td>
      <td className={s.last}>{price !== null ? price.toFixed(2) : empty}</td>
      <td className={`${s.num} ${tone}`}>{change !== null ? `${sign}${change.toFixed(2)}` : empty}</td>
      <td className={`${s.num} ${tone}`}>{pct !== null ? `${sign}${pct.toFixed(2)}%` : empty}</td>
      <td className={`${s.cellDim} ${s.hideNarrow}`} title={ticker?.volume ? ticker.volume.toLocaleString() : undefined}>
        {ticker?.volume ? compact.format(ticker.volume) : pending ? empty : '—'}
      </td>
    </tr>
  )
}
