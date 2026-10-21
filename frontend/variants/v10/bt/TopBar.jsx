'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtDateRange } from '../../../lib/backtest/format'
import { shareUrl } from '../../../lib/backtest/share'
import { gapsFor } from './gaps'

/**
 * What is loaded and how much searching has been done on it. Both are always
 * visible: the sample-data label and the missing-bar count say what the
 * numbers below are made of, and the simulation tally says how many draws the
 * best of them is the maximum of.
 */
export default function TopBar() {
  const dataset = useBacktest((s) => s.dataset)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const runCount = useBacktest((s) => s.runCount)
  const running = useBacktest((s) => s.running)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const togglePalette = useBacktest((s) => s.togglePalette)
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
    setTimeout(() => setCopied(false), 2000)
  }

  const gaps = gapsFor(dataset)
  const tally = runCount > 300 ? 'is-bad' : runCount > 80 ? 'is-warn' : ''
  const source = !dataset
    ? null
    : dataset.plane === 'research'
      ? dataset.example
        ? { cls: 'l10-flag-sample', text: 'Bundled sample, not live data' }
        : { cls: '', text: 'Research dataset with GEX' }
      : { cls: 'l10-flag-live', text: 'Live prices, no historical GEX' }

  return (
    <div className="l10-top" role="banner">
      <div className="l10-brand">
        <Link href="/" title="Market dashboard">GammaFlow</Link>
        <span className="l10-crumb" aria-hidden="true">/</span>
        <span className="l10-here">Backtester</span>
      </div>

      <div className="l10-ds" aria-live="polite">
        {dataset ? (
          <>
            <span><b>{dataset.symbol}</b> {dataset.interval}</span>
            <span className="l10-num">{fmtDateRange(dataset.start, dataset.end)}</span>
            <span><span className="l10-num">{dataset.n.toLocaleString()}</span> bars</span>
            {source && <span className={source.cls}>{source.text}</span>}
            {gaps.supported && gaps.totalMissing > 0 && (
              <span
                className="l10-flag-gap"
                title={`${gaps.idx.length} holes inside trading sessions, ${gaps.totalMissing} bars in total, on ${gaps.days} of ${gaps.sessions} days. The charts plot by bar, so each hole is marked with an amber tick; trades held across one are flagged in the trade list. Whole missing sessions are not counted.`}
              >
                <span className="l10-num">{gaps.totalMissing.toLocaleString()}</span> bars missing on {gaps.days} of {gaps.sessions} days
              </span>
            )}
            {gaps.supported && gaps.totalMissing === 0 && <span>No missing bars inside sessions</span>}
          </>
        ) : (
          <span>{datasetLoading ? 'Loading data…' : 'No data loaded'}</span>
        )}
      </div>

      <div className="l10-top-actions">
        <button
          type="button"
          onClick={() => toggleShortcuts(true)}
          className={`l10-link l10-runs ${tally}`}
          title="Every run, sweep cell and walk-forward trial this session. The more of these on one dataset, the more the best Sharpe is the maximum of many draws rather than an estimate of an edge."
        >
          {running ? 'Running…' : <><span className="l10-num">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session</>}
          {!running && lastRunMs > 0 && advanced && <span className="text-dim"> · last <span className="l10-num">{lastRunMs.toFixed(0)}</span> ms</span>}
        </button>
        <button type="button" role="switch" aria-checked={autoRun} onClick={toggleAutoRun} className="l10-toggle" title="Re-run automatically when a setting changes">
          <span className="switch pointer-events-none" aria-checked={autoRun} />
          Auto-run
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={advanced}
          onClick={() => setAdvanced(!advanced)}
          className="l10-toggle"
          title="Parameter sweeps, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules, A/B/C compare"
        >
          <span className="switch pointer-events-none" aria-checked={advanced} />
          Research tools
        </button>
        <button type="button" onClick={copyShare} className="l10-link" title="Copy a link that reproduces this run" aria-live="polite">
          {copied ? <span className="text-pos">{copied}</span> : 'Share link'}
        </button>
        <button type="button" onClick={() => toggleShortcuts(true)} className="l10-link" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <span className="kbd">?</span>
        </button>
        <button type="button" onClick={() => togglePalette(true)} className="l10-link" aria-label="Command palette" title="Command palette (Ctrl/⌘ K)">
          <span className="kbd">⌘K</span>
        </button>
      </div>
    </div>
  )
}
