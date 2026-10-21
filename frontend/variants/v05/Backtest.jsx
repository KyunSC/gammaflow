'use client'

import './bt.css'
import { useEffect, useState } from 'react'
import { Group as PanelGroup, Panel as RPanel, Separator as PanelResizeHandle } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig } from '../../lib/backtest/share'
import SweepPanel from '../../components/backtest/SweepPanel'
import MonteCarloPanel from '../../components/backtest/MonteCarloPanel'
import CostPanel from '../../components/backtest/CostPanel'
import RuleBuilder from '../../components/backtest/RuleBuilder'
import PropPanel from '../../components/backtest/PropPanel'
import TopBar from './TopBar'
import Record from './Record'
import Setup from './Setup'
import PriceChart from './PriceChart'
import EquityChart from './EquityChart'
import Trades from './Trades'
import Metrics from './Metrics'
import Compare from './Compare'
import WalkForward from './WalkForward'
import Palette from './Palette'
import Shortcuts from './Shortcuts'
import Block, { Notice } from './Block'

const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep' },
  { id: 'wf', label: 'Walk-forward' },
  { id: 'mc', label: 'Monte Carlo' },
  { id: 'costs', label: 'Cost ladder' },
  { id: 'prop', label: 'Prop account' },
  { id: 'rules', label: 'Rule builder' },
]

/**
 * Variant 05, "Research Ledger". Same store, same boot sequence and the same
 * keyboard map as components/backtest/BacktestTerminal.jsx. The layout reads
 * like a notebook entry: setup on the left, then the record of what ran and
 * what it is worth, then the evidence (price, equity, trades) under it.
 */
export default function Backtest() {
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const setExample = useBacktest((s) => s.setExample)
  const advanced = useBacktest((s) => s.advanced)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const loadDataset = useBacktest((s) => s.loadDataset)
  const wide = useWide()

  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useKeyboard()

  const tabs = (
    <div role="tablist" aria-label="Research tools" className="flex items-end gap-4 overflow-x-auto px-3">
      {TABS.map((t) => (
        <button
          key={t.id}
          role="tab"
          id={`v05-tab-${t.id}`}
          aria-selected={activeTab === t.id}
          aria-controls="v05-tabpanel"
          tabIndex={activeTab === t.id ? 0 : -1}
          onClick={() => setTab(t.id)}
          onKeyDown={(e) => {
            if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
            const i = TABS.findIndex((x) => x.id === activeTab)
            const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length]
            setTab(next.id)
            document.getElementById(`v05-tab-${next.id}`)?.focus()
          }}
          className="v05-tab"
        >
          {t.label}
        </button>
      ))}
    </div>
  )

  const tabBody = (
    <div id="v05-tabpanel" role="tabpanel" aria-labelledby={`v05-tab-${activeTab}`} className="h-full min-h-0 pt-1.5">
      {activeTab === 'blotter' && <Trades />}
      {activeTab === 'sweep' && <SweepPanel />}
      {activeTab === 'wf' && <WalkForward />}
      {activeTab === 'mc' && <MonteCarloPanel />}
      {activeTab === 'costs' && <CostPanel />}
      {activeTab === 'rules' && <RuleBuilder />}
      {activeTab === 'prop' && <PropPanel />}
    </div>
  )

  const lower = advanced ? (
    <section aria-label="Research tools" className="v05-block h-full">
      <div className="v05-rule-b flex-none">{tabs}</div>
      <div className="v05-body">{tabBody}</div>
    </section>
  ) : (
    <Block title="Trades" className="h-full">
      <Trades />
    </Block>
  )

  const notices = (
    <>
      {datasetNotice && !datasetError && (
        <Notice tone="amber">
          <span className="flex-1">{datasetNotice}</span>
          <button onClick={() => setExample(false)} className="btn !px-2 !py-0.5">
            retry server
          </button>
        </Notice>
      )}
      {datasetError && (
        <Notice>
          <span className="flex-1">Couldn&apos;t load bars: {datasetError}</span>
          <button onClick={loadDataset} className="btn !px-2 !py-0.5">
            retry
          </button>
        </Notice>
      )}
      {runError && <Notice>Run failed: {runError}</Notice>}
      {configError && <Notice>{configError}</Notice>}
    </>
  )

  return (
    <div className={`v05-bt flex flex-col ${wide ? 'h-screen overflow-hidden' : 'min-h-screen'}`}>
      <TopBar />
      {notices}

      {wide ? (
        <PanelGroup key={advanced ? "adv" : "simple"} orientation="horizontal" className="min-h-0 flex-1">
          <RPanel defaultSize={advanced ? '21' : '23'} minSize="16" maxSize="34" className="min-h-0">
            <Setup />
          </RPanel>
          <PanelResizeHandle className="v05-handle" />
          <RPanel defaultSize={advanced ? '57' : '77'} minSize="36" className="min-h-0">
            <div className="flex h-full min-h-0 flex-col">
              <Record />
              <div className="v05-rule-t min-h-0 flex-1">
                <PanelGroup orientation="vertical">
                  <RPanel defaultSize="44" minSize="18">
                    <PriceChart />
                  </RPanel>
                  <PanelResizeHandle className="v05-handle" />
                  <RPanel defaultSize="26" minSize="14">
                    <EquityChart />
                  </RPanel>
                  <PanelResizeHandle className="v05-handle" />
                  <RPanel defaultSize="30" minSize="14">
                    {lower}
                  </RPanel>
                </PanelGroup>
              </div>
            </div>
          </RPanel>
          {advanced && (
            <>
              <PanelResizeHandle className="v05-handle" />
              <RPanel defaultSize="22" minSize="16" maxSize="36" className="min-h-0">
                <PanelGroup orientation="vertical">
                  <RPanel defaultSize="62" minSize="25">
                    <Metrics />
                  </RPanel>
                  <PanelResizeHandle className="v05-handle" />
                  <RPanel defaultSize="38" minSize="16">
                    <Compare />
                  </RPanel>
                </PanelGroup>
              </RPanel>
            </>
          )}
        </PanelGroup>
      ) : (
        // Under 1024px: one scrolling column, results first, setup one tap away.
        <div>
          <Record />
          <p className="px-3 pb-2 font-mono text-[11px]">
            <a href="#v05-setup" className="text-amber underline underline-offset-2">
              edit setup ↓
            </a>
          </p>
          <div className="v05-rule-t h-[300px]">
            <PriceChart />
          </div>
          <div className="v05-rule-t h-[230px]">
            <EquityChart />
          </div>
          <div className="v05-rule-t h-[400px]">{lower}</div>
          <div className="v05-rule-t">
            <Setup />
          </div>
          {advanced && (
            <>
              <div className="v05-rule-t">
                <Metrics />
              </div>
              <div className="v05-rule-t">
                <Compare />
              </div>
            </>
          )}
        </div>
      )}

      <Palette />
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

/** Same map as the original terminal. Plain digits are left to the design
 *  switcher; strategy families are Alt+1–4. */
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
