'use client'

import { useMemo } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtMoneySigned, signClass } from '../../../lib/backtest/format'
import { tradingDay } from '../../../lib/backtest/time'
import { findGaps, missingInSpan, gapExposure } from './gaps'
import { Note } from './ui'

export const FOCUS_EVENT = 'v8:focus-range'

const dayLabel = (s) =>
  new Date(s * 1000).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/New_York' })
const hm = (s) => new Date(s * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' })

/**
 * Every session with missing bars, and what the strategy did across them.
 * Choosing a session pans the price chart to it.
 */
export default function GapsList() {
  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const gaps = findGaps(dataset)

  const rows = useMemo(() => {
    if (!gaps) return []
    const byDay = new Map(gaps.days.map((d) => [d.day, { ...d, holeList: [], trades: 0, pnl: 0 }]))
    for (const h of gaps.holes) byDay.get(h.day)?.holeList.push(h)
    for (const t of result?.trades || []) {
      if (missingInSpan(gaps, t.entryIdx, t.exitIdx) <= 0) continue
      const r = byDay.get(tradingDay(dataset.time[t.exitIdx])) || byDay.get(tradingDay(dataset.time[t.entryIdx]))
      if (r) {
        r.trades++
        r.pnl += t.pnl
      }
    }
    return [...byDay.values()]
  }, [gaps, result, dataset])

  if (!dataset) return <Note>No data loaded.</Note>
  if (!gaps) return <Note>Daily bars: holes inside a session do not apply at this interval.</Note>
  if (!gaps.holes.length) return <Note>Every session in this dataset has a continuous run of {dataset.interval} bars.</Note>

  const exposure = gapExposure(gaps, result?.trades)
  const focus = (h) => window.dispatchEvent(new CustomEvent(FOCUS_EVENT, { detail: { from: h.idx - 40, to: h.idx + 40 } }))

  return (
    <div className="v8-gaps">
      <p className="v8-gaps-lede">
        <span className="v8-gapnote">{gaps.days.length} of {gaps.sessions} sessions</span> have {gaps.holes.length} holes, {gaps.missingBars.toLocaleString()}{' '}
        {dataset.interval} bars in all. The price chart draws bar after bar with no space for a hole, so each one is marked on the rail under the candles.
        {exposure && exposure.n > 0 && (
          <>
            {' '}In this run, {exposure.n} of {exposure.total} trades were open across a hole and made{' '}
            <span className={signClass(exposure.pnl)}>{fmtMoneySigned(exposure.pnl)}</span> between them; their marks skip prices nobody could trade at.
          </>
        )}
      </p>
      <table className="v8-table">
        <thead>
          <tr>
            <th scope="col">Session</th>
            <th scope="col">Holes (ET)</th>
            <th scope="col" className="r">Missing bars</th>
            <th scope="col" className="r">Trades across</th>
            <th scope="col" className="r">Their P/L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.day}>
              <td>
                <button type="button" className="v8-textbtn" onClick={() => focus(r.holeList[0])} title="Show this session on the price chart">
                  {dayLabel(r.start)}
                </button>
              </td>
              <td className="text-dim">
                {r.holeList.slice(0, 3).map((h) => `${hm(h.from)}–${hm(h.to)}`).join(', ')}
                {r.holeList.length > 3 && ` +${r.holeList.length - 3} more`}
              </td>
              <td className="r num">{r.missing}</td>
              <td className="r num">{r.trades || <span className="text-dim">0</span>}</td>
              <td className={`r num ${r.trades ? signClass(r.pnl) : 'text-dim'}`}>{r.trades ? fmtMoneySigned(r.pnl) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
