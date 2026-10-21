'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../lib/backtest/store'

const KEYS = [
  ['⌘K', 'Command palette'],
  ['R', 'Run backtest'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['[  ]', 'Step the marked parameter down / up'],
  ['↑ ↓', 'Step through trades (in the trade list)'],
  ['S', 'Run parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A B C', 'Pin the current run to a compare slot'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
  ['1–0  `', 'Switch UI design (` = original)'],
]

/**
 * Variant 05 copy of components/backtest/ShortcutSheet.jsx, without the
 * fade-and-slide. Opens from `?`, the top bar, or the run tally in the record,
 * which is why it also explains what the tally means.
 */
export default function Shortcuts() {
  const open = useBacktest((s) => s.shortcutsOpen)
  const toggle = useBacktest((s) => s.toggleShortcuts)
  const runCount = useBacktest((s) => s.runCount)
  const closeRef = useRef(null)

  useEffect(() => {
    if (open) closeRef.current?.focus()
  }, [open])

  if (!open) return null

  return (
    <div className="v05-overlay flex items-center justify-center p-4" onClick={() => toggle(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="v05-keys-title"
        onClick={(e) => e.stopPropagation()}
        className="w-[min(480px,100%)] rounded-[2px] border border-hair-bright bg-panel p-4"
      >
        <div className="mb-3 flex items-baseline">
          <h2 id="v05-keys-title" className="text-[13px] font-semibold text-ink">Keyboard</h2>
          <span className="flex-1" />
          <button ref={closeRef} onClick={() => toggle(false)} className="font-mono text-[11px] text-dim hover:text-ink">
            close (Esc)
          </button>
        </div>
        <dl className="grid grid-cols-[72px_1fr] gap-x-3 gap-y-1.5">
          {KEYS.map(([k, label]) => (
            <div key={k} className="contents">
              <dt className="kbd text-center">{k}</dt>
              <dd className="text-[12px] text-muted">{label}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-4 border-t border-hair pt-3 text-[12px] leading-relaxed text-muted">
          <p>
            <span className="font-mono text-amber">{runCount.toLocaleString()} runs</span> this session counts every
            simulation: single runs, sweep cells and walk-forward trials alike.
          </p>
          <p className="mt-1">
            It is a data-snooping tally. The more of these you burn on one dataset, the more a
            good-looking Sharpe is the maximum of many draws rather than an estimate of an edge.
          </p>
        </div>
      </div>
    </div>
  )
}
