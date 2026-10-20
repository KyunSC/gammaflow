'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Group as PanelGroup, Panel as RPanel, Separator as PanelResizeHandle } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy } from '../../lib/backtest/strategies'
import { decodeConfig, shareUrl } from '../../lib/backtest/share'
import { fmtDateRange } from '../../lib/backtest/format'
import SweepPanel from '../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../components/backtest/MonteCarloPanel'
import CostPanel from '../../components/backtest/CostPanel'
import RuleBuilder from '../../components/backtest/RuleBuilder'
import PropPanel from '../../components/backtest/PropPanel'
import SiteBar from './SiteBar'
import { fontVars } from './fonts'
import site from './site.module.css'
import b from './backtest/bt.module.css'
import Setup from './backtest/Setup'
import Verdict from './backtest/Verdict'
import Evidence from './backtest/Evidence'
import PriceChart from './backtest/PriceChart'
import EquityChart from './backtest/EquityChart'
import Trades, { SelectedTrade } from './backtest/Trades'
import Palette from './backtest/Palette'
import Shortcuts from './backtest/Shortcuts'
import useKeyboard from './backtest/useKeyboard'
import { findGaps } from './backtest/gaps'

const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep', research: true },
  { id: 'wf', label: 'Walk-forward', research: true },
  { id: 'mc', label: 'Monte Carlo', research: true },
  { id: 'costs', label: 'Cost ladder', research: true },
  { id: 'prop', label: 'Prop account', research: true },
  { id: 'rules', label: 'Rules', research: true },
]

export default function Backtest() {
  const wide = useWide()

  // Boot exactly as BacktestTerminal does: UI preference, shared link, load.
  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useKeyboard()

  return (
    <div className={`${site.root} ${b.root} ${wide ? '' : b.stacked} ${fontVars}`}>
      <SiteBar current="backtest" right={<BarTools />} />
      <Context />
      {wide ? <Wide /> : <Stacked />}
      <Palette />
      <Shortcuts />
    </div>
  )
}

function Wide() {
  return (
    <div className={b.wide}>
      <aside className={`${b.col} ${b.colLeft}`} aria-label="Setup">
        <Setup />
      </aside>
      <main className={b.center}>
        <Verdict />
        <PanelGroup orientation="vertical" className="min-h-0 flex-1">
          <RPanel defaultSize="46" minSize="20">
            <PriceChart />
          </RPanel>
          <PanelResizeHandle className={b.handle} />
          <RPanel defaultSize="24" minSize="12">
            <EquityChart />
          </RPanel>
          <PanelResizeHandle className={b.handle} />
          <RPanel defaultSize="30" minSize="14">
            <Analysis />
          </RPanel>
        </PanelGroup>
      </main>
      <aside className={`${b.col} ${b.colRight}`} aria-label="Evidence">
        <Evidence />
      </aside>
    </div>
  )
}

/** Under 1100px: the answer first, setup one tap away, then the pictures. */
function Stacked() {
  const strategyId = useBacktest((s) => s.strategyId)
  const dataset = useBacktest((s) => s.dataset)
  const costs = useBacktest((s) => s.costs)
  const propOn = useBacktest((s) => s.prop.enabled)
  const summary = `${getStrategy(strategyId).label} · ${dataset ? `${dataset.symbol} ${dataset.interval}` : '…'} · ${propOn ? 'prop account' : `${costs.slippageBps} bp, $${costs.commissionPerTrade}/trade`}`
  return (
    <div className={b.stack}>
      <Verdict />
      <details className={b.setupDetails}>
        <summary className={b.setupSummary}>
          <span className="font-semibold">Setup</span>
          <span className={b.setupSummaryText}>{summary}</span>
        </summary>
        <div className="border-t border-hair">
          <Setup />
        </div>
      </details>
      <div className="h-[320px]"><PriceChart /></div>
      <div className="h-[230px]"><EquityChart /></div>
      <div className="h-[420px]"><Analysis /></div>
      <div className="bg-panel"><Evidence /></div>
    </div>
  )
}

/** Trades plus, with research tools on, the tools that try to break the result. */
function Analysis() {
  const advanced = useBacktest((s) => s.advanced)
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const tabs = advanced ? TABS : TABS.filter((t) => !t.research)
  const current = tabs.some((t) => t.id === activeTab) ? activeTab : 'blotter'
  const refs = useRef({})

  const onKeyDown = (e) => {
    const i = tabs.findIndex((t) => t.id === current)
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key]
    if (next === undefined) return
    e.preventDefault()
    e.stopPropagation()
    const t = tabs[(next + tabs.length) % tabs.length]
    setTab(t.id)
    refs.current[t.id]?.focus()
  }

  return (
    <section className={b.region} aria-label="Trades and research tools">
      <header className={b.regionHead}>
        <div role="tablist" aria-label="Analysis" className={b.tablist} onKeyDown={onKeyDown}>
          {tabs.map((t) => (
            <button
              key={t.id}
              ref={(el) => { refs.current[t.id] = el }}
              type="button"
              role="tab"
              id={`v01-tab-${t.id}`}
              aria-selected={current === t.id}
              aria-controls="v01-tabpanel"
              tabIndex={current === t.id ? 0 : -1}
              onClick={() => setTab(t.id)}
              className={`${b.tab} ${current === t.id ? b.tabActive : ''}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {!advanced && (
          <span className={b.tabHint}>
            <span className={b.hideNarrow}>Sweep, walk-forward, Monte Carlo, cost ladder, prop and rules:{' '}</span>
            <button type="button" className={b.linkButton} onClick={() => setAdvanced(true)}>show research tools</button>
          </span>
        )}
      </header>
      {current === 'blotter' && <SelectedTrade />}
      <div id="v01-tabpanel" role="tabpanel" aria-labelledby={`v01-tab-${current}`} className={b.regionBody}>
        <div className="absolute inset-0 overflow-hidden">
          {current === 'blotter' && <Trades />}
          {current === 'sweep' && <SweepPanel />}
          {current === 'wf' && <WalkForwardPanel />}
          {current === 'mc' && <MonteCarloPanel />}
          {current === 'costs' && <CostPanel />}
          {current === 'rules' && <RuleBuilder />}
          {current === 'prop' && <PropPanel />}
        </div>
      </div>
    </section>
  )
}

/** What is loaded, and how trustworthy it is — one line, always visible. */
function Context() {
  const dataset = useBacktest((s) => s.dataset)
  const loading = useBacktest((s) => s.datasetLoading)
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const setExample = useBacktest((s) => s.setExample)
  const loadDataset = useBacktest((s) => s.loadDataset)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const running = useBacktest((s) => s.running)
  const gaps = useMemo(() => findGaps(dataset), [dataset])

  return (
    <div className={b.context} role="status" aria-live="polite">
      {dataset ? (
        <>
          <span className={b.contextStrong}>{dataset.symbol} · {dataset.interval}</span>
          <span>{fmtDateRange(dataset.start, dataset.end)} ET</span>
          <span><span className={b.contextStrong}>{dataset.n.toLocaleString()}</span> bars</span>
          <span className={`${b.tag} ${dataset.plane === 'research' ? b.tagSample : b.tagLive}`}>
            {dataset.plane === 'research' ? (dataset.example ? 'Bundled sample data' : 'Research dataset with historical GEX') : 'Live prices, no historical GEX'}
          </span>
          {gaps?.holes.length > 0 && (
            <span className={`${b.tag} ${b.tagGap}`} title="Holes between two bars of the same session. The charts close them up, so they are marked explicitly.">
              {gaps.missingBars.toLocaleString()} bars missing inside {gaps.sessionsHit} of {gaps.sessions} sessions
            </span>
          )}
          {running ? <span className="text-amber">Running…</span> : lastRunMs > 0 && <span>Last run {lastRunMs.toFixed(0)} ms</span>}
        </>
      ) : loading ? (
        <span>Loading data…</span>
      ) : (
        <span className={b.tagError}>No data loaded.</span>
      )}

      {datasetNotice && !datasetError && (
        <span className={b.notice}>
          <span>{datasetNotice}</span>
          <button type="button" onClick={() => setExample(false)} className="btn shrink-0 !py-0 whitespace-nowrap">Retry server</button>
        </span>
      )}
      {datasetError && (
        <span className={`${b.notice} ${b.tagError}`} role="alert">
          <span>{datasetError}</span>
          <button type="button" onClick={loadDataset} className="btn !py-0">Retry</button>
        </span>
      )}
    </div>
  )
}

function BarTools() {
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const runCount = useBacktest((s) => s.runCount)
  const [copied, setCopied] = useState(false)

  // Same two-path copy as TapeBar: the URL always lands in the address bar.
  const copyShare = async () => {
    const url = shareUrl(useBacktest.getState())
    if (!url) return
    try { window.history.replaceState(null, '', url) } catch { /* ignore */ }
    try {
      await navigator.clipboard.writeText(url)
      setCopied('Link copied')
    } catch {
      setCopied('Link is in the address bar')
    }
    setTimeout(() => setCopied(false), 1800)
  }

  const tally = runCount > 300 ? 'text-neg' : runCount > 80 ? 'text-amber' : 'text-muted'

  return (
    <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
      <button type="button" onClick={() => toggleShortcuts(true)} className={`${tally} hover:text-ink`} title="Simulations this session — every sweep cell and walk-forward trial counts. Data-snooping tally.">
        <span className="font-mono">{runCount.toLocaleString()}</span> run{runCount === 1 ? '' : 's'} this session
      </button>
      <button type="button" onClick={copyShare} className="text-muted hover:text-ink" title="Copy a link that reproduces this run" aria-live="polite">
        {copied ? <span className="text-pos">{copied}</span> : 'Share link'}
      </button>
      <button
        type="button"
        role="switch"
        aria-checked={advanced}
        onClick={() => setAdvanced(!advanced)}
        className={`flex items-center gap-2 ${advanced ? 'text-ink' : 'text-muted'} hover:text-ink`}
        title="Parameter sweep, walk-forward, Monte Carlo, cost ladder, prop-firm accounts, custom rules and A/B/C compare"
      >
        <span className="switch pointer-events-none" aria-checked={advanced} />
        Research tools
      </button>
      <button type="button" onClick={() => toggleShortcuts(true)} className={`text-muted hover:text-ink ${b.hideNarrow}`} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
        Keys <span className="kbd">?</span>
      </button>
      <button type="button" onClick={() => togglePalette(true)} className={`text-muted hover:text-ink ${b.hideNarrow}`} title="Command palette">
        <span className="kbd">⌘K</span>
      </button>
    </span>
  )
}

function useWide() {
  const [wide, setWide] = useState(true)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1100px)')
    const apply = () => setWide(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return wide
}
