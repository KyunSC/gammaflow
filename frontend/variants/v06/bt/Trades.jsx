'use client'

import { useRef, useState, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../../lib/backtest/format'
import { EmptyState, NoRunYet } from '../../../components/backtest/Panel'
import { tradeMissing } from '../gaps'
import { useGaps, useV6 } from './ui'

const COLS = [
  { key: 'n', label: '#', w: 'w-9', align: 'text-right' },
  { key: 'side', label: 'Side', w: 'w-12', align: 'text-left' },
  { key: 'entryTime', label: 'Entry', w: 'w-[92px]', align: 'text-left' },
  { key: 'entryPrice', label: 'In', w: 'w-16', align: 'text-right' },
  { key: 'exitTime', label: 'Exit', w: 'w-[92px]', align: 'text-left' },
  { key: 'exitPrice', label: 'Out', w: 'w-16', align: 'text-right' },
  { key: 'bars', label: 'Bars', w: 'w-11', align: 'text-right' },
  { key: 'pnlPct', label: 'Return', w: 'w-16', align: 'text-right' },
  { key: 'pnl', label: 'P/L', w: 'w-20', align: 'text-right' },
  { key: 'mae', label: 'MAE', w: 'w-14', align: 'text-right', title: 'Maximum adverse excursion while the trade was open' },
  { key: 'gap', label: 'Gap', w: 'w-12', align: 'text-right', title: 'Missing bars inside the holding span' },
  { key: 'reason', label: 'Exit why', w: 'w-16', align: 'text-left' },
]

/**
 * Every fill the engine made, virtualised. Rows are options in a listbox: the
 * list takes focus, arrow keys step through trades, and each step pans the
 * price chart, so the trade that broke the curve can be found without a mouse.
 * The Gap column flags trades held across missing bars.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const gaps = useGaps()
  const gapOnly = useV6((s) => s.gapOnly)
  const setGapOnly = useV6((s) => s.setGapOnly)
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, gap: tradeMissing(gaps, t) })) : []),
    [result, gaps],
  )
  const nAcross = useMemo(() => all.filter((t) => t.gap > 0).length, [all])

  const trades = useMemo(() => {
    const list = gapOnly ? all.filter((t) => t.gap > 0) : all
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [all, sort, gapOnly])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 12,
  })

  if (!result) return <NoRunYet what="Trades" />
  if (!all.length) {
    return (
      <EmptyState>
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating the whole sample.
      </EmptyState>
    )
  }

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))
  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1

  const onKeyDown = (e) => {
    const page = Math.max(1, Math.floor((parentRef.current?.clientHeight || 240) / 24) - 1)
    const moves = { ArrowDown: 1, ArrowUp: -1, PageDown: page, PageUp: -page }
    let next = null
    if (e.key in moves) next = selIndex < 0 ? 0 : selIndex + moves[e.key]
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = trades.length - 1
    else return
    e.preventDefault()
    next = Math.max(0, Math.min(trades.length - 1, next))
    selectTrade(trades[next])
    rowVirtualizer.scrollToIndex(next, { align: 'auto' })
  }

  return (
    <div className="v6-trades flex h-full flex-col">
      {/* Head and rows scroll sideways together when the column is narrow. */}
      <div className="v6-trades-scroll">
      <div className="v6-trades-inner">
      <div className="v6-trades-head" role="presentation">
        {COLS.map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={() => toggleSort(c.key)}
            className={`${c.w} ${c.align} shrink-0 ${sort.key === c.key ? 'text-amber' : ''}`}
            title={c.title ? `${c.title}. Click to sort.` : 'Click to sort'}
            aria-label={`Sort by ${c.label}${sort.key === c.key ? (sort.dir > 0 ? ', ascending' : ', descending') : ''}`}
          >
            {c.label}
            {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
          </button>
        ))}
      </div>

      <div
        ref={parentRef}
        className="v6-trades-list flex-1 overflow-auto"
        role="listbox"
        tabIndex={0}
        aria-label={`Trades, ${trades.length}${gapOnly ? ' held across missing bars' : ''}. Arrow keys step through them.`}
        aria-activedescendant={selIndex >= 0 ? `v6-trade-${trades[selIndex].entryIdx}` : undefined}
        onKeyDown={onKeyDown}
      >
        {trades.length === 0 ? (
          <EmptyState>No trade in this run was held across missing bars.</EmptyState>
        ) : (
          <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
            {rowVirtualizer.getVirtualItems().map((v) => {
              const t = trades[v.index]
              const isSel = selIndex === v.index
              return (
                <div
                  key={v.key}
                  id={`v6-trade-${t.entryIdx}`}
                  role="option"
                  aria-selected={isSel}
                  onClick={() => selectTrade(t)}
                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                  className={`v6-trade-row ${isSel ? 'is-sel' : ''}`}
                >
                  <span className="w-9 shrink-0 text-right v6-dim">{t.n}</span>
                  <span className={`w-12 shrink-0 ${t.side === 'long' ? 'text-pos' : 'text-neg'}`}>{t.side}</span>
                  <span className="w-[92px] shrink-0">{fmtTime(t.entryTime)}</span>
                  <span className="w-16 shrink-0 text-right">{fmtNum(t.entryPrice, 2)}</span>
                  <span className="w-[92px] shrink-0">{fmtTime(t.exitTime)}</span>
                  <span className="w-16 shrink-0 text-right">{fmtNum(t.exitPrice, 2)}</span>
                  <span className="w-11 shrink-0 text-right v6-dim">{t.bars}</span>
                  <span className={`w-16 shrink-0 text-right ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                  <span className={`w-20 shrink-0 text-right ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                  <span className="w-14 shrink-0 text-right v6-dim">{fmtPct(t.mae, 1)}</span>
                  <span className={`w-12 shrink-0 text-right ${t.gap ? 'v6-warn' : 'v6-faint'}`}>{t.gap ? t.gap : '·'}</span>
                  <span className="w-16 shrink-0 v6-dim">{t.reason}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
      </div>
      </div>

      <div className="v6-trades-foot">
        <span>
          <span className="num">{trades.length}</span>
          {gapOnly ? ` of ${all.length}` : ''} trades · exits: {summariseReasons(all)}
        </span>
        {gaps && nAcross > 0 && (
          <label className="v6-check">
            <input type="checkbox" checked={gapOnly} onChange={(e) => setGapOnly(e.target.checked)} />
            Only the {nAcross} held across missing bars
          </label>
        )}
        <span className="v6-hint ml-auto">Click a row, or focus the list and use ↑ ↓, to pan the chart</span>
      </div>
    </div>
  )
}

function summariseReasons(trades) {
  const counts = {}
  for (const t of trades) counts[t.reason] = (counts[t.reason] || 0) + 1
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${v}`)
    .join(', ')
}
