'use client'

import { useRef, useState, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../../lib/backtest/format'
import { Empty, NotYet } from './Section'
import { gapsFor, gapsInTrade } from './gaps'

const COLS = [
  { key: 'n', label: '#', w: 'w-9', align: 'text-right' },
  { key: 'side', label: 'Side', w: 'w-12', align: 'text-left' },
  { key: 'entryTime', label: 'Entry (ET)', w: 'w-24', align: 'text-left' },
  { key: 'entryPrice', label: 'In', w: 'w-16', align: 'text-right' },
  { key: 'exitTime', label: 'Exit (ET)', w: 'w-24', align: 'text-left' },
  { key: 'exitPrice', label: 'Out', w: 'w-16', align: 'text-right' },
  { key: 'bars', label: 'Bars', w: 'w-11', align: 'text-right' },
  { key: 'pnlPct', label: 'Return', w: 'w-16', align: 'text-right' },
  { key: 'pnl', label: 'P/L', w: 'w-20', align: 'text-right' },
  { key: 'mae', label: 'MAE', w: 'w-14', align: 'text-right', title: 'Maximum adverse excursion while the trade was open' },
  { key: 'reason', label: 'Exit', w: 'w-16', align: 'text-left' },
  { key: 'gap', label: 'Gaps', w: 'w-24', align: 'text-left', title: 'Missing bars inside the holding period' },
]

/**
 * Every fill, virtualised (a 5m strategy can trade thousands of times).
 * Rows are keyboard-reachable; Enter or click pans the price chart. Trades
 * held across missing bars say so in their own column.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const gaps = gapsFor(dataset)

  const trades = useMemo(() => {
    const list = result?.trades
      ? result.trades.map((t, i) => {
          const g = gapsInTrade(gaps, t)
          return { ...t, n: i + 1, gapInfo: g, gap: g ? g.bars : 0 }
        })
      : []
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [result, sort, gaps])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 22,
    overscan: 12,
  })

  if (!result) return <NotYet what="Trades" />
  if (!trades.length) {
    return <Empty>The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating the whole sample.</Empty>
  }

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))
  const gapTrades = trades.filter((t) => t.gapInfo)
  const gapPnl = gapTrades.reduce((a, t) => a + t.pnl, 0)

  const onRowKey = (e, t, index) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      selectTrade(t)
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const next = Math.max(0, Math.min(trades.length - 1, index + (e.key === 'ArrowDown' ? 1 : -1)))
      rowVirtualizer.scrollToIndex(next)
      requestAnimationFrame(() => parentRef.current?.querySelector(`[data-row="${next}"]`)?.focus())
    }
  }

  return (
    <div className="l10-trades">
      <div className="l10-trades-scroll">
        <div className="l10-trades-inner">
          <div className="l10-thead" role="row">
            {COLS.map((c) => (
              <button
                type="button"
                key={c.key}
                onClick={() => toggleSort(c.key)}
                title={c.title ? `${c.title}. Click to sort.` : 'Click to sort'}
                aria-sort={sort.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : undefined}
                className={`${c.w} ${c.align} shrink-0`}
              >
                {c.label}
                {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
              </button>
            ))}
          </div>

          <div ref={parentRef} className="min-h-0 flex-1 overflow-y-auto" role="listbox" aria-label="Trades. Enter pans the price chart to a trade.">
            <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
              {rowVirtualizer.getVirtualItems().map((v) => {
                const t = trades[v.index]
                const isSel = Boolean(selected && selected.entryIdx === t.entryIdx)
                return (
                  <div
                    key={v.key}
                    data-row={v.index}
                    role="option"
                    tabIndex={isSel || (!selected && v.index === 0) ? 0 : -1}
                    aria-selected={isSel}
                    onClick={() => selectTrade(t)}
                    onKeyDown={(e) => onRowKey(e, t, v.index)}
                    style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                    className="l10-tr"
                  >
                    <span className="w-9 shrink-0 text-right text-dim">{t.n}</span>
                    <span className={`w-12 shrink-0 ${t.side === 'long' ? 'text-pos' : 'text-neg'}`}>{t.side}</span>
                    <span className="w-24 shrink-0">{fmtTime(t.entryTime)}</span>
                    <span className="w-16 shrink-0 text-right">{fmtNum(t.entryPrice, 2)}</span>
                    <span className="w-24 shrink-0">{fmtTime(t.exitTime)}</span>
                    <span className="w-16 shrink-0 text-right">{fmtNum(t.exitPrice, 2)}</span>
                    <span className="w-11 shrink-0 text-right text-dim">{t.bars}</span>
                    <span className={`w-16 shrink-0 text-right ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                    <span className={`w-20 shrink-0 text-right ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                    <span className="w-14 shrink-0 text-right text-dim">{fmtPct(t.mae, 1)}</span>
                    <span className="w-16 shrink-0 text-dim">{t.reason}</span>
                    <span className="w-24 shrink-0 whitespace-nowrap l10-gapmark">
                      {t.gapInfo ? `${t.gapInfo.bars} missing` : ''}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="l10-tfoot">
        <span><span className="l10-num">{trades.length}</span> trades</span>
        <span>Exits: {summariseReasons(trades)}</span>
        {gaps.idx.length > 0 && (
          <span className={gapTrades.length ? 'text-amber' : ''}>
            {gapTrades.length
              ? <><span className="l10-num">{gapTrades.length}</span> held across missing bars, net <span className="l10-num">{fmtMoneySigned(gapPnl, 0)}</span></>
              : 'None held across missing bars'}
          </span>
        )}
        <span className="ml-auto hidden sm:inline">Click a row, or Enter, to pan the chart · ↑ ↓ move</span>
      </div>
    </div>
  )
}

function summariseReasons(trades) {
  const counts = {}
  for (const t of trades) counts[t.reason] = (counts[t.reason] || 0) + 1
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(', ')
}
