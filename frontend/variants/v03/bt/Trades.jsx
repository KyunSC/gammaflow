'use client'

import { useRef, useState, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum } from '../../../lib/backtest/format'
import { Empty, NoResult } from './ui'
import { holesInTrade } from '../gaps'
import useGaps from './useGaps'

const COLS = [
  { key: 'n', label: '#', cls: 'c-n r' },
  { key: 'side', label: 'Side', cls: 'c-side' },
  { key: 'entryTime', label: 'Entry (ET)', cls: 'c-time' },
  { key: 'entryPrice', label: 'In', cls: 'c-px r' },
  { key: 'exitTime', label: 'Exit (ET)', cls: 'c-time' },
  { key: 'exitPrice', label: 'Out', cls: 'c-px r' },
  { key: 'bars', label: 'Bars', cls: 'c-bars r' },
  { key: 'pnlPct', label: 'Return', cls: 'c-ret r' },
  { key: 'pnl', label: 'P/L', cls: 'c-pl r' },
  { key: 'mae', label: 'MAE', cls: 'c-mae r', title: 'Maximum adverse excursion' },
  { key: 'reason', label: 'Exit by', cls: 'c-why' },
  { key: 'holes', label: 'Holes', cls: 'c-gap r', title: 'Data holes the trade was open across' },
]

const sign = (v) => (v > 0 ? 'v3-pos' : v < 0 ? 'v3-neg' : 'v3-dim')

/**
 * Every fill, virtualised. Same data and sort as components/backtest/Blotter,
 * plus: keyboard selection (the list is one tab stop; arrow keys step through
 * trades and pan the chart), a column counting the data holes each trade was
 * open across, and a filter to see only those trades.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const gaps = useGaps()
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const [onlyHoles, setOnlyHoles] = useState(false)

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, holes: holesInTrade(gaps, t) })) : []),
    [result, gaps],
  )
  const acrossCount = useMemo(() => all.filter((t) => t.holes > 0).length, [all])

  const trades = useMemo(() => {
    const list = onlyHoles ? all.filter((t) => t.holes > 0) : all
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [all, sort, onlyHoles])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 12,
    // The sticky header row (24px) sits above the list inside the same scroller.
    scrollMargin: 24,
    scrollPaddingStart: 24,
  })

  if (!result) return <NoResult what="Trades" />
  if (!all.length) {
    return (
      <Empty>
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating the whole sample.
      </Empty>
    )
  }

  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1
  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))

  const onKeyDown = (e) => {
    let next = null
    if (e.key === 'ArrowDown') next = Math.min(trades.length - 1, selIndex + 1)
    else if (e.key === 'ArrowUp') next = Math.max(0, selIndex < 0 ? 0 : selIndex - 1)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = trades.length - 1
    else if (e.key === 'PageDown') next = Math.min(trades.length - 1, Math.max(0, selIndex) + 10)
    else if (e.key === 'PageUp') next = Math.max(0, selIndex - 10)
    if (next === null) return
    e.preventDefault()
    selectTrade(trades[next])
    rowVirtualizer.scrollToIndex(next, { align: 'auto' })
  }

  const sel = selIndex >= 0 ? trades[selIndex] : selected ? all.find((t) => t.entryIdx === selected.entryIdx) : null

  return (
    <div className="v3-trades">
      <div className="v3-trades-tools">
        {sel ? (
          <p className="v3-trade-detail" aria-live="polite">
            <b>Trade {sel.n}</b>{' '}
            <span className={sel.side === 'long' ? 'v3-pos' : 'v3-neg'}>{sel.side}</span> {fmtTime(sel.entryTime)} → {fmtTime(sel.exitTime)}, {sel.bars} bars,{' '}
            <span className={sign(sel.pnl)}>{fmtMoneySigned(sel.pnl, 0)} ({fmtPct(sel.pnlPct)})</span>, exit by {sel.reason}.
            {sel.holes > 0 && <span className="v3-gapnote-inline"> Open across {sel.holes} data hole{sel.holes > 1 ? 's' : ''}.</span>}{' '}
            <button type="button" className="v3-link" onClick={() => selectTrade(null)}>Clear</button>
          </p>
        ) : (
          <p className="v3-trade-detail v3-dim">Select a trade (click, or focus the list and use ↑ ↓) to pan the chart to it.</p>
        )}
        {gaps?.holes?.length > 0 && (
          <label className="v3-check">
            <input type="checkbox" checked={onlyHoles} onChange={(e) => setOnlyHoles(e.target.checked)} />
            Only trades across holes ({acrossCount})
          </label>
        )}
      </div>

      <div className="v3-table-scroll v3-scroll" ref={parentRef}>
        <div className="v3-trow v3-thead" role="row">
          {COLS.map((c) => (
            <span key={c.key} className={c.cls} role="columnheader" aria-sort={sort.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}>
              <button type="button" onClick={() => toggleSort(c.key)} title={c.title} className={sort.key === c.key ? 'is-sorted' : ''}>
                {c.label}
                {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
              </button>
            </span>
          ))}
        </div>
        {!trades.length ? (
          <Empty>No trade was open across a data hole.</Empty>
        ) : (
          <div
            role="listbox"
            tabIndex={0}
            aria-label={`Trades, ${trades.length}`}
            aria-activedescendant={selIndex >= 0 ? `v3-trade-${trades[selIndex].n}` : undefined}
            onKeyDown={onKeyDown}
            className="v3-tbody"
            style={{ height: rowVirtualizer.getTotalSize() }}
          >
            {rowVirtualizer.getVirtualItems().map((v) => {
              const t = trades[v.index]
              const isSel = selected && selected.entryIdx === t.entryIdx
              return (
                <div
                  key={v.key}
                  id={`v3-trade-${t.n}`}
                  role="option"
                  aria-selected={Boolean(isSel)}
                  onClick={() => selectTrade(t)}
                  style={{ height: v.size, transform: `translateY(${v.start - 24}px)` }}
                  className={`v3-trow ${isSel ? 'is-sel' : ''} ${t.holes > 0 ? 'has-hole' : ''}`}
                >
                  <span className="c-n r v3-dim">{t.n}</span>
                  <span className={`c-side ${t.side === 'long' ? 'v3-pos' : 'v3-neg'}`}>{t.side}</span>
                  <span className="c-time">{fmtTime(t.entryTime)}</span>
                  <span className="c-px r">{fmtNum(t.entryPrice, 2)}</span>
                  <span className="c-time">{fmtTime(t.exitTime)}</span>
                  <span className="c-px r">{fmtNum(t.exitPrice, 2)}</span>
                  <span className="c-bars r v3-dim">{t.bars}</span>
                  <span className={`c-ret r ${sign(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                  <span className={`c-pl r ${sign(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                  <span className="c-mae r v3-dim">{fmtPct(t.mae, 1)}</span>
                  <span className="c-why v3-dim">{t.reason}</span>
                  <span className="c-gap r">{t.holes > 0 ? <><i className="v3-gap-swatch" aria-hidden="true" />{t.holes}</> : <span className="v3-dim">·</span>}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="v3-trades-foot">
        <span>{trades.length.toLocaleString()}{onlyHoles ? ` of ${all.length}` : ''} trades</span>
        <span>Exits: {summariseReasons(trades)}</span>
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
