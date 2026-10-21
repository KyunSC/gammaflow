'use client'

import './backtest.css'
import { useCallback, useEffect, useState } from 'react'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig, shareUrl } from '../../lib/backtest/share'
import { fmtDateRange } from '../../lib/backtest/format'
import SweepPanel from '../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../components/backtest/MonteCarloPanel'
import CostPanel from '../../components/backtest/CostPanel'
import RuleBuilder from '../../components/backtest/RuleBuilder'
import PropPanel from '../../components/backtest/PropPanel'
import Nav from './Nav'
import Setup from './Setup'
import Claim from './Claim'
import PriceChart from './PriceChart'
import EquityChart from './EquityChart'
import Trades from './Trades'
import GapsTab from './GapsTab'
import Ledger from './Ledger'
import Compare from './Compare'
import Palette from './Palette'
import Keys from './Keys'
import useMedia from './useMedia'

// Tabs the shared store knows about keep their store ids, so switching to
// another design lands on the same tab. Tabs only this design has (gaps,
// compare, metrics) are local state and never written to the store.
const STORE_TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep', research: true },
  { id: 'wf', label: 'Walk-forward', research: true },
  { id: 'mc', label: 'Monte Carlo', research: true },
  { id: 'costs', label: 'Cost ladder', research: true },
  { id: 'prop', label: 'Prop account', research: true },
  { id: 'rules', label: 'Rules', research: true },
]

export default function Backtest() {
  const advanced = useBacktest((s) => s.advanced)
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const propOn = useBacktest((s) => s.prop.enabled)
  const media = useMedia()
  const [localTab, setLocalTab] = useState(null)

  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  // A store-side tab change (palette, S/W/M keys, switching prop on) wins over a local tab.
  useEffect(() => setLocalTab(null), [activeTab, propOn])

  const clearLocalTab = useCallback(() => setLocalTab(null), [])
  useKeyboard(clearLocalTab)

  const tabs = [
    STORE_TABS[0],
    { id: 'gaps', label: 'Data gaps', local: true },
    ...(media === 'mid' ? [{ id: 'metrics', label: 'All metrics', local: true }] : []),
    ...(advanced ? STORE_TABS.slice(1) : []),
    ...(advanced ? [{ id: 'compare', label: 'Compare A/B/C', local: true }] : []),
  ]
  const storeTabVisible = tabs.some((t) => !t.local && t.id === activeTab)
  const current = localTab && tabs.some((t) => t.id === localTab) ? localTab : storeTabVisible ? activeTab : 'blotter'

  const pick = (t) => {
    if (t.local) setLocalTab(t.id)
    else {
      setLocalTab(null)
      setTab(t.id)
    }
  }

  const workbench = <Workbench tabs={tabs} current={current} onPick={pick} narrow={media === 'narrow'} />

  return (
    <div className="v9 flex min-h-screen flex-col lg:h-screen lg:overflow-hidden">
      <TopBar />
      <Notices />

      {media === 'narrow' ? (
        <main className="flex flex-col pb-16">
          <Claim onShowGaps={() => setLocalTab('gaps')} />
          <div className="h-[320px] border-t border-hair">
            <PriceChart />
          </div>
          <div className="h-[210px] border-t border-hair">
            <EquityChart />
          </div>
          <section id="v9-setup" className="border-t border-hair" aria-label="Setup">
            <Setup narrow />
          </section>
          <div className="h-[460px] border-t border-hair">{workbench}</div>
          <div className="border-t border-hair">
            <Ledger />
          </div>
          <MobileBar />
        </main>
      ) : (
        <div
          className="grid min-h-0 flex-1"
          style={{ gridTemplateColumns: media === 'wide' ? '292px minmax(0,1fr) 288px' : '284px minmax(0,1fr)' }}
        >
          <aside className="min-h-0 border-r border-hair" aria-label="Setup">
            <Setup />
          </aside>
          <main className="grid min-h-0 min-w-0" style={{ gridTemplateRows: 'auto minmax(200px,1fr) 168px minmax(220px,32%)' }}>
            <Claim onShowGaps={() => setLocalTab('gaps')} />
            <div className="min-h-0 border-t border-hair">
              <PriceChart />
            </div>
            <div className="min-h-0 border-t border-hair">
              <EquityChart />
            </div>
            <div className="min-h-0 border-t border-hair">{workbench}</div>
          </main>
          {media === 'wide' && (
            <aside className="min-h-0 overflow-y-auto border-l border-hair" aria-label="Metrics and caveats">
              <Ledger />
            </aside>
          )}
        </div>
      )}

      <Palette onShowTab={clearLocalTab} />
      <Keys />
    </div>
  )
}

function Workbench({ tabs, current, onPick, narrow }) {
  const result = useBacktest((s) => s.result)
  const onKeyDown = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const i = tabs.findIndex((t) => t.id === current)
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]
    e.preventDefault()
    onPick(next)
    requestAnimationFrame(() => document.getElementById(`v9-tab-${next.id}`)?.focus())
  }
  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Analysis">
      <div role="tablist" aria-label="Analysis views" className="v9-tabs shrink-0 px-2" onKeyDown={onKeyDown}>
        {tabs.map((t) => (
          <button
            key={t.id}
            id={`v9-tab-${t.id}`}
            role="tab"
            aria-selected={current === t.id}
            aria-controls="v9-tabpanel"
            tabIndex={current === t.id ? 0 : -1}
            className="v9-tab"
            onClick={() => onPick(t)}
          >
            {t.label}
            {t.id === 'blotter' && result && <span className="v9-count">{result.trades.length}</span>}
          </button>
        ))}
      </div>
      <div id="v9-tabpanel" role="tabpanel" aria-labelledby={`v9-tab-${current}`} className="v9-shared min-h-0 flex-1 overflow-hidden">
        {current === 'blotter' && <Trades narrow={narrow} />}
        {current === 'gaps' && <GapsTab />}
        {current === 'metrics' && (
          <div className="h-full overflow-y-auto">
            <Ledger />
          </div>
        )}
        {current === 'sweep' && <SweepPanel />}
        {current === 'wf' && <WalkForwardPanel />}
        {current === 'mc' && <MonteCarloPanel />}
        {current === 'costs' && <CostPanel />}
        {current === 'prop' && <PropPanel />}
        {current === 'rules' && <RuleBuilder />}
        {current === 'compare' && <Compare />}
      </div>
    </section>
  )
}

function TopBar() {
  const dataset = useBacktest((s) => s.dataset)
  const datasetLoading = useBacktest((s) => s.datasetLoading)
  const runCount = useBacktest((s) => s.runCount)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const toggleShortcuts = useBacktest((s) => s.toggleShortcuts)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const [copied, setCopied] = useState(false)

  const copyShare = async () => {
    const url = shareUrl(useBacktest.getState())
    if (!url) return
    try {
      window.history.replaceState(null, '', url)
    } catch { /* ignore */ }
    try {
      await navigator.clipboard.writeText(url)
      setCopied('Link copied')
    } catch {
      setCopied('Link is in the address bar')
    }
    setTimeout(() => setCopied(false), 2000)
  }

  const tally = runCount > 300 ? 'text-neg' : runCount > 80 ? 'text-amber' : 'text-ink'

  const extra = (
    <span className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-muted">
      {dataset ? (
        <>
          <span className="font-semibold text-ink">{dataset.symbol}</span>
          <span className="v9-num">{dataset.interval}</span>
          <span className="v9-num" title="New York dates">{fmtDateRange(dataset.start, dataset.end)}</span>
          <span className="v9-num">{dataset.n.toLocaleString()} bars</span>
          <span className={dataset.example ? 'text-violet' : dataset.plane === 'live' ? 'text-cyan' : 'text-muted'}>
            {dataset.plane === 'research' ? (dataset.example ? 'bundled sample data' : 'published history + GEX') : 'live prices'}
          </span>
        </>
      ) : (
        <span className="text-dim">{datasetLoading ? 'Loading data…' : 'No data loaded'}</span>
      )}
    </span>
  )

  const right = (
    <>
      <button
        onClick={() => toggleShortcuts(true)}
        className="text-[12px] text-muted hover:text-ink"
        title="Every run, sweep cell and walk-forward trial counts. The more you burn on one dataset, the more a good Sharpe is the best of many draws."
      >
        Runs this session <span className={`v9-num ${tally}`}>{runCount.toLocaleString()}</span>
      </button>
      <button onClick={copyShare} className="text-[12px] text-muted hover:text-ink" title="Copy a link that reproduces this run" aria-live="polite">
        {copied ? <span className="text-pos">{copied}</span> : 'Share link'}
      </button>
      <button
        role="switch"
        aria-checked={advanced}
        onClick={() => setAdvanced(!advanced)}
        className="v9-toggle"
        title="Sweep, walk-forward, Monte Carlo, cost ladder, prop accounts, custom rules and A/B/C compare"
      >
        Research tools
      </button>
      <button onClick={() => toggleShortcuts(true)} className="v9-kbd hidden hover:text-ink sm:inline" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
        ?
      </button>
      <button onClick={() => togglePalette(true)} className="v9-kbd hidden hover:text-ink sm:inline" aria-label="Command palette" title="Command palette (Ctrl/⌘ K)">
        ⌘K
      </button>
    </>
  )

  return <Nav current="backtest" extra={extra} right={right} />
}

function Notices() {
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const setExample = useBacktest((s) => s.setExample)
  const loadDataset = useBacktest((s) => s.loadDataset)
  const lines = []
  if (datasetNotice && !datasetError) {
    lines.push(
      <p key="n" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-amber">
        <span>{datasetNotice}</span>
        <button onClick={() => setExample(false)} className="v9-link">Try the server again</button>
      </p>,
    )
  }
  if (datasetError) {
    lines.push(
      <p key="e" className="flex flex-wrap items-center gap-x-3 text-neg" role="alert">
        <span>Couldn&apos;t load data: {datasetError}</span>
        <button onClick={loadDataset} className="v9-link">Retry</button>
      </p>,
    )
  }
  if (runError) lines.push(<p key="r" className="text-neg" role="alert">Run failed: {runError}</p>)
  if (configError) lines.push(<p key="c" className="text-neg" role="alert">{configError}</p>)
  if (!lines.length) return null
  return <div className="flex flex-col gap-1 border-b border-hair bg-panel px-4 py-2 text-[12px]">{lines}</div>
}

function MobileBar() {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 flex items-center gap-3 border-t border-hair-bright bg-canvas px-4 py-2">
      <a href="#v9-setup" className="v9-link min-w-0 flex-1 truncate text-[12px]">
        Edit setup · {getStrategy(strategyId).label}
      </a>
      <button onClick={run} disabled={running || !dataset} className="v9-run !w-auto !px-5 !py-2">
        {running ? 'Running…' : 'Run'}
      </button>
    </div>
  )
}

/** Same shortcuts as the original terminal. Plain digits belong to the design
 *  switcher, so strategy families are Alt+1–4. Typing in a field always wins. */
function useKeyboard(onStoreTab) {
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey) return
      const s = useBacktest.getState()
      if (e.altKey) {
        const fam = FAMILIES.find((f) => e.code === `Digit${f.hotkey}`)
        if (fam) {
          e.preventDefault()
          const first = strategiesForPlane(s.plane, s.dataset).find((st) => st.family === fam.id)
          if (first && getStrategy(s.strategyId).family !== fam.id) s.setStrategy(first.id)
        }
        return
      }
      switch (e.key) {
        case 'r':
        case 'R':
          e.preventDefault()
          s.run()
          break
        case '[':
          e.preventDefault()
          s.nudgeFocusedParam(-1)
          break
        case ']':
          e.preventDefault()
          s.nudgeFocusedParam(1)
          break
        case 's':
          s.setAdvanced(true)
          s.setTab('sweep')
          onStoreTab()
          s.runSweep()
          break
        case 'w':
          s.setAdvanced(true)
          s.setTab('wf')
          onStoreTab()
          s.runWalkForward()
          break
        case 'm':
          s.setAdvanced(true)
          s.setTab('mc')
          onStoreTab()
          s.runMonteCarlo()
          break
        case 'a':
        case 'b':
        case 'c':
          s.setAdvanced(true)
          s.saveSlot(e.key.toUpperCase())
          break
        case '?':
          s.toggleShortcuts(true)
          break
        case 'Escape':
          s.togglePalette(false)
          s.toggleShortcuts(false)
          break
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onStoreTab])
}
