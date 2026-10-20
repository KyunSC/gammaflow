'use client'

import { useEffect, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import b from './bt.module.css'

const KEYS = [
  ['⌘K / Ctrl K', 'Command palette'],
  ['R', 'Run the backtest'],
  ['[  ]', 'Step the focused parameter down / up'],
  ['Alt 1 – 4', 'Strategy family: technical, gamma, model, custom'],
  ['S', 'Run the parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A  B  C', 'Pin the current run to a compare slot'],
  ['↑ ↓  Home  End', 'In the trades list: step through trades (the chart follows)'],
  ['← →', 'In the tab row: switch tab'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
  ['1 – 0  `', 'Switch UI design (` = original)'],
]

/** Copy of components/backtest/ShortcutSheet.jsx as a plain dialog: no blur, no motion. */
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
    <div className={b.overlay} onClick={() => toggle(false)}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="v01-keys" className={b.sheet} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-baseline">
          <h2 id="v01-keys" className={`${b.h2} flex-1`}>Keyboard</h2>
          <button type="button" className="text-[12px] text-dim hover:text-ink" onClick={() => toggle(false)}>Close (Esc)</button>
        </div>
        <dl className={b.keys}>
          {KEYS.map(([k, label]) => (
            <div key={k} className="contents">
              <dt>{k}</dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
        <div className={b.sheetNote}>
          <p>
            <span className="font-mono text-amber">{runCount.toLocaleString()} runs</span> so far counts every simulation this
            session — single runs, sweep cells and walk-forward trials alike.
          </p>
          <p className="mt-1">
            It is a data-snooping tally. The more of these you spend on one dataset, the more a good-looking Sharpe is the
            maximum of many draws rather than an estimate of an edge.
          </p>
          <p className="mt-1">Shortcuts never fire while a text field or select has focus.</p>
        </div>
      </div>
    </div>
  )
}
