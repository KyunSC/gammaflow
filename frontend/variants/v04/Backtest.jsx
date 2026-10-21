'use client'

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
import ComparePanel from '../../components/backtest/ComparePanel'
import TopBar from './bt/TopBar'
import Result from './bt/Result'
import Setup from './bt/Setup'
import Price from './bt/Price'
import Equity from './bt/Equity'
import Trades from './bt/Trades'
import Metrics from './bt/Metrics'
import { ShortcutSheet, CommandPalette } from './bt/Overlays'
import './v04.css'

export const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep', advanced: true },
  { id: 'wf', label: 'Walk-forward', advanced: true },
  { id: 'mc', label: 'Monte Carlo', advanced: true },
  { id: 'costs', label: 'Cost ladder', advanced: true },
  { id: 'prop', label: 'Prop account', advanced: true },
  { id: 'rules', label: 'Rules', advanced: true },
]

/**
 * Lab Ledger backtester. Same store, same engine, same shortcuts as the
 * original terminal; the page reads top to bottom as result → caveats →
 * evidence, with the setup column on the left.
 */
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
    <div className="v4 v4bt">
      <TopBar />
      <Banners />
      {wide ? <WideLayout advanced={advanced} key={advanced ? 'adv' : 'simple'} /> : <NarrowLayout advanced={advanced} />}
      <CommandPalette />
      <ShortcutSheet />
    </div>
  )
}

function Banners() {
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const setExample = useBacktest((s) => s.setExample)
  const loadDataset = useBacktest((s) => s.loadDataset)
  return (
    <>
      {datasetNotice && !datasetError && (
        <div className="v4-banner" role="status">
          <span>{datasetNotice}</span>
          <button className="v4-textbtn" onClick={() => setExample(false)}>Try the server again</button>
        </div>
      )}
      {datasetError && (
        <div className="v4-banner v4-banner-err" role="alert">
          <span>{datasetError}</span>
          <button className="v4-textbtn" onClick={loadDataset}>Retry</button>
        </div>
      )}
      {runError && <div className="v4-banner v4-banner-err" role="alert">{runError}</div>}
      {configError && <div className="v4-banner v4-banner-err" role="alert">{configError}</div>}
    </>
  )
}

function Analysis({ advanced }) {
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const tab = advanced ? activeTab : 'blotter'
  const visible = TABS.filter((t) => advanced || !t.advanced)

  const onKey = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const i = visible.findIndex((t) => t.id === tab)
    const next = visible[(i + (e.key === 'ArrowRight' ? 1 : visible.length - 1)) % visible.length]
    setTab(next.id)
    e.currentTarget.querySelector(`#v4-tab-${next.id}`)?.focus()
  }

  return (
    <section className="v4-region" aria-label="Analysis">
      <div className="v4-rh" style={{ paddingBottom: 0 }}>
        {advanced ? (
          <div className="v4-tabs" role="tablist" aria-label="Analysis" onKeyDown={onKey}>
            {visible.map((t) => (
              <button
                key={t.id}
                id={`v4-tab-${t.id}`}
                role="tab"
                aria-selected={tab === t.id}
                aria-controls="v4-tabpanel"
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        ) : (
          <h2 style={{ paddingBottom: 5 }}>Trades</h2>
        )}
        {!advanced && (
          <span className="v4-rh-right">
            <button
              className="v4-textbtn"
              onClick={() => setAdvanced(true)}
              title="Sweep, walk-forward, Monte Carlo, cost ladder, prop account and rule builder"
            >
              More tests in Advanced
            </button>
          </span>
        )}
      </div>
      <div
        className="v4-region-body"
        id="v4-tabpanel"
        role={advanced ? 'tabpanel' : undefined}
        aria-labelledby={advanced ? `v4-tab-${tab}` : undefined}
        style={{ borderTop: '1px solid var(--v4-rule)' }}
      >
        <div className="absolute inset-0 overflow-hidden">
          {tab === 'blotter' && <Trades />}
          {tab === 'sweep' && <SweepPanel />}
          {tab === 'wf' && <WalkForwardPanel />}
          {tab === 'mc' && <MonteCarloPanel />}
          {tab === 'costs' && <CostPanel />}
          {tab === 'rules' && <RuleBuilder />}
          {tab === 'prop' && <PropPanel />}
        </div>
      </div>
    </section>
  )
}

const VSep = () => <Separator className="v4-handle v4-handle-v" />
const HSep = () => <Separator className="v4-handle v4-handle-h" />

function WideLayout({ advanced }) {
  return (
    <PanelGroup orientation="horizontal" className="min-h-0 flex-1">
      <RPanel defaultSize={advanced ? '20' : '22'} minSize="15" maxSize="34" className="min-h-0">
        <Setup />
      </RPanel>
      <VSep />
      <RPanel defaultSize={advanced ? '58' : '78'} minSize="36" className="min-h-0">
        <div className="flex h-full min-h-0 flex-col">
          <Result />
          <PanelGroup orientation="vertical" className="min-h-0 flex-1">
            <RPanel defaultSize="44" minSize="18">
              <Price />
            </RPanel>
            <HSep />
            <RPanel defaultSize="28" minSize="14">
              <Equity />
            </RPanel>
            <HSep />
            <RPanel defaultSize="28" minSize="14">
              <Analysis advanced={advanced} />
            </RPanel>
          </PanelGroup>
        </div>
      </RPanel>
      {advanced && (
        <>
          <VSep />
          <RPanel defaultSize="22" minSize="16" maxSize="36" className="min-h-0">
            <PanelGroup orientation="vertical">
              <RPanel defaultSize="64" minSize="28">
                <Metrics />
              </RPanel>
              <HSep />
              <RPanel defaultSize="36" minSize="16">
                <ComparePanel />
              </RPanel>
            </PanelGroup>
          </RPanel>
        </>
      )}
    </PanelGroup>
  )
}

/** Under 1024px: answer, caveats and setup first, so a parameter change is
 *  never below 550px of charts. */
function NarrowLayout({ advanced }) {
  return (
    <div className="flex flex-col">
      <Result />
      <div className="v4-narrow-setup">
        <Setup collapsible />
      </div>
      <div className="h-[300px] shrink-0 border-b border-hair">
        <Price />
      </div>
      <div className="h-[230px] shrink-0 border-b border-hair">
        <Equity />
      </div>
      <div className="h-[420px] shrink-0 border-b border-hair">
        <Analysis advanced={advanced} />
      </div>
      {advanced && (
        <>
          <div className="shrink-0 border-b border-hair">
            <Metrics />
          </div>
          <div className="h-[300px] shrink-0">
            <ComparePanel />
          </div>
        </>
      )}
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

/** The original terminal's shortcuts, unchanged. Plain digits belong to the
 *  design switcher, so strategy families are Alt+1–4. Typing in a field
 *  always wins. */
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
