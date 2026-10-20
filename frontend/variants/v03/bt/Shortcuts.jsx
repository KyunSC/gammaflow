'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'

const KEYS = [
  ['R', 'Run the backtest'],
  ['[  ]', 'Step the focused parameter down / up'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['S', 'Run a parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A  B  C', 'Pin the current run to a compare slot'],
  ['↑  ↓', 'Step through trades (trade list focused)'],
  ['⌘K', 'Command palette (Ctrl+K)'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
  ['1–0  `', 'Switch UI design (` is the original)'],
]

/** Shortcut sheet and the meaning of the run tally. No animation. */
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
    <div className="v3-overlay" onClick={() => toggle(false)}>
      <div className="v3-dialog v3-sheet" role="dialog" aria-modal="true" aria-labelledby="v3-keys-title" onClick={(e) => e.stopPropagation()}>
        <div className="v3-sheet-head">
          <h2 id="v3-keys-title">Keyboard</h2>
          <button type="button" ref={closeRef} className="v3-link" onClick={() => toggle(false)}>Close <kbd className="kbd">Esc</kbd></button>
        </div>
        <table className="v3-keys">
          <tbody>
            {KEYS.map(([k, label]) => (
              <tr key={k}>
                <th scope="row"><kbd className="kbd">{k}</kbd></th>
                <td>{label}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="v3-sheet-foot">
          <p>
            <b className="v3-amber">{runCount.toLocaleString()} simulation{runCount === 1 ? '' : 's'}</b> this session: single
            runs, sweep cells and walk-forward trials all count.
          </p>
          <p>
            It is a data-snooping tally. The more runs you spend on one dataset, the more a good-looking Sharpe is the
            maximum of many draws rather than an estimate of an edge.
          </p>
        </div>
      </div>
    </div>
  )
}
