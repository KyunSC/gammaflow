'use client'

import './v10.css'
import { useEffect, useState } from 'react'
import { Group as PanelGroup, Panel as RPanel, Separator } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig } from '../../lib/backtest/share'
import SweepPanel from '../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../components/backtest/MonteCarloPanel'
import CostPanel from '../../components/backtest/CostPanel'
import RuleBuilder from '../../components/backtest/RuleBuilder'
import PropPanel from '../../components/backtest/PropPanel'
import TopBar from './bt/TopBar'
import Setup from './bt/Setup'
import Verdict from './bt/Verdict'
import PriceChart from './bt/PriceChart'
import EquityChart from './bt/EquityChart'
import Trades from './bt/Trades'
import Metrics from './bt/Metrics'
import Compare from './bt/Compare'
import Palette from './bt/Palette'
import ShortcutSheet from './bt/ShortcutSheet'
import Section from './bt/Section'

const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep', key: 'S' },
  { id: 'wf', label: 'Walk-forward', key: 'W' },
  { id: 'mc', label: 'Monte Carlo', key: 'M' },
  { id: 'costs', label: 'Cost ladder' },
  { id: 'prop', label: 'Prop account' },
  { id: 'rules', label: 'Rules' },
]

const HX = () => <Separator className="l10-handle l10-handle-x" />
const HY = () => <Separator className="l10-handle l10-handle-y" />

export default function Backtest() {
  const advanced = useBacktest((s) => s.advanced)
  const wide = useWide()

  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useKeyboard()

  return (
    <div className="l10-app">
      <TopBar />
      <Notices />
      {wide ? (advanced ? <AdvancedWide /> : <SimpleWide />) : <Narrow advanced={advanced} />}
      <Palette />
      <ShortcutSheet />
    </div>
  )
}

function Notices() {
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const setExample = useBacktest((s) => s.setExample)
  const loadDataset = useBacktest((s) => s.loadDataset)
  return (
    <>
      {datasetNotice && !datasetError && (
        <div className="l10-notice" role="status">
          <span>{datasetNotice}</span>
          <button type="button" onClick={() => setExample(false)} className="btn !py-0.5">Try the server again</button>
        </div>
      )}
      {datasetError && (
        <div className="l10-notice is-error" role="alert">
          <span>Could not load data: {datasetError}</span>
          <button type="button" onClick={loadDataset} className="btn !py-0.5">Retry</button>
        </div>
      )}
      {runError && <div className="l10-notice is-error" role="alert"><span>Run failed: {runError}</span></div>}
      {configError && <div className="l10-notice is-error" role="alert"><span>{configError}</span></div>}
    </>
  )
}

function Tabs() {
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  return (
    <div className="l10-tabs" role="tablist" aria-label="Analysis">
      {TABS.map((t) => (
        <button
          type="button"
          role="tab"
          key={t.id}
          aria-selected={activeTab === t.id}
          onClick={() => setTab(t.id)}
          className="l10-tab"
          title={t.key ? `Run with ${t.key}` : undefined}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

function TabBody() {
  const activeTab = useBacktest((s) => s.activeTab)
  return (
    <div role="tabpanel" className="h-full">
      {activeTab === 'blotter' && <Trades />}
      {activeTab === 'sweep' && <SweepPanel />}
      {activeTab === 'wf' && <WalkForwardPanel />}
      {activeTab === 'mc' && <MonteCarloPanel />}
      {activeTab === 'costs' && <CostPanel />}
      {activeTab === 'rules' && <RuleBuilder />}
      {activeTab === 'prop' && <PropPanel />}
    </div>
  )
}

/** Default: setup on the left; the answer, price, equity and trades on the right. */
function SimpleWide() {
  return (
    <PanelGroup orientation="horizontal" className="min-h-0 flex-1">
      <RPanel defaultSize="22" minSize="17" maxSize="34" className="min-h-0">
        <Setup />
      </RPanel>
      <HX />
      <RPanel defaultSize="78" minSize="40" className="min-h-0">
        <div className="flex h-full min-h-0 flex-col">
          <Verdict />
          <PanelGroup orientation="vertical" className="min-h-0 flex-1">
            <RPanel defaultSize="46" minSize="20"><PriceChart /></RPanel>
            <HY />
            <RPanel defaultSize="28" minSize="14"><EquityChart /></RPanel>
            <HY />
            <RPanel defaultSize="26" minSize="12">
              <Section title="Trades" scroll={false}><Trades /></Section>
            </RPanel>
          </PanelGroup>
        </div>
      </RPanel>
    </PanelGroup>
  )
}

/** Research tools on: analysis tabs under the charts, all metrics and compare on the right. */
function AdvancedWide() {
  return (
    <PanelGroup orientation="horizontal" className="min-h-0 flex-1">
      <RPanel defaultSize="20" minSize="15" maxSize="32" className="min-h-0">
        <Setup />
      </RPanel>
      <HX />
      <RPanel defaultSize="58" minSize="30" className="min-h-0">
        <div className="flex h-full min-h-0 flex-col">
          <Verdict compact />
          <PanelGroup orientation="vertical" className="min-h-0 flex-1">
            <RPanel defaultSize="38" minSize="16"><PriceChart /></RPanel>
            <HY />
            <RPanel defaultSize="27" minSize="12"><EquityChart /></RPanel>
            <HY />
            <RPanel defaultSize="35" minSize="16">
              <Section title="Analysis" right={<Tabs />} scroll={false}><TabBody /></Section>
            </RPanel>
          </PanelGroup>
        </div>
      </RPanel>
      <HX />
      <RPanel defaultSize="22" minSize="15" maxSize="36" className="min-h-0">
        <PanelGroup orientation="vertical">
          <RPanel defaultSize="64" minSize="25"><Metrics /></RPanel>
          <HY />
          <RPanel defaultSize="36" minSize="15"><Compare /></RPanel>
        </PanelGroup>
      </RPanel>
    </PanelGroup>
  )
}

/** Under 1024px: one column, answer first, with jump links so setup is one tap away. */
function Narrow({ advanced }) {
  return (
    <>
      <nav className="l10-jump" aria-label="Sections">
        <a href="#bt-setup">Setup</a>
        <a href="#bt-price">Price</a>
        <a href="#bt-equity">Equity</a>
        <a href="#bt-trades">{advanced ? 'Analysis' : 'Trades'}</a>
        {advanced && <a href="#bt-metrics">Metrics</a>}
      </nav>
      <div className="l10-stack">
        <Verdict />
        <div className="h-[340px] shrink-0"><PriceChart id="bt-price" /></div>
        <div className="h-[230px] shrink-0"><EquityChart id="bt-equity" /></div>
        <div className="h-[380px] shrink-0">
          {advanced ? (
            <Section id="bt-trades" title="Analysis" right={<Tabs />} scroll={false}><TabBody /></Section>
          ) : (
            <Section id="bt-trades" title="Trades" scroll={false}><Trades /></Section>
          )}
        </div>
        <div className="shrink-0"><Setup id="bt-setup" /></div>
        {advanced && (
          <>
            <div className="shrink-0" id="bt-metrics"><Metrics /></div>
            <div className="shrink-0"><Compare /></div>
          </>
        )}
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

/** Same shortcuts as the original terminal. Plain digits belong to the design
 *  switcher, so strategy families are Alt+1–4 (e.code: Alt rewrites e.key on macOS). */
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
