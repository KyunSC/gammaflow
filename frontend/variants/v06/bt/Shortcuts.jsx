'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'

const KEYS = [
  ['⌘K', 'Command palette'],
  ['R', 'Run backtest'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['[  ]', 'Step the focused parameter down / up'],
  ['S', 'Run parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A B C', 'Pin the current run to a compare slot'],
  ['↑ ↓', 'Step through trades (trade list focused)'],
  ['1–0  `', 'Switch UI design (` is the original)'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
]

/** The keyboard sheet, without the blur and slide of the original, as a
 *  labelled dialog that takes focus and gives it back. */
export default function Shortcuts() {
  const open = useBacktest((s) => s.shortcutsOpen)
  const toggle = useBacktest((s) => s.toggleShortcuts)
  const runCount = useBacktest((s) => s.runCount)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const prev = document.activeElement
    ref.current?.focus()
    return () => prev?.focus?.()
  }, [open])

  if (!open) return null
  return (
    <div className="v6-overlay" onClick={() => toggle(false)}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="v6-keys-title"
        className="v6-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center">
          <h2 id="v6-keys-title" className="v6-h">Keyboard</h2>
          <button type="button" className="v6-link ml-auto" onClick={() => toggle(false)}>Close</button>
        </div>
        <dl className="v6-keys">
          {KEYS.map(([k, label]) => (
            <div key={k}>
              <dt><span className="kbd">{k}</span></dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
        <div className="v6-dialog-note">
          <p>
            <span className="text-amber">Run {runCount.toLocaleString()}</span> counts every simulation this session: single runs, sweep
            cells and walk-forward trials alike.
          </p>
          <p>
            It is a data-snooping tally. The more of these you spend on one dataset, the more a good-looking Sharpe is the
            maximum of many draws rather than an estimate of an edge.
          </p>
        </div>
      </div>
    </div>
  )
}
