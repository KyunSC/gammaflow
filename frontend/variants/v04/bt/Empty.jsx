'use client'

import { useBacktest } from '../../../lib/backtest/store'

export function Empty({ children, action }) {
  return (
    <div className="v4-empty">
      <p>{children}</p>
      {action}
    </div>
  )
}

/** "Nothing yet" worded for what to do next, same rules as the original. */
export function NoRunYet({ what = 'Results' }) {
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  if (loading) return <Empty>Loading bars…</Empty>
  if (running) return <Empty>Running…</Empty>
  return <Empty>{autoRun ? `${what} appear here once a strategy runs.` : `Press Run (or R) to see ${what.toLowerCase()}.`}</Empty>
}
