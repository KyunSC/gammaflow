'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../lib/backtest/store'

const KEYS = [
  ['R', 'Run backtest'],
  ['[  ]', 'Step the selected parameter down / up'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['S', 'Run parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A  B  C', 'Pin the current run to a compare slot'],
  ['↑  ↓', 'Next / previous trade (trade list focused)'],
  ['⌘K / Ctrl K', 'Command palette'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
  ['1–0  `', 'Switch UI design (` is the original)'],
]

/** Shortcut sheet: a plain dialog, no blur or entrance animation. */
export default function Keys() {
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(5,6,7,0.78)] p-4" onClick={() => toggle(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="v9-keys-title"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-[min(480px,100%)] overflow-y-auto border border-hair-bright bg-canvas p-5"
      >
        <div className="mb-3 flex items-baseline">
          <h2 id="v9-keys-title" className="text-[14px] font-semibold text-ink">Keyboard</h2>
          <span className="flex-1" />
          <button ref={closeRef} onClick={() => toggle(false)} className="v9-btn">Close <span className="v9-kbd">Esc</span></button>
        </div>
        <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5 text-[12.5px]">
          {KEYS.map(([k, label]) => (
            <div key={k} className="contents">
              <dt className="v9-num text-right text-amber">{k}</dt>
              <dd className="text-muted">{label}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 border-t border-hair pt-3 text-[12px] leading-relaxed text-dim">
          <span className="v9-num text-ink">{runCount.toLocaleString()}</span> run{runCount === 1 ? '' : 's'} this session. The tally counts every simulation:
          single runs, sweep cells and walk-forward trials. The more of these you spend on one dataset, the more a good-looking Sharpe is
          the maximum of many draws rather than an estimate of an edge.
        </p>
      </div>
    </div>
  )
}
