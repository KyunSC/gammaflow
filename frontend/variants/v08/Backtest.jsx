'use client'

import { useEffect, useState } from 'react'
import { Group as PanelGroup, Panel as RPanel, Separator as PanelResizeHandle } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig } from '../../lib/backtest/share'
import SweepPanel from '../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../components/backtest/MonteCarloPanel'
import CostPanel from '../../components/backtest/CostPanel'
import RuleBuilder from '../../components/backtest/RuleBuilder'
import PropPanel from '../../components/backtest/PropPanel'
import CommandPalette from '../../components/backtest/CommandPalette'
import Header from './bt/Header'
import Setup from './bt/Setup'
import Result, { MetricsList } from './bt/Result'
import PriceChart from './bt/PriceChart'
import Equity from './bt/Equity'
import Trades from './bt/Trades'
import GapsList from './bt/GapsList'
import Compare from './bt/Compare'
import Shortcuts from './bt/Shortcuts'
import { Region, ErrorLine } from './bt/ui'
import { findGaps } from './bt/gaps'
import './v08.css'

const TABS = [
  { id: 'blotter', label: 'Trades', simple: true },
  { id: 'gaps', label: 'Data gaps', simple: true, local: true },
  { id: 'sweep', label: 'Sweep', key: 'S' },
  { id: 'wf', label: 'Walk-forward', key: 'W' },
  { id: 'mc', label: 'Monte Carlo', key: 'M' },
  { id: 'costs', label: 'Cost ladder' },
  { id: 'prop', label: 'Prop account' },
  { id: 'rules', label: 'Rule builder' },
]

export default function Backtest() {
  const advanced = useBacktest((s) => s.advanced)
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const setExample = useBacktest((s) => s.setExample)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const loadDataset = useBacktest((s) => s.loadDataset)
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const dataset = useBacktest((s) => s.dataset)
  const wide = useWide()
  // "Data gaps" is this design's own tab, kept out of the shared store so the
  // other designs never see a tab id they don't know.
  const [gapsOpen, setGapsOpen] = useState(false)

  // Boot once per page load. Switching designs keeps the store, so a run that
  // is already loaded is not reloaded (and the runs tally is not inflated).
  useEffect(() => {
    const store = useBacktest.getState()
    if (store.dataset) return
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useEffect(() => setGapsOpen(false), [activeTab])

  useKeyboard()

  const tab = gapsOpen ? 'gaps' : !advanced && !TABS.find((t) => t.id === activeTab)?.simple ? 'blotter' : activeTab
  const visibleTabs = TABS.filter((t) => advanced || t.simple)
  const gaps = findGaps(dataset)

  const choose = (id) => {
    if (id === 'gaps') setGapsOpen(true)
    else {
      setGapsOpen(false)
      setTab(id)
    }
  }
  const showGaps = () => {
    setGapsOpen(true)
    document.getElementById('v8-analysis')?.scrollIntoView?.({ block: 'nearest' })
  }

  const onTabKey = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const i = visibleTabs.findIndex((t) => t.id === tab)
    const next = visibleTabs[(i + (e.key === 'ArrowRight' ? 1 : visibleTabs.length - 1)) % visibleTabs.length]
    choose(next.id)
    document.getElementById(`v8-tab-${next.id}`)?.focus()
  }

  const analysis = (
    <Region
      id="v8-analysis"
      className="v8-fill"
      title={null}
      aside={null}
      bodyClassName="v8-analysis-body"
    >
      <div className="v8-tabs" role="tablist" aria-label="Analysis" onKeyDown={onTabKey}>
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            id={`v8-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls="v8-tabpanel"
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => choose(t.id)}
            className="v8-tab"
            title={t.key ? `Key ${t.key} runs it` : undefined}
          >
            {t.label}
            {t.id === 'gaps' && gaps?.holes.length > 0 && <span className="v8-tabcount">{gaps.days.length}</span>}
          </button>
        ))}
        {!advanced && (
          <span className="v8-tabs-more text-dim">Sweeps, walk-forward and Monte Carlo are under Research tools</span>
        )}
      </div>
      <div id="v8-tabpanel" role="tabpanel" aria-labelledby={`v8-tab-${tab}`} className="v8-tabpanel">
        {tab === 'blotter' && <Trades />}
        {tab === 'gaps' && <GapsList />}
        {tab === 'sweep' && <SweepPanel />}
        {tab === 'wf' && <WalkForwardPanel />}
        {tab === 'mc' && <MonteCarloPanel />}
        {tab === 'costs' && <CostPanel />}
        {tab === 'rules' && <RuleBuilder />}
        {tab === 'prop' && <PropPanel />}
      </div>
    </Region>
  )

  const notices = (
    <>
      {datasetNotice && !datasetError && (
        <div className="v8-notice" role="status">
          <span>{datasetNotice}</span>
          <button type="button" onClick={() => setExample(false)} className="v8-textbtn">
            Try the server again
          </button>
        </div>
      )}
      {datasetError && (
        <ErrorLine>
          Couldn&apos;t load data: {datasetError}{' '}
          <button type="button" onClick={loadDataset} className="v8-textbtn">
            Retry
          </button>
        </ErrorLine>
      )}
      {runError && <ErrorLine>The run failed: {runError}</ErrorLine>}
      {configError && <ErrorLine>{configError}</ErrorLine>}
    </>
  )

  const side = (
    <aside className="v8-side" aria-label="Metrics and comparison">
      <Region title="All metrics">
        <MetricsList />
      </Region>
      <Compare />
    </aside>
  )

  return (
    <div className="v8 v8-bt">
      <a href="#v8-setup" className="v8-skip">Skip to setup</a>
      <Header onShowGaps={showGaps} />
      {notices}

      {wide ? (
        <PanelGroup key={advanced ? 'adv' : 'simple'} orientation="horizontal" className="v8-cols">
          <RPanel defaultSize={advanced ? '20' : '22'} minSize="15" maxSize="34" className="v8-col">
            <Setup />
          </RPanel>
          <PanelResizeHandle className="v8-handle v8-handle-v" />
          <RPanel defaultSize={advanced ? '58' : '78'} minSize="36" className="v8-col">
            <div className="v8-main">
              <Result />
              <PanelGroup orientation="vertical" className="v8-stack">
                <RPanel defaultSize={advanced ? '36' : '44'} minSize="18">
                  <PriceChart />
                </RPanel>
                <PanelResizeHandle className="v8-handle v8-handle-h" />
                <RPanel defaultSize={advanced ? '22' : '26'} minSize="14">
                  <Equity />
                </RPanel>
                <PanelResizeHandle className="v8-handle v8-handle-h" />
                <RPanel defaultSize={advanced ? '42' : '30'} minSize="14">
                  {analysis}
                </RPanel>
              </PanelGroup>
            </div>
          </RPanel>
          {advanced && (
            <>
              <PanelResizeHandle className="v8-handle v8-handle-v" />
              <RPanel defaultSize="22" minSize="16" maxSize="36" className="v8-col">
                {side}
              </RPanel>
            </>
          )}
        </PanelGroup>
      ) : (
        <div className="v8-narrow">
          <Result />
          <a href="#v8-setup" className="v8-jump">Change data, strategy or costs ↓</a>
          <div className="v8-h-price"><PriceChart /></div>
          <div className="v8-h-equity"><Equity /></div>
          <div className="v8-h-analysis">{analysis}</div>
          <Setup />
          {advanced && side}
        </div>
      )}

      <CommandPalette />
      <Shortcuts />
    </div>
  )
}

function useWide() {
  const [wide, setWide] = useState(true)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const apply = () => setWide(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return wide
}

/** Same bindings as the original terminal. Typing in a field always wins, and
 *  plain digits belong to the design switcher, so families are Alt+1–4. */
function useKeyboard() {
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
          s.runSweep()
          break
        case 'w':
          s.setAdvanced(true)
          s.setTab('wf')
          s.runWalkForward()
          break
        case 'm':
          s.setAdvanced(true)
          s.setTab('mc')
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
  }, [])
}
