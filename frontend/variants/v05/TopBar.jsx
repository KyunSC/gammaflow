'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useBacktest } from '../../lib/backtest/store'
import { fmtDateRange } from '../../lib/backtest/format'
import { shareUrl } from '../../lib/backtest/share'

/**
 * One line: where you are, what is loaded, and the page-level controls. The
 * run tally moved down into the record, next to the numbers it qualifies, so
 * it is visible in the simple view too.
 */
export default function TopBar() {
  const dataset = useBacktest((s) => s.dataset)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const running = useBacktest((s) => s.running)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const [copied, setCopied] = useState(false)

  // Same copy path as the original: the URL always lands in the address bar,
  // so a refused clipboard still leaves a shareable link.
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
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="v05-rule-b flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-[12px]">
      <nav aria-label="Site" className="flex items-baseline gap-2">
        <Link href="/" className="font-mono text-[12px] font-semibold tracking-[0.04em] text-amber no-underline hover:text-ink">
          GammaFlow
        </Link>
        <span className="text-hair-bright" aria-hidden>/</span>
        <h1 className="text-[12px] font-semibold text-ink">Backtester</h1>
      </nav>

      <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 font-mono text-[11px] text-muted" aria-live="polite">
        {dataset ? (
          <>
            <span className="text-ink">{dataset.symbol}</span>
            <span>{dataset.interval} bars</span>
            <span>{fmtDateRange(dataset.start, dataset.end)} ET</span>
            <span className="hidden sm:inline">{dataset.n.toLocaleString()} bars</span>
            <span className={dataset.plane === 'research' ? 'text-violet' : 'text-cyan'}>
              {dataset.plane === 'research' ? (dataset.example ? 'bundled sample' : 'historical + GEX') : 'live prices, no GEX'}
            </span>
          </>
        ) : datasetLoading ? (
          <span className="text-dim">loading bars…</span>
        ) : (
          <span className="text-dim">no dataset loaded</span>
        )}
      </p>

      <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px]">
        <span className="min-w-[64px] text-right" aria-live="polite">
          {running ? <span className="text-amber">running…</span> : advanced && lastRunMs > 0 ? <span className="text-dim">{lastRunMs.toFixed(0)} ms</span> : null}
        </span>
        {advanced && (
          <button
            role="switch"
            aria-checked={autoRun}
            onClick={toggleAutoRun}
            className={`${autoRun ? 'text-cyan' : 'text-dim'} hover:text-ink`}
            title="Re-run automatically when a setting changes"
          >
            auto-run {autoRun ? 'on' : 'off'}
          </button>
        )}
        <button onClick={copyShare} className="text-muted hover:text-ink" title="Copy a link that reproduces this run">
          {copied ? <span className="text-pos">{copied}</span> : 'share link'}
        </button>
        <button
          role="switch"
          aria-checked={advanced}
          onClick={() => setAdvanced(!advanced)}
          className={`flex items-center gap-1.5 ${advanced ? 'text-amber' : 'text-muted'} hover:text-ink`}
          title="Parameter sweeps, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules and A/B/C compare"
        >
          <span className="switch pointer-events-none" aria-checked={advanced} aria-hidden />
          research tools
        </button>
        <button onClick={() => toggleShortcuts(true)} className="text-muted hover:text-ink" title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts">
          ?
        </button>
        <button onClick={() => togglePalette(true)} className="kbd hover:text-ink" title="Command palette" aria-label="Open command palette (Cmd or Ctrl + K)">
          ⌘K
        </button>
      </div>
    </div>
  )
}
