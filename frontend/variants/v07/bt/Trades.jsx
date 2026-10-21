'use client'

import { useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtNum, signClass } from '../../../lib/backtest/format'
import { scanGaps, tradeMissing } from '../gaps'
import { useV7 } from './uiStore'
import { Empty, NoRunYet, minus } from './ui'

const COLS = [
  { key: 'n', label: '#', cls: 'c-n' },
  { key: 'side', label: 'Side', cls: 'c-side' },
  { key: 'entryTime', label: 'Entry (ET)', cls: 'c-time' },
  { key: 'entryPrice', label: 'In', cls: 'c-px opt' },
  { key: 'exitTime', label: 'Exit (ET)', cls: 'c-time opt' },
  { key: 'exitPrice', label: 'Out', cls: 'c-px opt' },
  { key: 'bars', label: 'Bars', cls: 'c-bars' },
  { key: 'missing', label: 'Missing', cls: 'c-miss', title: 'Bars missing from the data while this trade was open' },
  { key: 'pnlPct', label: 'Return', cls: 'c-ret' },
  { key: 'pnl', label: 'P/L', cls: 'c-pnl' },
  { key: 'mae', label: 'MAE', cls: 'c-mae opt', title: 'Maximum adverse excursion' },
  { key: 'reason', label: 'Exit', cls: 'c-why' },
]

const tone = (v) => {
  const c = signClass(v)
  return c === 'text-pos' ? 'v7-pos' : c === 'text-neg' ? 'v7-neg' : 'v7-flat'
}

/**
 * Every fill, virtualised. Rows are options in a listbox: Tab in, then ↑ ↓
 * (or Home / End) step through trades and the chart follows. A "Missing"
 * column says how many bars were absent while the position was open.
 */
export default function Trades() {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const selected = useBacktest((s) => s.selectedTrade)
  const holesOnly = useV7((s) => s.holesOnly)
  const setHolesOnly = useV7((s) => s.setHolesOnly)
  const parentRef = useRef(null)
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const gaps = useMemo(() => scanGaps(dataset), [dataset])

  const all = useMemo(
    () => (result?.trades ? result.trades.map((t, i) => ({ ...t, n: i + 1, missing: tradeMissing(gaps, t) })) : []),
    [result, gaps],
  )
  const holeCount = useMemo(() => all.filter((t) => t.missing > 0).length, [all])

  const trades = useMemo(() => {
    const list = holesOnly ? all.filter((t) => t.missing > 0) : all
    if (!sort.key) return list
    return [...list].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (typeof av === 'string') return sort.dir * av.localeCompare(bv)
      return sort.dir * (av - bv)
    })
  }, [all, sort, holesOnly])

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 12,
  })

  if (!result) return <NoRunYet what="Trades" />
  if (!all.length) {
    return (
      <Empty>
        The strategy never entered. Loosen the entry condition, or check that the warm-up period isn&apos;t
        eating the whole sample.
      </Empty>
    )
  }

  const selIndex = selected ? trades.findIndex((t) => t.entryIdx === selected.entryIdx) : -1
  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))

  const move = (to) => {
    if (!trades.length) return
    const i = Math.max(0, Math.min(trades.length - 1, to))
    selectTrade(trades[i])
    rowVirtualizer.scrollToIndex(i, { align: 'auto' })
  }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(selIndex < 0 ? 0 : selIndex + 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(selIndex < 0 ? 0 : selIndex - 1) }
    else if (e.key === 'Home') { e.preventDefault(); move(0) }
    else if (e.key === 'End') { e.preventDefault(); move(trades.length - 1) }
  }

  const sel = selIndex >= 0 ? trades[selIndex] : selected && all.find((t) => t.entryIdx === selected.entryIdx)

  return (
    <div className="v7-trades">
      <div className="v7-trades-bar">
        <div className="v7-seg" role="group" aria-label="Which trades">
          <button type="button" aria-pressed={!holesOnly} onClick={() => setHolesOnly(false)}>All {all.length}</button>
          <button type="button" aria-pressed={holesOnly} onClick={() => setHolesOnly(true)} disabled={!holeCount}
            title="Trades that were open while bars were missing from the data">
            Held across a hole {holeCount}
          </button>
        </div>
        <p className="v7-trade-detail" aria-live="polite">
          {sel ? <SelectedLine t={sel} /> : <span className="v7-dim">Select a trade to see it on the chart.</span>}
        </p>
      </div>

      <div className="v7-trades-scroll">
        <div className="v7-trades-table">
          <div className="v7-trow v7-thead" role="presentation">
            {COLS.map((c) => (
              <button
                type="button"
                key={c.key}
                onClick={() => toggleSort(c.key)}
                className={`${c.cls} ${sort.key === c.key ? 'is-sorted' : ''}`}
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
            className="v7-tbody"
            role="listbox"
            tabIndex={0}
            aria-label={`Trades, ${trades.length}. Use arrow keys to step through.`}
            aria-activedescendant={selIndex >= 0 ? `v7-trade-${trades[selIndex].n}` : undefined}
            onKeyDown={onKey}
          >
            <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
              {rowVirtualizer.getVirtualItems().map((v) => {
                const t = trades[v.index]
                const isSel = v.index === selIndex
                return (
                  <div
                    key={v.key}
                    id={`v7-trade-${t.n}`}
                    role="option"
                    aria-selected={isSel}
                    onClick={() => selectTrade(t)}
                    style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                    className={`v7-trow${isSel ? ' is-sel' : ''}${t.missing ? ' has-hole' : ''}`}
                  >
                    <span className="c-n">{t.n}</span>
                    <span className={`c-side ${t.side === 'long' ? 'v7-pos' : 'v7-neg'}`}>{t.side}</span>
                    <span className="c-time">{fmtTime(t.entryTime)}</span>
                    <span className="c-px opt">{fmtNum(t.entryPrice, 2)}</span>
                    <span className="c-time opt">{fmtTime(t.exitTime)}</span>
                    <span className="c-px opt">{fmtNum(t.exitPrice, 2)}</span>
                    <span className="c-bars">{t.bars}</span>
                    <span className="c-miss">{t.missing ? `+${t.missing}` : ''}</span>
                    <span className={`c-ret ${tone(t.pnlPct)}`}>{minus(fmtPct(t.pnlPct))}</span>
                    <span className={`c-pnl ${tone(t.pnl)}`}>{minus(fmtMoneySigned(t.pnl, 0))}</span>
                    <span className="c-mae opt">{minus(fmtPct(t.mae, 1))}</span>
                    <span className="c-why">{t.reason}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      <p className="v7-trades-foot">
        {trades.length.toLocaleString()} {holesOnly ? 'of ' + all.length + ' ' : ''}trades · exits: {summariseReasons(all)}
        <span className="v7-trades-hint">Click a row, or focus the list and use ↑ ↓</span>
      </p>
    </div>
  )
}

function SelectedLine({ t }) {
  return (
    <>
      <strong>Trade {t.n}</strong> <span className={t.side === 'long' ? 'v7-pos' : 'v7-neg'}>{t.side}</span>{' '}
      {fmtTime(t.entryTime)} → {fmtTime(t.exitTime)} ET · {t.bars} bars
      {t.missing ? <span className="v7-hole-note"> with {t.missing} missing</span> : null} · {fmtNum(t.entryPrice, 2)} → {fmtNum(t.exitPrice, 2)} ·{' '}
      <span className={tone(t.pnl)}>{minus(fmtPct(t.pnlPct))}, {minus(fmtMoneySigned(t.pnl, 0))}</span> · exit: {t.reason}
    </>
  )
}

function summariseReasons(trades) {
  const counts = {}
  for (const t of trades) counts[t.reason] = (counts[t.reason] || 0) + 1
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(', ')
}
