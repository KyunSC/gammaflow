'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtDateRange } from '../../../lib/backtest/format'
import { shareUrl } from '../../../lib/backtest/share'
import { findHoles } from '../gaps'

/**
 * What is loaded, how trustworthy it is, and how many simulations this
 * session has burned. The run tally is always on screen here (the original
 * hid it outside Advanced): every run, sweep cell and walk-forward trial adds
 * to it, so it is the size of the multiple-testing problem in front of you.
 */
export default function TopBar() {
  const dataset = useBacktest((s) => s.dataset)
  const runCount = useBacktest((s) => s.runCount)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const running = useBacktest((s) => s.running)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const [copied, setCopied] = useState(false)

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

  const holes = findHoles(dataset)
  const tally = runCount > 300 ? 'v4-neg' : runCount > 80 ? 'v4-amber' : 'v4-muted'
  const source = !dataset
    ? null
    : dataset.plane === 'research'
      ? dataset.example
        ? { text: 'Bundled sample', cls: 'v4-amber', title: 'The QQQ/SPY 5m file shipped with the app, not the published research dataset' }
        : { text: 'Published history + GEX', cls: 'v4-muted', title: dataset.version ? `Version ${dataset.version.slice(0, 8)}` : undefined }
      : { text: 'Live prices, exploratory', cls: 'v4-muted', title: 'DB-backed OHLCV with no historical GEX. Shared links reload current history.' }

  return (
    <header className="v4-top">
      <Link href="/" className="v4-top-brand" title="Back to the markets dashboard">
        <b>GammaFlow</b>
        <span>Backtester</span>
      </Link>

      {dataset ? (
        <span className="v4-top-ds">
          <span className="v4-sym">{dataset.symbol}</span>
          <span className="v4-mono">{dataset.interval}</span>
          <span className="v4-mono">{fmtDateRange(dataset.start, dataset.end)}</span>
          <span><span className="v4-mono">{dataset.n.toLocaleString()}</span> bars</span>
          {source && <span className={source.cls} title={source.title}>{source.text}</span>}
          {holes?.holes.length > 0 && (
            <span
              className="v4-amber"
              title={`${holes.holes.length} gaps inside a session, ${holes.missing.toLocaleString()} missing ${dataset.interval} bars in all. Drawn as stripes on the price chart.`}
            >
              {holes.sessions} sessions with missing bars
            </span>
          )}
        </span>
      ) : (
        <span className="v4-top-ds">{datasetLoading ? 'Loading data…' : 'No data loaded'}</span>
      )}

      <span className="v4-top-right">
        {running ? (
          <span className="v4-amber" role="status">Running…</span>
        ) : advanced && runCount > 0 ? (
          <span className="v4-dim v4-mono" title="Time the last run took">{lastRunMs.toFixed(0)} ms</span>
        ) : null}
        <button
          onClick={() => toggleShortcuts(true)}
          className={tally}
          title="Simulations this session, counting every sweep cell and walk-forward trial. A data-snooping tally."
        >
          <span className="v4-mono">{runCount.toLocaleString()}</span> {runCount === 1 ? 'run' : 'runs'}
        </button>
        <button onClick={copyShare} title="Copy a link that reproduces this run" aria-live="polite">
          {copied ? <span className="v4-pos">{copied}</span> : 'Share'}
        </button>
        <button
          role="switch"
          aria-checked={advanced}
          onClick={() => setAdvanced(!advanced)}
          className="flex items-center gap-1.5"
          title="Research tools: parameter sweeps, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules, A/B/C compare"
          style={advanced ? { color: 'var(--v4-amber)' } : undefined}
        >
          <span className="switch pointer-events-none" aria-checked={advanced} />
          Advanced
        </button>
        <button onClick={() => toggleShortcuts(true)} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <span className="v4-kbd">?</span>
        </button>
        <button onClick={() => togglePalette(true)} aria-label="Command palette" title="Command palette (⌘K / Ctrl K)">
          <span className="v4-kbd">⌘K</span>
        </button>
      </span>
    </header>
  )
}
