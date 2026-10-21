'use client'

import { useRef, useState, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../../lib/backtest/format'
import { findGaps, missingInSpan } from './gaps'
import { Note, NoRunYet } from './ui'

const COLS = [
  { key: 'n', label: '#', cls: 'c-n' },
  { key: 'side', label: 'Side', cls: 'c-side' },
  { key: 'entryTime', label: 'Entry (ET)', cls: 'c-time' },
  { key: 'entryPrice', label: 'In', cls: 'c-px' },
  { key: 'exitTime', label: 'Exit (ET)', cls: 'c-time' },
  { key: 'exitPrice', label: 'Out', cls: 'c-px' },
  { key: 'bars', label: 'Bars', cls: 'c-bars' },
  { key: 'missing', label: 'Missing', cls: 'c-miss', title: 'Bars missing from the data inside this trade' },
  { key: 'pnlPct', label: 'Return', cls: 'c-ret' },
  { key: 'pnl', label: 'P/L', cls: 'c-pnl' },
  { key: 'mae', label: 'MAE', cls: 'c-mae', title: 'Maximum adverse excursion' },
  { key: 'reason', label: 'Exit reason', cls: 'c-why' },
]

const ROW = 24

/**
 * Every fill the engine made, virtualised because a 5m strategy over three
 * months makes thousands. Focus the list and use ↑ ↓ (Home / End) to step
 * through trades; the chart follows. Trades held across missing bars are
 * flagged, and can be listed on their own.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const [onlyGaps, setOnlyGaps] = useState(false)
  const gaps = findGaps(dataset)

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, missing: missingInSpan(gaps, t.entryIdx, t.exitIdx) })) : []),
    [result, gaps],
  )
  const gapCount = useMemo(() => all.filter((t) => t.missing > 0).length, [all])

  const trades = useMemo(() => {
    const list = onlyGaps ? all.filter((t) => t.missing > 0) : all
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [all, sort, onlyGaps])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW,
    overscan: 12,
  })

  if (!result) return <NoRunYet what="Trades" />
  if (!all.length) {
    return (
      <Note>
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating the whole sample.
      </Note>
    )
  }

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))
  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1

  const onKeyDown = (e) => {
    if (!trades.length) return
    let next = null
    if (e.key === 'ArrowDown') next = selIndex < 0 ? 0 : Math.min(trades.length - 1, selIndex + 1)
    else if (e.key === 'ArrowUp') next = selIndex < 0 ? 0 : Math.max(0, selIndex - 1)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = trades.length - 1
    if (next === null) return
    e.preventDefault()
    selectTrade(trades[next])
    rowVirtualizer.scrollToIndex(next, { align: 'auto' })
  }

  return (
    <div className="v8-blotter">
      <div className="v8-blotter-head" role="row">
        {COLS.map((c) => (
          <button
            type="button"
            key={c.key}
            onClick={() => toggleSort(c.key)}
            className={`${c.cls} ${sort.key === c.key ? 'is-sorted' : ''}`}
            title={c.title ? `${c.title}. Click to sort.` : 'Click to sort'}
            aria-sort={sort.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : undefined}
          >
            {c.label}
            {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
          </button>
        ))}
      </div>

      <div
        ref={parentRef}
        className="v8-blotter-body"
        tabIndex={0}
        role="listbox"
        aria-label="Trades. Use the up and down arrow keys to step through them."
        aria-activedescendant={selIndex >= 0 ? `v8-trade-${trades[selIndex].entryIdx}` : undefined}
        onKeyDown={onKeyDown}
      >
        {!trades.length ? (
          <Note>No trade in this run was held across missing bars.</Note>
        ) : (
          <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
            {rowVirtualizer.getVirtualItems().map((v) => {
              const t = trades[v.index]
              const isSel = selected && selected.entryIdx === t.entryIdx
              return (
                <div
                  key={v.key}
                  id={`v8-trade-${t.entryIdx}`}
                  role="option"
                  aria-selected={Boolean(isSel)}
                  onClick={() => selectTrade(t)}
                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                  className={`v8-trow ${isSel ? 'is-sel' : ''} ${t.missing ? 'has-gap' : ''}`}
                >
                  <span className="c-n text-dim">{t.n}</span>
                  <span className={`c-side ${t.side === 'long' ? 'text-pos' : 'text-neg'}`}>{t.side}</span>
                  <span className="c-time">{fmtTime(t.entryTime)}</span>
                  <span className="c-px">{fmtNum(t.entryPrice, 2)}</span>
                  <span className="c-time">{fmtTime(t.exitTime)}</span>
                  <span className="c-px">{fmtNum(t.exitPrice, 2)}</span>
                  <span className="c-bars text-dim">{t.bars}</span>
                  <span className="c-miss">{t.missing ? <span className="v8-gapnote">{t.missing}</span> : <span className="text-dim">·</span>}</span>
                  <span className={`c-ret ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                  <span className={`c-pnl ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                  <span className="c-mae text-dim">{fmtPct(t.mae, 1)}</span>
                  <span className="c-why text-dim">{t.reason}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="v8-blotter-foot">
        <span>
          {trades.length.toLocaleString()} {onlyGaps ? `of ${all.length.toLocaleString()} ` : ''}trades
        </span>
        <span className="text-dim">exits: {summariseReasons(trades)}</span>
        {gaps && gapCount > 0 && (
          <label className="v8-check">
            <input type="checkbox" checked={onlyGaps} onChange={(e) => setOnlyGaps(e.target.checked)} />
            <span>
              Only the <span className="v8-gapnote">{gapCount}</span> held across missing bars
            </span>
          </label>
        )}
        <span className="v8-blotter-hint text-dim">Click a row, or focus the list and use ↑ ↓, to pan the chart</span>
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
