'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtDateRange } from '../../../lib/backtest/format'
import { shareUrl } from '../../../lib/backtest/share'
import { Switch } from './ui'

/** One line: where you are, what is loaded, and the page-level actions. */
export default function TopBar() {
  const dataset = useBacktest((s) => s.dataset)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const running = useBacktest((s) => s.running)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const [copied, setCopied] = useState(false)

  // Clipboard can be refused; the URL always lands in the address bar too.
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

  return (
    <header className="v3-top">
      <nav className="v3-crumbs" aria-label="Site">
        <Link href="/" className="v3-brand">GammaFlow</Link>
        <span className="v3-crumb-sep" aria-hidden="true">/</span>
        <span className="v3-crumb-here" aria-current="page">Backtester</span>
      </nav>

      <p className="v3-top-data">
        {dataset ? (
          <>
            <b>{dataset.symbol}</b> {dataset.interval} · {fmtDateRange(dataset.start, dataset.end)} · {dataset.n.toLocaleString()} bars ·{' '}
            <span className={dataset.plane === 'research' ? 'v3-violet' : 'v3-cyan'}>
              {dataset.plane === 'research' ? (dataset.example ? 'bundled sample' : 'historical + GEX') : 'live prices'}
            </span>
            {advanced && !running && lastRunMs > 0 && <span className="v3-dim"> · last run {lastRunMs.toFixed(0)} ms</span>}
          </>
        ) : (
          <span className="v3-dim">No data loaded</span>
        )}
      </p>

      <div className="v3-top-actions">
        <button type="button" onClick={copyShare} className="v3-link" title="Copy a link that reproduces this run" aria-live="polite">
          {copied ? <span className="v3-pos">{copied}</span> : 'Share'}
        </button>
        <label className="v3-check" title="Show research tools: sweeps, walk-forward, Monte Carlo, cost ladder, prop accounts, custom rules, A/B/C compare">
          <Switch checked={advanced} onChange={setAdvanced} label="Advanced view" />
          <span>Advanced</span>
        </label>
        <button type="button" onClick={() => toggleShortcuts(true)} className="v3-link" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <kbd className="kbd">?</kbd>
        </button>
        <button type="button" onClick={() => togglePalette(true)} className="v3-link v3-hide-sm" title="Command palette (⌘K / Ctrl+K)">
          <kbd className="kbd">⌘K</kbd>
        </button>
      </div>
    </header>
  )
}
