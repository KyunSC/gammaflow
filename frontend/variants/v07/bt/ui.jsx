'use client'

import { useBacktest } from '../../../lib/backtest/store'

export function Empty({ children, action }) {
  return (
    <div className="v7-empty">
      <p>{children}</p>
      {action}
    </div>
  )
}

/** "Nothing yet" worded for what is actually happening. */
export function NoRunYet({ what = 'Results' }) {
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const datasetError = useBacktest((s) => s.datasetError)
  if (datasetError) return <Empty>No data loaded, so nothing to show. See the error above.</Empty>
  if (loading) return <Empty>Loading bars…</Empty>
  if (running) return <Empty>Running…</Empty>
  return <Empty>{autoRun ? `${what} appear here once the strategy runs.` : `Press Run (R) to see ${what.toLowerCase()}.`}</Empty>
}

export function Switch({ checked, onChange, label, title, id }) {
  return (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={Boolean(checked)}
      aria-label={label}
      title={title}
      onClick={() => onChange(!checked)}
      className="v7-switch"
    />
  )
}

/** Section heading inside the rail and the ledger. */
export function Heading({ children, right, id }) {
  return (
    <div className="v7-heading">
      <h3 id={id}>{children}</h3>
      {right}
    </div>
  )
}

const DAY = { day: 'numeric', month: 'short', timeZone: 'America/New_York' }

/** "24 Apr – 10 Jul 2026" — the original tape dropped the year. */
export function fmtRange(startMs, endMs) {
  if (!startMs || !endMs) return '—'
  const s = new Date(startMs)
  const e = new Date(endMs)
  const year = (d) => d.toLocaleDateString('en-US', { year: 'numeric', timeZone: 'America/New_York' })
  const day = (d, withYear) => d.toLocaleDateString('en-GB', withYear ? { ...DAY, year: 'numeric' } : DAY)
  return year(s) === year(e) ? `${day(s)} – ${day(e, true)}` : `${day(s, true)} – ${day(e, true)}`
}

export function fmtDay(ms) {
  if (!ms) return '—'
  return new Date(ms).toLocaleDateString('en-GB', { ...DAY, year: 'numeric' })
}

/** Signed money with a real minus sign. */
export const minus = (s) => (typeof s === 'string' ? s.replace(/^-/, '−') : s)
