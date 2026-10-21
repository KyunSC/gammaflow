'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'

const KEYS = [
  ['R', 'Run the backtest'],
  ['[ ]', 'Step the focused parameter down / up'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['S', 'Run a parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A B C', 'Pin the current run to a compare slot'],
  ['↑ ↓', 'Step through trades (trade list focused)'],
  ['⌘K', 'Command palette (Ctrl K on Windows / Linux)'],
  ['?', 'This list'],
  ['Esc', 'Close'],
  ['1–9 0 `', 'Switch UI design (` = original)'],
]

/** Keyboard reference and what the simulation count means. No blur, no motion. */
export default function Shortcuts() {
  const open = useBacktest((s) => s.shortcutsOpen)
  const toggle = useBacktest((s) => s.toggleShortcuts)
  const runCount = useBacktest((s) => s.runCount)
  const closeRef = useRef(null)
  const returnTo = useRef(null)

  useEffect(() => {
    if (open) {
      returnTo.current = document.activeElement
      closeRef.current?.focus()
    } else if (returnTo.current) {
      returnTo.current.focus?.()
      returnTo.current = null
    }
  }, [open])

  if (!open) return null
  return (
    <div className="v7-overlay" onClick={() => toggle(false)}>
      <div className="v7-sheet" role="dialog" aria-modal="true" aria-labelledby="v7-keys-title" onClick={(e) => e.stopPropagation()}>
        <div className="v7-sheet-head">
          <h2 id="v7-keys-title">Keyboard</h2>
          <button ref={closeRef} type="button" className="v7-link" onClick={() => toggle(false)}>
            Close <kbd>Esc</kbd>
          </button>
        </div>
        <dl className="v7-keys">
          {KEYS.map(([k, label]) => (
            <div key={k}>
              <dt><kbd>{k}</kbd></dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
        <p className="v7-sheet-note">
          Shortcuts are ignored while a text field or select has focus.
        </p>
        <p className="v7-sheet-note">
          <strong className="v7-amber">{runCount.toLocaleString()} simulation{runCount === 1 ? '' : 's'}</strong> this session counts
          every run, sweep cell and walk-forward trial. It is a data-snooping tally: the more of them you spend on one
          dataset, the more a good-looking Sharpe is the maximum of many draws rather than an estimate of an edge.
        </p>
      </div>
    </div>
  )
}
