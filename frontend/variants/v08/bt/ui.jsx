'use client'

import { useBacktest } from '../../../lib/backtest/store'

/**
 * A titled region. No box: a hairline on top, a sentence-case title, and an
 * optional right-hand slot for the region's own controls. The grouping comes
 * from the title and the alignment, not from a border around everything.
 */
export function Region({ title, aside, children, className = '', bodyClassName = '', id, as: Tag = 'section' }) {
  return (
    <Tag className={`v8-region ${className}`} id={id} aria-label={typeof title === 'string' ? title : undefined}>
      {(title || aside) && (
        <header className="v8-region-head">
          {title && <h2 className="v8-region-title">{title}</h2>}
          {aside && <div className="v8-region-aside">{aside}</div>}
        </header>
      )}
      <div className={`v8-region-body ${bodyClassName}`}>{children}</div>
    </Tag>
  )
}

export function Note({ children, action, tone }) {
  return (
    <div className="v8-note" data-tone={tone}>
      <p>{children}</p>
      {action}
    </div>
  )
}

/** What to do next when there is no result yet, worded for the current state. */
export function NoRunYet({ what = 'Results' }) {
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const dataset = useBacktest((s) => s.dataset)
  const datasetError = useBacktest((s) => s.datasetError)
  if (datasetError) return <Note>No data loaded, so there is nothing to show. See the message at the top of the page.</Note>
  if (loading && !dataset) return <Note>Loading bars…</Note>
  if (running) return <Note>Running the backtest…</Note>
  return (
    <Note>
      {autoRun ? `${what} appear once the strategy has run.` : (
        <>
          Auto-run is off. Press <kbd className="kbd">R</kbd> or Run to see {what.toLowerCase()}.
        </>
      )}
    </Note>
  )
}

export function ErrorLine({ children }) {
  return (
    <div className="v8-errline" role="alert">
      {children}
    </div>
  )
}
