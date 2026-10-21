'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../../lib/backtest/store'
import { shareUrl } from '../../../lib/backtest/share'
import { findGaps } from './gaps'

const day = (ms, withYear) =>
  new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'America/New_York' })

export const dateRange = (startMs, endMs) => (startMs && endMs ? `${day(startMs)} – ${day(endMs, true)}` : '—')

/** Where the bars came from, said plainly. */
export function sourceLabel(dataset) {
  if (!dataset) return null
  if (dataset.plane === 'research') return dataset.example ? 'Bundled sample, not live data' : 'Published history with GEX'
  return 'Live prices, exploratory'
}

/**
 * The page header: what is loaded, where it came from, how many holes it has,
 * and how many runs this session has burned. The runs tally shows in every
 * view: a Sharpe found on run 3 and one found on run 900 are not the same claim.
 */
export default function Header({ onShowGaps }) {
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

  const gaps = findGaps(dataset)

  // The Clipboard API rejects on insecure origins and when permission is
  // denied, so the URL always lands in the address bar too.
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
    setTimeout(() => setCopied(false), 2000)
  }

  const tally = runCount > 300 ? 'v8-tally-high' : runCount > 80 ? 'v8-tally-mid' : ''

  return (
    <header className="v8-bthead">
      <div className="v8-bthead-id">
        <Link href="/" className="v8-wordmark" title="Back to the markets dashboard">
          GammaFlow
        </Link>
        <span className="v8-crumb-sep" aria-hidden>/</span>
        <h1 className="v8-pagename">Backtest</h1>
      </div>

      <div className="v8-bthead-data" aria-live="polite">
        {dataset ? (
          <>
            <span className="v8-ink">
              {dataset.symbol} {dataset.interval}
            </span>
            <span>{dateRange(dataset.start, dataset.end)}</span>
            <span className="num">{dataset.n.toLocaleString()} bars</span>
            <span className={dataset.example ? 'v8-flag' : dataset.plane === 'live' ? 'text-cyan' : 'text-violet'}>
              {sourceLabel(dataset)}
            </span>
            {gaps && gaps.holes.length > 0 && (
              <button type="button" className="v8-gapflag" onClick={onShowGaps} title="List the sessions with missing bars">
                {gaps.days.length} of {gaps.sessions} sessions have missing bars
              </button>
            )}
            {gaps && gaps.holes.length === 0 && <span className="text-dim">No missing bars inside sessions</span>}
          </>
        ) : (
          <span className="text-dim">{datasetLoading ? 'Loading data…' : 'No data loaded'}</span>
        )}
      </div>

      <div className="v8-bthead-tools">
        <button
          type="button"
          onClick={() => toggleShortcuts(true)}
          className={`v8-tally ${tally}`}
          title="Every run, sweep cell and walk-forward trial this session. The more you run on one dataset, the more a good Sharpe is the best of many draws."
        >
          <span className="text-dim">Runs this session</span> <span className="num">{runCount.toLocaleString()}</span>
        </button>
        <span className="v8-runstate num" aria-live="polite">
          {running ? 'running…' : lastRunMs ? `${lastRunMs.toFixed(0)} ms` : ''}
        </span>
        <label className="v8-toggle" title="Re-run automatically when a setting changes">
          <button type="button" role="switch" aria-checked={autoRun} onClick={toggleAutoRun} className="switch" aria-label="Auto-run" />
          <span>Auto-run</span>
        </label>
        <label
          className="v8-toggle"
          title="Parameter sweeps, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules and A/B/C compare"
        >
          <button type="button" role="switch" aria-checked={advanced} onClick={() => setAdvanced(!advanced)} className="switch" aria-label="Research tools" />
          <span>Research tools</span>
        </label>
        <button type="button" onClick={copyShare} className="v8-textbtn" title="Copy a link that reproduces this run">
          {copied ? <span className="text-pos">{copied}</span> : 'Copy link'}
        </button>
        <button type="button" onClick={() => toggleShortcuts(true)} className="v8-textbtn" title="Keyboard shortcuts (?)">
          Keys <kbd className="kbd">?</kbd>
        </button>
        <button type="button" onClick={() => togglePalette(true)} className="v8-textbtn" title="Command palette (⌘K or Ctrl+K)">
          <kbd className="kbd">⌘K</kbd>
        </button>
      </div>
    </header>
  )
}
