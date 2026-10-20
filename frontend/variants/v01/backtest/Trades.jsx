'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../../lib/backtest/format'
import { findGaps, tradeGapSummary } from './gaps'
import { Empty, NotYet } from './Empty'
import b from './bt.module.css'

const COLS = [
  { key: 'n', label: '#', w: 'w-9', align: 'text-right' },
  { key: 'side', label: 'Side', w: 'w-12', align: 'text-left' },
  { key: 'entryTime', label: 'Entry (ET)', w: 'w-[92px]', align: 'text-left' },
  { key: 'entryPrice', label: 'In', w: 'w-16', align: 'text-right' },
  { key: 'exitTime', label: 'Exit (ET)', w: 'w-[92px]', align: 'text-left' },
  { key: 'exitPrice', label: 'Out', w: 'w-16', align: 'text-right' },
  { key: 'bars', label: 'Bars', w: 'w-10', align: 'text-right' },
  { key: 'pnlPct', label: 'Return', w: 'w-16', align: 'text-right' },
  { key: 'pnl', label: 'P/L', w: 'w-[72px]', align: 'text-right' },
  { key: 'mae', label: 'MAE', w: 'w-12', align: 'text-right', title: 'Maximum adverse excursion while the trade was open' },
  { key: 'reason', label: 'Exit', w: 'w-14', align: 'text-left' },
  { key: 'gap', label: 'Gap', w: 'w-16', align: 'text-left', title: 'Bars missing from the data while this trade was open' },
]

const HEAD = 26
const ROW = 24

/**
 * Copy of components/backtest/Blotter.jsx with three changes:
 *  - the header lives inside the scroll container, so columns stay aligned
 *    when the table scrolls sideways on a narrow screen;
 *  - the list is a keyboard listbox (↑ ↓ Home End PageUp PageDown);
 *  - a Gap column flags trades held across missing bars, with a filter.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const scrollRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const [onlyGaps, setOnlyGaps] = useState(false)

  const gaps = useMemo(() => findGaps(dataset), [dataset])
  const gapSummary = useMemo(() => tradeGapSummary(result, gaps), [result, gaps])

  const trades = useMemo(() => {
    let list = result?.trades
      ? result.trades.map((t, i) => {
          const g = gapSummary?.byEntry.get(t.entryIdx)
          return { ...t, n: i + 1, gap: g ? g.missing : 0, gapHoles: g ? g.count : 0 }
        })
      : []
    if (onlyGaps) list = list.filter((t) => t.gap > 0)
    if (!sort.key) return list
    return [...list].sort((a, c) => {
      const av = a[sort.key]
      const cv = c[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(cv)
      return sort.dir * (av - cv)
    })
  }, [result, sort, onlyGaps, gapSummary])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW,
    overscan: 12,
    scrollMargin: HEAD,
    scrollPaddingStart: HEAD,
  })

  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1

  // Keep the selected row in view when it changes from the keyboard or the chart.
  useEffect(() => {
    if (selIndex >= 0) rowVirtualizer.scrollToIndex(selIndex, { align: 'auto' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selIndex])

  if (!result) return <NotYet what="Trades" />
  if (!result.trades.length) {
    return (
      <Empty>
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating the
        whole sample.
      </Empty>
    )
  }

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))

  const onKeyDown = (e) => {
    if (!trades.length) return
    const page = Math.max(1, Math.floor((scrollRef.current?.clientHeight || 200) / ROW) - 1)
    const at = selIndex < 0 ? -1 : selIndex
    const go = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: trades.length - 1, PageDown: at + page, PageUp: at - page }[e.key]
    if (go === undefined) return
    e.preventDefault()
    e.stopPropagation()
    selectTrade(trades[Math.max(0, Math.min(trades.length - 1, go))])
  }

  const reasons = summariseReasons(result.trades)

  return (
    <div className={b.blotter}>
      <div ref={scrollRef} className={b.blotterScroll}>
        <div className={b.blotterHead} role="presentation">
          {COLS.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => toggleSort(c.key)}
              className={`${c.w} ${c.align} shrink-0 hover:text-ink ${sort.key === c.key ? 'text-amber' : ''}`}
              title={c.title ? `${c.title}. Click to sort.` : 'Click to sort'}
              aria-label={`Sort by ${c.label}${sort.key === c.key ? (sort.dir > 0 ? ', ascending' : ', descending') : ''}`}
            >
              {c.label}
              {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
            </button>
          ))}
        </div>

        <div
          role="listbox"
          tabIndex={0}
          aria-label={`Trades, ${trades.length}. Arrow keys move the selection; the chart follows.`}
          aria-activedescendant={selIndex >= 0 ? `v01-trade-${trades[selIndex].entryIdx}` : undefined}
          onKeyDown={onKeyDown}
          className={b.listbox}
          style={{ height: Math.max(rowVirtualizer.getTotalSize(), trades.length ? 0 : ROW) }}
        >
          {trades.length === 0 && (
            <p className="px-3 py-2 text-[12px] text-dim">No trades were held across missing bars.</p>
          )}
          {rowVirtualizer.getVirtualItems().map((v) => {
            const t = trades[v.index]
            const isSel = v.index === selIndex
            return (
              <div
                key={v.key}
                id={`v01-trade-${t.entryIdx}`}
                role="option"
                aria-selected={isSel}
                onClick={() => selectTrade(t)}
                style={{ position: 'absolute', top: 0, left: 0, minWidth: '100%', height: v.size, transform: `translateY(${v.start - HEAD}px)` }}
                className={`${b.row} ${isSel ? b.rowSelected : ''}`}
              >
                <span className="w-9 shrink-0 text-right text-dim">{t.n}</span>
                <span className={`w-12 shrink-0 ${t.side === 'long' ? 'text-pos' : 'text-neg'}`}>{t.side}</span>
                <span className="w-[92px] shrink-0 text-muted">{fmtTime(t.entryTime)}</span>
                <span className="w-16 shrink-0 text-right text-muted">{fmtNum(t.entryPrice, 2)}</span>
                <span className="w-[92px] shrink-0 text-muted">{fmtTime(t.exitTime)}</span>
                <span className="w-16 shrink-0 text-right text-muted">{fmtNum(t.exitPrice, 2)}</span>
                <span className="w-10 shrink-0 text-right text-dim">{t.bars}</span>
                <span className={`w-16 shrink-0 text-right ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                <span className={`w-[72px] shrink-0 text-right ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                <span className="w-12 shrink-0 text-right text-dim">{fmtPct(t.mae, 1)}</span>
                <span className="w-14 shrink-0 text-dim">{t.reason}</span>
                <span className="w-16 shrink-0" style={{ color: 'var(--v01-gap)' }}>
                  {t.gap ? `${t.gap} bar${t.gap === 1 ? '' : 's'}` : ''}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      <div className={b.blotterFoot}>
        <span>{result.trades.length} trades</span>
        <span>Exits: {reasons}</span>
        {gapSummary?.n > 0 && (
          <span style={{ color: 'var(--v01-gap)' }}>
            {gapSummary.n} held across missing bars · {(gapSummary.share * 100).toFixed(0)}% of gross P/L
          </span>
        )}
        {gapSummary?.n > 0 && (
          <button type="button" onClick={() => setOnlyGaps((v) => !v)} className={`btn !px-2 !py-0 ${onlyGaps ? 'btn-active' : ''}`} aria-pressed={onlyGaps}>
            {onlyGaps ? 'Show all trades' : 'Only these'}
          </button>
        )}
        <span className={`ml-auto ${b.hideNarrow}`}>Click a row or use ↑ ↓ in the list to pan the chart</span>
      </div>
    </div>
  )
}

/** One line about the selected trade, above the tabs. */
export function SelectedTrade() {
  const selected = useBacktest((s) => s.selectedTrade)
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const gaps = useMemo(() => findGaps(dataset), [dataset])
  const summary = useMemo(() => tradeGapSummary(result, gaps), [result, gaps])
  if (!selected || !result) return null
  const n = result.trades.findIndex((t) => t.entryIdx === selected.entryIdx) + 1
  const g = summary?.byEntry.get(selected.entryIdx)
  return (
    <div className={b.detail} aria-live="polite">
      <span>
        Trade <b>#{n}</b> <span className={selected.side === 'long' ? 'text-pos' : 'text-neg'}>{selected.side}</span>
      </span>
      <span>
        <b>{fmtTime(selected.entryTime)}</b> at <b>{fmtNum(selected.entryPrice, 2)}</b> → <b>{fmtTime(selected.exitTime)}</b> at{' '}
        <b>{fmtNum(selected.exitPrice, 2)}</b>
      </span>
      <span>
        <span className={signClass(selected.pnl)}>
          {fmtPct(selected.pnlPct)} · {fmtMoneySigned(selected.pnl, 0)}
        </span>{' '}
        over {selected.bars} bar{selected.bars === 1 ? '' : 's'}, exit: {selected.reason}
      </span>
      {g && (
        <span style={{ color: 'var(--v01-gap)' }}>
          Held across {g.count} gap{g.count === 1 ? '' : 's'} ({g.missing} missing bar{g.missing === 1 ? '' : 's'}) — stops and exits could not be checked during them
        </span>
      )}
      <button type="button" className="ml-auto text-[12px] text-dim hover:text-ink" onClick={() => selectTrade(null)}>
        Clear selection
      </button>
    </div>
  )
}

function summariseReasons(trades) {
  const counts = {}
  for (const t of trades) counts[t.reason] = (counts[t.reason] || 0) + 1
  return Object.entries(counts)
    .sort((a, c) => c[1] - a[1])
    .map(([k, v]) => `${k} ${v}`)
    .join(', ')
}
