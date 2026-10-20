'use client'

import { useBacktest } from '../../lib/backtest/store'
import s from './bt.module.css'

const KEYS = [
  ['R', 'Run backtest'],
  ['[  ]', 'Step the focused parameter down / up'],
  ['Alt 1–4', 'Strategy family: technical, gamma, model, custom'],
  ['S', 'Run parameter sweep'],
  ['W', 'Run walk-forward'],
  ['M', 'Run Monte Carlo'],
  ['A B C', 'Pin the current run to a compare slot'],
  ['⌘K', 'Command palette'],
  ['1–0  `', 'Switch UI design (` = original)'],
  ['?', 'This sheet'],
  ['Esc', 'Close'],
]

/** Shortcut sheet and the meaning of the run tally. No motion, no blur. */
export default function Shortcuts() {
  const open = useBacktest((st) => st.shortcutsOpen)
  const toggle = useBacktest((st) => st.toggleShortcuts)
  const runCount = useBacktest((st) => st.runCount)
  if (!open) return null

  return (
    <div className={s.scrim} onClick={() => toggle(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="v02-keys-title" className={s.sheet} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="v02-keys-title" className="text-[13px] font-semibold text-ink">Keyboard</h2>
          <button onClick={() => toggle(false)} className="text-[11px] text-dim hover:text-ink" autoFocus>
            close (Esc)
          </button>
        </div>
        <dl className="grid grid-cols-[76px_1fr] gap-x-3 gap-y-1.5 text-[12px]">
          {KEYS.map(([k, label]) => (
            <div key={k} className="contents">
              <dt><span className="kbd">{k}</span></dt>
              <dd className="text-muted">{label}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-4 border-t border-hair pt-3 text-[12px] leading-relaxed text-muted">
          <p>
            <span className="font-mono text-amber">{runCount.toLocaleString()}</span> simulation{runCount === 1 ? '' : 's'} this session, counting single runs, every sweep cell and every walk-forward trial.
          </p>
          <p className="mt-1.5 text-dim">
            It is a data-snooping tally. The more runs you spend on one dataset, the more a good-looking Sharpe is the best of many draws rather than an estimate of an edge.
          </p>
        </div>
      </div>
    </div>
  )
}
