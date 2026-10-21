'use client'

import { useRef, useState, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../../lib/backtest/format'
import useSize from '../../../components/backtest/useSize'
import { findHoles, crossesHole } from '../gaps'
import { Empty, NoRunYet } from './Empty'

// `min` is the container width at which the column appears, so narrow
// screens keep the columns that answer "what happened" and drop the rest.
const COLS = [
  { key: 'n', label: '#', w: '34px', r: true, min: 430 },
  { key: 'side', label: 'Side', w: '44px' },
  { key: 'entryTime', label: 'Entry', w: '92px' },
  { key: 'entryPrice', label: 'In', w: '62px', r: true, min: 760 },
  { key: 'exitTime', label: 'Exit', w: '92px', min: 520 },
  { key: 'exitPrice', label: 'Out', w: '62px', r: true, min: 760 },
  { key: 'bars', label: 'Bars', w: '40px', r: true, min: 600 },
  { key: 'pnlPct', label: 'Return', w: '62px', r: true },
  { key: 'pnl', label: 'P&L', w: '70px', r: true },
  { key: 'mae', label: 'MAE', w: '52px', r: true, min: 860, title: 'Maximum adverse excursion' },
  { key: 'reason', label: 'Exit on', w: '58px', min: 680 },
  { key: 'hole', label: 'Gap', w: 'minmax(28px, 1fr)', title: 'Held across bars missing from the data' },
]

const ROW = 22

/**
 * Every fill the engine made, virtualised. Copied from the original blotter
 * with three changes: a Gap column flags trades held across missing bars;
 * the list is one tab stop where ↑/↓ step the selection (and pan the price
 * chart) and Enter re-centres it; and columns drop by width instead of
 * overflowing a phone screen.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const parentRef = useRef(null)
  const [sizeRef, { width }] = useSize()
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const holes = findHoles(dataset)

  const trades = useMemo(() => {
    const list = result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, hole: crossesHole(holes, t) ? 1 : 0 })) : []
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [result, sort, holes])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW,
    overscan: 12,
  })

  const cols = COLS.filter((c) => !c.min || (width || 1200) >= c.min)
  const grid = { gridTemplateColumns: cols.map((c) => c.w).join(' ') }
  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1
  const holeCount = trades.reduce((a, t) => a + t.hole, 0)

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))

  const onKeyDown = (e) => {
    if (!trades.length) return
    let next = null
    if (e.key === 'ArrowDown') next = Math.min(trades.length - 1, selIndex + 1)
    else if (e.key === 'ArrowUp') next = Math.max(0, selIndex < 0 ? 0 : selIndex - 1)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = trades.length - 1
    else if ((e.key === 'Enter' || e.key === ' ') && selIndex >= 0) {
      e.preventDefault()
      selectTrade({ ...trades[selIndex] })
      return
    }
    if (next === null) return
    e.preventDefault()
    selectTrade(trades[next])
    rowVirtualizer.scrollToIndex(next, { align: 'auto' })
  }

  return (
    <div ref={sizeRef} className="flex h-full flex-col">
      {!result ? (
        <NoRunYet what="Trades" />
      ) : !trades.length ? (
        <Empty>
          The strategy never entered. Loosen the entry condition, or check that the warm-up period is not eating
          the whole sample.
        </Empty>
      ) : (
        <>
          <div className="v4-trades-head" style={grid} role="presentation">
            {cols.map((c) => (
              <button
                key={c.key}
                onClick={() => toggleSort(c.key)}
                className={c.r ? 'v4-r' : ''}
                title={c.title ? `${c.title}. Sort` : 'Sort'}
                aria-sort={sort.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : undefined}
              >
                {c.label}
                {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
              </button>
            ))}
          </div>

          <div
            ref={parentRef}
            className="v4-trades-list flex-1 overflow-auto"
            role="listbox"
            aria-label="Trades. Arrow keys select a trade and pan the price chart."
            aria-activedescendant={selIndex >= 0 ? `v4-trade-${trades[selIndex].entryIdx}` : undefined}
            tabIndex={0}
            onKeyDown={onKeyDown}
          >
            <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
              {rowVirtualizer.getVirtualItems().map((v) => {
                const t = trades[v.index]
                const isSel = selIndex === v.index
                return (
                  <div
                    key={v.key}
                    id={`v4-trade-${t.entryIdx}`}
                    role="option"
                    aria-selected={isSel}
                    onClick={() => selectTrade(t)}
                    className="v4-trade"
                    style={{ ...grid, position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                  >
                    {cols.map((c) => (
                      <Cell key={c.key} c={c} t={t} />
                    ))}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="v4-foot">
            <span>{trades.length.toLocaleString()} trades</span>
            <span>Exits: {summariseReasons(trades)}</span>
            {holeCount > 0 && <span className="v4-amber">{holeCount} held across a data gap</span>}
            <span className="ml-auto">Click a row, or focus the list and use ↑ ↓, to pan the chart</span>
          </div>
        </>
      )}
    </div>
  )
}

function Cell({ c, t }) {
  const r = c.r ? 'v4-r' : ''
  switch (c.key) {
    case 'n':
      return <span className={`${r} v4-dim`}>{t.n}</span>
    case 'side':
      return <span className={t.side === 'long' ? 'v4-pos' : 'v4-neg'}>{t.side}</span>
    case 'entryTime':
      return <span>{fmtTime(t.entryTime)}</span>
    case 'exitTime':
      return <span>{fmtTime(t.exitTime)}</span>
    case 'entryPrice':
      return <span className={r}>{fmtNum(t.entryPrice, 2)}</span>
    case 'exitPrice':
      return <span className={r}>{fmtNum(t.exitPrice, 2)}</span>
    case 'bars':
      return <span className={`${r} v4-dim`}>{t.bars}</span>
    case 'pnlPct':
      return <span className={`${r} ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
    case 'pnl':
      return <span className={`${r} ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
    case 'mae':
      return <span className={`${r} v4-dim`}>{fmtPct(t.mae, 1)}</span>
    case 'reason':
      return <span className="v4-dim">{t.reason}</span>
    case 'hole':
      return t.hole ? <span className="v4-hole" title="Held across bars missing from the data">gap</span> : <span />
    default:
      return null
  }
}

function summariseReasons(trades) {
  const counts = {}
  for (const t of trades) counts[t.reason] = (counts[t.reason] || 0) + 1
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${v}`)
    .join(', ')
}
