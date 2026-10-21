'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../../lib/backtest/store'
import { shareUrl } from '../../../lib/backtest/share'
import { Switch, fmtRange, fmtDay } from './ui'

/**
 * One line: where you are, what data is loaded (with the year, and whether it
 * is the bundled sample), and the session's simulation count — which is shown
 * in every mode, because it is the size of the multiple-testing problem, not a
 * power-user statistic.
 */
export default function TopBar() {
  const dataset = useBacktest((s) => s.dataset)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const runCount = useBacktest((s) => s.runCount)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const [copied, setCopied] = useState(false)

  // Clipboard can be refused; the URL always lands in the address bar too.
  const copyShare = async () => {
    const url = shareUrl(useBacktest.getState())
    if (!url) return
    try {
      window.history.replaceState(null, '', url)
    } catch { /* ignore */ }
    try {
      await navigator.clipboard.writeText(url)
      setCopied('Link copied')
    } catch {
      setCopied('Link is in the address bar')
    }
    setTimeout(() => setCopied(false), 2200)
  }

  const level = runCount > 300 ? 'high' : runCount > 80 ? 'mid' : 'low'

  return (
    <header className="v7-top">
      <nav className="v7-crumbs" aria-label="Site">
        <Link href="/">GammaFlow</Link>
        <span aria-hidden="true">/</span>
        <h1>Backtester</h1>
      </nav>

      <p className="v7-top-data" aria-live="polite">
        {dataset ? (
          <>
            <strong>{dataset.symbol}</strong>
            <span>{dataset.interval} bars</span>
            <span>{fmtRange(dataset.start, dataset.end)}</span>
            <span className="v7-num">{dataset.n.toLocaleString()} bars</span>
            <Source dataset={dataset} />
          </>
        ) : datasetLoading ? (
          <span>Loading data…</span>
        ) : (
          <span>No data loaded</span>
        )}
      </p>

      <div className="v7-top-tools">
        <button
          type="button"
          className={`v7-runs v7-runs-${level}`}
          onClick={() => toggleShortcuts(true)}
          title={`Every run, sweep cell and walk-forward trial since this page loaded. The more you try on one dataset, the more the best result is luck.${runCount > 0 ? ` Last run took ${lastRunMs.toFixed(0)} ms.` : ''}`}
        >
          <span className="v7-num">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session
          {running ? <span className="v7-top-running"> · running…</span> : null}
        </button>
        <label className="v7-top-switch" title="Re-run automatically when a setting changes">
          <Switch checked={autoRun} onChange={toggleAutoRun} label="Auto-run" />
          <span>Auto-run</span>
        </label>
        <label className="v7-top-switch" title="Parameter sweep, walk-forward, Monte Carlo, cost ladder, prop accounts, custom rules, A/B/C compare">
          <Switch checked={advanced} onChange={setAdvanced} label="Research tools" />
          <span>Research tools</span>
        </label>
        <button type="button" className="v7-link" onClick={copyShare} title="Copy a link that reproduces this configuration">
          {copied ? <span role="status">{copied}</span> : 'Share link'}
        </button>
        <button type="button" className="v7-link" onClick={() => toggleShortcuts(true)} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          Keys <kbd>?</kbd>
        </button>
        <button type="button" className="v7-link" onClick={() => togglePalette(true)} title="Command palette (⌘K / Ctrl K)">
          Commands <kbd>⌘K</kbd>
        </button>
      </div>
    </header>
  )
}

function Source({ dataset }) {
  if (dataset.plane === 'live') {
    return <span className="v7-src v7-src-live" title="DB-backed OHLCV from /api/historical. No historical GEX.">live prices, no GEX history</span>
  }
  if (dataset.example) {
    return (
      <span className="v7-src v7-src-sample" title={`The bundled sample in public/backtest, used when the dataset service is unreachable or chosen by hand.${dataset.generatedAt ? ` Built ${fmtDay(Date.parse(dataset.generatedAt))}.` : ''}`}>
        bundled sample
      </span>
    )
  }
  return <span className="v7-src">historical + GEX{dataset.version ? ` · v${dataset.version.slice(0, 8)}` : ''}</span>
}
