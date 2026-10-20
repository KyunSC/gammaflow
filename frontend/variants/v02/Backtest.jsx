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
import TopBar from './TopBar'
import ResultHeader from './ResultHeader'
import Setup from './Setup'
import PriceChart from './PriceChart'
import Equity from './Equity'
import Trades from './Trades'
import Metrics from './Metrics'
import Compare from './Compare'
import Palette from './Palette'
import Shortcuts from './Shortcuts'
import s from './bt.module.css'

const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep', key: 'S' },
  { id: 'wf', label: 'Walk-forward', key: 'W' },
  { id: 'mc', label: 'Monte Carlo', key: 'M' },
  { id: 'costs', label: 'Cost ladder' },
  { id: 'prop', label: 'Prop account' },
  { id: 'rules', label: 'Rule builder' },
]

/**
 * Lab Ledger. One sheet: setup on the left, the result and its caveats on
 * top of the main column, the evidence (price, equity, trades and the
 * research tabs) underneath, and — with research tools on — every metric
 * and the compare slots in a right rail.
 */
export default function Backtest() {
  const datasetError = useBacktest((st) => st.datasetError)
  const runError = useBacktest((st) => st.runError)
  const configError = useBacktest((st) => st.configError)
  const loadDataset = useBacktest((st) => st.loadDataset)
  const advanced = useBacktest((st) => st.advanced)
  const wide = useWide()

  // Boot exactly as the original terminal does.
  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useKeyboard()

  const errors = (datasetError || runError || configError) && (
    <div role="alert" className="flex flex-col gap-1 border-b border-neg/40 bg-neg/5 px-4 py-2 text-[12px] text-neg">
      {datasetError && (
        <p>
          Could not load data: {datasetError}{' '}
          <button onClick={loadDataset} className={s.inlineBtn}>retry</button>
        </p>
      )}
      {runError && <p>Run failed: {runError}</p>}
      {configError && <p>Shared link not applied: {configError}</p>}
    </div>
  )

  return (
    <div className={`${s.root} flex h-screen flex-col overflow-hidden`}>
      <TopBar />
      {errors}
      {wide ? <Wide advanced={advanced} /> : <Narrow advanced={advanced} />}
      <Palette />
      <Shortcuts />
    </div>
  )
}

function Tabs() {
  const activeTab = useBacktest((st) => st.activeTab)
  const advanced = useBacktest((st) => st.advanced)
  const setTab = useBacktest((st) => st.setTab)
  const setAdvanced = useBacktest((st) => st.setAdvanced)
  // Research tabs are always listed; opening one turns the research tools on,
  // the same thing the S / W / M shortcuts already did.
  const tab = advanced ? activeTab : 'blotter'
  return (
    <div className={s.pane}>
      <div className={s.tabs} role="tablist" aria-label="Analysis">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => {
              if (t.id !== 'blotter' && !advanced) setAdvanced(true)
              setTab(t.id)
            }}
            className={`${s.tab} ${tab === t.id ? s.tabOn : ''}`}
            title={t.key ? `Press ${t.key} to run` : undefined}
          >
            {t.label}
          </button>
        ))}
        {!advanced && <span className={s.tabNote}>research tabs turn on research tools</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden" role="tabpanel">
        {tab === 'blotter' && <Trades />}
        {tab === 'sweep' && <SweepPanel />}
        {tab === 'wf' && <WalkForwardPanel />}
        {tab === 'mc' && <MonteCarloPanel />}
        {tab === 'costs' && <CostPanel />}
        {tab === 'rules' && <RuleBuilder />}
        {tab === 'prop' && <PropPanel />}
      </div>
    </div>
  )
}

function Wide({ advanced }) {
  return (
    <PanelGroup key={advanced ? 'adv' : 'simple'} orientation="horizontal" className="min-h-0 flex-1">
      <RPanel id="setup" defaultSize={advanced ? '20' : '22'} minSize="15" maxSize="32" className="min-h-0">
        <Setup />
      </RPanel>
      <PanelResizeHandle className={s.handleH} />
      <RPanel id="main" defaultSize={advanced ? '58' : '78'} minSize="36" className="min-h-0">
        <div className="flex h-full min-h-0 flex-col">
          <ResultHeader />
          <PanelGroup orientation="vertical" className="min-h-0 flex-1">
            <RPanel id="price" defaultSize="44" minSize="18">
              <PriceChart />
            </RPanel>
            <PanelResizeHandle className={s.handleV} />
            <RPanel id="equity" defaultSize="26" minSize="14">
              <Equity />
            </RPanel>
            <PanelResizeHandle className={s.handleV} />
            <RPanel id="tabs" defaultSize="30" minSize="14">
              <Tabs />
            </RPanel>
          </PanelGroup>
        </div>
      </RPanel>
      {advanced && (
        <>
          <PanelResizeHandle className={s.handleH} />
          <RPanel id="rail" defaultSize="22" minSize="15" maxSize="36" className="min-h-0">
            <PanelGroup orientation="vertical">
              <RPanel id="metrics" defaultSize="62" minSize="25">
                <Metrics />
              </RPanel>
              <PanelResizeHandle className={s.handleV} />
              <RPanel id="compare" defaultSize="38" minSize="18">
                <Compare />
              </RPanel>
            </PanelGroup>
          </RPanel>
        </>
      )}
    </PanelGroup>
  )
}

/** Under 1024px: result first, then evidence, then setup, with Run pinned to the bottom edge. */
function Narrow({ advanced }) {
  const run = useBacktest((st) => st.run)
  const running = useBacktest((st) => st.running)
  const dataset = useBacktest((st) => st.dataset)
  return (
    <>
      <div className={s.stack}>
        <div className={s.stackBlock}>
          <ResultHeader />
        </div>
        <div className={`${s.stackBlock} h-[320px]`}>
          <PriceChart />
        </div>
        <div className={`${s.stackBlock} h-[230px]`}>
          <Equity />
        </div>
        <div className={`${s.stackBlock} h-[380px]`}>
          <Tabs />
        </div>
        {advanced && (
          <>
            <div className={s.stackBlock}>
              <Metrics />
            </div>
            <div className={`${s.stackBlock} max-h-[520px]`}>
              <Compare />
            </div>
          </>
        )}
        <div className={s.stackBlock}>
          <Setup runBar={false} />
        </div>
      </div>
      <div className={s.mobileBar}>
        <a href="#v02-setup" className="btn flex flex-1 items-center justify-center !py-2 no-underline">
          Setup ↓
        </a>
        <button onClick={run} disabled={running || !dataset} className="btn btn-primary flex-[2] !py-2 !text-[12px]">
          {running ? 'Running…' : 'Run backtest'}
        </button>
      </div>
    </>
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

/** Copied from BacktestTerminal unchanged: typing in a field always wins, and
 *  plain digits are left to the design switcher. */
function useKeyboard() {
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey) return
      const st = useBacktest.getState()
      if (e.altKey) {
        const fam = FAMILIES.find((f) => e.code === `Digit${f.hotkey}`)
        if (fam) {
          e.preventDefault()
          const first = strategiesForPlane(st.plane, st.dataset).find((x) => x.family === fam.id)
          if (first && getStrategy(st.strategyId).family !== fam.id) st.setStrategy(first.id)
        }
        return
      }
      switch (e.key) {
        case 'r':
        case 'R':
          e.preventDefault()
          st.run()
          break
        case '[':
          e.preventDefault()
          st.nudgeFocusedParam(-1)
          break
        case ']':
          e.preventDefault()
          st.nudgeFocusedParam(1)
          break
        case 's':
          st.setAdvanced(true)
          st.setTab('sweep')
          st.runSweep()
          break
        case 'w':
          st.setAdvanced(true)
          st.setTab('wf')
          st.runWalkForward()
          break
        case 'm':
          st.setAdvanced(true)
          st.setTab('mc')
          st.runMonteCarlo()
          break
        case 'a':
        case 'b':
        case 'c':
          st.setAdvanced(true)
          st.saveSlot(e.key.toUpperCase())
          break
        case '?':
          st.toggleShortcuts(true)
          break
        case 'Escape':
          st.togglePalette(false)
          st.toggleShortcuts(false)
          break
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
}
