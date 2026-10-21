'use client'

import { useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../lib/backtest/format'
import useSize from '../../components/backtest/useSize'
import { findGaps, missingInTrade } from './gaps'

const COLS = [
  { key: 'n', label: '#', w: 36, right: true },
  { key: 'side', label: 'Side', w: 46 },
  { key: 'entryTime', label: 'Entry (ET)', w: 96 },
  { key: 'entryPrice', label: 'In', w: 70, right: true, wide: true },
  { key: 'exitTime', label: 'Exit (ET)', w: 96, wide: true },
  { key: 'exitPrice', label: 'Out', w: 70, right: true, wide: true },
  { key: 'bars', label: 'Bars', w: 46, right: true, wide: true },
  { key: 'gap', label: 'Missing', w: 60, right: true, title: 'Bars missing from the data while this trade was open' },
  { key: 'pnlPct', label: 'Return', w: 66, right: true },
  { key: 'pnl', label: 'P/L', w: 70, right: true },
  { key: 'mae', label: 'MAE', w: 58, right: true, wide: true, title: 'Maximum adverse excursion' },
  { key: 'reason', label: 'Exit reason', w: 86, wide: true },
]

/**
 * Every fill, virtualized. Rows are options in a listbox: focus the list and
 * use the arrow keys to walk trades, each one pans the price chart. The
 * Missing column and filter show which trades were open across a hole.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const running = useBacktest((s) => s.running)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const parentRef = useRef(null)
  const [sizeRef, { width }] = useSize()
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const [onlyGaps, setOnlyGaps] = useState(false)
  const gaps = useMemo(() => findGaps(dataset), [dataset])
  const compact = width > 0 && width < 720

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, gap: missingInTrade(gaps, t) })) : []),
    [result, gaps],
  )
  const trades = useMemo(() => {
    const list = onlyGaps ? all.filter((t) => t.gap > 0) : all
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [all, sort, onlyGaps])
  const gapCount = useMemo(() => all.filter((t) => t.gap > 0).length, [all])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 12,
  })

  const cols = COLS.filter((c) => !(compact && c.wide))
  const minW = cols.reduce((s, c) => s + c.w, 0) + 16

  if (!result) {
    return (
      <div ref={sizeRef} className="h-full"><p className="flex h-full items-center justify-center p-4 text-center text-[12px] text-dim">
        {datasetLoading ? 'Loading data…' : running ? 'Running…' : 'Trades appear here after a run.'}
      </p></div>
    )
  }
  if (!all.length) {
    return (
      <div ref={sizeRef} className="h-full"><p className="mx-auto flex h-full max-w-[52ch] items-center justify-center p-4 text-center text-[12px] text-dim">
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating the whole sample.
      </p></div>
    )
  }

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))
  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1

  const onKeyDown = (e) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) || !trades.length) return
    e.preventDefault()
    let i = selIndex
    if (e.key === 'ArrowDown') i = Math.min(trades.length - 1, i + 1)
    else if (e.key === 'ArrowUp') i = Math.max(0, i < 0 ? 0 : i - 1)
    else if (e.key === 'Home') i = 0
    else i = trades.length - 1
    selectTrade(trades[i])
    rowVirtualizer.scrollToIndex(i, { align: 'auto' })
  }

  return (
    <div ref={sizeRef} className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 text-[11.5px] text-dim">
        <span>
          {trades.length.toLocaleString()} {onlyGaps ? `of ${all.length.toLocaleString()} ` : ''}trades · exits: {summariseReasons(trades)}
        </span>
        <span className="flex-1" />
        {gaps?.supported && gapCount > 0 && (
          <button role="switch" aria-checked={onlyGaps} onClick={() => setOnlyGaps(!onlyGaps)} className="v9-toggle">
            Only trades held across a hole ({gapCount})
          </button>
        )}
        <span className="hidden sm:inline">Select a row, or focus the list and use ↑ ↓, to pan the chart.</span>
      </div>
      <div className="min-h-0 flex-1 overflow-x-auto">
        <div className="flex h-full flex-col" style={{ minWidth: minW }}>
          <div className="flex shrink-0 border-y border-hair px-2 text-[11.5px] text-dim" role="presentation">
            {cols.map((c) => (
              <button
                key={c.key}
                onClick={() => toggleSort(c.key)}
                style={{ width: c.w }}
                className={`shrink-0 px-1 py-1 hover:text-ink ${c.right ? 'text-right' : 'text-left'} ${sort.key === c.key ? 'text-amber' : ''}`}
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
            className="min-h-0 flex-1 overflow-y-auto"
            role="listbox"
            tabIndex={0}
            aria-label="Trades"
            aria-activedescendant={selIndex >= 0 ? `v9-trade-${trades[selIndex].entryIdx}` : undefined}
            onKeyDown={onKeyDown}
          >
            <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
              {rowVirtualizer.getVirtualItems().map((v) => {
                const t = trades[v.index]
                const isSel = selected && selected.entryIdx === t.entryIdx
                return (
                  <div
                    key={v.key}
                    id={`v9-trade-${t.entryIdx}`}
                    role="option"
                    aria-selected={Boolean(isSel)}
                    onClick={() => selectTrade(t)}
                    style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                    className={`flex cursor-pointer items-center px-2 text-[12px] ${isSel ? 'bg-[rgba(232,179,57,0.12)] shadow-[inset_2px_0_0_#e8b339]' : 'hover:bg-panel-3'}`}
                  >
                    {cols.map((c) => (
                      <span key={c.key} style={{ width: c.w }} className={`shrink-0 truncate px-1 ${c.right ? 'text-right' : ''} ${cellTone(c.key, t)}`}>
                        {cell(c.key, t)}
                      </span>
                    ))}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function cell(key, t) {
  switch (key) {
    case 'entryTime':
    case 'exitTime':
      return <span className="v9-num">{fmtTime(t[key])}</span>
    case 'entryPrice':
    case 'exitPrice':
      return <span className="v9-num">{fmtNum(t[key], 2)}</span>
    case 'pnlPct':
      return <span className="v9-num">{fmtPct(t.pnlPct)}</span>
    case 'pnl':
      return <span className="v9-num">{fmtMoneySigned(t.pnl, 0)}</span>
    case 'mae':
      return <span className="v9-num">{fmtPct(t.mae, 1)}</span>
    case 'gap':
      return <span className="v9-num">{t.gap > 0 ? t.gap : ''}</span>
    case 'n':
    case 'bars':
      return <span className="v9-num">{t[key]}</span>
    default:
      return t[key]
  }
}

function cellTone(key, t) {
  if (key === 'side') return t.side === 'long' ? 'text-pos' : 'text-neg'
  if (key === 'pnl' || key === 'pnlPct') return signClass(t[key])
  if (key === 'gap') return 'text-amber'
  if (key === 'n' || key === 'mae' || key === 'reason' || key === 'bars') return 'text-dim'
  return 'text-muted'
}

function summariseReasons(trades) {
  const counts = {}
  for (const t of trades) counts[t.reason] = (counts[t.reason] || 0) + 1
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${v}`)
    .join(', ')
}
