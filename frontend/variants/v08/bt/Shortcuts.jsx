'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'

const KEYS = [
  ['R', 'Run the backtest'],
  ['[  ]', 'Step the focused parameter down / up'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['↑  ↓', 'Step through trades (with the trade list focused)'],
  ['S', 'Run a parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A  B  C', 'Pin the current run to a compare slot'],
  ['⌘K / Ctrl K', 'Command palette'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
  ['1–9, 0,  `', 'Switch UI design (` is the original)'],
]

export default function Shortcuts() {
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
    <div className="v8-overlay" onClick={() => toggle(false)}>
      <div className="v8-dialog" role="dialog" aria-modal="true" aria-labelledby="v8-keys-title" onClick={(e) => e.stopPropagation()}>
        <div className="v8-dialog-head">
          <h2 id="v8-keys-title">Keyboard</h2>
          <button ref={closeRef} type="button" className="v8-textbtn" onClick={() => toggle(false)}>
            Close <kbd className="kbd">Esc</kbd>
          </button>
        </div>
        <dl className="v8-keys">
          {KEYS.map(([k, label]) => (
            <div key={k}>
              <dt><kbd className="kbd">{k}</kbd></dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
        <p className="v8-hint">Shortcuts never fire while a text field or menu has focus.</p>
        <div className="v8-dialog-foot">
          <p>
            <span className="text-amber num">{runCount.toLocaleString()}</span> run{runCount === 1 ? '' : 's'} this session. Every single run, sweep cell and
            walk-forward trial counts.
          </p>
          <p>
            It is a data-snooping tally: the more of these you spend on one dataset, the more a good-looking Sharpe is the
            maximum of many draws rather than an estimate of an edge.
          </p>
        </div>
      </div>
    </div>
  )
}
