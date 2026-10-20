'use client'

import { useMemo } from 'react'
import useGaps from './useGaps'
import { dayLabel } from '../gaps'

/**
 * Bar coverage of the loaded data. The charts compress time, so this is the
 * only place the number of holes is written down; the charts draw them as
 * hatched columns and the trade list flags trades held across one.
 */
export default function DataQuality() {
  const gaps = useGaps()

  const byDay = useMemo(() => {
    if (!gaps?.holes?.length) return []
    const m = new Map()
    for (const h of gaps.holes) {
      const cur = m.get(h.day) || { day: h.day, holes: 0, missing: 0 }
      cur.holes++
      cur.missing += h.missing
      m.set(h.day, cur)
    }
    return [...m.values()]
  }, [gaps])

  if (!gaps || !gaps.prefix) return null

  if (!gaps.holes.length && !gaps.shortDays.length) {
    return <p className="v3-note">No missing bars inside sessions ({gaps.sessions} sessions checked).</p>
  }

  return (
    <details className="v3-quality">
      <summary>
        <span className="v3-gap-swatch" aria-hidden="true" />
        <span>
          <strong>{gaps.missingBars.toLocaleString()} missing bars</strong> in {gaps.holes.length} holes on {gaps.days} of {gaps.sessions} sessions
          {gaps.shortDays.length > 0 && <>; {gaps.shortDays.length} sessions have under half the usual {gaps.medianBars} bars</>}.
        </span>
      </summary>
      <div className="v3-quality-body">
        <p className="v3-note">
          Charts draw bars edge to edge, so holes are marked as hatched columns. Trades held across a hole are
          flagged in the trade list: the engine saw no bars inside the hole, so no stop, target or exit signal
          could fire there.
        </p>
        {byDay.length > 0 && (
          <table className="v3-mini-table">
            <thead>
              <tr><th scope="col">Session</th><th scope="col">Holes</th><th scope="col">Bars missing</th></tr>
            </thead>
            <tbody>
              {byDay.map((d) => (
                <tr key={d.day}><td>{dayLabel(d.day)}</td><td>{d.holes}</td><td>{d.missing}</td></tr>
              ))}
            </tbody>
          </table>
        )}
        {gaps.shortDays.length > 0 && (
          <p className="v3-note">
            Short sessions (under half of {gaps.medianBars} bars, from early closes or missing data):{' '}
            {gaps.shortDays.map((d) => `${dayLabel(d.day)} (${d.bars})`).join(', ')}.
          </p>
        )}
      </div>
    </details>
  )
}
