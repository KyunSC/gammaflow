'use client'

import { useMemo } from 'react'
import { useBacktest } from '../../lib/backtest/store'
import { fmtMoneySigned, signClass } from '../../lib/backtest/format'
import { findGaps, missingInTrade, tradeExposure } from './gaps'

const hm = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false })
const dayLabel = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric' })

/**
 * Per-session list of holes in the bars: when they are, how many bars are
 * missing, and which trades were open across them. Counted from the
 * timestamps; nothing is interpolated.
 */
export default function GapsTab() {
  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const gaps = useMemo(() => findGaps(dataset), [dataset])

  const rows = useMemo(() => {
    if (!gaps?.supported) return []
    const trades = result?.trades || []
    return gaps.days
      .filter((d) => d.missing > 0)
      .map((d) => {
        const held = trades.filter((t) => missingInTrade(gaps, t) > 0 && d.holes.some((h) => h.i > t.entryIdx && h.i <= t.exitIdx))
        return { ...d, held, heldPnl: held.reduce((s, t) => s + t.pnl, 0) }
      })
  }, [gaps, result])

  if (!dataset) return <p className="p-4 text-[12px] text-dim">No data loaded.</p>
  if (!gaps?.supported) {
    return <p className="p-4 text-[12px] text-dim">The missing-bar check runs on intraday bars only; this dataset is {dataset.interval}.</p>
  }
  const exp = tradeExposure(gaps, result?.trades)

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[96ch] px-4 py-2.5 text-[12.5px] leading-snug text-muted">
        {gaps.missingBars === 0 ? (
          <p>No missing bars inside any of the {gaps.sessionCount} sessions in {dataset.symbol} {dataset.interval}.</p>
        ) : (
          <>
            <p>
              <span className="text-ink">{gaps.gapDays} of {gaps.sessionCount} sessions</span> have holes:{' '}
              <span className="v9-num text-ink">{gaps.missingBars.toLocaleString()}</span> {dataset.interval} bars missing across{' '}
              <span className="v9-num text-ink">{gaps.holes.length}</span> holes. A trade open across a hole is marked to market only
              on the bars that exist, so its fill path and P&amp;L inside the hole are unknown.
            </p>
            {exp && exp.trades > 0 && (
              <p className="mt-1">
                {exp.affected} of {exp.trades} trades were held across a hole. Together they made{' '}
                <span className={`v9-num ${signClass(exp.affectedPnl)}`}>{fmtMoneySigned(exp.affectedPnl)}</span>; the run made{' '}
                <span className={`v9-num ${signClass(exp.totalPnl)}`}>{fmtMoneySigned(exp.totalPnl)}</span> in total, or{' '}
                <span className={`v9-num ${signClass(exp.totalPnl - exp.affectedPnl)}`}>{fmtMoneySigned(exp.totalPnl - exp.affectedPnl)}</span>{' '}
                without them.
              </p>
            )}
            <p className="mt-1 text-dim">Shaded slots on the price chart and ticks under the equity curve mark the same holes. Sessions that start late or end early are not counted here.</p>
          </>
        )}
      </div>
      {rows.length > 0 && (
        <table className="w-full min-w-[560px] text-left text-[12px]">
          <thead className="text-[11.5px] text-dim">
            <tr className="border-y border-hair">
              <th scope="col" className="px-4 py-1 font-normal">Session</th>
              <th scope="col" className="px-2 py-1 text-right font-normal">Bars</th>
              <th scope="col" className="px-2 py-1 text-right font-normal">Missing</th>
              <th scope="col" className="px-2 py-1 font-normal">Holes (ET)</th>
              <th scope="col" className="px-2 py-1 text-right font-normal">Trades across</th>
              <th scope="col" className="px-4 py-1 text-right font-normal">Their P/L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.day} className="border-b border-hair align-top">
                <td className="px-4 py-1 whitespace-nowrap text-muted">{dayLabel.format(new Date(dataset.time[d.first] * 1000))}</td>
                <td className="v9-num px-2 py-1 text-right text-dim">{d.bars}</td>
                <td className="v9-num px-2 py-1 text-right text-amber">{d.missing}</td>
                <td className="v9-num px-2 py-1 text-dim">
                  {d.holes.map((h) => `${hm.format(new Date((h.from + gaps.step) * 1000))}–${hm.format(new Date((h.to - gaps.step) * 1000))}`).join(', ')}
                </td>
                <td className="v9-num px-2 py-1 text-right">
                  {d.held.length ? (
                    <button className="v9-link" onClick={() => selectTrade(d.held[0])} title="Pan the price chart to the first of these trades">
                      {d.held.length}
                    </button>
                  ) : (
                    <span className="text-dim">0</span>
                  )}
                </td>
                <td className={`v9-num px-4 py-1 text-right ${d.held.length ? signClass(d.heldPnl) : 'text-dim'}`}>{d.held.length ? fmtMoneySigned(d.heldPnl) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
