'use client'

import { useRef, useState, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../lib/backtest/format'
import { holesFor, spansHole } from './gaps'
import s from './bt.module.css'

const COLS = [
  { key: 'n', label: '#', r: true },
  { key: 'side', label: 'Side' },
  { key: 'entryTime', label: 'Entry (ET)' },
  { key: 'entryPrice', label: 'In', r: true },
  { key: 'exitTime', label: 'Exit (ET)' },
  { key: 'exitPrice', label: 'Out', r: true },
  { key: 'bars', label: 'Bars', r: true },
  { key: 'pnlPct', label: 'Return', r: true },
  { key: 'pnl', label: 'P/L', r: true },
  { key: 'mae', label: 'MAE', r: true, title: 'Maximum adverse excursion: the worst open loss during the trade' },
  { key: 'hole', label: 'Hole', title: 'Held across bars missing from the data' },
  { key: 'reason', label: 'Exit reason' },
]

const ROW = 22

/**
 * Every fill, virtualized (a 5m strategy makes thousands). Rows are buttons
 * so the blotter can be walked with Tab; Enter pans the chart. A trade held
 * across a data hole is flagged, and the list can be cut down to just those.
 */
export default function Trades() {
  const result = useBacktest((st) => st.result)
  const dataset = useBacktest((st) => st.dataset)
  const selectTrade = useBacktest((st) => st.selectTrade)
  const selected = useBacktest((st) => st.selectedTrade)
  const running = useBacktest((st) => st.running)
  const loading = useBacktest((st) => st.datasetLoading)
  const autoRun = useBacktest((st) => st.autoRun)
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const [onlyHoles, setOnlyHoles] = useState(false)
  const gaps = holesFor(dataset)

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, hole: spansHole(gaps, t) ? 1 : 0 })) : []),
    [result, gaps],
  )
  const holeCount = useMemo(() => all.reduce((a, t) => a + t.hole, 0), [all])

  const trades = useMemo(() => {
    const list = onlyHoles ? all.filter((t) => t.hole) : all
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
    estimateSize: () => ROW,
    overscan: 12,
  })

  if (!result) {
    return (
      <p className="flex h-full items-center justify-center px-6 text-center text-[12px] text-dim">
        {loading ? 'Loading bars…' : running ? 'Running…' : autoRun ? 'Trades are listed here after the first run.' : 'Press Run (R) to list trades.'}
      </p>
    )
  }
  if (!all.length) {
    return (
      <p className="flex h-full items-center justify-center px-6 text-center text-[12px] leading-relaxed text-dim">
        The strategy never entered. Loosen the entry condition, or check that the warm-up period is not using up the whole sample.
      </p>
    )
  }

  const toggleSort = (key) => setSort((p) => (p.key === key ? { key, dir: -p.dir } : { key, dir: 1 }))
  const holePnl = all.reduce((a, t) => a + (t.hole ? t.pnl : 0), 0)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
        <div role="row" className={`${s.tgrid} ${s.thead}`}>
          {COLS.map((c) => (
            <button
              key={c.key}
              role="columnheader"
              aria-sort={sort.key === c.key ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}
              onClick={() => toggleSort(c.key)}
              className={`${c.r ? s.r : ''} ${sort.key === c.key ? 'text-amber' : ''}`}
              title={c.title ? `${c.title}. Click to sort.` : 'Click to sort'}
            >
              {c.label}
              {sort.key === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
            </button>
          ))}
        </div>
        <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', minWidth: 860 }}>
          {rowVirtualizer.getVirtualItems().map((v) => {
            const t = trades[v.index]
            const isSel = selected && selected.entryIdx === t.entryIdx
            return (
              <button
                key={v.key}
                onClick={() => selectTrade(t)}
                aria-pressed={Boolean(isSel)}
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                className={`${s.tgrid} ${s.trow} ${isSel ? s.trowSel : ''}`}
                title="Pan the price chart to this trade"
              >
                <span className={`${s.r} text-dim`}>{t.n}</span>
                <span className={t.side === 'long' ? 'text-pos' : 'text-neg'}>{t.side}</span>
                <span>{fmtTime(t.entryTime)}</span>
                <span className={s.r}>{fmtNum(t.entryPrice, 2)}</span>
                <span>{fmtTime(t.exitTime)}</span>
                <span className={s.r}>{fmtNum(t.exitPrice, 2)}</span>
                <span className={`${s.r} text-dim`}>{t.bars}</span>
                <span className={`${s.r} ${signClass(t.pnlPct)}`}>{fmtPct(t.pnlPct)}</span>
                <span className={`${s.r} ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>
                <span className={`${s.r} text-dim`}>{fmtPct(t.mae, 1)}</span>
                <span className={t.hole ? 'text-amber' : 'text-hair-bright'}>{t.hole ? 'yes' : '·'}</span>
                <span className="truncate text-dim">{t.reason}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className={s.tfoot}>
        <span>
          {onlyHoles ? `${trades.length} of ${all.length}` : all.length} trades
        </span>
        <span>exits: {summariseReasons(all)}</span>
        {holeCount > 0 && (
          <label className="flex cursor-pointer items-center gap-1.5 text-amber">
            <input type="checkbox" checked={onlyHoles} onChange={(e) => setOnlyHoles(e.target.checked)} className="accent-amber" />
            <span>
              only the {holeCount} held across a hole (net <span className={signClass(holePnl)}>{fmtMoneySigned(holePnl)}</span>)
            </span>
          </label>
        )}
        <span className="ml-auto">select a row to pan the chart</span>
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
