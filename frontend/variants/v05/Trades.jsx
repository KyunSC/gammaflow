'use client'

import { useRef, useState, useMemo, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../lib/backtest/format'
import { EmptyState, NoRunYet } from '../../components/backtest/Panel'
import { holesFor, holesInTrade } from './gaps'

// `hide` columns drop out under 640px so the list fits a phone without
// scrolling sideways; the selected trade's full detail shows in the price
// heading and the footer.
const COLS = [
  { key: 'n', label: '#', w: 'w-8', align: 'text-right', hide: true },
  { key: 'side', label: 'side', w: 'w-10', align: 'text-left' },
  { key: 'entryTime', label: 'entry ET', w: 'w-[92px]', align: 'text-left' },
  { key: 'entryPrice', label: 'in', w: 'w-16', align: 'text-right', hide: true },
  { key: 'exitTime', label: 'exit ET', w: 'w-[92px]', align: 'text-left', hide: true },
  { key: 'exitPrice', label: 'out', w: 'w-16', align: 'text-right', hide: true },
  { key: 'bars', label: 'bars', w: 'w-10', align: 'text-right', hide: true },
  { key: 'pnlPct', label: 'ret', w: 'w-16', align: 'text-right' },
  { key: 'pnl', label: 'p/l', w: 'w-[72px]', align: 'text-right' },
  { key: 'mae', label: 'mae', w: 'w-14', align: 'text-right', hide: true },
  { key: 'reason', label: 'exit', w: 'w-14', align: 'text-left', hide: true },
  { key: 'holes', label: 'holes', w: 'w-12', align: 'text-right', title: 'Missing-bar holes the trade was open across' },
]
const hideCls = (c) => (c.hide ? 'hidden sm:block' : '')

/**
 * Variant 05 copy of components/backtest/Blotter.jsx: the same virtualized,
 * sortable list. Rows are now focusable options (arrow keys step through
 * trades and pan the chart), each trade says how many missing-bar holes it
 * was open across, and the list can be narrowed to just those trades.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const [onlyHoles, setOnlyHoles] = useState(false)
  const holes = holesFor(dataset)

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, holes: holesInTrade(holes, t) })) : []),
    [result, holes],
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
    estimateSize: () => 22,
    overscan: 12,
  })

  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1

  // Keep the selected row in view when it changes from the keyboard.
  useEffect(() => {
    if (selIndex >= 0) rowVirtualizer.scrollToIndex(selIndex, { align: 'auto' })
  }, [selIndex]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!result) return <NoRunYet what="Trades" />
  if (!all.length) {
    return (
      <EmptyState>
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not
        eating the whole sample.
      </EmptyState>
    )
  }

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))

  const onKeyDown = (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return
    e.preventDefault()
    let next = selIndex
    if (e.key === 'ArrowDown') next = Math.min(trades.length - 1, selIndex + 1)
    if (e.key === 'ArrowUp') next = Math.max(0, selIndex < 0 ? 0 : selIndex - 1)
    if (e.key === 'Home') next = 0
    if (e.key === 'End') next = trades.length - 1
    if (trades[next]) selectTrade(trades[next])
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 pb-1.5 font-mono text-[11px] text-dim">
        <span>
          {all.length.toLocaleString()} trades · exits {summariseReasons(all)}
        </span>
        {holes.checked && acrossCount > 0 && (
          <span role="group" aria-label="Filter trades" className="flex items-center gap-1">
            show
            <button aria-pressed={!onlyHoles} onClick={() => setOnlyHoles(false)} className={`btn !px-1.5 !py-0 ${!onlyHoles ? 'btn-active' : ''}`}>
              all
            </button>
            <button aria-pressed={onlyHoles} onClick={() => setOnlyHoles(true)} className={`btn !px-1.5 !py-0 ${onlyHoles ? 'btn-active' : ''}`}>
              across holes ({acrossCount})
            </button>
          </span>
        )}
        <span className="ml-auto hidden lg:inline">click a row or use ↑ ↓ to pan the chart</span>
      </div>

      <div className="v05-rule-t v05-rule-b flex gap-2 px-3 py-1" role="presentation">
        {COLS.map((c) => (
          <button
            key={c.key}
            onClick={() => toggleSort(c.key)}
            title={c.title || `Sort by ${c.label}`}
            className={`v05-colhead ${c.w} ${c.align} ${hideCls(c)} shrink-0 hover:text-ink ${sort.key === c.key ? '!text-amber' : ''}`}
          >
            {c.label}
            {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
          </button>
        ))}
      </div>

      <div
        ref={parentRef}
        className="min-h-0 flex-1 overflow-auto"
        role="listbox"
        aria-label="Trades"
        aria-activedescendant={selIndex >= 0 ? `v05-trade-${trades[selIndex].n}` : undefined}
        tabIndex={0}
        onKeyDown={onKeyDown}
      >
        <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
          {rowVirtualizer.getVirtualItems().map((v) => {
            const t = trades[v.index]
            const isSel = selected && selected.entryIdx === t.entryIdx
            return (
              <div
                key={v.key}
                id={`v05-trade-${t.n}`}
                role="option"
                aria-selected={Boolean(isSel)}
                onClick={() => selectTrade(t)}
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                className="v05-row cursor-pointer"
              >
                <span className="hidden w-8 shrink-0 text-right text-dim sm:block">{t.n}</span>
                <span className={`w-10 shrink-0 ${t.side === 'long' ? 'text-pos' : 'text-neg'}`}>{t.side}</span>
                <span className="w-[92px] shrink-0 text-muted">{fmtTime(t.entryTime)}</span>
                <span className="hidden w-16 shrink-0 text-right text-muted sm:block">{fmtNum(t.entryPrice, 2)}</span>
                <span className="hidden w-[92px] shrink-0 text-muted sm:block">{fmtTime(t.exitTime)}</span>
                <span className="hidden w-16 shrink-0 text-right text-muted sm:block">{fmtNum(t.exitPrice, 2)}</span>
                <span className="hidden w-10 shrink-0 text-right text-dim sm:block">{t.bars}</span>
                <span className={`w-16 shrink-0 text-right ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                <span className={`w-[72px] shrink-0 text-right ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                <span className="hidden w-14 shrink-0 text-right text-dim sm:block">{fmtPct(t.mae, 1)}</span>
                <span className="hidden w-14 shrink-0 text-dim sm:block">{t.reason}</span>
                <span className={`w-12 shrink-0 text-right ${t.holes ? 'text-amber' : 'text-hair-bright'}`}>{t.holes || '–'}</span>
              </div>
            )
          })}
        </div>
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
