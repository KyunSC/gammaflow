'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../lib/backtest/store'
import { fmtDateRange } from '../../lib/backtest/format'
import { shareUrl } from '../../lib/backtest/share'
import s from './bt.module.css'

/**
 * One line: where you are, what is loaded, and the session controls.
 * The run tally is always visible — it is the size of the multiple-testing
 * problem, and hiding it behind a mode switch made it easy to ignore.
 */
export default function TopBar() {
  const dataset = useBacktest((st) => st.dataset)
  const runCount = useBacktest((st) => st.runCount)
  const lastRunMs = useBacktest((st) => st.lastRunMs)
  const running = useBacktest((st) => st.running)
  const loading = useBacktest((st) => st.datasetLoading)
  const autoRun = useBacktest((st) => st.autoRun)
  const toggleAutoRun = useBacktest((st) => st.toggleAutoRun)
  const togglePalette = useBacktest((st) => st.togglePalette)
  const toggleShortcuts = useBacktest((st) => st.toggleShortcuts)
  const advanced = useBacktest((st) => st.advanced)
  const setAdvanced = useBacktest((st) => st.setAdvanced)
  const [copied, setCopied] = useState(false)

  // Same two-path copy as the original: the URL always lands in the address
  // bar, the clipboard is a bonus when the browser allows it.
  const copyShare = async () => {
    const url = shareUrl(useBacktest.getState())
    if (!url) return
    try {
      window.history.replaceState(null, '', url)
    } catch { /* ignore */ }
    try {
      await navigator.clipboard.writeText(url)
      setCopied('link copied')
    } catch {
      setCopied('link in address bar')
    }
    setTimeout(() => setCopied(false), 1800)
  }

  const tally = runCount > 300 ? 'text-neg' : runCount > 80 ? 'text-amber' : 'text-muted'

  return (
    <header className={s.topbar}>
      <nav aria-label="Breadcrumb" className="flex items-baseline gap-1.5">
        <Link href="/" className={s.brand} title="Market board">
          GammaFlow
        </Link>
        <span className={s.crumb}>/</span>
        <span className="text-ink">Backtester</span>
      </nav>

      <div className={s.dsline} aria-live="polite">
        {dataset ? (
          <>
            <span className="text-ink">{dataset.symbol}</span>
            <span>{dataset.interval}</span>
            <span>{fmtDateRange(dataset.start, dataset.end)}</span>
            <span>{dataset.n.toLocaleString()} bars</span>
            <span className={dataset.plane === 'research' ? 'text-violet' : 'text-cyan'}>
              {dataset.plane === 'research' ? (dataset.example ? 'bundled sample' : 'historical + GEX') : 'live prices'}
            </span>
          </>
        ) : (
          <span className="text-dim">{loading ? 'loading data…' : 'no data loaded'}</span>
        )}
      </div>

      <div className={s.tools}>
        <button
          onClick={() => toggleShortcuts(true)}
          className={`${s.toolBtn} ${tally}`}
          title="Every run, sweep cell and walk-forward trial this session. Click for what it means."
        >
          {running ? <span className="text-amber">running…</span> : <>run {runCount.toLocaleString()}{advanced && lastRunMs ? <span className="text-dim"> · {lastRunMs.toFixed(0)} ms</span> : null}</>}
        </button>
        <label className="flex cursor-pointer items-center gap-1.5 text-dim" title="Re-run automatically when a setting changes">
          <button role="switch" aria-checked={autoRun} onClick={toggleAutoRun} className="switch" aria-label="Auto-run" />
          <span className={autoRun ? 'text-muted' : ''}>auto-run</span>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-dim" title="Parameter sweep, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules, A/B/C compare">
          <button role="switch" aria-checked={advanced} onClick={() => setAdvanced(!advanced)} className="switch" aria-label="Research tools" />
          <span className={advanced ? 'text-amber' : ''}>research tools</span>
        </label>
        <button onClick={copyShare} className={s.toolBtn} title="Copy a link that reproduces this run">
          {copied ? <span className="text-pos">{copied}</span> : 'share'}
        </button>
        <span className="flex items-center gap-1.5">
          <button onClick={() => toggleShortcuts(true)} className="kbd hover:text-ink" title="Keyboard shortcuts" aria-label="Keyboard shortcuts">
            ?
          </button>
          <button onClick={() => togglePalette(true)} className="kbd hover:text-ink" title="Command palette" aria-label="Command palette">
            ⌘K
          </button>
        </span>
      </div>
    </header>
  )
}
