'use client'

import { useMemo, useState } from 'react'
import { useBacktest } from '../../lib/backtest/store'
import { fmtTime, fmtMoneySigned, fmtPct, fmtPctAbs, fmtNum, signClass } from '../../lib/backtest/format'
import { barSeconds, tradeContext, inspectTrade, readInputs, inputLabel } from '../../lib/backtest/tradeInsight'

const MAX_INPUTS = 8

/**
 * One trade, explained. Sits over the price chart while a trade is selected:
 * what the strategy saw on the bar that fired, what the trade made before and
 * after costs, how much of the best move it kept, and the warnings that say
 * when its P&L should not be believed.
 */
export default function TradeInspector({ state }) {
  const result = useBacktest((s) => s.result)
  const dataset = useBacktest((s) => s.dataset)
  const selected = useBacktest((s) => s.selectedTrade)
  const selectTrade = useBacktest((s) => s.selectTrade)
  const stepTrade = useBacktest((s) => s.stepTrade)

  // On a phone the full card would cover the chart it explains.
  const [collapsed, setCollapsed] = useState(() => typeof window !== 'undefined' && window.innerWidth < 640)
  const ctx = useMemo(() => (result ? tradeContext(result.trades) : null), [result])
  const spacing = useMemo(() => (dataset ? barSeconds(dataset.time) : 0), [dataset])

  if (!result || !dataset || !selected || result.config.datasetId !== dataset.id) return null
  const k = result.trades.findIndex((t) => t.entryIdx === selected.entryIdx)
  if (k < 0) return null

  const info = inspectTrade(result.trades, k, dataset.time, ctx, spacing)
  const t = info.trade
  const long = t.side === 'long'
  const warnings = tradeWarnings(info)

  const entryInputs = readInputs(state, info.entrySignalIdx, dataset.n)
  const exitInputs = info.exitSignalIdx !== null ? readInputs(state, info.exitSignalIdx, dataset.n) : null
  const exitByKey = exitInputs ? Object.fromEntries(exitInputs.map((x) => [x.key, x.value])) : null

  return (
    <div
      className="absolute top-1.5 left-1.5 z-10 flex max-h-[calc(100%-12px)] w-[272px] flex-col overflow-auto rounded-[2px] border border-hair-bright bg-panel/95 font-mono text-[10px] text-muted shadow-lg backdrop-blur-[2px]"
      onKeyDown={(e) => e.stopPropagation()}
    >
      <div className="hair-b flex items-center gap-1.5 bg-panel-2 px-2 py-1">
        <span className="text-dim">trade</span>
        <span className="num text-ink">{k + 1}</span>
        <span className="text-dim">/ {result.trades.length}</span>
        <span className={long ? 'text-pos' : 'text-neg'}>{t.side}</span>
        <span className="text-dim">· {t.reason}</span>
        {collapsed && <span className={`num ${signClass(t.pnl)}`}>{fmtMoneySigned(t.pnl, 0)}</span>}
        {collapsed && warnings.some((w) => w.tone === 'text-neg') && <span className="text-neg">⚠</span>}
        <span className="ml-auto flex gap-1">
          <button className="btn !px-1.5 !py-0" onClick={() => stepTrade(-1)} disabled={k === 0} title="Previous trade (J)">‹</button>
          <button className="btn !px-1.5 !py-0" onClick={() => stepTrade(1)} disabled={k === result.trades.length - 1} title="Next trade (K)">›</button>
          <button className="btn !px-1.5 !py-0" onClick={() => setCollapsed((c) => !c)} title={collapsed ? 'Show details' : 'Collapse to this line'}>
            {collapsed ? '+' : '–'}
          </button>
          <button className="btn !px-1.5 !py-0" onClick={() => selectTrade(null)} title="Close (Esc)">×</button>
        </span>
      </div>

      {!collapsed && (
        <>
          <div className="flex flex-col gap-0.5 px-2 py-1.5">
            <Line label="in" value={`${fmtTime(t.entryTime)}  ${fmtNum(t.entryPrice, 2)}`} />
            <Line label="out" value={`${fmtTime(t.exitTime)}  ${fmtNum(t.exitPrice, 2)}`} />
            <Line label="held" value={`${t.bars} bar${t.bars === 1 ? '' : 's'}${info.calendar.sessionsHeld > 1 ? ` · ${info.calendar.sessionsHeld} sessions` : ''}`} />
            {(t.stopPrice || t.targetPrice) && (
              <Line
                label="stop / tgt"
                value={`${t.stopPrice ? fmtNum(t.stopPrice, 2) : '—'} / ${t.targetPrice ? fmtNum(t.targetPrice, 2) : '—'}`}
              />
            )}
          </div>

          <Section title="result">
            <Line label="net" value={`${fmtMoneySigned(t.pnl, 0)}  (${fmtPct(t.pnlPct)})`} tone={signClass(t.pnl)} />
            <Line
              label="at the quote"
              value={fmtMoneySigned(info.beforeCosts, 0)}
              tone={signClass(info.beforeCosts)}
              title="What the trade made before slippage and commission"
            />
            <Line label="slippage · fees" value={`−$${info.slippage.toFixed(0)} · −$${info.fees.toFixed(2)}`} tone="text-dim" />
            <Line
              label="rank"
              value={`${info.rank} of ${info.of}`}
              title="Rank by net P&L (1 = best)"
            />
            {info.pnlShare !== null && <Line label="share" value={shareText(info)} title="This trade's net P&L against the whole run's net P&L" />}
            <Line
              label="run without it"
              value={fmtMoneySigned(info.netWithout, 0)}
              tone={signClass(info.netWithout)}
            />
          </Section>

          <Section title="excursion">
            <Line label="best / worst" value={`${fmtPct(t.mfe)} / ${fmtPct(t.mae)}`} title="Most favourable and most adverse move while the position was open" />
            <Line
              label="kept"
              value={`${fmtPct(t.grossPct)}${info.kept !== null && t.grossPct > 0 ? ` · ${fmtPctAbs(info.kept, 0)} of best` : ''}`}
              tone={signClass(t.grossPct)}
              title="Return at exit (gross of costs), and how much of the best move that is"
            />
            {info.rMultiple !== null && <Line label="R" value={fmtNum(info.rMultiple, 2)} tone={signClass(info.rMultiple)} title="Return in units of the stop distance" />}
          </Section>

          {entryInputs.length > 0 && (
            <Section title={exitInputs ? 'signal bars · entry / exit' : 'entry signal bar'}>
              <Line label="entry bar" value={fmtTime(dataset.time[info.entrySignalIdx])} tone="text-dim" />
              {exitInputs && <Line label="exit bar" value={fmtTime(dataset.time[info.exitSignalIdx])} tone="text-dim" />}
              <Line
                label="close"
                value={`${fmtNum(dataset.close[info.entrySignalIdx], 2)}${exitInputs ? ` / ${fmtNum(dataset.close[info.exitSignalIdx], 2)}` : ''}`}
              />
              {entryInputs.slice(0, MAX_INPUTS).map((x) => (
                <Line
                  key={x.key}
                  label={inputLabel(x.key)}
                  value={`${fmtInput(x.value)}${exitByKey ? ` / ${fmtInput(exitByKey[x.key])}` : ''}`}
                />
              ))}
              <p className="pt-0.5 text-[9px] leading-snug text-dim">
                Orders fill at the next bar's open, so these are the values that decided the trade.
              </p>
            </Section>
          )}

          {warnings.length > 0 && (
            <div className="hair-t flex flex-col gap-1 px-2 py-1.5 text-[10px] leading-snug">
              {warnings.map((w) => (
                <p key={w.text} className={w.tone}>⚠ {w.text}</p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** What would make a careful reader distrust this trade's P&L, worst first. */
export function tradeWarnings(info) {
  const out = []
  const cal = info.calendar
  if (cal.missingSessions > 0) {
    out.push({
      tone: 'text-neg',
      text: `Held across ${cal.missingSessions} weekday session${cal.missingSessions === 1 ? '' : 's'} with no bars and no exchange holiday: a hole in the data. Part of this P&L is a move no one could have traded.`,
    })
  }
  if (cal.missingBars > 0) {
    out.push({
      tone: 'text-neg',
      text: `${cal.missingBars} bar${cal.missingBars === 1 ? '' : 's'} missing inside the hold. The price jump across the hole is in the P&L, with no chance to exit during it.`,
    })
  }
  if (info.pnlShare !== null && Math.abs(info.pnlShare) >= 0.2) {
    out.push({
      tone: 'text-amber',
      text: `One trade, ${shareText(info)}. Without it the run nets ${fmtMoneySigned(info.netWithout, 0)}.`,
    })
  }
  if (cal.overnight && cal.missingSessions === 0) {
    out.push({ tone: 'text-amber', text: 'Held overnight, so the result includes the open gap the strategy could not react to.' })
  }
  if (info.beforeCosts > 0 && info.trade.pnl < 0) {
    out.push({ tone: 'text-amber', text: 'A winner at the quote that costs turned into a loser.' })
  }
  if (info.trade.reason === 'end-of-data') {
    out.push({ tone: 'text-dim', text: 'Closed by the end of the data, not by the strategy.' })
  }
  return out
}

/** The trade's share of the run's net, worded so the sign reads correctly
 *  whether the run made or lost money. */
function shareText(info) {
  const a = Math.abs(info.pnlShare)
  const pct = fmtPctAbs(a, a < 0.1 ? 1 : 0)
  const runUp = info.netWithout + info.trade.pnl > 0
  const same = info.pnlShare > 0
  if (runUp) return same ? `${pct} of the run's net profit` : `gave back ${pct} of the run's net profit`
  return same ? `${pct} of the run's net loss` : `offset ${pct} of the run's net loss`
}

function fmtInput(v) {
  if (v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (!Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  return fmtNum(v, a >= 100 ? 2 : a >= 1 ? 3 : 4)
}

function Section({ title, children }) {
  return (
    <div className="hair-t flex flex-col gap-0.5 px-2 py-1.5">
      <span className="text-[9px] tracking-[0.12em] text-dim uppercase">{title}</span>
      {children}
    </div>
  )
}

function Line({ label, value, tone, title }) {
  return (
    <div className="flex items-baseline justify-between gap-2" title={title}>
      <span className="shrink-0 text-dim">{label}</span>
      <span className={`num truncate text-right ${tone || 'text-muted'}`}>{value}</span>
    </div>
  )
}
