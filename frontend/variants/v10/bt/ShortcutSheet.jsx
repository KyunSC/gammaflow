'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'

const KEYS = [
  ['⌘K / Ctrl K', 'Command palette'],
  ['R', 'Run backtest'],
  ['Alt 1 – 4', 'Strategy family: technical, gamma, model, custom'],
  ['[  ]', 'Step the focused parameter down / up'],
  ['S', 'Run parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A  B  C', 'Pin the current run to a compare slot'],
  ['↑ ↓  Enter', 'Move through trades, pan the chart to one'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
  ['1 – 0  `', 'Switch UI design (` = original)'],
]

export default function ShortcutSheet() {
  const open = useBacktest((s) => s.shortcutsOpen)
  const toggle = useBacktest((s) => s.toggleShortcuts)
  const runCount = useBacktest((s) => s.runCount)
  const closeRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const prev = document.activeElement
    closeRef.current?.focus()
    return () => prev?.focus?.()
  }, [open])

  if (!open) return null
  return (
    <div className="l10-scrim items-center" onClick={() => toggle(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="l10-keys-title"
        onClick={(e) => e.stopPropagation()}
        className="l10-sheet w-[min(480px,calc(100vw-32px))] p-4"
      >
        <div className="mb-3 flex items-baseline">
          <h2 id="l10-keys-title" className="text-[13px] font-semibold">Keyboard</h2>
          <span className="ml-2 text-[11px] text-dim">ignored while typing in a field</span>
          <button ref={closeRef} type="button" onClick={() => toggle(false)} className="l10-link ml-auto text-[12px]">Close</button>
        </div>
        <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5">
          {KEYS.map(([k, label]) => (
            <div key={k} className="contents">
              <dt><span className="kbd inline-block min-w-[80px] text-center">{k}</span></dt>
              <dd className="text-[12px] text-muted">{label}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-4 border-t border-hair pt-3 text-[12px] leading-relaxed text-dim">
          <p>
            <span className="font-mono text-amber">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session:
            single runs, sweep cells and walk-forward trials all count.
          </p>
          <p className="mt-1">
            It is a data-snooping tally. The more of these you burn on one dataset, the more a good-looking Sharpe is
            the maximum of many draws rather than an estimate of an edge.
          </p>
        </div>
      </div>
    </div>
  )
}
