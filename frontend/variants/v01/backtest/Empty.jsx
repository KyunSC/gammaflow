'use client'

import { useBacktest } from '../../../lib/backtest/store'
import b from './bt.module.css'

export function Empty({ children, action }) {
  return (
    <div className={b.empty}>
      <p>{children}</p>
      {action}
    </div>
  )
}

/** "Nothing yet", worded for what the user should do next. */
export function NotYet({ what = 'Results' }) {
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const dataset = useBacktest((s) => s.dataset)
  const error = useBacktest((s) => s.datasetError)
  if (loading) return <Empty>Loading bars…</Empty>
  if (!dataset && error) return <Empty>No data loaded, so there is nothing to show. See the message at the top.</Empty>
  if (running) return <Empty>Running the backtest…</Empty>
  return <Empty>{autoRun ? `${what} appear here once the strategy runs.` : `Press Run (R) to see ${what.toLowerCase()}.`}</Empty>
}
