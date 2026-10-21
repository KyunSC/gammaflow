'use client'

import { useBacktest } from '../../../lib/backtest/store'

/**
 * A region of the one surface: a plain heading row and a body. No card, no
 * border of its own — the layout's hairline separators do the grouping.
 */
export default function Section({ id, title, meta, right, children, className = '', bodyClassName = '', scroll = true }) {
  return (
    <section id={id} className={`l10-sec ${className}`} aria-label={typeof title === 'string' ? title : undefined}>
      {(title || right) && (
        <header className="l10-sec-head">
          {title && <h2 className="l10-sec-title">{title}</h2>}
          {meta && <span className="l10-sec-meta">{meta}</span>}
          <span className="flex-1" />
          {right}
        </header>
      )}
      <div className={`l10-sec-body ${scroll ? 'overflow-auto' : 'overflow-hidden'} ${bodyClassName}`}>{children}</div>
    </section>
  )
}

export function Empty({ children }) {
  return <div className="l10-empty"><p className="max-w-[46ch] leading-relaxed">{children}</p></div>
}

/** "Nothing to show yet", worded for what to do next. */
export function NotYet({ what = 'Results' }) {
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const error = useBacktest((s) => s.datasetError || s.runError)
  if (loading) return <Empty>Loading bars…</Empty>
  if (running) return <Empty>Running…</Empty>
  if (error) return <Empty>No result: see the message at the top of the page.</Empty>
  return <Empty>{autoRun ? `${what} appear here once a strategy runs.` : `Press Run (or R) to see ${what.toLowerCase()}.`}</Empty>
}

export function Legend({ color, label, dashed, tick }) {
  return (
    <span className="l10-legend">
      <svg width="14" height="8" aria-hidden="true">
        {tick ? (
          <rect x="6" y="0" width="2" height="8" fill={color} />
        ) : (
          <line x1="0" y1="4" x2="14" y2="4" stroke={color} strokeWidth="1.5" strokeDasharray={dashed ? '3,2' : undefined} />
        )}
      </svg>
      {label}
    </span>
  )
}
