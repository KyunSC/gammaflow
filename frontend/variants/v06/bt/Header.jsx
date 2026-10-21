'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtDateRange } from '../../../lib/backtest/format'
import { shareUrl } from '../../../lib/backtest/share'

/**
 * What is loaded, where it came from, and how many simulations this session
 * has run. The run count is shown in both views: it is the size of the
 * multiple-testing problem, and hiding it in the simple view hid it from the
 * view most people use.
 */
export default function Header({ wide }) {
  const dataset = useBacktest((s) => s.dataset)
  const loading = useBacktest((s) => s.datasetLoading)
  const runCount = useBacktest((s) => s.runCount)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const running = useBacktest((s) => s.running)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const [copied, setCopied] = useState(false)

  // Same two copy paths as the original tape: the address bar always gets the
  // link, the clipboard only when the browser allows it.
  const copyShare = async () => {
    const url = shareUrl(useBacktest.getState())
    if (!url) return
    try { window.history.replaceState(null, '', url) } catch { /* ignore */ }
    try {
      await navigator.clipboard.writeText(url)
      setCopied('Link copied')
    } catch {
      setCopied('Link is in the address bar')
    }
    setTimeout(() => setCopied(false), 1800)
  }

  const tone = runCount > 300 ? 'v6-bad' : runCount > 80 ? 'v6-warn' : ''
  const source = dataset
    ? dataset.plane === 'research'
      ? dataset.example ? 'bundled sample' : 'published history + GEX'
      : 'live prices'
    : null

  return (
    <header className="v6-top">
      <nav className="v6-top-brand" aria-label="Site">
        <Link href="/" className="v6-brand">GammaFlow</Link>
        <span className="v6-crumb-sep" aria-hidden="true">/</span>
        <h1 className="v6-top-title">Backtester</h1>
      </nav>

      <p className="v6-top-data">
        {dataset ? (
          <>
            <span className="v6-ink">{dataset.symbol}</span>
            <span>{dataset.interval}</span>
            <span>{fmtDateRange(dataset.start, dataset.end)}</span>
            <span><span className="num">{dataset.n.toLocaleString()}</span> bars</span>
            <span className={dataset.example ? 'v6-warn' : dataset.plane === 'live' ? 'text-cyan' : ''}>{source}</span>
          </>
        ) : (
          <span>{loading ? 'Loading data…' : 'No dataset loaded'}</span>
        )}
      </p>

      <div className="v6-top-tools">
        <button
          type="button"
          onClick={() => toggleShortcuts(true)}
          className={`v6-runs ${tone}`}
          title="Every run, sweep cell and walk-forward trial this session. Opens the explanation."
        >
          {running ? 'running…' : <>run <span className="num">{runCount.toLocaleString()}</span>{wide && advanced && lastRunMs ? <span className="v6-dim"> · {lastRunMs.toFixed(0)} ms</span> : null}</>}
        </button>
        <button type="button" onClick={copyShare} className="v6-link" title="Put a link that reproduces this run in the address bar and clipboard" aria-live="polite">
          {copied || 'Share'}
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={advanced}
          onClick={() => setAdvanced(!advanced)}
          className="v6-toggle"
          title="Research tools: sweeps, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules, A/B/C compare"
        >
          <span className="switch pointer-events-none" aria-checked={advanced} aria-hidden="true" />
          Advanced
        </button>
        {wide ? (
          <>
            <button type="button" onClick={() => toggleShortcuts(true)} className="v6-link" title="Keyboard shortcuts (?)">Keys</button>
            <button type="button" onClick={() => togglePalette(true)} className="kbd" title="Command palette">⌘K</button>
          </>
        ) : (
          <a href="#v6-setup" className="v6-link">Setup</a>
        )}
      </div>
    </header>
  )
}
